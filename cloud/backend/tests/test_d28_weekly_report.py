from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
    FeatureWindow,
    Patient,
    Task,
    TaskResult,
    User,
    WeeklyReport,
)
from app.db.session import get_db
from app.main import app
from app.services.weekly_report import (
    generate_weekly_report,
    week_bounds,
    weekly_reports_payload,
)

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.weekly.d28@example.invalid"
PATIENT_ID = "patient-001"


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _week_range() -> tuple[datetime, datetime]:
    return week_bounds(datetime.now(timezone.utc))


def _seed_full_week(session: Session, patient_id: str = PATIENT_ID) -> None:
    """Popola una settimana completa con dati multi-fonte per D28."""
    week_start, week_end = _week_range()

    samples = [
        (0, "green", 20.0),
        (1, "yellow", 40.0),
        (2, "green", 25.0),
        (3, "orange", 65.0),
        (4, "green", 22.0),
        (5, "red", 88.0),
        (6, "green", 24.0),
    ]
    for index, (day, level, score) in enumerate(samples):
        ts = week_start + timedelta(days=day, hours=10)
        session.add(
            Decision(
                message_id=f"weekly-dec-{index:03d}",
                patient_id=patient_id,
                timestamp=ts,
                window_start=ts,
                window_end=ts + timedelta(minutes=4),
                level=level,
                should_publish=level == "red",
                anomaly_score=score,
                payload={"evidence": {}},
            )
        )

    for day in range(7):
        ts = week_start + timedelta(days=day, hours=6)
        session.add(
            FeatureWindow(
                message_id=f"weekly-win-{day:03d}",
                patient_id=patient_id,
                timestamp=ts,
                window_start=ts,
                window_end=ts + timedelta(hours=4),
                features={
                    "sleep_minutes": 480 if day != 2 else 300,
                    "steps": 3000,
                    "night_room_changes": 2,
                    "bedroom_minutes": 500,
                    "kitchen_minutes": 200,
                },
            )
        )

    for index in range(2):
        opened = week_start + timedelta(days=index, hours=12)
        session.add(
            Alert(
                message_id=f"weekly-alert-{index:03d}",
                patient_id=patient_id,
                level="orange",
                status="resolved" if index == 0 else "new",
                category="behavioral",
                title="Segnale da verificare",
                opened_at=opened,
                closed_at=opened + timedelta(hours=3) if index == 0 else None,
            )
        )

    task = Task(
        patient_id=patient_id,
        task_type="check_in",
        status="completed",
        title="Controllo benessere",
    )
    session.add(task)
    session.flush()
    session.add(
        TaskResult(
            task_id=task.id,
            message_id="weekly-task-result-001",
            patient_id=patient_id,
            completed_at=week_start + timedelta(days=1, hours=9),
            result={"answer": "bene"},
        )
    )
    session.commit()


def test_week_bounds_starts_on_monday():
    start, end = week_bounds(datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc))
    assert start.isoformat().startswith("2026-09-07")
    assert (end - start).days == 7


def test_generate_weekly_report_aggregates_metrics():
    with make_session() as session:
        _seed_full_week(session)
        payload = generate_weekly_report(session, PATIENT_ID)

        assert payload["mean_score"] == pytest.approx(40.571, abs=0.01)
        assert payload["max_score"] == 88.0
        assert payload["attention_days"] == 1
        assert payload["risk_days"] == 1
        assert payload["alert_days"] == 1
        assert payload["alerts"]["created"] == 2
        assert payload["alerts"]["resolved"] == 1
        assert payload["tasks"]["sent"] == 1
        assert payload["tasks"]["completed"] == 1
        assert payload["sleep"]["mean_minutes"] == pytest.approx(454.29, abs=0.01)
        assert payload["steps"]["mean"] == 3000.0
        assert payload["night_room_changes"] == 2.0
        assert payload["prevalent_room"] == "bedroom"
        assert "Riepilogo" in payload["summary"] or "Score AI" in payload["summary"]
        assert payload["range"]["days"] == 7
        assert payload["week_start"] and payload["week_end"]


