from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Alert, Doctor, DoctorPatient, FeatureWindow, Patient, User
from app.db.session import get_db
from app.main import app
from app.mqtt.ingest import ingest_mqtt_message

TEST_PASSWORD = "unit-test-password-not-secret"
PATIENT_ID = "patient-001"
DOCTOR_EMAIL = "doctor.d30@example.invalid"
CAREGIVER_EMAIL = "caregiver.d30@example.invalid"


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _mqtt_msg(*, message_id: str, patient_id: str = PATIENT_ID, body: dict | None = None, event_type: str = "alert_created", timestamp: str = "2026-07-10T10:00:00Z") -> bytes:
    import json
    data = {
        "schema_version": 1,
        "message_id": message_id,
        "event_type": event_type,
        "patient_id": patient_id,
        "edge_id": "edge-rpi5-001",
        "timestamp": timestamp,
        "payload": body or {"level": "orange", "title": "Test alert"},
    }
    return json.dumps(data).encode("utf-8")


def test_duplicate_alert_message_id_does_not_create_second_row() -> None:
    with make_session() as session:
        ingest_mqtt_message(session, "iot/patients/patient-001/alerts/critical", _mqtt_msg(message_id="dup-alert-001"))
        ingest_mqtt_message(session, "iot/patients/patient-001/alerts/critical", _mqtt_msg(message_id="dup-alert-001"))
        rows = session.execute(select(Alert).where(Alert.message_id == "dup-alert-001")).scalars().all()
        assert len(rows) == 1


def test_duplicate_feature_window_message_id_is_rejected() -> None:
    import json
    with make_session() as session:
        body = {"window_start": "2026-07-10T10:00:00Z", "window_end": "2026-07-10T10:04:00Z", "features": {"steps": 100}}
        first = ingest_mqtt_message(session, "iot/patients/patient-001/telemetry/window", _mqtt_msg(message_id="dup-win-001", event_type="patient_window_updated", body=body))
        second = ingest_mqtt_message(session, "iot/patients/patient-001/telemetry/window", _mqtt_msg(message_id="dup-win-001", event_type="patient_window_updated", body=body))
        assert first.status == "stored"
        assert second.status == "duplicate"
        assert session.execute(select(FeatureWindow).where(FeatureWindow.message_id == "dup-win-001")).scalar_one()


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
        session.add(Patient(patient_id=PATIENT_ID, display_name="Paziente D30"))
        for email, role, name in [(DOCTOR_EMAIL, "doctor", "Medico D30"), (CAREGIVER_EMAIL, "caregiver", "Caregiver D30")]:
            user = User(email=email, password_hash=hash_password(TEST_PASSWORD), role=role, display_name=name)
            session.add(user)
        session.commit()


def _caregiver_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": CAREGIVER_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_caregiver_cannot_read_weekly_reports(client: TestClient) -> None:
    response = client.get(f"/api/v1/patients/{PATIENT_ID}/reports/weekly", headers=_caregiver_headers(client))
    assert response.status_code == 403


def test_caregiver_cannot_generate_weekly_report(client: TestClient) -> None:
    response = client.post(f"/api/v1/patients/{PATIENT_ID}/reports/generate", json={}, headers=_caregiver_headers(client))
    assert response.status_code == 403


def test_caregiver_cannot_read_morning_brief_without_access(client: TestClient) -> None:
    response = client.get(f"/api/v1/patients/{PATIENT_ID}/morning-brief", headers=_caregiver_headers(client))
    assert response.status_code == 403