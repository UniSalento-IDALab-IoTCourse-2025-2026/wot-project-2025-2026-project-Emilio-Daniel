from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.routes.utils import paginated, utc_iso
from app.api.routes.task_rules import effective_task_status, is_patient_message_task
from app.auth.dependencies import CurrentUser, can_access_patient, get_current_user, write_audit
from app.db.models import Notification, PatientAppStatus, Task
from app.db.session import get_db

router = APIRouter()


@router.get("/status", summary="Notifications module status")
def notifications_status() -> dict[str, str]:
    """Espone lo stato del modulo usato dall'app companion."""
    return {"status": "implemented", "module": "notifications"}


@router.get("", summary="List patient notifications")
def list_notifications(
    patient_id: str = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce esclusivamente le notifiche del paziente autorizzato."""
    ensure_patient_access(db, current_user, patient_id)
    rows = db.execute(
        select(Notification)
        .where(Notification.patient_id == patient_id, Notification.status != "dismissed")
        .order_by(desc(Notification.created_at), desc(Notification.id))
    ).scalars().all()
    return paginated([notification_payload(row) for row in rows], page=page, page_size=page_size)


@router.get("/caregiver", summary="List caregiver messages")
def list_caregiver_notifications(
    patient_id: str = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce solo messaggi operativi destinati al caregiver."""
    if current_user.role not in {"caregiver", "admin"}:
        raise HTTPException(status_code=403, detail="Only caregiver or admin can read caregiver messages.")
    ensure_patient_access(db, current_user, patient_id)
    rows = db.execute(
        select(Notification)
        .where(
            Notification.patient_id == patient_id,
            Notification.status != "dismissed",
        )
        .order_by(desc(Notification.created_at), desc(Notification.id))
    ).scalars().all()
    rows = [row for row in rows if (row.payload or {}).get("kind") == "caregiver_message"]
    return paginated([notification_payload(row) for row in rows], page=page, page_size=page_size)


@router.patch("/{notification_id}/seen", summary="Mark notification as seen")
def mark_notification_seen(
    notification_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Registra la visualizzazione di una notifica in modo idempotente."""
    numeric_id = parse_prefixed_id(notification_id, "notification")
    row = db.get(Notification, numeric_id) if numeric_id is not None else None
    if row is None or row.patient_id is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    ensure_patient_access(db, current_user, row.patient_id)
    row.status = "seen"
    row.seen_at = row.seen_at or datetime.now(timezone.utc)
    write_audit(
        db,
        actor=current_user,
        action="notification.seen",
        patient_id=row.patient_id,
        target_type="notification",
        target_id=f"notification-{row.id}",
    )
    db.commit()
    db.refresh(row)
    return notification_payload(row)


@router.delete("/{notification_id}", summary="Dismiss patient notification")
def dismiss_notification(
    notification_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Archivia una notifica rispettando il vincolo sui task non completati."""
    numeric_id = parse_prefixed_id(notification_id, "notification")
    row = db.get(Notification, numeric_id) if numeric_id is not None else None
    if row is None or row.patient_id is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    ensure_patient_access(db, current_user, row.patient_id)

    linked_task = linked_task_from_notification(db, row)
    if linked_task is not None:
        task_status = effective_task_status(linked_task.status, linked_task.due_at)
        if is_patient_message_task(linked_task.task_type, linked_task.payload or {}) or task_status == "expired":
            linked_task.status = "dismissed"
            task_payload = dict(linked_task.payload or {})
            task_payload["dismissed_at"] = datetime.now(timezone.utc).isoformat()
            task_payload["dismissed_by"] = current_user.display_name or current_user.email
            linked_task.payload = task_payload
        elif task_status != "completed":
            raise HTTPException(status_code=409, detail="Complete the activity before deleting this notification.")

    row.status = "dismissed"
    row.seen_at = row.seen_at or datetime.now(timezone.utc)
    write_audit(
        db,
        actor=current_user,
        action="notification.dismissed",
        patient_id=row.patient_id,
        target_type="notification",
        target_id=f"notification-{row.id}",
        details={"linked_task_id": f"task-{linked_task.id}" if linked_task else None},
    )
    db.commit()
    db.refresh(row)
    return notification_payload(row)


@router.post("/devices/register", summary="Register patient companion device")
def register_device(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Associa device e token FCM al paziente autenticato senza riesporre il token."""
    patient_id, device_id = validate_device_payload(db, current_user, payload)
    row = get_or_create_device(db, patient_id, device_id)
    token = str(payload.get("fcm_token") or "").strip()
    row.fcm_token = token or row.fcm_token
    row.platform = str(payload.get("platform") or "android")[:32]
    row.app_version = optional_text(payload.get("app_version"), 64)
    row.notifications_enabled = bool(payload.get("notifications_enabled", bool(token)))
    row.status = "online"
    row.last_seen_at = datetime.now(timezone.utc)
    write_audit(
        db,
        actor=current_user,
        action="patient_app.device_registered",
        patient_id=patient_id,
        target_type="patient_device",
        target_id=device_id,
        details={"platform": row.platform, "fcm_configured": bool(row.fcm_token)},
    )
    db.commit()
    return public_device_payload(row)


@router.post("/caregiver/devices/register", summary="Register caregiver companion device")
def register_caregiver_device(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Associa il telefono caregiver a un paziente autorizzato senza esporre il token FCM."""
    patient_id, device_id = validate_caregiver_device_payload(db, current_user, payload)
    row = get_or_create_device(db, patient_id, device_id)
    token = str(payload.get("fcm_token") or "").strip()
    row.fcm_token = token or row.fcm_token
    row.platform = "android_caregiver"
    row.app_version = optional_text(payload.get("app_version"), 64)
    row.notifications_enabled = bool(payload.get("notifications_enabled", bool(token)))
    row.status = "online"
    row.last_seen_at = datetime.now(timezone.utc)
    write_audit(
        db,
        actor=current_user,
        action="caregiver_app.device_registered",
        patient_id=patient_id,
        target_type="caregiver_device",
        target_id=device_id,
        details={"platform": row.platform, "fcm_configured": bool(row.fcm_token)},
    )
    db.commit()
    return public_device_payload(row)


@router.post("/devices/status", summary="Update patient companion status")
def update_device_status(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Salva heartbeat e batteria del telefono associato al paziente."""
    patient_id, device_id = validate_device_payload(db, current_user, payload)
    row = get_or_create_device(db, patient_id, device_id)
    row.status = str(payload.get("status") or "online")[:32]
    row.last_seen_at = datetime.now(timezone.utc)
    row.app_version = optional_text(payload.get("app_version"), 64) or row.app_version
    row.platform = str(payload.get("platform") or row.platform or "android")[:32]
    row.notifications_enabled = bool(payload.get("notifications_enabled", row.notifications_enabled))
    battery = payload.get("battery_pct")
    if battery is not None:
        try:
            row.battery_pct = max(0.0, min(100.0, float(battery)))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="battery_pct must be numeric.") from exc
    db.commit()
    return public_device_payload(row)


@router.post("/caregiver/devices/status", summary="Update caregiver companion status")
def update_caregiver_device_status(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Aggiorna heartbeat e batteria dell'app caregiver associata al paziente."""
    patient_id, device_id = validate_caregiver_device_payload(db, current_user, payload)
    row = get_or_create_device(db, patient_id, device_id)
    row.status = str(payload.get("status") or "online")[:32]
    row.platform = "android_caregiver"
    row.last_seen_at = datetime.now(timezone.utc)
    row.app_version = optional_text(payload.get("app_version"), 64) or row.app_version
    row.notifications_enabled = bool(payload.get("notifications_enabled", row.notifications_enabled))
    battery = payload.get("battery_pct")
    if battery is not None:
        try:
            row.battery_pct = max(0.0, min(100.0, float(battery)))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="battery_pct must be numeric.") from exc
    db.commit()
    return public_device_payload(row)


def validate_device_payload(
    db: Session,
    current_user: CurrentUser,
    payload: dict[str, Any],
) -> tuple[str, str]:
    """Valida identita' paziente e device prima di qualunque scrittura."""
    if current_user.role not in {"patient", "admin"}:
        raise HTTPException(status_code=403, detail="Only patient or admin can register companion devices.")
    patient_id = str(payload.get("patient_id") or "").strip()
    device_id = str(payload.get("device_id") or "").strip()
    if not patient_id or not device_id:
        raise HTTPException(status_code=422, detail="patient_id and device_id are required.")
    ensure_patient_access(db, current_user, patient_id)
    return patient_id, device_id[:128]


def validate_caregiver_device_payload(
    db: Session,
    current_user: CurrentUser,
    payload: dict[str, Any],
) -> tuple[str, str]:
    """Valida il device caregiver e il paziente associato prima di salvarlo."""
    if current_user.role not in {"caregiver", "admin"}:
        raise HTTPException(status_code=403, detail="Only caregiver or admin can register caregiver devices.")
    patient_id = str(payload.get("patient_id") or "").strip()
    device_id = str(payload.get("device_id") or "").strip()
    if not patient_id or not device_id:
        raise HTTPException(status_code=422, detail="patient_id and device_id are required.")
    ensure_patient_access(db, current_user, patient_id)
    return patient_id, f"caregiver-{device_id}"[:128]


def ensure_patient_access(db: Session, user: CurrentUser, patient_id: str) -> None:
    """Applica la stessa associazione account-paziente usata dal resto delle API."""
    if not can_access_patient(db, user, patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")


def get_or_create_device(db: Session, patient_id: str, device_id: str) -> PatientAppStatus:
    """Carica il device oppure crea il primo record di stato."""
    row = db.execute(
        select(PatientAppStatus).where(
            PatientAppStatus.patient_id == patient_id,
            PatientAppStatus.device_id == device_id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = PatientAppStatus(
            patient_id=patient_id,
            device_id=device_id,
            status="online",
            platform="android",
            notifications_enabled=False,
        )
        db.add(row)
        db.flush()
    return row


def public_device_payload(row: PatientAppStatus) -> dict[str, Any]:
    """Serializza il device escludendo sempre il token FCM."""
    return {
        "patient_id": row.patient_id,
        "device_id": row.device_id,
        "status": row.status,
        "platform": row.platform,
        "app_version": row.app_version,
        "battery_pct": row.battery_pct,
        "notifications_enabled": row.notifications_enabled,
        "fcm_registered": bool(row.fcm_token),
        "last_seen_at": utc_iso(row.last_seen_at),
    }


def notification_payload(row: Notification) -> dict[str, Any]:
    """Serializza la notifica destinata all'app paziente."""
    return {
        "notification_id": f"notification-{row.id}",
        "patient_id": row.patient_id,
        "channel": row.channel,
        "status": row.status,
        "title": row.title,
        "body": row.body,
        "payload": row.payload or {},
        "sent_at": utc_iso(row.sent_at),
        "seen_at": utc_iso(row.seen_at),
        "created_at": utc_iso(row.created_at),
    }


def parse_prefixed_id(value: str, prefix: str) -> int | None:
    text = value.removeprefix(f"{prefix}-")
    return int(text) if text.isdigit() else None


def linked_task_from_notification(db: Session, notification: Notification) -> Task | None:
    payload = notification.payload or {}
    task_ref = str(payload.get("task_id") or "").strip()
    if not task_ref:
        return None
    task_id = parse_prefixed_id(task_ref, "task")
    return db.get(Task, task_id) if task_id is not None else None


def optional_text(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] or None
