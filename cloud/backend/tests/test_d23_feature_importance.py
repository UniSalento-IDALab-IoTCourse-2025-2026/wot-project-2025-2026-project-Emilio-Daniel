from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.db.base import Base
from app.db.models import Decision, Doctor, DoctorPatient, Patient, User
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.importance@example.invalid"

FEATURE_IMPORTANCE = {
    "available": True,
    "method": "leave_one_out_median_replacement",
    "baseline_score": 82.0,
    "items": [
        {
            "feature": "heart_rate_mean",
            "label": "Frequenza cardiaca media",
            "category": "wearable",
            "impact": "aumenta_indice",
            "weight": 0.42,
            "value": 108.0,
            "reference": 74.0,
            "score_delta": -38.2,
        },
        {
            "feature": "spo2_mean",
            "label": "Saturazione ossigeno (SpO2)",
            "category": "wearable",
            "impact": "aumenta_indice",
            "weight": 0.27,
            "value": 84.5,
            "reference": 97.5,
            "score_delta": -24.1,
        },
    ],
}


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    with Session(engine) as session:
        session.add(Patient(patient_id="patient-001", display_name="Paziente Demo"))
        user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico Test",
        )
        session.add(user)
        session.flush()
        doctor = Doctor(user_id=user.id, license_number="TEST")
        session.add(doctor)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"))
        session.add(
            Decision(
                message_id="decision-imp-001",
                patient_id="patient-001",
                timestamp=now - timedelta(minutes=4),
                window_start=now - timedelta(minutes=8),
                window_end=now - timedelta(minutes=4),
                level="orange",
                should_publish=False,
                anomaly_score=74.5,
                model_label="test-fusion",
                payload={
                    "payload": {
                        "reasons": ["Anomalia rilevata"],
                        "feature_importance": FEATURE_IMPORTANCE,
                    }
                },
            )
        )
        session.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _auth(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "patient_id": "patient-001"}


def test_current_exposes_feature_importance(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/current", headers=_auth(client))
    assert response.status_code == 200
    body = response.json()
    assert body["feature_importance"] == FEATURE_IMPORTANCE


def test_decision_payload_exposes_feature_importance(client: TestClient) -> None:
    response = client.get(
        "/api/v1/patients/patient-001/decisions",
        params={"limit": 20},
        headers=_auth(client),
    )
    assert response.status_code == 200
    decisions = response.json()["items"]
    assert len(decisions) == 1
    importance = decisions[0]["feature_importance"]
    assert importance["available"] is True
    assert importance["items"][0]["feature"] == "heart_rate_mean"
    assert importance["items"][0]["impact"] == "aumenta_indice"
    assert 0.0 <= importance["items"][0]["weight"] <= 1.0


def test_report_data_includes_feature_importance(client: TestClient) -> None:
    response = client.get(
        "/api/v1/patients/patient-001/report-data",
        params={"days": 7},
        headers=_auth(client),
    )
    assert response.status_code == 200
    sections = response.json()["sections"]
    assert sections["current"]["feature_importance"] == FEATURE_IMPORTANCE
    decisions = sections["recent_decisions"]
    assert any(d["feature_importance"]["available"] for d in decisions)