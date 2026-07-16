from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.utils import dump_event_note
from app.auth.security import hash_password
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Alert, AlertEvent, Decision, Doctor, DoctorPatient, FeatureWindow, Notification, Patient, PatientUser, Task, User
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.alert.workflow@example.invalid"
PATIENT_EMAIL = "patient.alert.workflow@example.invalid"


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    seed_database(engine)

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def seed_database(engine) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with Session(engine) as session:
        session.add(Patient(patient_id="patient-001", display_name="Paziente Alert"))
        doctor_user = User(email=DOCTOR_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="doctor", display_name="Medico Alert")
        patient_user = User(email=PATIENT_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="patient", display_name="Paziente Alert")
        session.add_all([doctor_user, patient_user])
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="ALERT")
        session.add(doctor)
        session.flush()
        session.add_all(
            [
                DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"),
                PatientUser(user_id=patient_user.id, patient_id="patient-001"),
            ]
        )
        decision = Decision(
            message_id="workflow-decision-001",
            patient_id="patient-001",
            timestamp=now - timedelta(minutes=10),
            window_start=now - timedelta(minutes=14),
            window_end=now - timedelta(minutes=10),
            level="orange",
            should_publish=True,
            anomaly_score=76.5,
            model_label="workflow-model",
            payload={"payload": {"reasons": ["Wearable fuori routine"]}},
        )
        window = FeatureWindow(
            message_id="workflow-window-001",
            patient_id="patient-001",
            timestamp=now - timedelta(minutes=10),
            window_start=now - timedelta(minutes=14),
            window_end=now - timedelta(minutes=10),
            features={"heart_rate_mean": 83.0, "spo2_mean": 94.0, "kitchen_minutes": 4.0, "room_changes": 1},
        )
        session.add_all([decision, window])
        session.flush()
        alert = Alert(
            message_id="workflow-alert-001",
            patient_id="patient-001",
            decision_id=decision.id,
            level="orange",
            status="new",
            category="behavioral",
            source="ai",
            clinical_severity="orange",
            title="Alert workflow",
            description="Evento da verificare.",
            opened_at=now - timedelta(minutes=9),
        )
        session.add(alert)
        session.flush()
        task = Task(
            patient_id="patient-001",
            created_by_user_id=doctor_user.id,
            task_type="check_in",
            status="created",
            title="Follow-up alert",
            payload={"priority": "high", "content": {"workflow": "alert_follow_up", "source_alert_id": f"alert-{alert.id}"}},
        )
        task.created_at = now - timedelta(minutes=7)
        notification = Notification(
            patient_id="patient-001",
            channel="push",
            status="sent",
            title="Messaggio dal medico",
            body="Verifica come ti senti.",
            payload={"kind": "patient_message", "source_alert_id": f"alert-{alert.id}"},
            sent_at=now - timedelta(minutes=6),
        )
        session.add_all(
            [
                AlertEvent(
                    alert_id=alert.id,
                    user_id=doctor_user.id,
                    event_type="acknowledged",
                    timestamp=now - timedelta(minutes=8),
                    note=dump_event_note(user_id="Medico Alert", role="doctor", note="Verifico il caso."),
                ),
                task,
                notification,
            ]
        )
        session.commit()


def test_alert_details_returns_context_related_events_and_history(client: TestClient) -> None:
    details = client.get("/api/v1/alerts/alert-1/details", headers=auth_headers(client, DOCTOR_EMAIL))

    assert details.status_code == 200
    body = details.json()
    assert body["alert_id"] == "alert-1"
    assert body["context"]["decision"]["anomaly_score"] == 76.5
    assert body["context"]["feature_window"]["key_features"]["heart_rate_mean"] == 83.0
    assert body["workflow"]["delete_policy"] == "permanent_delete_allowed_only_when_resolved"
    assert "acknowledge" in body["workflow"]["available_actions"]
    assert "resolve" in body["workflow"]["available_actions"]
    event_types = {event["event_type"] for event in body["related_events"]}
    assert {"alert_created", "decision_updated", "patient_window_updated", "task_created", "patient_message_created"}.issubset(event_types)
    assert body["history"][0]["event_type"] == "acknowledged"
    assert body["history"][0]["note"] == "Verifico il caso."


def test_patient_cannot_read_alert_workflow_details(client: TestClient) -> None:
    response = client.get("/api/v1/alerts/alert-1/details", headers=auth_headers(client, PATIENT_EMAIL))

    assert response.status_code == 403


def test_alert_delete_requires_resolved_status(client: TestClient) -> None:
    headers = auth_headers(client, DOCTOR_EMAIL)
    blocked = client.delete("/api/v1/alerts/alert-1", headers=headers)
    assert blocked.status_code == 409

    resolved = client.patch("/api/v1/alerts/alert-1/resolve", json={"note": "Caso chiuso."}, headers=headers)
    assert resolved.status_code == 200

    deleted = client.delete("/api/v1/alerts/alert-1", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
