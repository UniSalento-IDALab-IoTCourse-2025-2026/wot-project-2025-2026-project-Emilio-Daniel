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
from app.db.models import Decision, Doctor, DoctorPatient, ModelRetrainingLog, Patient, PatientModelDrift, User
from app.db.session import get_db
from app.main import app
from app.services.drift import (
    approve_retraining,
    drift_state_payload,
    refresh_patient_drift,
    reject_retraining,
    personal_score_stats,
)

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.drift.d27@example.invalid"

REFERENCE = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


class _FakeUser:
    def __init__(self, uid=1, role="doctor"):
        self.id = uid
        self.role = role


def _seed_baseline_and_recent(session, patient_id="patient-001", baseline_mean=30.0, recent_mean=40.0):
    base = REFERENCE - timedelta(days=35)
    for i in range(10):
        ts = base + timedelta(days=i * 2)
        session.add(
            Decision(
                message_id=f"drift-base-{i:03d}",
                patient_id=patient_id,
                timestamp=ts,
                window_start=ts,
                window_end=ts + timedelta(minutes=4),
                level="green",
                should_publish=False,
                anomaly_score=baseline_mean + (i % 3),
            )
        )
    for i in range(10):
        ts = REFERENCE - timedelta(days=14) + timedelta(days=i)
        session.add(
            Decision(
                message_id=f"drift-recent-{i:03d}",
                patient_id=patient_id,
                timestamp=ts,
                window_start=ts,
                window_end=ts + timedelta(minutes=4),
                level="orange" if i > 6 else "green",
                should_publish=False,
                anomaly_score=recent_mean + (i % 2),
            )
        )
    session.commit()


def test_personal_score_stats():
    with make_session() as session:
        _seed_baseline_and_recent(session)
        baseline = personal_score_stats(
            session, "patient-001", REFERENCE - timedelta(days=35), REFERENCE - timedelta(days=15)
        )
        assert baseline["count"] == 10
        assert 30.0 <= baseline["mean"] <= 32.0
        recent = personal_score_stats(session, "patient-001", REFERENCE - timedelta(days=14), REFERENCE)
        assert recent["count"] == 10
        assert 40.0 <= recent["mean"] <= 41.0


def test_refresh_patient_drift_detects_drift():
    with make_session() as session:
        _seed_baseline_and_recent(session, recent_mean=42.0)
        user = _FakeUser()
        payload = refresh_patient_drift(session, "patient-001", user)
        assert payload["status"] in {"possible_drift", "needs_review"}
        assert payload["requires_approval"] is True
        assert payload["baseline"]["available"] is True
        assert payload["detected_at"] is not None


def test_refresh_patient_drift_stable_when_similar():
    with make_session() as session:
        _seed_baseline_and_recent(session, recent_mean=31.0)
        user = _FakeUser()
        payload = refresh_patient_drift(session, "patient-001", user)
        assert payload["status"] == "stable"
        assert payload["requires_approval"] is False


def test_refresh_patient_drift_insufficient_data():
    with make_session() as session:
        session.add(
            Decision(
                message_id="drift-single",
                patient_id="patient-001",
                timestamp=REFERENCE,
                window_start=REFERENCE,
                window_end=REFERENCE + timedelta(minutes=4),
                level="green",
                should_publish=False,
                anomaly_score=30.0,
            )
        )
        session.commit()
        user = _FakeUser()
        payload = refresh_patient_drift(session, "patient-001", user)
        assert payload["status"] == "stable"
        assert payload["baseline"]["available"] is False


def test_refresh_patient_drift_escalates_to_needs_review():
    with make_session() as session:
        _seed_baseline_and_recent(session, recent_mean=45.0)
        user = _FakeUser()
        refresh_patient_drift(session, "patient-001", user)
        second = refresh_patient_drift(session, "patient-001", user)
        assert second["status"] == "needs_review"
        assert second["drift_count"] >= 2


def test_approve_retraining_sets_retrained():
    with make_session() as session:
        _seed_baseline_and_recent(session, recent_mean=45.0)
        user = _FakeUser()
        refresh_patient_drift(session, "patient-001", user)
        refresh_patient_drift(session, "patient-001", user)
        payload = approve_retraining(session, "patient-001", user, note="Medico approva")
        assert payload["status"] == "retrained"
        assert payload["requires_approval"] is False
        assert payload["retrained_at"] is not None
        log = session.execute(
            select(ModelRetrainingLog).where(
                ModelRetrainingLog.patient_id == "patient-001",
                ModelRetrainingLog.action == "approved",
            )
        ).scalars().all()
        assert len(log) == 1
        assert "Medico approva" in (log[0].note or "")


def test_reject_retraining_sets_stable():
    with make_session() as session:
        _seed_baseline_and_recent(session, recent_mean=45.0)
        user = _FakeUser()
        refresh_patient_drift(session, "patient-001", user)
        refresh_patient_drift(session, "patient-001", user)
        payload = reject_retraining(session, "patient-001", user, note="Bloccato")
        assert payload["status"] == "stable"
        assert payload["requires_approval"] is False
        log = session.execute(
            select(ModelRetrainingLog).where(
                ModelRetrainingLog.patient_id == "patient-001",
                ModelRetrainingLog.action == "blocked",
            )
        ).scalars().all()
        assert len(log) == 1


def test_drift_resets_when_scores_return_to_normal():
    with make_session() as session:
        _seed_baseline_and_recent(session, recent_mean=45.0)
        user = _FakeUser()
        refresh_patient_drift(session, "patient-001", user)
        refresh_patient_drift(session, "patient-001", user)
        for i in range(10):
            dec = session.execute(
                select(Decision).where(Decision.message_id == f"drift-recent-{i:03d}")
            ).scalar_one()
            dec.anomaly_score = 30.0 + (i % 3)
        session.commit()
        result = refresh_patient_drift(session, "patient-001", user)
        assert result["status"] == "stable"
        assert result["requires_approval"] is False


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
        session.add(Patient(patient_id="patient-001", display_name="Paziente D27"))
        doctor_user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico D27",
        )
        session.add(doctor_user)
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="D27")
        session.add(doctor)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"))
        session.commit()


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_drift_endpoint_returns_state(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/ai/drift", headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()
    assert "drift" in body
    assert "status" in body["drift"]
    assert "retraining_log" in body


def test_approve_endpoint_retrained(client: TestClient) -> None:
    response = client.post(
        "/api/v1/patients/patient-001/ai/retraining/approve",
        json={"note": "Test approvazione"},
        headers=auth_headers(client),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "retrained"
    assert body["drift"]["retrained_at"] is not None


def test_reject_endpoint_stable(client: TestClient) -> None:
    response = client.post(
        "/api/v1/patients/patient-001/ai/retraining/reject",
        json={"note": "Blocco"},
        headers=auth_headers(client),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "stable"


def test_model_metrics_includes_drift(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/ai/model-metrics", headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()
    assert "drift" in body
    assert "status" in body["drift"]