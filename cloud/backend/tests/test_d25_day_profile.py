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
from app.db.models import Decision, Doctor, DoctorPatient, FeatureWindow, Patient, User
from app.db.session import get_db
from app.main import app
from app.api.routes.patients import day_profile_payload

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.dayprofile.d25@example.invalid"

REFERENCE = datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc)  # 15:00 local Europe/Rome


def utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_day_profile(session):
    session.add(
        FeatureWindow(
            message_id="d25-today-07",
            patient_id="patient-001",
            timestamp=utc(2026, 9, 8, 5, 0),
            window_start=utc(2026, 9, 8, 5, 0),
            window_end=utc(2026, 9, 8, 5, 4),
            features={
                "heart_rate_mean": 72,
                "steps": 500,
                "sedentary_minutes": 60,
                "room_changes": 1,
                "sleep_minutes": 0,
                "bedroom_minutes": 3.0,
                "kitchen_minutes": 1.0,
            },
        )
    )
    session.add(
        FeatureWindow(
            message_id="d25-today-11",
            patient_id="patient-001",
            timestamp=utc(2026, 9, 8, 9, 0),
            window_start=utc(2026, 9, 8, 9, 0),
            window_end=utc(2026, 9, 8, 9, 4),
            features={
                "heart_rate_mean": 88,
                "steps": 1200,
                "sedentary_minutes": 30,
                "room_changes": 2,
                "sleep_minutes": 0,
                "kitchen_minutes": 3.0,
                "living_room_minutes": 2.0,
            },
        )
    )
    session.add(
        FeatureWindow(
            message_id="d25-yesterday-15",
            patient_id="patient-001",
            timestamp=utc(2026, 9, 7, 13, 0),
            window_start=utc(2026, 9, 7, 13, 0),
            window_end=utc(2026, 9, 7, 13, 4),
            features={
                "heart_rate_mean": 75,
                "steps": 900,
                "sedentary_minutes": 40,
                "room_changes": 1,
                "sleep_minutes": 0,
                "living_room_minutes": 4.0,
            },
        )
    )
    session.add(
        FeatureWindow(
            message_id="d25-base-07",
            patient_id="patient-001",
            timestamp=utc(2026, 9, 6, 5, 0),
            window_start=utc(2026, 9, 6, 5, 0),
            window_end=utc(2026, 9, 6, 5, 4),
            features={
                "heart_rate_mean": 70,
                "steps": 800,
                "sedentary_minutes": 55,
                "room_changes": 1,
                "sleep_minutes": 0,
                "bedroom_minutes": 4.0,
            },
        )
    )
    session.add(
        FeatureWindow(
            message_id="d25-base-11",
            patient_id="patient-001",
            timestamp=utc(2026, 9, 6, 9, 0),
            window_start=utc(2026, 9, 6, 9, 0),
            window_end=utc(2026, 9, 6, 9, 4),
            features={
                "heart_rate_mean": 65,
                "steps": 700,
                "sedentary_minutes": 50,
                "room_changes": 2,
                "sleep_minutes": 0,
                "kitchen_minutes": 4.0,
            },
        )
    )
    session.add(
        Decision(
            message_id="d25-dec-today-07",
            patient_id="patient-001",
            timestamp=utc(2026, 9, 8, 5, 0),
            window_start=utc(2026, 9, 8, 5, 0),
            window_end=utc(2026, 9, 8, 5, 4),
            level="orange",
            should_publish=True,
            anomaly_score=45.0,
        )
    )
    session.add(
        Decision(
            message_id="d25-dec-today-11",
            patient_id="patient-001",
            timestamp=utc(2026, 9, 8, 9, 0),
            window_start=utc(2026, 9, 8, 9, 0),
            window_end=utc(2026, 9, 8, 9, 4),
            level="orange",
            should_publish=True,
            anomaly_score=55.0,
        )
    )
    session.add(
        Decision(
            message_id="d25-dec-base-07",
            patient_id="patient-001",
            timestamp=utc(2026, 9, 6, 5, 0),
            window_start=utc(2026, 9, 6, 5, 0),
            window_end=utc(2026, 9, 6, 5, 4),
            level="green",
            should_publish=False,
            anomaly_score=30.0,
        )
    )
    session.commit()


