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
DOCTOR_EMAIL = "doctor.confidence@example.invalid"

CONFIDENCE = {
    "score": 82,
    "level": "alta",
    "reasons": ["BLE completo", "Google Health parziale", "modello personale disponibile"],
}
LOW_CONFIDENCE = {
    "score": 34,
    "level": "bassa",
    "reasons": ["Google Health assente", "modello personale non disponibile"],
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
        session.add_all(
            [
                Decision(
                    message_id="decision-conf-001",
                    patient_id="patient-001",
                    timestamp=now - timedelta(minutes=4),
                    window_start=now - timedelta(minutes=8),
                    window_end=now - timedelta(minutes=4),
                    level="yellow",
                    should_publish=False,
                    anomaly_score=52.0,
                    model_label="test-fusion",
                    payload={
                        "payload": {
                            "reasons": ["Score in attenzione"],
                            "confidence": CONFIDENCE,
                        }
                    },
                ),
                Decision(
                    message_id="decision-conf-002",
                    patient_id="patient-001",
                    timestamp=now - timedelta(minutes=12),
                    window_start=now - timedelta(minutes=16),
                    window_end=now - timedelta(minutes=12),
                    level="red",
                    should_publish=True,
                    anomaly_score=91.0,
                    model_label="test-fusion",
                    payload={
                        "payload": {
                            "reasons": ["Anomalia severa"],
                            "confidence": LOW_CONFIDENCE,
                        }
                    },
                ),
            ]
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


def test_current_exposes_confidence(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/current", headers=_auth(client))
    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == CONFIDENCE
    assert body["ai_confidence"] == CONFIDENCE


def test_decision_payload_exposes_confidence(client: TestClient) -> None:
    response = client.get(
        "/api/v1/patients/patient-001/decisions",
        params={"limit": 20},
        headers=_auth(client),
    )
    assert response.status_code == 200
    decisions = response.json()["items"]
    by_message = {d["message_id"]: d for d in decisions}
    assert by_message["decision-conf-001"]["confidence"] == CONFIDENCE
    assert by_message["decision-conf-002"]["confidence"] == LOW_CONFIDENCE


def test_timeline_events_carry_confidence_for_low_conf_highlight(client: TestClient) -> None:
    response = client.get(
        "/api/v1/patients/patient-001/timeline",
        params={"page_size": 50},
        headers=_auth(client),
    )
    assert response.status_code == 200
    events = response.json()["items"]
    decision_events = [e for e in events if e["event_type"] == "decision_updated"]
    assert len(decision_events) >= 1
    low = next(e for e in decision_events if e["linked_resource"]["message_id"] == "decision-conf-002")
    assert low["confidence"]["level"] == "bassa"
    high = next(e for e in decision_events if e["linked_resource"]["message_id"] == "decision-conf-001")
    assert high["confidence"]["level"] == "alta"


def test_system_status_ai_section_exposes_confidence(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/system-status", headers=_auth(client))
    assert response.status_code == 200
    body = response.json()
    assert body["ai"]["confidence"] == CONFIDENCE


def test_confidence_missing_for_decision_without_confidence(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/current", headers=_auth(client))
    body = response.json()
    assert body["confidence"] is not None
    # Le decisioni senza confidence non devono rompere nulla
    response = client.get(
        "/api/v1/patients/patient-001/decisions",
        params={"limit": 50},
        headers=_auth(client),
    )
    assert response.status_code == 200