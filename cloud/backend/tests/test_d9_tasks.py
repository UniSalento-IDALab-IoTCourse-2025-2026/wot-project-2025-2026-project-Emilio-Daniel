from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Doctor, DoctorPatient, Patient, PatientUser, User
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.unit.test@example.invalid"
PATIENT_EMAIL = "patient.unit.test@example.invalid"


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
        session.add(Patient(patient_id="patient-001", display_name="Paziente Demo"))
        doctor_user = User(email=DOCTOR_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="doctor", display_name="Medico Test")
        patient_user = User(email=PATIENT_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="patient", display_name="Paziente Test")
        session.add_all([doctor_user, patient_user])
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="TEST")
        session.add(doctor)
        session.flush()
        session.add_all(
            [
                DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"),
                PatientUser(user_id=patient_user.id, patient_id="patient-001"),
            ]
        )
        session.commit()


def test_rejects_unsupported_task_type(client: TestClient) -> None:
    response = client.post(
        "/api/v1/patients/patient-001/tasks",
        json={"type": "unknown_test", "title": "Sconosciuto", "payload": {}},
        headers=auth_headers(client, DOCTOR_EMAIL),
    )

    assert response.status_code == 422


def test_cognitive_test_requires_questions(client: TestClient) -> None:
    missing_questions = client.post(
        "/api/v1/patients/patient-001/tasks",
        json={"type": "cognitive_test", "title": "Test cognitivo", "payload": {}},
        headers=auth_headers(client, DOCTOR_EMAIL),
    )
    assert missing_questions.status_code == 422

    created = create_cognitive_task(client)
    assert created.status_code == 200
    assert created.json()["type"] == "cognitive_test"


def test_exact_match_score_is_computed_only_when_rule_exists(client: TestClient) -> None:
    task_id = create_cognitive_task(client).json()["task_id"]

    result = client.post(
        f"/api/v1/tasks/{task_id}/results",
        json={
            "patient_id": "patient-001",
            "completed_at": "2026-07-12T10:10:00Z",
            "answers": [
                {"question_id": "q1", "value": "rosso"},
                {"question_id": "q2", "value": "4"},
            ],
        },
        headers=auth_headers(client, PATIENT_EMAIL),
    )

    assert result.status_code == 200
    assert result.json()["score"] == 100.0
    assert result.json()["score_details"]["correct"] == 2
    assert result.json()["score_details"]["total"] == 2
    assert result.json()["result_type"] == "cognitive_test"
    assert result.json()["content"]["answers"][0]["question_id"] == "q1"


def test_task_result_cannot_be_submitted_twice(client: TestClient) -> None:
    task_id = create_check_in_task(client).json()["task_id"]
    payload = {"patient_id": "patient-001", "completed_at": "2026-07-12T10:10:00Z"}
    headers = auth_headers(client, PATIENT_EMAIL)

    first = client.post(f"/api/v1/tasks/{task_id}/results", json=payload, headers=headers)
    second = client.post(f"/api/v1/tasks/{task_id}/results", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409


def test_expired_task_cannot_be_completed(client: TestClient) -> None:
    created = client.post(
        "/api/v1/patients/patient-001/tasks",
        json={
            "type": "check_in",
            "title": "Task scaduto",
            "expires_at": "2026-07-12T10:00:00Z",
            "payload": {},
        },
        headers=auth_headers(client, DOCTOR_EMAIL),
    )
    task_id = created.json()["task_id"]

    result = client.post(
        f"/api/v1/tasks/{task_id}/results",
        json={"patient_id": "patient-001", "completed_at": "2026-07-12T10:05:00Z"},
        headers=auth_headers(client, PATIENT_EMAIL),
    )

    assert result.status_code == 409


def test_expired_status_is_visible_when_listing_tasks(client: TestClient) -> None:
    created = client.post(
        "/api/v1/patients/patient-001/tasks",
        json={
            "type": "check_in",
            "title": "Task scaduto in lista",
            "expires_at": "2026-07-12T10:00:00Z",
            "payload": {},
        },
        headers=auth_headers(client, DOCTOR_EMAIL),
    )
    assert created.status_code == 200

    tasks = client.get("/api/v1/patients/patient-001/tasks", headers=auth_headers(client, DOCTOR_EMAIL))

    assert tasks.status_code == 200
    assert tasks.json()["items"][0]["status"] == "expired"


def test_task_can_be_assigned_to_caregiver_and_include_medical_note(client: TestClient) -> None:
    created = client.post(
        "/api/v1/patients/patient-001/tasks",
        json={
            "type": "custom",
            "title": "Controllo caregiver",
            "assigned_to": "caregiver",
            "medical_note": "Verificare se il paziente ha pranzato.",
            "payload": {"kind": "caregiver_check"},
        },
        headers=auth_headers(client, DOCTOR_EMAIL),
    )

    assert created.status_code == 200
    assert created.json()["assigned_to"] == "caregiver"
    assert created.json()["medical_note"] == "Verificare se il paziente ha pranzato."


def test_task_can_be_cancelled_before_completion(client: TestClient) -> None:
    task_id = create_check_in_task(client).json()["task_id"]

    cancelled = client.patch(
        f"/api/v1/tasks/{task_id}/cancel",
        json={"note": "Non serve piu'."},
        headers=auth_headers(client, DOCTOR_EMAIL),
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancelled_note"] == "Non serve piu'."

    result = client.post(
        f"/api/v1/tasks/{task_id}/results",
        json={"patient_id": "patient-001", "completed_at": "2026-07-12T10:10:00Z"},
        headers=auth_headers(client, PATIENT_EMAIL),
    )
    assert result.status_code == 409


def test_completed_task_cannot_be_cancelled(client: TestClient) -> None:
    task_id = create_check_in_task(client).json()["task_id"]
    result = client.post(
        f"/api/v1/tasks/{task_id}/results",
        json={"patient_id": "patient-001", "completed_at": "2026-07-12T10:10:00Z"},
        headers=auth_headers(client, PATIENT_EMAIL),
    )
    assert result.status_code == 200

    cancelled = client.patch(
        f"/api/v1/tasks/{task_id}/cancel",
        json={"note": "Troppo tardi."},
        headers=auth_headers(client, DOCTOR_EMAIL),
    )
    assert cancelled.status_code == 409


def create_check_in_task(client: TestClient):
    return client.post(
        "/api/v1/patients/patient-001/tasks",
        json={"type": "check_in", "title": "Check-in", "payload": {}},
        headers=auth_headers(client, DOCTOR_EMAIL),
    )


def create_cognitive_task(client: TestClient):
    return client.post(
        "/api/v1/patients/patient-001/tasks",
        json={
            "type": "cognitive_test",
            "title": "Test cognitivo",
            "payload": {
                "questions": [
                    {"id": "q1", "type": "text", "text": "Colore?"},
                    {"id": "q2", "type": "text", "text": "2+2?"},
                ]
            },
            "scoring": {
                "type": "exact_match",
                "expected_answers": {"q1": "rosso", "q2": "4"},
            },
        },
        headers=auth_headers(client, DOCTOR_EMAIL),
    )


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
