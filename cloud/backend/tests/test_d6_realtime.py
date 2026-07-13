from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import dependencies
from app.auth.security import hash_password
from app.api.routes import realtime
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Doctor, DoctorPatient, Patient, User
from app.db.session import get_db
from app.main import app
from app.mqtt.events import event_bus

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.unit.test@example.invalid"


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
        doctor_user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico Test",
        )
        session.add(doctor_user)
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
    event_bus.events.clear()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        event_bus.events.clear()


def test_patient_websocket_connects_and_receives_task_event(client: TestClient) -> None:
    token = access_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    with client.websocket_connect(f"/ws/v1/patients/patient-001?token={token}") as websocket:
        initial = websocket.receive_json()
        assert initial["event_type"] == "system_status_updated"
        assert initial["patient_id"] == "patient-001"

        created = client.post(
            "/api/v1/patients/patient-001/tasks",
            json={
                "type": "check_in",
                "priority": "normal",
                "title": "Task realtime",
                "payload": {"questions": []},
            },
            headers=headers,
        )
        assert created.status_code == 200

        event = websocket.receive_json()
        assert event["event_type"] == "task_created"
        assert event["patient_id"] == "patient-001"


def test_snapshot_change_produces_decision_event() -> None:
    old = realtime.PatientRealtimeSnapshot(latest_decision_id=1)
    new = realtime.PatientRealtimeSnapshot(latest_decision_id=2)

    events = realtime.events_from_snapshot_change("patient-001", old, new)

    assert [event.event_type for event in events] == ["decision_updated"]
    assert events[0].timestamp <= datetime.now(timezone.utc)


def test_multiple_patient_websocket_clients_receive_same_event(client: TestClient) -> None:
    token = access_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    with client.websocket_connect(f"/ws/v1/patients/patient-001?token={token}") as first:
        with client.websocket_connect(f"/ws/v1/patients/patient-001?token={token}") as second:
            assert first.receive_json()["event_type"] == "system_status_updated"
            assert second.receive_json()["event_type"] == "system_status_updated"

            created = client.post(
                "/api/v1/patients/patient-001/tasks",
                json={
                    "type": "check_in",
                    "priority": "normal",
                    "title": "Task due client",
                    "payload": {"questions": []},
                },
                headers=headers,
            )
            assert created.status_code == 200

            assert first.receive_json()["event_type"] == "task_created"
            assert second.receive_json()["event_type"] == "task_created"


def access_token(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD})
    assert response.status_code == 200
    return response.json()["access_token"]