def test_generate_weekly_report_is_idempotent_and_force_regenerates():
    with make_session() as session:
        _seed_full_week(session)
        first = generate_weekly_report(session, PATIENT_ID)
        second = generate_weekly_report(session, PATIENT_ID)
        assert second["report_id"] == first["report_id"]
        rows = session.execute(
            select(WeeklyReport).where(WeeklyReport.patient_id == PATIENT_ID)
        ).scalars().all()
        assert len(rows) == 1

        forced = generate_weekly_report(session, PATIENT_ID, force=True)
        assert forced["report_id"] == first["report_id"]
        assert session.execute(
            select(WeeklyReport).where(WeeklyReport.patient_id == PATIENT_ID)
        ).scalars().all()


def test_generate_weekly_report_compares_with_previous_week():
    with make_session() as session:
        _seed_full_week(session)
        week_start, week_end = _week_range()

        for index in range(3):
            ts = week_start - timedelta(days=7) + timedelta(days=index, hours=10)
            session.add(
                Decision(
                    message_id=f"weekly-prev-{index:03d}",
                    patient_id=PATIENT_ID,
                    timestamp=ts,
                    window_start=ts,
                    window_end=ts + timedelta(minutes=4),
                    level="green",
                    should_publish=False,
                    anomaly_score=30.0 + index,
                )
            )
        session.commit()

        previous = generate_weekly_report(
            session, PATIENT_ID, reference=week_start - timedelta(days=1)
        )
        current = generate_weekly_report(session, PATIENT_ID)
        assert previous["mean_score"] == pytest.approx(31.0)
        assert current["vs_previous_mean_score"] == pytest.approx(31.0)
        assert current["vs_previous_attention_days"] == 0


def test_weekly_reports_payload_returns_sorted_reports():
    with make_session() as session:
        _seed_full_week(session)
        generate_weekly_report(session, PATIENT_ID)
        payload = weekly_reports_payload(session, PATIENT_ID, limit=8)
        assert len(payload) == 1
        report = payload[0]
        assert report["report_id"].startswith("WeeklyReport:")
        assert report["mean_score"] is not None
        assert report["sleep"]["mean_minutes"] is not None
        assert report["tasks"]["completed"] == 1


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
        session.add(Patient(patient_id=PATIENT_ID, display_name="Paziente D28"))
        doctor_user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico D28",
        )
        session.add(doctor_user)
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="D28")
        session.add(doctor)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id=PATIENT_ID))
        session.commit()


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _seed_client_db() -> None:
    override = app.dependency_overrides.get(get_db)
    assert override is not None
    with next(override()) as session:
        _seed_full_week(session)


def test_weekly_reports_endpoint_returns_items(client: TestClient) -> None:
    _seed_client_db()
    response = client.get(
        f"/api/v1/patients/{PATIENT_ID}/reports/weekly",
        headers=auth_headers(client),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == PATIENT_ID
    assert isinstance(body["items"], list)
    assert isinstance(body["reports"], list)
    report = body["items"][0]
    assert report["title"]
    assert report["week_start"]
    assert report["mean_score"] == pytest.approx(40.571, abs=0.01)
    assert report["tasks"]["completed"] == 1
    assert report["sleep"]["mean_minutes"] is not None
    assert report["summary"]


def test_weekly_reports_endpoint_autogenerates_on_empty(client: TestClient) -> None:
    response = client.get(
        f"/api/v1/patients/{PATIENT_ID}/reports/weekly",
        headers=auth_headers(client),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) >= 1


def test_generate_report_endpoint_manual(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/patients/{PATIENT_ID}/reports/generate",
        json={"force": True},
        headers=auth_headers(client),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["generated"] is True
    assert body["report"]["report_id"]