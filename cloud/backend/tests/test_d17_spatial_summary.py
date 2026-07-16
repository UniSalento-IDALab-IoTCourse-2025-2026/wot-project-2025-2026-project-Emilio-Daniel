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
from app.db.models import Doctor, DoctorPatient, EdgeCycle, FeatureWindow, Patient, SensorStatus, User
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.spatial@example.invalid"


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
                Patient(patient_id="patient-001", display_name="Paziente Spatial"),
                Patient(patient_id="patient-999", display_name="Paziente Non Autorizzato"),
            ]
        )
        doctor_user = User(email=DOCTOR_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="doctor", display_name="Medico Spatial")
        session.add(doctor_user)
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="SPATIAL")
        session.add(doctor)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"))
        session.add(
            EdgeCycle(
                message_id="spatial-cycle-001",
                patient_id="patient-001",
                event_type="edge_cycle_completed",
                timestamp=now - timedelta(minutes=1),
                payload={"payload": {"baseline_auto_train": {"trained": False, "reason": "baseline_not_ready"}}},
            )
        )
        session.add(
            SensorStatus(
                patient_id="patient-001",
                sensor_type="ble",
                status="active",
                last_seen_at=now - timedelta(minutes=2),
                details={"current_room": "kitchen"},
            )
        )
        current_end = now - timedelta(hours=1)
        night_end = now.replace(hour=2, minute=10, second=0)
        if night_end > now:
            night_end = night_end - timedelta(days=1)
        rows = [
            (
                "spatial-window-current-1",
                current_end,
                {
                    "kitchen_minutes": 20.0,
                    "bedroom_minutes": 5.0,
                    "room_changes": 2,
                    "longest_single_room_minutes": 20.0,
                    "room_transitions": [{"from": "bedroom", "to": "kitchen", "count": 2}],
                },
            ),
            (
                "spatial-window-current-2",
                night_end,
                {
                    "bathroom_minutes": 4.0,
                    "bedroom_minutes": 4.0,
                    "room_changes": 1,
                    "night_room_changes": 1,
                    "longest_single_room_minutes": 8.0,
                },
            ),
            (
                "spatial-window-previous-1",
                now - timedelta(days=1, hours=1),
                {
                    "kitchen_minutes": 10.0,
                    "bedroom_minutes": 10.0,
                    "room_changes": 1,
                    "night_room_changes": 0,
                    "longest_single_room_minutes": 10.0,
                },
            ),
        ]
        for message_id, end, features in rows:
            session.add(
                FeatureWindow(
                    message_id=message_id,
                    patient_id="patient-001",
                    timestamp=end,
                    window_start=end - timedelta(minutes=4),
                    window_end=end,
                    features=features,
                )
            )
        session.commit()


def test_spatial_summary_aggregates_rooms_transitions_night_and_quality(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/spatial-summary?days=1", headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()

    assert body["patient_id"] == "patient-001"
    assert body["room_minutes"]["kitchen"] == 20.0
    assert body["room_minutes"]["bedroom"] == 9.0
    assert body["prevalent_room"] == "kitchen"
    assert body["transitions"]["total"] == 3.0
    assert body["transitions"]["matrix"]["bedroom"]["kitchen"] == 2
    assert body["night"]["room_changes"] == 1.0
    assert body["night"]["event_count"] == 1
    assert body["longest_single_room_minutes"] == 20.0
    assert body["baseline"]["source"] == "previous_period"
    assert body["baseline"]["comparison"]["room_minutes"]["kitchen"]["absolute"] == 10.0
    assert body["baseline"]["comparison"]["room_minutes"]["kitchen"]["percent"] == 100.0
    assert body["ble_quality"]["available_windows"] == 2
    assert body["ble_quality"]["expected_windows"] > 0
    assert body["ble_quality"]["sensor_status"] == "active"


def test_spatial_summary_handles_missing_reference(client: TestClient) -> None:
    response = client.get(
        "/api/v1/patients/patient-001/spatial-summary?date_from=2026-01-01T00:00:00Z&date_to=2026-01-02T00:00:00Z",
        headers=auth_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["windows"] == 0
    assert body["baseline"]["source"] == "none"
    assert body["baseline"]["reason"] == "reference_not_available"
    assert body["room_minutes"]["kitchen"] is None


def test_spatial_summary_requires_patient_authorization(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-999/spatial-summary", headers=auth_headers(client))
    assert response.status_code == 403


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
