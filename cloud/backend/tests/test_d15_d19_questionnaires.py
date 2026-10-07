from __future__ import annotations

from collections.abc import Generator

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
DOCTOR_EMAIL = "doctor.questionnaire@example.invalid"
PATIENT_EMAIL = "patient.questionnaire@example.invalid"


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


def test_template_schedule_and_due_task_generation(client: TestClient) -> None:
    template = create_template(client)
    assert template.status_code == 200
    assert template.json()["template_key"] == "daily_checkin"

    schedule = create_schedule(client, template.json()["template_id"])
    assert schedule.status_code == 200
    assert schedule.json()["status"] == "active"

    generated = client.post(
        f"/api/v1/questionnaires/schedules/{schedule.json()['schedule_id']}/generate-due-task",
        json={"now": "2026-07-16T08:00:00Z"},
        headers=auth_headers(client, DOCTOR_EMAIL),
    )

    assert generated.status_code == 200
    assert generated.json()["status"] == "generated"
    assert generated.json()["task"]["type"] == "check_in"
    assert generated.json()["schedule"]["last_task_id"] == generated.json()["task"]["task_id"]


def test_schedule_does_not_generate_duplicate_task_in_same_period(client: TestClient) -> None:
    template = create_template(client).json()
    schedule = create_schedule(client, template["template_id"]).json()
    headers = auth_headers(client, DOCTOR_EMAIL)

    first = client.post(
        f"/api/v1/questionnaires/schedules/{schedule['schedule_id']}/generate-due-task",
        json={"now": "2026-07-16T08:00:00Z"},
        headers=headers,
    )
    second = client.post(
        f"/api/v1/questionnaires/schedules/{schedule['schedule_id']}/generate-due-task",
        json={"now": "2026-07-16T09:00:00Z"},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "already_generated"
    assert second.json()["task"]["task_id"] == first.json()["task"]["task_id"]


def test_checkin_answers_are_validated_and_scored(client: TestClient) -> None:
    task_id = generated_questionnaire_task_id(client)

    result = client.post(
        f"/api/v1/tasks/{task_id}/results",
        json={
            "patient_id": "patient-001",
            "started_at": "2026-07-16T08:01:00Z",
            "completed_at": "2026-07-16T08:03:00Z",
            "duration_seconds": 120,
            "device_info": {"device_id": "android-test", "platform": "android"},
            "answers": [
                {"question_id": "mood", "value": 7},
                {"question_id": "dizziness", "value": False},
                {"question_id": "sleep", "value": "bene"},
            ],
        },
        headers=auth_headers(client, PATIENT_EMAIL),
    )

    assert result.status_code == 200
    assert result.json()["score"] == 7.0
    assert result.json()["score_details"]["type"] == "scale_average"
    assert result.json()["answers"][1]["value"] is False

    history = client.get(
        "/api/v1/questionnaires/patients/patient-001/results",
        headers=auth_headers(client, DOCTOR_EMAIL),
    )
    assert history.status_code == 200
    assert history.json()["items"][0]["score"] == 7.0
    assert history.json()["items"][0]["template_key"] == "daily_checkin"


def test_invalid_checkin_answer_is_rejected(client: TestClient) -> None:
    task_id = generated_questionnaire_task_id(client)

    result = client.post(
        f"/api/v1/tasks/{task_id}/results",
        json={
            "patient_id": "patient-001",
            "completed_at": "2026-07-16T08:03:00Z",
            "answers": [
                {"question_id": "mood", "value": 11},
                {"question_id": "dizziness", "value": False},
                {"question_id": "sleep", "value": "bene"},
            ],
        },
        headers=auth_headers(client, PATIENT_EMAIL),
    )

    assert result.status_code == 422


def test_manual_android_questionnaire_result_reaches_dashboard_history(client: TestClient) -> None:
    created = client.post(
        "/api/v1/patients/patient-001/tasks",
        json={
            "type": "check_in",
            "title": "Test cognitivo breve - benessere",
            "payload": {
                "questionnaire": "short_wellbeing_checkin",
                "questions": [
                    {
                        "id": "overall",
                        "type": "scale",
                        "text": "Come valuti il tuo benessere generale oggi?",
                        "options": ["Molto basso", "Basso", "Discreto", "Buono", "Molto buono"],
                    },
                    {"id": "contact", "type": "yes_no", "text": "Vuoi essere contattato?"},
                    {"id": "note", "type": "text", "text": "Nota facoltativa", "required": False},
                ],
            },
        },
        headers=auth_headers(client, DOCTOR_EMAIL),
    )
    assert created.status_code == 200

    submitted = client.post(
        f"/api/v1/tasks/{created.json()['task_id']}/results",
        json={
            "patient_id": "patient-001",
            "message_id": "android-manual-result-001",
            "completed_at": "2026-07-16T10:03:00Z",
            "duration_seconds": 45,
            "answers": [
                {"question_id": "overall", "value": "Buono"},
                {"question_id": "contact", "value": False},
            ],
            "device_info": {"device_id": "android-test", "platform": "android"},
        },
        headers=auth_headers(client, PATIENT_EMAIL),
    )
    assert submitted.status_code == 200
    assert submitted.json()["answers"][0]["value"] == 3
    assert submitted.json()["answers"][0]["display_value"] == "Buono"
    assert submitted.json()["answers"][0]["question_text"].startswith("Come valuti")

    history = client.get(
        "/api/v1/questionnaires/patients/patient-001/results",
        headers=auth_headers(client, DOCTOR_EMAIL),
    )
    assert history.status_code == 200
    assert history.json()["items"][0]["task_id"] == created.json()["task_id"]
    assert history.json()["items"][0]["template_key"] == "short_wellbeing_checkin"

    tasks = client.get(
        "/api/v1/patients/patient-001/tasks",
        headers=auth_headers(client, DOCTOR_EMAIL),
    )
    completed = next(item for item in tasks.json()["items"] if item["task_id"] == created.json()["task_id"])
    assert completed["status"] == "completed"
    assert completed["result"]["answers"][0]["value"] == 3


def create_template(client: TestClient):
    return client.post(
        "/api/v1/questionnaires/templates",
        json={
            "template_key": "daily_checkin",
            "title": "Check-in quotidiano",
            "description": "Breve controllo sullo stato percepito.",
            "task_type": "check_in",
            "questions": [
                {"id": "mood", "type": "scale", "text": "Come ti senti oggi?", "min": 0, "max": 10},
                {"id": "dizziness", "type": "yes_no", "text": "Hai avuto capogiri?"},
                {"id": "sleep", "type": "single_choice", "text": "Hai dormito bene?", "options": ["bene", "cosi_cosi", "male"]},
            ],
            "scoring": {"type": "scale_average", "question_ids": ["mood"]},
        },
        headers=auth_headers(client, DOCTOR_EMAIL),
    )


def create_schedule(client: TestClient, template_id: str):
    return client.post(
        "/api/v1/questionnaires/patients/patient-001/schedules",
        json={
            "template_id": template_id,
            "frequency": "daily",
            "next_run_at": "2026-07-16T08:00:00Z",
            "payload_overrides": {"task_due_hours": 12},
        },
        headers=auth_headers(client, DOCTOR_EMAIL),
    )


def generated_questionnaire_task_id(client: TestClient) -> str:
    template = create_template(client).json()
    schedule = create_schedule(client, template["template_id"]).json()
    generated = client.post(
        f"/api/v1/questionnaires/schedules/{schedule['schedule_id']}/generate-due-task",
        json={"now": "2026-07-16T08:00:00Z"},
        headers=auth_headers(client, DOCTOR_EMAIL),
    )
    assert generated.status_code == 200
    return generated.json()["task"]["task_id"]


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
