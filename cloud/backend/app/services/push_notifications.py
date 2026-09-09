from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.telemetry import increment_firebase_errors
from app.db.models import Alert, Notification, PatientAppStatus, Task

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PushSendResult:
    """Rappresenta l'esito sintetico dell'invio senza contenere il token FCM."""

    success: bool
    provider_message_id: str | None = None
    error_code: str | None = None
    invalid_token: bool = False
    provider: str = "firebase"


class FirebasePushSender:
    """Invia notifiche push reali tramite Firebase Cloud Messaging."""

    def __init__(self) -> None:
        self._initialized = False

    def send(self, *, token: str, title: str, body: str, data: dict[str, str]) -> PushSendResult:
        """Invia una push a un singolo token FCM leggendo le credenziali dal `.env`."""
        settings = get_settings()
        if settings.firebase_fake_enabled:
            return PushSendResult(success=True, provider_message_id=f"fake-{data.get('notification_id', 'notification')}", provider="fake")
        if not settings.firebase_enabled:
            return PushSendResult(success=False, error_code="firebase_disabled")
        if not settings.firebase_credentials_file:
            return PushSendResult(success=False, error_code="firebase_credentials_missing")

        try:
            from firebase_admin import credentials, get_app, initialize_app, messaging
        except ImportError:
            return PushSendResult(success=False, error_code="firebase_admin_missing")

        credentials_path = Path(settings.firebase_credentials_file)
        if not credentials_path.is_absolute():
            credentials_path = Path.cwd() / credentials_path
        if not credentials_path.exists():
            return PushSendResult(success=False, error_code="firebase_credentials_not_found")

        if not self._initialized:
            try:
                get_app()
            except ValueError:
                initialize_app(credentials.Certificate(str(credentials_path)))
            self._initialized = True

        android_notification = messaging.AndroidNotification(
            title=title,
            body=body,
            icon="ic_notification",
            color="#087F78",
            channel_id="patient_updates",
            priority="high",
            visibility="private",
        )
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={key: str(value) for key, value in data.items()},
            android=messaging.AndroidConfig(
                priority="high",
                notification=android_notification,
            ),
            token=token,
        )
        try:
            provider_message_id = messaging.send(message)
        except Exception as exc:  # noqa: BLE001 - Firebase usa eccezioni diverse in base all'errore.
            code = firebase_error_code(exc)
            increment_firebase_errors()
            return PushSendResult(success=False, error_code=code, invalid_token=is_invalid_fcm_token(code, exc))
        return PushSendResult(success=True, provider_message_id=provider_message_id)


_firebase_sender = FirebasePushSender()


def notify_task_created(db: Session, task: Task) -> Notification:
    """Crea la notifica paziente per un nuovo task e prova l'invio push reale."""
    notification_title, notification_body, payload = task_notification_content(task)
    notification = create_notification(
        db,
        patient_id=task.patient_id,
        title=notification_title,
        body=notification_body,
        payload=payload,
    )
    send_notification_to_patient_devices(db, notification, allowed_platforms={"android", "ios"})
    return notification


def notify_caregiver_message(
    db: Session,
    *,
    patient_id: str,
    title: str,
    body: str,
    payload: dict[str, Any],
) -> Notification:
    """Crea una notifica operativa destinata solo ai device caregiver autorizzati."""
    notification = create_notification(
        db,
        patient_id=patient_id,
        title=title,
        body=body,
        payload={
            **payload,
            "type": "caregiver_message",
            "kind": "caregiver_message",
        },
    )
    send_notification_to_patient_devices(db, notification, allowed_platforms={"android_caregiver"})
    return notification


def task_notification_content(task: Task) -> tuple[str, str, dict[str, Any]]:
    """Prepara testo e payload push distinguendo task operativi e messaggi medico-paziente."""
    title = str(task.title or "").strip() or "Nuova attivita'"
    instructions = str(task.instructions or "").strip()
    base_payload = {
        "type": "task_created",
        "task_id": f"task-{task.id}",
        "task_type": task.task_type,
    }
    if is_patient_message_task(task):
        message = task.payload.get("message", {}) if isinstance(task.payload, dict) else {}
        message_title = str(message.get("title") or task.title or "Messaggio dal medico").strip()
        return (
            message_title[:255],
            "Apri l'app per leggere il messaggio.",
            {
                **base_payload,
                "type": "patient_message",
                "kind": "patient_message",
                "message_title": message_title[:120],
            },
        )
    return (
        title[:255],
        instructions[:180] if instructions else "Apri l'app per vedere i dettagli dell'attivita'.",
        base_payload,
    )


def is_patient_message_task(task: Task) -> bool:
    """Riconosce i messaggi creati dalla dashboard come task custom per l'app paziente."""
    return task.task_type == "custom" and isinstance(task.payload, dict) and task.payload.get("kind") == "patient_message"