def test_day_profile_empty_no_baseline():
    with make_session() as session:
        result = day_profile_payload(session, "patient-001", reference=REFERENCE)
        assert result["baseline_available"] is False
        assert result["bands"] == ["00-06", "06-10", "10-14", "14-18", "18-22", "22-24"]
        assert len(result["today"]) == 6
        assert len(result["yesterday"]) == 6
        assert len(result["baseline_day"]) == 6
        assert all(row["ai"] is None for row in result["today"])


def test_day_profile_bands_values_and_rooms():
    with make_session() as session:
        _seed_day_profile(session)
        result = day_profile_payload(session, "patient-001", reference=REFERENCE)
        assert result["baseline_available"] is True
        assert result["bands"] == ["00-06", "06-10", "10-14", "14-18", "18-22", "22-24"]

        today = {row["band"]: row for row in result["today"]}
        assert today["06-10"]["ai"] == pytest.approx(45.0)
        assert today["06-10"]["heart_rate_mean"] == pytest.approx(72.0)
        assert today["06-10"]["steps"] == pytest.approx(500.0)
        assert today["06-10"]["sedentary_minutes"] == pytest.approx(60.0)
        assert today["06-10"]["room_changes"] == pytest.approx(1.0)
        assert today["06-10"]["dominant_room"] == "bedroom"

        assert today["10-14"]["ai"] == pytest.approx(55.0)
        assert today["10-14"]["heart_rate_mean"] == pytest.approx(88.0)
        assert today["10-14"]["dominant_room"] == "kitchen"

        yesterday = {row["band"]: row for row in result["yesterday"]}
        assert yesterday["14-18"]["heart_rate_mean"] == pytest.approx(75.0)
        assert yesterday["14-18"]["dominant_room"] == "living_room"

        baseline = {row["band"]: row for row in result["baseline_day"]}
        assert baseline["06-10"]["ai"] == pytest.approx(30.0)
        assert baseline["06-10"]["heart_rate_mean"] == pytest.approx(70.0)
        assert baseline["06-10"]["steps"] == pytest.approx(800.0)
        assert baseline["10-14"]["heart_rate_mean"] == pytest.approx(65.0)
        assert baseline["10-14"]["dominant_room"] == "kitchen"


def test_day_profile_timezone_band_for_late_utc_window():
    with make_session() as session:
        session.add(
            FeatureWindow(
                message_id="d25-late-utc",
                patient_id="patient-001",
                timestamp=utc(2026, 9, 8, 23, 30),
                window_start=utc(2026, 9, 8, 23, 30),
                window_end=utc(2026, 9, 8, 23, 34),
                features={"heart_rate_mean": 61, "sleep_minutes": 10, "bedroom_minutes": 4.0},
            )
        )
        session.commit()
        result = day_profile_payload(session, "patient-001", reference=REFERENCE)
        baseline = {row["band"]: row for row in result["baseline_day"]}
        assert baseline["00-06"]["sleep_minutes"] == pytest.approx(10.0)
        assert baseline["00-06"]["heart_rate_mean"] == pytest.approx(61.0)


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
    with Session(engine) as session:
        session.add(Patient(patient_id="patient-001", display_name="Paziente D25"))
        doctor_user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico D25",
        )
        session.add(doctor_user)
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="D25")
        session.add(doctor)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"))
        session.commit()


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_day_profile_endpoint_shape(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/day-profile", headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()
    assert "today" in body and "yesterday" in body and "baseline_day" in body
    assert body["bands"] == ["00-06", "06-10", "10-14", "14-18", "18-22", "22-24"]
    assert len(body["today"]) == 6
    assert "baseline_available" in body
    assert body["today"][0]["band"] == "00-06"