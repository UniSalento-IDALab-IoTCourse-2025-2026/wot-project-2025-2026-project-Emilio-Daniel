from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Notification, Patient, PatientUser, Task, User
from app.db.session import get_db
from app.main import app

PASSWORD = "companion-test-password"
PATIENT_EMAIL = "patient.companion@example.invalid"


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                Patient(patient_id="patient-001", display_name="Paziente Uno"),
                Patient(patient_id="patient-002", display_name="Paziente Due"),
            ]
        )
        user = User(
            email=PATIENT_EMAIL,
            password_hash=hash_password(PASSWORD),
            role="patient",
            display_name="Paziente Uno",
        )
        db.add(user)
        db.flush()
        db.add(PatientUser(user_id=user.id, patient_id="patient-001"))
        check_in_task = Task(
            patient_id="patient-001",
            task_type="check_in",
            status="created",
            title="Come ti senti?",
            payload={"assigned_to": "patient", "content": {}},
        )
        db.add(check_in_task)
        message_task = Task(
            patient_id="patient-001",
            task_type="custom",
            status="created",
            title="Messaggio dal medico",
            instructions="Ricordati di fare una breve passeggiata se ti senti bene.",
            payload={
                "assigned_to": "patient",
                "content": {
                    "kind": "patient_message",
                    "message": {
                        "title": "Suggerimento quotidiano",
                        "body": "Prova a muoverti qualche minuto in sicurezza.",
                    },
                },
            },
        )
        db.add(message_task)
        db.flush()
        db.add(
            Notification(
                patient_id="patient-001",
                channel="in_app",
                status="sent",
                title="Promemoria",
                body="Ricorda di bere.",
                payload={},
                sent_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            Notification(
                patient_id="patient-001",
                channel="push",
                status="sent",
                title="Nuova attivita'",
                body="Hai una nuova attivita' da completare nell'app.",
                payload={"type": "task_created", "task_id": f"task-{check_in_task.id}", "task_type": "check_in"},
                sent_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            Notification(
                patient_id="patient-001",
                channel="push",
                status="sent",
                title="Nuovo messaggio",
                body="Hai ricevuto un messaggio dal team di cura.",
                payload={"type": "task_created", "task_id": f"task-{message_task.id}", "task_type": "custom"},
                sent_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_device_is_bound_to_authenticated_patient_and_token_is_hidden(client: TestClient) -> None:
    headers = auth_headers(client)
    registered = client.post(
        "/api/v1/notifications/devices/register",
        headers=headers,
        json={
            "patient_id": "patient-001",
            "device_id": "android-test-001",
            "platform": "android",
            "app_version": "0.2.0",
            "fcm_token": "private-fcm-token",
            "notifications_enabled": True,
        },
    )
    assert registered.status_code == 200
    assert registered.json()["patient_id"] == "patient-001"
    assert registered.json()["fcm_registered"] is True
    assert "fcm_token" not in registered.json()

    wrong_patient = client.post(
        "/api/v1/notifications/devices/status",
        headers=headers,
        json={"patient_id": "patient-002", "device_id": "android-test-001", "battery_pct": 80},
    )
    assert wrong_patient.status_code == 403


def test_task_seen_started_and_completed_keep_device_identity(client: TestClient) -> None:
    headers = auth_headers(client)
    tasks = client.get("/api/v1/patients/patient-001/tasks", headers=headers).json()["items"]
    task_id = next(item for item in tasks if item["type"] == "check_in")["task_id"]

    seen = client.patch(
        f"/api/v1/tasks/{task_id}/state",
        headers=headers,
        json={"state": "seen", "device_id": "android-test-001", "occurred_at": "2026-07-14T10:00:00Z"},
    )
    assert seen.status_code == 200
    assert seen.json()["status"] == "seen"
    assert seen.json()["device_id"] == "android-test-001"

    started = client.patch(
        f"/api/v1/tasks/{task_id}/state",
        headers=headers,
        json={"state": "started", "device_id": "android-test-001", "occurred_at": "2026-07-14T10:01:00Z"},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "started"

    completed = client.post(
        f"/api/v1/tasks/{task_id}/results",
        headers=headers,
        json={
            "patient_id": "patient-001",
            "message_id": "result-test-e10",
            "started_at": "2026-07-14T10:01:00Z",
            "completed_at": "2026-07-14T10:02:00Z",
            "duration_seconds": 60,
            "answers": [{"question_id": "wellbeing", "value": "bene"}],
            "device_info": {"device_id": "android-test-001", "platform": "android"},
        },
    )
    assert completed.status_code == 200
    listed_items = client.get("/api/v1/patients/patient-001/tasks", headers=headers).json()["items"]
    listed = next(item for item in listed_items if item["task_id"] == task_id)
    assert listed["status"] == "completed"
    assert listed["seen_at"] is not None
    assert listed["started_at"] is not None
    assert listed["completed_at"] is not None
    assert listed["last_device_id"] == "android-test-001"


def test_patient_can_read_and_acknowledge_only_own_notification(client: TestClient) -> None:
    headers = auth_headers(client)
    response = client.get("/api/v1/notifications?patient_id=patient-001", headers=headers)
    assert response.status_code == 200
    notification = response.json()["items"][0]
    seen = client.patch(
        f"/api/v1/notifications/{notification['notification_id']}/seen",
        headers=headers,
    )
    assert seen.status_code == 200
    assert seen.json()["status"] == "seen"
    assert seen.json()["seen_at"] is not None


def test_patient_can_delete_task_notification_only_after_completion(client: TestClient) -> None:
    headers = auth_headers(client)
    tasks = client.get("/api/v1/patients/patient-001/tasks", headers=headers).json()["items"]
    task = next(item for item in tasks if item["type"] == "check_in")
    notifications = client.get("/api/v1/notifications?patient_id=patient-001", headers=headers).json()["items"]
    notification = next(item for item in notifications if item["payload"].get("task_id") == task["task_id"])

    blocked = client.delete(f"/api/v1/notifications/{notification['notification_id']}", headers=headers)
    assert blocked.status_code == 409

    completed = client.post(
        f"/api/v1/tasks/{task['task_id']}/results",
        headers=headers,
        json={
            "patient_id": "patient-001",
            "message_id": "result-delete-after-completion",
            "completed_at": "2026-07-14T10:03:00Z",
            "answers": [],
            "device_info": {"device_id": "android-test-001"},
        },
    )
    assert completed.status_code == 200

    dismissed = client.delete(f"/api/v1/notifications/{notification['notification_id']}", headers=headers)
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"

    remaining = client.get("/api/v1/notifications?patient_id=patient-001", headers=headers).json()["items"]
    assert notification["notification_id"] not in {item["notification_id"] for item in remaining}


def test_patient_can_delete_free_message_from_companion(client: TestClient) -> None:
    headers = auth_headers(client)
    tasks = client.get("/api/v1/patients/patient-001/tasks", headers=headers).json()["items"]
    message = next(item for item in tasks if item["payload"].get("kind") == "patient_message")

    dismissed = client.delete(f"/api/v1/tasks/{message['task_id']}", headers=headers)
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"

    remaining = client.get("/api/v1/patients/patient-001/tasks", headers=headers).json()["items"]
    assert message["task_id"] not in {item["task_id"] for item in remaining}


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": PATIENT_EMAIL, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
