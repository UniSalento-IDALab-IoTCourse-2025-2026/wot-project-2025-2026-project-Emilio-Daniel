from __future__ import annotations

import json
from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import realtime
from app.api.routes.auth import LOGIN_ATTEMPTS
from app.auth import dependencies
from app.auth.security import hash_password
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Alert, AuditLog, Doctor, DoctorPatient, Patient, User
from app.db.session import get_db
from app.main import app
from app.mqtt.ingest import ingest_mqtt_message

TEST_PASSWORD = "unit-test-password-not-secret"
ADMIN_EMAIL = "admin.unit.test@example.invalid"
DOCTOR_EMAIL = "doctor.unit.test@example.invalid"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    LOGIN_ATTEMPTS.clear()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Patient(patient_id="patient-001", display_name="Paziente Demo"))
        admin = User(email=ADMIN_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="admin", display_name="Admin Test")
        doctor_user = User(email=DOCTOR_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="doctor", display_name="Medico Test")
        session.add_all([admin, doctor_user])
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="TEST")
        session.add(doctor)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"))
        session.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(realtime, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: Session(engine))
    try:
        yield TestClient(app)
    finally:
        LOGIN_ATTEMPTS.clear()
        app.dependency_overrides.clear()


def test_auth_me_change_password_and_revoke_session(client: TestClient) -> None:
    login = login_response(client, DOCTOR_EMAIL)
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == DOCTOR_EMAIL
    assert me.json()["last_login_at"] is not None

    revoke = client.post("/api/v1/auth/sessions/revoke", json={"refresh_token": login["refresh_token"]}, headers=headers)
    assert revoke.status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}).status_code == 401

    second = login_response(client, DOCTOR_EMAIL)
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": "new-unit-test-password"},
        headers={"Authorization": f"Bearer {second['access_token']}"},
    )
    assert changed.status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD}).status_code == 401


def test_failed_login_is_audited_and_rate_limited(client: TestClient) -> None:
    for _ in range(5):
        response = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": "wrong-password"})
        assert response.status_code == 401

    blocked = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": "wrong-password"})
    assert blocked.status_code == 429


def test_admin_can_create_user_patient_and_assignment(client: TestClient) -> None:
    headers = auth_headers(client, ADMIN_EMAIL)
    patient = client.post("/api/v1/admin/patients", json={"patient_id": "patient-002", "display_name": "Paziente Due"}, headers=headers)
    assert patient.status_code == 200

    user = client.post(
        "/api/v1/admin/users",
        json={"email": "newdoctor.unit.test@example.invalid", "password": TEST_PASSWORD, "role": "doctor", "display_name": "Nuovo medico"},
        headers=headers,
    )
    assert user.status_code == 200
    user_id = user.json()["id"]

    assignment = client.post(f"/api/v1/admin/users/{user_id}/patients/patient-002", headers=headers)
    assert assignment.status_code == 200
    assert assignment.json()["association"] == "doctor_patient"


def test_websocket_ping_pong(client: TestClient) -> None:
    token = login_response(client, DOCTOR_EMAIL)["access_token"]
    with client.websocket_connect(f"/ws/v1/patients/patient-001?token={token}") as websocket:
        assert websocket.receive_json()["event_type"] == "system_status_updated"
        websocket.send_text("ping")
        assert websocket.receive_json()["event_type"] == "pong"


def test_decision_alert_antispam_and_source_metadata(client: TestClient) -> None:
    with next(app.dependency_overrides[get_db]()) as session:
        first = ingest_mqtt_message(session, "iot/patients/patient-001/telemetry/decision", decision_payload("decision-a"))
        second = ingest_mqtt_message(session, "iot/patients/patient-001/telemetry/decision", decision_payload("decision-b"))
        alerts = session.execute(select(Alert)).scalars().all()
        assert first.status == "stored"
        assert second.status == "stored"
        assert len(alerts) == 1
        assert alerts[0].source == "ai"
        assert alerts[0].clinical_severity == "orange"


def decision_payload(message_id: str) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "message_id": message_id,
            "event_type": "decision_updated",
            "patient_id": "patient-001",
            "edge_id": "edge-rpi5-001",
            "timestamp": "2026-07-13T10:00:00Z",
            "payload": {"level": "orange", "should_publish": True, "model_label": "wearable"},
        }
    ).encode("utf-8")


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {login_response(client, email)['access_token']}"}


def login_response(client: TestClient, email: str) -> dict:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200
    return response.json()
