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
from app.db.models import Decision, Doctor, DoctorPatient, FeatureWindow, Patient, User
from app.db.session import get_db
from app.main import app
from app.services.morning_brief import morning_brief_payload, morning_night_bounds

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.morning.d29@example.invalid"
PATIENT_ID = "patient-001"

REFERENCE = datetime(2026, 9, 9, 14, 0, tzinfo=timezone.utc)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _night_end(reference: datetime) -> datetime:
    _, end = morning_night_bounds(reference)
    return end


def _seed_night(session: Session, patient_id: str, night_end: datetime, *, scores: list[float] | None = None) -> None:
    start = night_end - timedelta(hours=10)
    for index in range(6):
        ts = start + timedelta(hours=1 + index * 1.5)
        active = index in (3, 4)
        session.add(
            FeatureWindow(
                message_id=f"mb-win-{night_end.isoformat()}-{index}",
                patient_id=patient_id,
                timestamp=ts,
                window_start=ts,
                window_end=ts + timedelta(minutes=30),
                features={
                    "sleep_minutes": 80,
                    "awake_minutes": 5 if active else 0,
                    "heart_rate_mean": 60,
                    "spo2_mean": 97.0,
                    "night_room_changes": 1 if active else 0,
                    "bedroom_minutes": 20,
                    "kitchen_minutes": 3 if index < 5 else 0,
                },
            )
        )
    for index, score in enumerate(scores or [20.0, 25.0, 30.0]):
        ts = start + timedelta(hours=1 + index)
        session.add(
            Decision(
                message_id=f"mb-dec-{night_end.isoformat()}-{index}",
                patient_id=patient_id,
                timestamp=ts,
                window_start=ts,
                window_end=ts + timedelta(minutes=4),
                level="green",
                should_publish=False,
                anomaly_score=score,
            )
        )
    session.commit()


def test_morning_night_bounds_after_8am():
    start, end = morning_night_bounds(REFERENCE)
    assert (end - start) == timedelta(hours=10)
    assert end <= REFERENCE
    assert end.isoformat().startswith("2026-09-09")
    assert start.isoformat().startswith("2026-09-08")
    assert end.hour == 6  # 08:00 Europe/Rome = 06:00 UTC
    assert (start.day, end.day) == (8, 9)


def test_morning_night_bounds_before_8am():
    reference = datetime(2026, 9, 9, 4, 0, tzinfo=timezone.utc)
    start, end = morning_night_bounds(reference)
    assert (end - start) == timedelta(hours=10)
    assert end < reference
    assert end.isoformat().startswith("2026-09-08")


def test_morning_brief_computes_metrics():
    with make_session() as session:
        night_end = _night_end(REFERENCE)
        _seed_night(session, PATIENT_ID, night_end, scores=[20.0, 25.0, 30.0])
        payload = morning_brief_payload(session, PATIENT_ID, reference=REFERENCE)

        assert payload["sleep_minutes"] == pytest.approx(480.0, abs=0.01)
        assert payload["awake_minutes"] == pytest.approx(10.0, abs=0.01)
        assert payload["wakeups"] == 2
        assert payload["night_room_changes"] == pytest.approx(2.0, abs=0.01)
        assert payload["night_heart_rate_mean"] == pytest.approx(60.0, abs=0.01)
        assert payload["spo2_mean"] == 97.0
        assert payload["away_from_bedroom_minutes"] == pytest.approx(15.0, abs=0.01)
        assert payload["ai_score"] == pytest.approx(25.0, abs=0.01)
        assert payload["max_score"] == 30.0
        assert payload["confidence"] == "alta"
        assert payload["summary"].startswith("Notte")
        assert "2 movimenti notturni" in payload["summary"]


def test_morning_brief_baseline_unavailable_without_history():
    with make_session() as session:
        night_end = _night_end(REFERENCE)
        _seed_night(session, PATIENT_ID, night_end)
        payload = morning_brief_payload(session, PATIENT_ID, reference=REFERENCE)
        assert payload["baseline"]["available"] is False
        assert payload["baseline"]["nights"] == 0


def test_morning_brief_compares_with_baseline():
    with make_session() as session:
        night_end = _night_end(REFERENCE)
        _seed_night(session, PATIENT_ID, night_end, scores=[20.0, 25.0, 30.0])
        for offset in range(1, 4):
            _seed_night(session, PATIENT_ID, night_end - timedelta(days=offset), scores=[18.0, 22.0, 26.0])
        payload = morning_brief_payload(session, PATIENT_ID, reference=REFERENCE)

        assert payload["baseline"]["available"] is True
        assert payload["baseline"]["nights"] == 3
        assert payload["baseline"]["sleep_minutes"] == pytest.approx(480.0, abs=0.01)
        assert payload["vs_baseline"]["sleep_delta_minutes"] == pytest.approx(0.0, abs=0.01)
        assert payload["vs_baseline"]["ai_score_delta"] == pytest.approx(3.0, abs=0.01)


def test_morning_brief_summary_reflects_sleep_reduction():
    with make_session() as session:
        night_end = _night_end(REFERENCE)
        _seed_night(session, PATIENT_ID, night_end, scores=[20.0, 25.0, 30.0])
        for offset in range(1, 4):
            _seed_night(session, PATIENT_ID, night_end - timedelta(days=offset), scores=[18.0, 22.0, 26.0])
        # Riduci il sonno della notte in esame per forzare "sonno ridotto".
        for window in session.query(FeatureWindow).filter(
            FeatureWindow.window_end <= night_end,
            FeatureWindow.window_end > night_end - timedelta(hours=10),
        ):
            window.features = {**window.features, "sleep_minutes": 60}
        session.commit()
        payload = morning_brief_payload(session, PATIENT_ID, reference=REFERENCE)
        assert "sonno" in payload["summary"]

        # baseline è 480 → la riduzione porta il delta sotto -30
        assert payload["vs_baseline"]["sleep_delta_minutes"] is not None
        assert payload["vs_baseline"]["sleep_delta_minutes"] < -30


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
        session.add(Patient(patient_id=PATIENT_ID, display_name="Paziente D29"))
        doctor_user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico D29",
        )
        session.add(doctor_user)
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="D29")
        session.add(doctor)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id=PATIENT_ID))
        session.commit()


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_morning_brief_endpoint_returns_payload(client: TestClient) -> None:
    override = app.dependency_overrides.get(get_db)
    assert override is not None
    with next(override()) as session:
        _seed_night(session, PATIENT_ID, _night_end(datetime.now(timezone.utc)))
    response = client.get(f"/api/v1/patients/{PATIENT_ID}/morning-brief", headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == PATIENT_ID
    assert body["summary"]
    assert "sleep_minutes" in body
    assert "confidence" in body
    assert "baseline" in body