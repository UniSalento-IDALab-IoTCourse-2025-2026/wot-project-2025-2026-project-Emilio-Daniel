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
from app.db.models import Alert, Decision, Doctor, DoctorPatient, FeatureWindow, Patient, User
from app.db.session import get_db
from app.main import app
from app.api.routes.patients import compute_patient_trend, trend_should_trigger_alert
from app.mqtt.ingest import store_decision, _check_trend_degradation_alert

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.trend.d26@example.invalid"

REFERENCE = datetime.now(timezone.utc).replace(microsecond=0)


def utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_increasing_scores(session, patient_id="patient-001", n=14):
    base = REFERENCE - timedelta(days=n)
    for i in range(n):
        ts = base + timedelta(days=i)
        session.add(
            Decision(
                message_id=f"trend-dec-{i:03d}",
                patient_id=patient_id,
                timestamp=ts,
                window_start=ts,
                window_end=ts + timedelta(minutes=4),
                level="green" if i < 8 else "orange",
                should_publish=i == n - 1,
                anomaly_score=20.0 + i * 3.5,
            )
        )
    session.commit()


def test_compute_patient_trend_returns_slope_and_direction():
    with make_session() as session:
        _seed_increasing_scores(session)
        result = compute_patient_trend(session, "patient-001", reference=REFERENCE)
        best = result["best"]
        assert best["direction"] == "in_aumento"
        assert best["score_slope_per_day"] is not None
        assert best["score_slope_per_day"] > 2.0
        assert best["window_days"] in {3, 7, 14}
        assert result["windows"]["7"]["score_slope_per_day"] > 2.0
        assert "features" in result
        assert "steps" in result["features"]
        assert result["features"]["steps"]["n_points"] >= 0


def test_compute_patient_trend_returns_stable_when_flat():
    with make_session() as session:
        base = REFERENCE - timedelta(days=14)
        for i in range(14):
            session.add(
                Decision(
                    message_id=f"trend-flat-{i:03d}",
                    patient_id="patient-001",
                    timestamp=base + timedelta(days=i),
                    window_start=base + timedelta(days=i),
                    window_end=base + timedelta(days=i, minutes=4),
                    level="green",
                    should_publish=False,
                    anomaly_score=30.0,
                )
            )
        session.commit()
        result = compute_patient_trend(session, "patient-001", reference=REFERENCE)
        assert result["best"]["direction"] == "stabile"
        assert abs(result["best"]["score_slope_per_day"]) < 2.0


def test_compute_patient_trend_returns_unknown_with_insufficient_data():
    with make_session() as session:
        session.add(
            Decision(
                message_id="trend-single",
                patient_id="patient-001",
                timestamp=REFERENCE - timedelta(hours=1),
                window_start=REFERENCE - timedelta(hours=1),
                window_end=REFERENCE,
                level="green",
                should_publish=False,
                anomaly_score=30.0,
            )
        )
        session.commit()
        result = compute_patient_trend(session, "patient-001", reference=REFERENCE)
        assert result["best"]["direction"] == "unknown"


def test_trend_should_trigger_alert():
    assert trend_should_trigger_alert({"best": {"score_slope_per_day": 4.0, "direction": "in_aumento", "window_days": 7}})
    assert not trend_should_trigger_alert({"best": {"score_slope_per_day": 1.5, "direction": "in_aumento", "window_days": 7}})
    assert not trend_should_trigger_alert({"best": {"score_slope_per_day": 4.0, "direction": "stabile", "window_days": 7}})
    assert not trend_should_trigger_alert({"best": {"score_slope_per_day": 4.0, "direction": "in_aumento", "window_days": 3}})


def test_trend_degradation_alert_created_on_strong_slope():
    with make_session() as session:
        base = REFERENCE - timedelta(days=14)
        for i in range(14):
            session.add(
                Decision(
                    message_id=f"trend-alert-{i:03d}",
                    patient_id="patient-001",
                    timestamp=base + timedelta(days=i),
                    window_start=base + timedelta(days=i),
                    window_end=base + timedelta(days=i, minutes=4),
                    level="green" if i < 10 else "orange",
                    should_publish=False,
                    anomaly_score=20.0 + i * 3.0,
                )
            )
        session.flush()
        last_decision = session.execute(
            select(Decision).where(Decision.message_id == "trend-alert-013")
        ).scalar_one()
        _check_trend_degradation_alert(session, last_decision)
        alerts = session.execute(select(Alert).where(Alert.patient_id == "patient-001")).scalars().all()
        trend_alerts = [a for a in alerts if a.source == "trend"]
        assert len(trend_alerts) == 1
        assert "peggioramento" in trend_alerts[0].title.lower()
        assert trend_alerts[0].category == "behavioral"


def test_trend_degradation_alert_not_duplicated():
    with make_session() as session:
        base = REFERENCE - timedelta(days=10)
        for i in range(10):
            session.add(
                Decision(
                    message_id=f"trend-dedup-{i:03d}",
                    patient_id="patient-001",
                    timestamp=base + timedelta(days=i),
                    window_start=base + timedelta(days=i),
                    window_end=base + timedelta(days=i, minutes=4),
                    level="green",
                    should_publish=False,
                    anomaly_score=20.0 + i * 4.0,
                )
            )
        session.flush()
        for i in range(8, 10):
            dec = session.execute(
                select(Decision).where(Decision.message_id == f"trend-dedup-{i:03d}")
            ).scalar_one()
            _check_trend_degradation_alert(session, dec)
        trend_alerts = (
            session.execute(select(Alert).where(Alert.patient_id == "patient-001", Alert.source == "trend"))
            .scalars()
            .all()
        )
        assert len(trend_alerts) == 1


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
        session.add(Patient(patient_id="patient-001", display_name="Paziente D26"))
        doctor_user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico D26",
        )
        session.add(doctor_user)
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="D26")
        session.add(doctor)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"))
        base = REFERENCE - timedelta(days=14)
        for i in range(14):
            ts = base + timedelta(days=i)
            session.add(
                FeatureWindow(
                    message_id=f"trend-win-{i:03d}",
                    patient_id="patient-001",
                    timestamp=ts,
                    window_start=ts,
                    window_end=ts + timedelta(minutes=4),
                    features={"heart_rate_mean": 70 + i, "steps": 2000 - i * 100},
                )
            )
            session.add(
                Decision(
                    message_id=f"trend-dec-{i:03d}",
                    patient_id="patient-001",
                    timestamp=ts,
                    window_start=ts,
                    window_end=ts + timedelta(minutes=4),
                    level="green" if i < 10 else "orange",
                    should_publish=i == 13,
                    anomaly_score=25.0 + i * 3.0,
                )
            )
        session.commit()


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_current_payload_includes_trend(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/current", headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()
    trend = body["trend"]
    assert "best" in trend
    assert "windows" in trend
    assert trend["best"]["direction"] in {"in_aumento", "stabile", "in_diminuzione", "unknown"}
    assert body["drift"]["status"] == "stable"


def test_decision_payload_includes_trend(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/decisions?limit=3", headers=auth_headers(client))
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 1
    trend = items[-1].get("trend")
    assert trend is not None
    assert "best" in trend
    assert trend["best"]["direction"] in {"in_aumento", "stabile", "in_diminuzione", "unknown"}