def notify_alert_created(db: Session, alert: Alert) -> Notification | None:
    """Crea una notifica generica per alert importanti senza esporre dati clinici sensibili."""
    level = alert.level.lower()
    if level not in {"orange", "red"}:
        return None
    notification = create_notification(
        db,
        patient_id=alert.patient_id,
        title="Aggiornamento importante",
        body="Apri l'app per verificare un aggiornamento del sistema.",
        payload={
            "type": "alert_created",
            "alert_id": f"alert-{alert.id}",
            "level": level,
            "category": alert.category,
            "source": alert.source,
        },
    )
    send_notification_to_patient_devices(db, notification, allowed_platforms={"android_caregiver"})
    return notification


def create_notification(
    db: Session,
    *,
    patient_id: str,
    title: str,
    body: str,
    payload: dict[str, Any],
) -> Notification:
    """Salva una notifica applicativa prima del tentativo di push."""
    notification = Notification(
        patient_id=patient_id,
        channel="push",
        status="pending",
        title=title,
        body=body,
        payload=payload,
    )
    db.add(notification)
    db.flush()
    return notification


def send_notification_to_patient_devices(
    db: Session,
    notification: Notification,
    *,
    sender: FirebasePushSender | None = None,
    allowed_platforms: set[str] | None = None,
) -> None:
    """Invia la notifica ai device FCM abilitati e registra solo conteggi/esito."""
    if notification.patient_id is None:
        notification.status = "failed"
        notification.payload = with_delivery(notification.payload, {"error": "missing_patient_id"})
        return

    query = (
        select(PatientAppStatus).where(
            PatientAppStatus.patient_id == notification.patient_id,
            PatientAppStatus.notifications_enabled.is_(True),
            PatientAppStatus.fcm_token.is_not(None),
        )
    )
    if allowed_platforms is not None:
        query = query.where(PatientAppStatus.platform.in_(allowed_platforms))
    devices = db.execute(query).scalars().all()
    if not devices:
        notification.status = "no_device"
        notification.payload = with_delivery(notification.payload, {"attempted": 0, "success": 0, "failed": 0})
        return

    push_sender = sender or _firebase_sender
    success_count = 0
    failed_count = 0
    invalid_count = 0
    last_error: str | None = None
    provider = "firebase"
    data = notification_data(notification)

    for device in devices:
        token = device.fcm_token
        if not token:
            continue
        result = push_sender.send(token=token, title=notification.title, body=notification.body or "", data=data)
        provider = result.provider
        if result.success:
            success_count += 1
        else:
            failed_count += 1
            last_error = result.error_code
            if result.invalid_token:
                invalid_count += 1
                device.fcm_token = None
                device.notifications_enabled = False

    notification.sent_at = datetime.now(timezone.utc) if success_count else None
    notification.status = "sent" if success_count else (last_error or "failed")
    notification.payload = with_delivery(
        notification.payload,
        {
            "provider": provider,
            "attempted": len(devices),
            "success": success_count,
            "failed": failed_count,
            "invalid_tokens": invalid_count,
            "last_error": last_error,
        },
    )
    logger.info(
        "push_notification_delivery_recorded",
        extra={
            "patient_id": notification.patient_id,
            "notification_id": notification.id,
            "status": notification.status,
            "attempted": len(devices),
            "success": success_count,
            "failed": failed_count,
            "invalid_tokens": invalid_count,
        },
    )


def notification_data(notification: Notification) -> dict[str, str]:
    """Costruisce i dati silenziosi che l'app usa per aprire la schermata corretta."""
    payload = notification.payload or {}
    return {
        "notification_id": f"notification-{notification.id}",
        "patient_id": notification.patient_id or "",
        "type": str(payload.get("type") or "notification"),
        "task_id": str(payload.get("task_id") or ""),
        "alert_id": str(payload.get("alert_id") or ""),
    }


def with_delivery(payload: dict[str, Any] | None, delivery: dict[str, Any]) -> dict[str, Any]:
    """Aggiunge l'esito tecnico senza modificare i dati funzionali della notifica."""
    updated = dict(payload or {})
    updated["delivery"] = delivery
    return updated


def firebase_error_code(exc: Exception) -> str:
    """Normalizza l'errore Firebase evitando di includere token o dettagli sensibili."""
    code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    return str(code or exc.__class__.__name__)


def is_invalid_fcm_token(code: str, exc: Exception) -> bool:
    """Riconosce token scaduti o non validi per disattivarli nel database."""
    normalized = f"{code} {exc}".lower()
    invalid_markers = {
        "unregistered",
        "registration-token-not-registered",
        "invalid-registration-token",
        "invalid_argument",
        "sender_id_mismatch",
    }
    return any(marker in normalized for marker in invalid_markers)
