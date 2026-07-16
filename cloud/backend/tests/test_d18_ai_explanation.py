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
from app.db.models import Decision, Doctor, DoctorPatient, EdgeDevice, FeatureWindow, Patient, User
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.ai.explain@example.invalid"


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
        session.add(Patient(patient_id="patient-001", display_name="Paziente AI"))
        doctor_user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico AI",
        )
        session.add(doctor_user)
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="AI")
        session.add(doctor)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"))
        session.add(
            EdgeDevice(
                edge_id="edge-ai",
                patient_id="patient-001",
                status="online",
                last_seen_at=now,
            )
        )
        previous_time = now - timedelta(minutes=8)
        current_time = now - timedelta(minutes=4)
        session.add(
            FeatureWindow(
                message_id="ai-window-current",
                patient_id="patient-001",
                edge_id="edge-ai",
                timestamp=current_time,
                window_start=current_time - timedelta(minutes=4),
                window_end=current_time,
                features={
                    "wearable_present": True,
                    "heart_rate_mean": 82.0,
                    "heart_rate_std": None,
                    "spo2_mean": 94.0,
                    "steps": None,
                    "kitchen_minutes": 4.0,
                    "bedroom_minutes": None,
                    "room_changes": 2,
                },
            )
        )
        session.add_all(
            [
                Decision(
                    message_id="ai-decision-previous",
                    patient_id="patient-001",
                    edge_id="edge-ai",
                    timestamp=previous_time,
                    window_start=previous_time - timedelta(minutes=4),
                    window_end=previous_time,
                    level="yellow",
                    should_publish=False,
                    anomaly_score=40.0,
                    model_label="previous",
                    payload={"payload": {"reasons": ["precedente"], "evidence": {}}},
                ),
                Decision(
                    message_id="ai-decision-current",
                    patient_id="patient-001",
                    edge_id="edge-ai",
                    timestamp=current_time,
                    window_start=current_time - timedelta(minutes=4),
                    window_end=current_time,
                    level="orange",
                    should_publish=True,
                    anomaly_score=72.5,
                    model_label="generic_wearable_anomaly_only",
                    payload={
                        "quality_status": "warning",
                        "payload": {
                            "reasons": ["Score alto"],
                            "evidence": {
                                "fusion": {
                                    "models": {
                                        "generic_wearable": {
                                            "available": True,
                                            "score": 82.5,
                                            "label": "outlier",
                                            "decision_value": -0.25,
                                            "feature_explanation": {
                                                "available": True,
                                                "top_features": [
                                                    {
                                                        "feature": "heart_rate_mean",
                                                        "value": 82.0,
                                                        "model_value": 82.0,
                                                        "z_score": 2.1,
                                                        "abs_z_score": 2.1,
                                                        "direction": "above_training",
                                                        "imputed": False,
                                                    },
                                                    {
                                                        "feature": "steps",
                                                        "value": None,
                                                        "model_value": 0.0,
                                                        "z_score": -1.4,
                                                        "abs_z_score": 1.4,
                                                        "direction": "below_training",
                                                        "imputed": True,
                                                    },
                                                ],
                                            },
                                        },
                                        "generic_spatial": {
                                            "available": True,
                                            "score": 62.0,
                                            "label": "normal",
                                            "decision_value": 0.1,
                                            "feature_explanation": {
                                                "available": True,
                                                "top_features": [
                                                    {
                                                        "feature": "room_changes",
                                                        "value": 2,
                                                        "model_value": 2,
                                                        "z_score": 1.2,
                                                        "abs_z_score": 1.2,
                                                        "direction": "above_training",
                                                        "imputed": False,
                                                    }
                                                ],
                                            },
                                        },
                                    }
                                }
                            },
                        },
                    },
                ),
            ]
        )
        session.commit()


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_decision_payload_contains_normalized_ai_explanation(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/decisions?limit=5", headers=auth_headers(client))
    assert response.status_code == 200
    current = response.json()["items"][-1]
    explanation = current["ai_explanation"]

    assert explanation["previous_score"] == 40.0
    assert explanation["score_delta"] == 32.5
    assert explanation["score_direction"] == "aumento"
    assert explanation["updated_at"] == current["timestamp"]
    assert explanation["data_reliability"]["level"] in {"bassa", "media"}
    assert explanation["data_reliability"]["quality_status"] == "warning"
    assert explanation["message"] == "Supporto al triage: la decisione finale resta al medico."

    labels = {item["feature"]: item["label"] for item in explanation["feature_explanations"]}
    assert labels["heart_rate_mean"] == "Frequenza cardiaca media"
    assert labels["room_changes"] == "Cambi stanza"
    assert explanation["positive_factors"][0]["feature"] == "heart_rate_mean"
    assert any(item["feature"] == "steps" for item in explanation["negative_factors"])
    assert any(item["feature"] == "steps" and item["status"] == "imputed" for item in explanation["missing_or_imputed_features"])
    assert explanation["model_contributions"]["generic_wearable"]["score"] == 82.5


def test_current_payload_exposes_same_ai_explanation(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/current", headers=auth_headers(client))
    assert response.status_code == 200
    explanation = response.json()["ai_explanation"]

    assert explanation["score_delta"] == 32.5
    assert explanation["score_direction"] == "aumento"
    assert any(item["label"] == "Frequenza cardiaca media" for item in explanation["positive_factors"])


def test_telemetry_decisions_use_normalized_ai_explanation(client: TestClient) -> None:
    response = client.get("/api/v1/telemetry/patients/patient-001/decisions?limit=5", headers=auth_headers(client))
    assert response.status_code == 200
    explanation = response.json()["items"][-1]["ai_explanation"]

    assert explanation["previous_score"] == 40.0
    assert explanation["feature_explanations"][0]["label"] == "Frequenza cardiaca media"
