from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Alert, Notification, Patient, PatientAppStatus, Task
from app.core.config import get_settings
from app.services import push_notifications
from app.services.push_notifications import PushSendResult, notify_alert_created, notify_task_created, send_notification_to_patient_devices


class RecordingSender:
    """Sostituisce Firebase nei test unitari senza eseguire chiamate di rete."""

    def __init__(self, result: PushSendResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def send(self, *, token: str, title: str, body: str, data: dict[str, str]) -> PushSendResult:
        self.calls.append({"token": token, "title": title, "body": body, "data": data})
        return self.result


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Patient(patient_id="patient-001", display_name="Paziente Uno"))
    session.commit()
    return session


def test_task_notification_is_sent_without_storing_fcm_token() -> None:
    with make_session() as session:
        session.add(
            PatientAppStatus(
                patient_id="patient-001",
                device_id="android-001",
                status="online",
                platform="android",
                fcm_token="private-token",
                notifications_enabled=True,
            )
        )
        notification = Notification(
            patient_id="patient-001",
            channel="push",
            status="pending",
            title="Controllo",
            body="Apri l'app.",
            payload={"type": "task_created", "task_id": "task-1"},
        )
        session.add(notification)
        session.flush()
        sender = RecordingSender(PushSendResult(success=True, provider_message_id="firebase-message-001"))

        send_notification_to_patient_devices(session, notification, sender=sender)
        session.commit()

        stored = session.execute(select(Notification)).scalar_one()
        assert stored.status == "sent"
        assert stored.sent_at is not None
        assert stored.payload["delivery"]["success"] == 1
        assert "private-token" not in str(stored.payload)
        assert sender.calls[0]["token"] == "private-token"


def test_invalid_fcm_token_is_disabled() -> None:
    with make_session() as session:
        device = PatientAppStatus(
            patient_id="patient-001",
            device_id="android-001",
            status="online",
            platform="android",
            fcm_token="expired-token",
            notifications_enabled=True,
        )
        notification = Notification(
            patient_id="patient-001",
            channel="push",
            status="pending",
            title="Avviso",
            body="Apri l'app.",
            payload={"type": "alert_created"},
        )
        session.add_all([device, notification])
        session.flush()
        sender = RecordingSender(PushSendResult(success=False, error_code="UNREGISTERED", invalid_token=True))

        send_notification_to_patient_devices(session, notification, sender=sender)
        session.commit()

        assert notification.status == "UNREGISTERED"
        assert notification.payload["delivery"]["invalid_tokens"] == 1
        assert device.fcm_token is None
        assert device.notifications_enabled is False


def test_notification_without_registered_device_stays_in_app_visible() -> None:
    with make_session() as session:
        task = Task(patient_id="patient-001", task_type="check_in", title="Controllo benessere", instructions="Compila il check-in di oggi.", payload={})
        session.add(task)
        session.flush()

        notification = notify_task_created(session, task)
        session.commit()

        assert notification.title == "Controllo benessere"
        assert notification.body == "Compila il check-in di oggi."
        assert notification.status == "no_device"
        assert notification.payload["type"] == "task_created"
        assert notification.payload["delivery"]["attempted"] == 0


def test_patient_message_task_uses_message_push_title() -> None:
    with make_session() as session:
        session.add(
            PatientAppStatus(
                patient_id="patient-001",
                device_id="android-001",
                status="online",
                platform="android",
                fcm_token="private-token",
                notifications_enabled=True,
            )
        )
        task = Task(
            patient_id="patient-001",
            task_type="custom",
            title="Promemoria personalizzato",
            instructions="Testo lungo da leggere solo dentro l'app.",
            payload={
                "kind": "patient_message",
                "message": {
                    "title": "Messaggio dal medico",
                    "body": "Testo lungo da leggere solo dentro l'app.",
                    "tone": "normal",
                },
            },
        )
        session.add(task)
        session.flush()
        sender = RecordingSender(PushSendResult(success=True, provider_message_id="firebase-message-002"))

        notification = notify_task_created(session, task)
        send_notification_to_patient_devices(session, notification, sender=sender)
        session.commit()

        assert notification.title == "Messaggio dal medico"
        assert notification.body == "Apri l'app per leggere il messaggio."
        assert notification.payload["type"] == "patient_message"
        assert notification.payload["kind"] == "patient_message"
        assert notification.payload["message_title"] == "Messaggio dal medico"
        assert "Testo lungo da leggere solo dentro l'app." not in str(notification.payload)


def test_fake_mode_marks_delivery_without_firebase_credentials(monkeypatch) -> None:
    monkeypatch.setenv("IOT_BACKEND_FIREBASE_ENABLED", "false")
    monkeypatch.setenv("IOT_BACKEND_FIREBASE_FAKE_ENABLED", "true")
    get_settings.cache_clear()
    try:
        with make_session() as session:
            session.add(
                PatientAppStatus(
                    patient_id="patient-001",
                    device_id="android-001",
                    status="online",
                    platform="android",
                    fcm_token="fake-token",
                    notifications_enabled=True,
                )
            )
            task = Task(patient_id="patient-001", task_type="check_in", title="Controllo", payload={})
            session.add(task)
            session.flush()

            notification = notify_task_created(session, task)
            session.commit()

            assert notification.status == "sent"
            assert notification.payload["delivery"]["provider"] == "fake"
            assert notification.payload["delivery"]["success"] == 1
            assert "fake-token" not in str(notification.payload)
    finally:
        get_settings.cache_clear()


def test_important_alert_push_is_sent_only_to_caregiver_devices(monkeypatch) -> None:
    with make_session() as session:
        sender = RecordingSender(PushSendResult(success=True, provider_message_id="firebase-alert"))
        monkeypatch.setattr(push_notifications, "_firebase_sender", sender)
        session.add_all(
            [
                PatientAppStatus(
                    patient_id="patient-001",
                    device_id="android-patient-001",
                    status="online",
                    platform="android",
                    fcm_token="patient-token",
                    notifications_enabled=True,
                ),
                PatientAppStatus(
                    patient_id="patient-001",
                    device_id="caregiver-android-001",
                    status="online",
                    platform="android_caregiver",
                    fcm_token="caregiver-token",
                    notifications_enabled=True,
                ),
            ]
        )
        alert = Alert(
            patient_id="patient-001",
            message_id="alert-caregiver-only",
            level="red",
            status="new",
            category="behavioral",
            title="Alert importante",
            description="Solo caregiver.",
            opened_at=datetime.now(timezone.utc),
        )
        session.add(alert)
        session.flush()

        notification = notify_alert_created(session, alert)
        session.commit()

        assert notification is not None
        assert notification.status != "no_device"
        assert notification.payload["delivery"]["attempted"] == 1
        assert [call["token"] for call in sender.calls] == ["caregiver-token"]
