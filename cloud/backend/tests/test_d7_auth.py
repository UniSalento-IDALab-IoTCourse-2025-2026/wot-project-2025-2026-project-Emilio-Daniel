from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.auth import dependencies
from app.auth.security import hash_password
from app.api.routes import realtime
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Caregiver, CaregiverPatient, Doctor, DoctorPatient, Patient, PatientUser, User
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.unit.test@example.invalid"
CAREGIVER_EMAIL = "caregiver.unit.test@example.invalid"
PATIENT_EMAIL = "patient.unit.test@example.invalid"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Patient(patient_id="patient-001", display_name="Paziente Demo"))
        session.add(Patient(patient_id="patient-999", display_name="Paziente Non Autorizzato"))
        doctor_user = User(email=DOCTOR_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="doctor", display_name="Medico Test")
        caregiver_user = User(
            email=CAREGIVER_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="caregiver",
            display_name="Caregiver Test",
        )
        patient_user = User(email=PATIENT_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="patient", display_name="Paziente Test")
        session.add_all([doctor_user, caregiver_user, patient_user])
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="TEST")
        caregiver = Caregiver(user_id=caregiver_user.id, relationship="test")
        session.add_all([doctor, caregiver])
        session.flush()
        session.add_all(
            [
                DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"),
                CaregiverPatient(caregiver_id=caregiver.id, patient_id="patient-001"),
                PatientUser(user_id=patient_user.id, patient_id="patient-001"),
            ]
        )
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
        app.dependency_overrides.clear()


def test_login_refresh_and_logout(client: TestClient) -> None:
    login = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    body = login.json()
    assert body["token_type"] == "bearer"
    assert body["refresh_token"]

    refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert refresh.status_code == 200
    assert refresh.json()["access_token"]

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    logout = client.post("/api/v1/auth/logout", json={"refresh_token": body["refresh_token"]}, headers=headers)
    assert logout.status_code == 200

    revoked = client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert revoked.status_code == 401


def test_wrong_password_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": "wrong-unit-test-password"})
    assert response.status_code == 401


def test_user_reads_only_authorized_patients(client: TestClient) -> None:
    caregiver_headers = auth_headers(client, CAREGIVER_EMAIL)

    allowed = client.get("/api/v1/patients/patient-001/current", headers=caregiver_headers)
    assert allowed.status_code in {200, 404}

    denied = client.get("/api/v1/patients/patient-999/current", headers=caregiver_headers)
    assert denied.status_code == 403


def test_patient_cannot_create_task_but_doctor_can(client: TestClient) -> None:
    patient_headers = auth_headers(client, PATIENT_EMAIL)
    doctor_headers = auth_headers(client, DOCTOR_EMAIL)
    payload = {"type": "check_in", "title": "Test", "payload": {}}

    denied = client.post("/api/v1/patients/patient-001/tasks", json=payload, headers=patient_headers)
    assert denied.status_code == 403

    created = client.post("/api/v1/patients/patient-001/tasks", json=payload, headers=doctor_headers)
    assert created.status_code == 200


def test_task_result_requires_patient_role(client: TestClient) -> None:
    doctor_headers = auth_headers(client, DOCTOR_EMAIL)
    created = client.post(
        "/api/v1/patients/patient-001/tasks",
        json={"type": "check_in", "title": "Test result", "payload": {}},
        headers=doctor_headers,
    )
    task_id = created.json()["task_id"]

    denied = client.post(
        f"/api/v1/tasks/{task_id}/results",
        json={"patient_id": "patient-001", "completed_at": "2026-07-12T10:00:00Z"},
        headers=doctor_headers,
    )
    assert denied.status_code == 403

    patient_headers = auth_headers(client, PATIENT_EMAIL)
    accepted = client.post(
        f"/api/v1/tasks/{task_id}/results",
        json={
            "patient_id": "patient-001",
            "completed_at": datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc).isoformat(),
        },
        headers=patient_headers,
    )
    assert accepted.status_code == 200


def test_websocket_requires_authorized_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/v1/patients/patient-001"):
            pass

    token = access_token(client, DOCTOR_EMAIL)
    with client.websocket_connect(f"/ws/v1/patients/patient-001?token={token}") as websocket:
        assert websocket.receive_json()["event_type"] == "system_status_updated"

    caregiver_token = access_token(client, CAREGIVER_EMAIL)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/v1/patients/patient-999?token={caregiver_token}"):
            pass


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token(client, email)}"}


def access_token(client: TestClient, email: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200
    return response.json()["access_token"]
