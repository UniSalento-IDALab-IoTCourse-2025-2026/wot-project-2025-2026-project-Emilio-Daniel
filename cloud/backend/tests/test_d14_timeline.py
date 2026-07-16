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
from app.db.models import (
    Alert,
    AlertEvent,
    Decision,
    Doctor,
    DoctorPatient,
    EdgeCycle,
    EdgeDevice,
    FeatureWindow,
    Notification,
    Patient,
    SensorStatus,
    Task,
    TaskResult,
    User,
)
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.timeline@example.invalid"
OTHER_DOCTOR_EMAIL = "other.timeline@example.invalid"


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
        session.add_all(
            [
                Patient(patient_id="patient-001", display_name="Paziente Timeline"),
                Patient(patient_id="patient-999", display_name="Paziente Non Autorizzato"),
            ]
        )
        doctor_user = User(email=DOCTOR_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="doctor", display_name="Medico Timeline")
        other_doctor_user = User(email=OTHER_DOCTOR_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="doctor", display_name="Altro Medico")
        session.add_all([doctor_user, other_doctor_user])
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="TIMELINE")
        other_doctor = Doctor(user_id=other_doctor_user.id, license_number="OTHER")
        session.add_all([doctor, other_doctor])
        session.flush()
        session.add_all(
            [
                DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"),
                DoctorPatient(doctor_id=other_doctor.id, patient_id="patient-999"),
            ]
        )
        session.add(
            EdgeDevice(
                edge_id="edge-timeline",
                patient_id="patient-001",
                status="online",
                last_seen_at=now,
            )
        )
        cycle = EdgeCycle(
            message_id="timeline-cycle-001",
            patient_id="patient-001",
            edge_id="edge-timeline",
            event_type="edge_cycle_completed",
            timestamp=now - timedelta(minutes=20),
            window_start=now - timedelta(minutes=24),
            window_end=now - timedelta(minutes=20),
            payload={"payload": {"quality_status": "ok", "inference": "completed"}},
        )
        window = FeatureWindow(
            message_id="timeline-window-001",
            patient_id="patient-001",
            edge_id="edge-timeline",
            timestamp=now - timedelta(minutes=19),
            window_start=now - timedelta(minutes=23),
            window_end=now - timedelta(minutes=19),
            features={"heart_rate_mean": 72.0, "kitchen_minutes": 4.0, "room_changes": 1},
        )
        decision = Decision(
            message_id="timeline-decision-001",
            patient_id="patient-001",
            edge_id="edge-timeline",
            timestamp=now - timedelta(minutes=18),
            window_start=now - timedelta(minutes=22),
            window_end=now - timedelta(minutes=18),
            level="orange",
            should_publish=True,
            anomaly_score=74.5,
            model_label="timeline-model",
            payload={"payload": {"reasons": ["Test timeline"]}},
        )
        session.add_all([cycle, window, decision])
        session.flush()
        alert = Alert(
            message_id="timeline-alert-001",
            patient_id="patient-001",
            decision_id=decision.id,
            level="orange",
            status="resolved",
            category="behavioral",
            title="Alert timeline",
            description="Evento da rivedere.",
            opened_at=now - timedelta(minutes=17),
            closed_at=now - timedelta(minutes=10),
        )
        session.add(alert)
        session.flush()
        session.add_all(
            [
                AlertEvent(
                    alert_id=alert.id,
                    user_id=doctor_user.id,
                    event_type="acknowledged",
                    timestamp=now - timedelta(minutes=16),
                    note=dump_event_note(user_id="Medico Timeline", role="doctor"),
                ),
                AlertEvent(
                    alert_id=alert.id,
                    user_id=doctor_user.id,
                    event_type="resolved",
                    timestamp=now - timedelta(minutes=10),
                    note=dump_event_note(user_id="Medico Timeline", role="doctor", note="Controllo completato."),
                ),
            ]
        )
        task = Task(
            patient_id="patient-001",
            created_by_user_id=doctor_user.id,
            task_type="check_in",
            status="completed",
            title="Check-in timeline",
            instructions="Rispondi al controllo.",
            payload={"priority": "high", "assigned_to": "patient"},
            seen_at=now - timedelta(minutes=14),
            started_at=now - timedelta(minutes=13),
            completed_at=now - timedelta(minutes=12),
            last_device_id="android-timeline",
        )
        task.created_at = now - timedelta(minutes=15)
        session.add(task)
        session.flush()
        session.add(
            TaskResult(
                task_id=task.id,
                message_id="timeline-result-001",
                patient_id="patient-001",
                completed_at=now - timedelta(minutes=11),
                duration_seconds=90,
                result={"score": 2, "answers": [{"question_id": "q1", "value": "bene"}]},
            )
        )
        notification = Notification(
            patient_id="patient-001",
            channel="push",
            status="sent",
            title="Messaggio dal medico",
            body="Ricordati di bere acqua.",
            payload={"kind": "patient_message", "priority": "normal"},
            sent_at=now - timedelta(minutes=9),
        )
        notification.created_at = now - timedelta(minutes=9)
        sensor = SensorStatus(
            patient_id="patient-001",
            sensor_type="ble",
            status="active",
            last_seen_at=now - timedelta(minutes=8),
            details={"current_room": "kitchen"},
        )
        session.add_all([notification, sensor])
        session.commit()


def auth_headers(client: TestClient, email: str = DOCTOR_EMAIL) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_timeline_returns_normalized_events_ordered_from_newest(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/timeline?page_size=50", headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    event_types = [item["event_type"] for item in items]

    timestamps = [item["timestamp"] for item in items]
    assert body["total"] >= 10
    assert timestamps == sorted(timestamps, reverse=True)
    assert "patient_window_updated" in event_types
    assert "decision_updated" in event_types
    assert "alert_created" in event_types
    assert "alert_acknowledged" in event_types
    assert "alert_resolved" in event_types
    assert "task_created" in event_types
    assert "task_result_received" in event_types
    assert "patient_message_created" in event_types
    assert "sensor_ble_updated" in event_types

    first = items[0]
    assert set(first) == {"event_id", "event_type", "timestamp", "title", "summary", "severity", "source", "linked_resource"}
    assert first["linked_resource"]["type"]


def test_timeline_filters_by_type_date_and_paginates(client: TestClient) -> None:
    headers = auth_headers(client)
    decisions = client.get("/api/v1/patients/patient-001/timeline?event_type=decision_updated", headers=headers)
    assert decisions.status_code == 200
    assert decisions.json()["total"] == 1
    assert decisions.json()["items"][0]["event_type"] == "decision_updated"

    all_items = client.get("/api/v1/patients/patient-001/timeline?page_size=50", headers=headers).json()["items"]
    newest_timestamp = all_items[0]["timestamp"]
    filtered = client.get(f"/api/v1/patients/patient-001/timeline?date_from={newest_timestamp}&page_size=50", headers=headers)
    assert filtered.status_code == 200
    assert filtered.json()["total"] >= 1
    assert all(item["timestamp"] >= newest_timestamp for item in filtered.json()["items"])

    first_page = client.get("/api/v1/patients/patient-001/timeline?page=1&page_size=2", headers=headers).json()
    second_page = client.get("/api/v1/patients/patient-001/timeline?page=2&page_size=2", headers=headers).json()
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 2
    assert first_page["items"][0]["event_id"] != second_page["items"][0]["event_id"]


def test_timeline_requires_patient_authorization(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-999/timeline", headers=auth_headers(client))
    assert response.status_code == 403
