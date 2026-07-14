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
from app.db.models import (
    Alert,
    Decision,
    Doctor,
    DoctorPatient,
    EdgeCycle,
    EdgeDevice,
    FeatureWindow,
    Patient,
    PatientAppStatus,
    PatientUser,
    SensorStatus,
    User,
)
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.unit.test@example.invalid"
PATIENT_EMAIL = "patient.unit.test@example.invalid"


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
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(Patient(patient_id="patient-001", display_name="Paziente Demo"))
        doctor_user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico Test",
        )
        patient_user = User(
            email=PATIENT_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="patient",
            display_name="Paziente Test",
        )
        session.add_all([doctor_user, patient_user])
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="TEST")
        session.add(doctor)
        session.flush()
        session.add_all(
            [
                DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"),
                PatientUser(user_id=patient_user.id, patient_id="patient-001"),
            ]
        )
        session.add(
            EdgeDevice(
                edge_id="edge-rpi5-001",
                patient_id="patient-001",
                status="online",
                last_seen_at=now,
            )
        )
        session.add(
            EdgeCycle(
                message_id="edge-cycle-001",
                patient_id="patient-001",
                edge_id="edge-rpi5-001",
                event_type="edge_cycle_completed",
                timestamp=now,
                window_start=now,
                window_end=now,
                payload={
                    "payload": {
                        "status": "cycle_completed",
                        "quality_status": "warning",
                        "quality_issue_count": 1,
                        "quality_warning_count": 1,
                        "quality_error_count": 0,
                        "ble_samples_collected": 12,
                        "google_health_enabled": True,
                        "google_health_available_feature_count": 3,
                        "google_health_available_features": [
                            "heart_rate_mean",
                            "hrv_rmssd",
                            "spo2_mean",
                        ],
                        "mqtt_publish": {
                            "enabled": True,
                            "status": "published",
                            "attempted": 3,
                            "published": 3,
                            "queued": 0,
                            "queue_depth": 0,
                            "errors": [],
                        },
                    }
                },
            )
        )
        session.add(
            FeatureWindow(
                message_id="window-001",
                patient_id="patient-001",
                edge_id="edge-rpi5-001",
                timestamp=now,
                window_start=now,
                window_end=now,
                features={
                    "wearable_present": True,
                    "wearable_battery_pct": 80,
                    "heart_rate_mean": 70.0,
                    "kitchen_minutes": 3.0,
                    "bedroom_minutes": 1.0,
                },
            )
        )
        session.add_all(
            [
                SensorStatus(
                    patient_id="patient-001",
                    sensor_type="watch",
                    status="active",
                    last_seen_at=now,
                    details={},
                ),
                SensorStatus(
                    patient_id="patient-001",
                    sensor_type="ble",
                    status="active",
                    last_seen_at=now,
                    details={},
                ),
            ]
        )
        session.add(
            PatientAppStatus(
                patient_id="patient-001",
                device_id="android-test-001",
                status="online",
                last_seen_at=now,
                battery_pct=73,
                app_version="0.3.0",
                platform="android",
                fcm_token="private-token",
                notifications_enabled=True,
            )
        )
        session.add(
            Decision(
                message_id="decision-001",
                patient_id="patient-001",
                edge_id="edge-rpi5-001",
                timestamp=now,
                window_start=now,
                window_end=now,
                level="orange",
                should_publish=True,
                anomaly_score=72.5,
                model_label="test_model",
                payload={"payload": {"reasons": ["Score alto"], "evidence": {"fusion": {"score": 72.5}}}},
            )
        )
        session.add(
            Alert(
                message_id="alert-001",
                patient_id="patient-001",
                level="orange",
                status="new",
                category="behavioral",
                title="Alert test",
                description="Alert creato dal test",
                opened_at=now,
            )
        )
        session.commit()


def auth_headers(client: TestClient, email: str = DOCTOR_EMAIL) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_login_and_patient_current(client: TestClient) -> None:
    login = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "doctor"
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    patients = client.get("/api/v1/patients", headers=headers)
    assert patients.status_code == 200
    assert patients.json()["items"][0]["patient_id"] == "patient-001"

    current = client.get("/api/v1/patients/patient-001/current", headers=headers)
    assert current.status_code == 200
    body = current.json()
    assert body["level"] == "orange"
    assert body["current_room"] == "kitchen"
    assert body["watch"]["present"] is True
    assert body["edge"]["online"] is True


def test_windows_decisions_and_system_status(client: TestClient) -> None:
    headers = auth_headers(client)
    windows = client.get("/api/v1/patients/patient-001/windows?limit=5", headers=headers)
    assert windows.status_code == 200
    assert windows.json()["items"][0]["features"]["heart_rate_mean"] == 70.0

    decisions = client.get("/api/v1/patients/patient-001/decisions?limit=5", headers=headers)
    assert decisions.status_code == 200
    assert decisions.json()["items"][0]["reasons"] == ["Score alto"]

    system_status = client.get("/api/v1/patients/patient-001/system-status", headers=headers)
    assert system_status.status_code == 200
    body = system_status.json()
    assert body["sensors"]["google_health"]["status"] == "active"
    assert body["thresholds_minutes"]["edge_stale"] == 10
    assert body["edge"]["last_cycle_at"] is not None
    assert body["edge"]["status"] == "online"
    assert body["edge"]["quality_status"] == "warning"
    assert body["edge"]["mqtt"]["status"] == "published"
    assert body["sensors"]["ble"]["samples_collected"] == 12
    assert body["sensors"]["patient_app"]["status"] == "active"
    assert body["sensors"]["patient_app"]["fcm_registered"] is True
    assert "private-token" not in str(body)


def test_alert_acknowledge_and_resolve(client: TestClient) -> None:
    headers = auth_headers(client)
    alerts = client.get("/api/v1/patients/patient-001/alerts", headers=headers)
    alert_id = alerts.json()["items"][0]["alert_id"]

    acknowledged = client.patch(f"/api/v1/alerts/{alert_id}/acknowledge", json={}, headers=headers)
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "acknowledged"
    assert acknowledged.json()["acknowledged_by"] == "Medico Test"

    missing_note = client.patch(f"/api/v1/alerts/{alert_id}/resolve", json={}, headers=headers)
    assert missing_note.status_code == 422

    resolved = client.patch(
        f"/api/v1/alerts/{alert_id}/resolve",
        json={"note": "Controllo completato."},
        headers=headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution_note"] == "Controllo completato."


def test_task_create_list_and_result(client: TestClient) -> None:
    doctor_headers = auth_headers(client)
    created = client.post(
        "/api/v1/patients/patient-001/tasks",
        json={
            "type": "check_in",
            "priority": "normal",
            "title": "Controllo benessere",
            "payload": {"questions": []},
        },
        headers=doctor_headers,
    )
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    tasks = client.get("/api/v1/patients/patient-001/tasks", headers=doctor_headers)
    assert tasks.status_code == 200
    assert tasks.json()["items"][0]["task_id"] == task_id

    patient_headers = auth_headers(client, PATIENT_EMAIL)
    result = client.post(
        f"/api/v1/tasks/{task_id}/results",
        json={
            "patient_id": "patient-001",
            "completed_at": "2026-07-12T10:10:00Z",
            "answers": [{"question_id": "q1", "value": "bene"}],
            "score": None,
            "duration_seconds": 120,
        },
        headers=patient_headers,
    )
    assert result.status_code == 200
    assert result.json()["status"] == "received"
