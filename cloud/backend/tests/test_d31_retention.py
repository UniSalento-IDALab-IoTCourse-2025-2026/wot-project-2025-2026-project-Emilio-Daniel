from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import (
    Alert,
    Decision,
    EdgeCycle,
    FeatureWindow,
    Patient,
    SensorStatus,
    User,
)
from app.db.session import get_db
from app.main import app
from app.services.retention import (
    purge_old_decisions,
    purge_old_edge_cycles,
    purge_old_feature_windows,
    purge_old_sensor_status,
    retention_summary,
    run_full_purge,
)

TEST_PASSWORD = "unit-test-password-not-secret"
ADMIN_EMAIL = "admin.retention@example.invalid"
DOCTOR_EMAIL = "doctor.retention@example.invalid"
PATIENT_ID = "patient-001"

OLD = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
RECENT = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_data(session: Session) -> None:
    session.add(Patient(patient_id=PATIENT_ID, display_name="Retention Patient"))
    session.add(FeatureWindow(
        message_id="fw-old", patient_id=PATIENT_ID,
        timestamp=OLD, window_start=OLD, window_end=OLD + timedelta(minutes=4),
        features={"steps": 100}, created_at=OLD,
    ))
    session.add(FeatureWindow(
        message_id="fw-recent", patient_id=PATIENT_ID,
        timestamp=RECENT, window_start=RECENT, window_end=RECENT + timedelta(minutes=4),
        features={"steps": 200}, created_at=RECENT,
    ))
    session.add(Decision(
        message_id="dec-old", patient_id=PATIENT_ID,
        timestamp=OLD, window_start=OLD, window_end=OLD + timedelta(minutes=4),
        level="green", should_publish=False, anomaly_score=20.0, created_at=OLD,
    ))
    session.add(Decision(
        message_id="dec-recent", patient_id=PATIENT_ID,
        timestamp=RECENT, window_start=RECENT, window_end=RECENT + timedelta(minutes=4),
        level="green", should_publish=False, anomaly_score=25.0, created_at=RECENT,
    ))
    session.add(EdgeCycle(
        message_id="ec-old", patient_id=PATIENT_ID,
        event_type="cycle_completed", timestamp=OLD, payload={}, created_at=OLD,
    ))
    session.add(SensorStatus(
        patient_id=PATIENT_ID, sensor_type="ble", status="active",
        last_seen_at=OLD, details={}, created_at=OLD,
    ))
    session.add(Alert(
        message_id="alert-old", patient_id=PATIENT_ID,
        level="orange", status="new", category="behavioral",
        title="Old alert", opened_at=OLD, created_at=OLD,
    ))
    session.commit()


def test_retention_summary_counts_correctly() -> None:
    with make_session() as session:
        _seed_data(session)
        summary = retention_summary(session, now=RECENT)
        assert summary["counts"]["feature_windows"]["total"] == 2
        assert summary["counts"]["feature_windows"]["purgable"] == 1
        assert summary["counts"]["decisions"]["purgable"] == 1
        assert summary["counts"]["edge_cycles"]["purgable"] == 1
        assert summary["counts"]["alerts"]["purgable"] == 0
        assert summary["counts"]["alerts"]["total"] == 1


def test_purge_old_feature_windows() -> None:
    with make_session() as session:
        _seed_data(session)
        deleted = purge_old_feature_windows(session, now=RECENT)
        assert deleted == 1
        remaining = session.execute(select(FeatureWindow)).scalars().all()
        assert len(remaining) == 1
        assert remaining[0].message_id == "fw-recent"


def test_purge_old_decisions() -> None:
    with make_session() as session:
        _seed_data(session)
        deleted = purge_old_decisions(session, now=RECENT)
        assert deleted == 1
        remaining = session.execute(select(Decision)).scalars().all()
        assert len(remaining) == 1
        assert remaining[0].message_id == "dec-recent"


def test_purge_old_edge_cycles() -> None:
    with make_session() as session:
        _seed_data(session)
        deleted = purge_old_edge_cycles(session, now=RECENT)
        assert deleted == 1
        assert session.execute(select(EdgeCycle)).scalars().all() == []


def test_purge_old_sensor_status() -> None:
    with make_session() as session:
        _seed_data(session)
        deleted = purge_old_sensor_status(session, now=RECENT)
        assert deleted == 1
        assert session.execute(select(SensorStatus)).scalars().all() == []


def test_alerts_are_never_purged() -> None:
    with make_session() as session:
        _seed_data(session)
        run_full_purge(session, now=RECENT)
        assert session.execute(select(Alert)).scalars().all() != []


def test_run_full_purge_returns_totals() -> None:
    with make_session() as session:
        _seed_data(session)
        result = run_full_purge(session, now=RECENT)
        assert result["deleted"]["total"] == 4
        assert result["deleted"]["feature_windows"] == 1
        assert result["deleted"]["decisions"] == 1


def test_custom_retention_days() -> None:
    with make_session() as session:
        _seed_data(session)
        deleted = purge_old_feature_windows(session, retention_days=720, now=RECENT)
        assert deleted == 0


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
        session.add(Patient(patient_id=PATIENT_ID, display_name="Retention Patient"))
        admin_user = User(email=ADMIN_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="admin", display_name="Admin D31")
        doctor_user = User(email=DOCTOR_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="doctor", display_name="Doctor D31")
        session.add_all([admin_user, doctor_user])
        session.commit()


def auth_headers(client: TestClient, email: str = ADMIN_EMAIL) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_retention_endpoint_returns_summary(client: TestClient) -> None:
    response = client.get("/api/v1/admin/retention", headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()
    assert "counts" in body
    assert "feature_windows" in body["counts"]


def test_purge_endpoint_requires_admin(client: TestClient) -> None:
    response = client.post("/api/v1/admin/retention/purge", json={}, headers=auth_headers(client, DOCTOR_EMAIL))
    assert response.status_code == 403


def test_purge_endpoint_executes(client: TestClient) -> None:
    response = client.post("/api/v1/admin/retention/purge", json={}, headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()
    assert "deleted" in body
    assert body["deleted"]["total"] >= 0
