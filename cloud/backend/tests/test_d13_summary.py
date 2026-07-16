from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Decision, Doctor, DoctorPatient, EdgeCycle, EdgeDevice, FeatureWindow, Patient, PatientAppStatus, User
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.summary@example.invalid"
OTHER_DOCTOR_EMAIL = "other.summary@example.invalid"


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
        session.add_all(
            [
                Patient(patient_id="patient-001", display_name="Paziente Demo"),
                Patient(patient_id="patient-empty", display_name="Paziente Senza Dati"),
                Patient(patient_id="patient-999", display_name="Paziente Non Autorizzato"),
            ]
        )
        doctor_user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico Summary",
        )
        other_doctor_user = User(
            email=OTHER_DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Altro Medico",
        )
        session.add_all([doctor_user, other_doctor_user])
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="SUMMARY")
        other_doctor = Doctor(user_id=other_doctor_user.id, license_number="OTHER")
        session.add_all([doctor, other_doctor])
        session.flush()
        session.add_all(
            [
                DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"),
                DoctorPatient(doctor_id=doctor.id, patient_id="patient-empty"),
                DoctorPatient(doctor_id=other_doctor.id, patient_id="patient-999"),
            ]
        )
        session.add(
            EdgeDevice(
                edge_id="edge-rpi5-summary",
                patient_id="patient-001",
                status="online",
                last_seen_at=now - timedelta(minutes=2),
            )
        )
        session.add(
            EdgeCycle(
                message_id="summary-cycle-001",
                patient_id="patient-001",
                edge_id="edge-rpi5-summary",
                event_type="edge_cycle_completed",
                timestamp=now - timedelta(minutes=2),
                window_start=now - timedelta(minutes=6),
                window_end=now - timedelta(minutes=2),
                payload={
                    "payload": {
                        "status": "cycle_completed",
                        "mqtt_publish": {
                            "enabled": True,
                            "status": "published",
                            "attempted": 3,
                            "published": 3,
                            "queued": 0,
                            "queue_depth": 0,
                            "errors": [],
                        },
                        "baseline_auto_train": {
                            "trained": False,
                            "reason": "not_enough_windows",
                            "baseline_row_count": 150,
                            "min_training_windows": 1000,
                        },
                    }
                },
            )
        )
        session.add(
            PatientAppStatus(
                patient_id="patient-001",
                device_id="android-summary",
                status="online",
                last_seen_at=now - timedelta(minutes=3),
                battery_pct=67,
                platform="android",
                fcm_token="private-token",
                notifications_enabled=True,
            )
        )
        for index, (hours_ago, features) in enumerate(
            [
                (
                    20,
                    {
                        "heart_rate_mean": 70.0,
                        "spo2_mean": 96.0,
                        "steps": 10,
                        "kitchen_minutes": 20.0,
                        "bedroom_minutes": 10.0,
                        "room_changes": 2,
                        "night_room_changes": 1,
                        "longest_single_room_minutes": 30.0,
                    },
                ),
                (
                    12,
                    {
                        "heart_rate_mean": 80.0,
                        "spo2_mean": 94.0,
                        "steps": 20,
                        "kitchen_minutes": 30.0,
                        "living_room_minutes": 15.0,
                        "room_changes": 1,
                        "longest_single_room_minutes": 45.0,
                    },
                ),
                (
                    1,
                    {
                        "wearable_present": True,
                        "kitchen_minutes": 5.0,
                        "bathroom_minutes": 5.0,
                        "room_changes": 0,
                    },
                ),
            ],
            start=1,
        ):
            end = now - timedelta(hours=hours_ago)
            session.add(
                FeatureWindow(
                    message_id=f"summary-window-{index}",
                    patient_id="patient-001",
                    edge_id="edge-rpi5-summary",
                    timestamp=end,
                    window_start=end - timedelta(minutes=4),
                    window_end=end,
                    features=features,
                )
            )
        previous_end = now - timedelta(hours=30)
        session.add(
            FeatureWindow(
                message_id="summary-window-previous",
                patient_id="patient-001",
                edge_id="edge-rpi5-summary",
                timestamp=previous_end,
                window_start=previous_end - timedelta(minutes=4),
                window_end=previous_end,
                features={"heart_rate_mean": 60.0, "kitchen_minutes": 10.0},
            )
        )
        for message_id, hours_ago, score, level in [
            ("summary-decision-1", 20, 40.0, "yellow"),
            ("summary-decision-2", 1, 80.0, "orange"),
            ("summary-decision-previous", 30, 20.0, "green"),
        ]:
            timestamp = now - timedelta(hours=hours_ago)
            session.add(
                Decision(
                    message_id=message_id,
                    patient_id="patient-001",
                    edge_id="edge-rpi5-summary",
                    timestamp=timestamp,
                    window_start=timestamp - timedelta(minutes=4),
                    window_end=timestamp,
                    level=level,
                    should_publish=level in {"orange", "red"},
                    anomaly_score=score,
                    model_label="summary-test",
                    payload={"payload": {"reasons": ["summary"]}},
                )
            )
        session.commit()


def auth_headers(client: TestClient, email: str = DOCTOR_EMAIL) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_patient_summary_24h_aggregates_ai_wearable_spatial_and_completeness(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/summary/24h", headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()

    assert body["patient_id"] == "patient-001"
    assert body["counts"]["windows"] == 3
    assert body["counts"]["decisions"] == 2
    assert body["ai"]["average_score"] == 60.0
    assert body["ai"]["max_score"] == 80.0
    assert body["ai"]["last_score"] == 80.0
    assert body["ai"]["last_level"] == "orange"
    assert body["ai"]["previous_day_average_score"] == 20.0
    assert body["ai"]["score_delta_vs_previous_day"] == 40.0
    assert body["spatial"]["prevalent_room"] == "kitchen"
    assert body["spatial"]["room_minutes"]["kitchen"] == 55.0
    assert body["spatial"]["room_changes"] == 3.0
    assert body["spatial"]["night_room_changes"] == 1.0
    assert body["spatial"]["longest_single_room_minutes"] == 45.0
    assert body["wearable"]["heart_rate"]["average"] == 75.0
    assert body["wearable"]["spo2"]["average"] == 95.0
    assert body["wearable"]["steps"]["total"] == 30.0
    assert body["data_completeness"]["ble"]["level"] == "alta"
    assert body["data_completeness"]["google_health"]["level"] == "media"
    assert body["data_completeness"]["patient_app"]["status"] == "active"
    assert body["data_completeness"]["mqtt"]["status"] == "published"
    assert body["baseline"]["available"] is False
    assert body["baseline"]["reason"] == "not_enough_windows"


def test_patient_summary_24h_handles_missing_data(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-empty/summary/24h", headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()

    assert body["counts"]["windows"] == 0
    assert body["ai"]["average_score"] is None
    assert body["spatial"]["prevalent_room"] is None
    assert body["wearable"]["heart_rate"]["average"] is None
    assert body["data_completeness"]["overall"]["level"] == "bassa"


def test_patient_summary_24h_requires_patient_authorization(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-999/summary/24h", headers=auth_headers(client))
    assert response.status_code == 403
