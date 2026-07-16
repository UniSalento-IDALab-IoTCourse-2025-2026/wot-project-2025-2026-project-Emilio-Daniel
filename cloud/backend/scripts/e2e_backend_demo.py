from __future__ import annotations

from collections.abc import Generator

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

PASSWORD = "E2ePassword001!"
DOCTOR_EMAIL = "e2e.doctor@localhost.invalid"
PATIENT_EMAIL = "e2e.patient@localhost.invalid"


def main() -> None:
    """Esegue un flusso end-to-end backend usando SQLite in memoria."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    seed(engine)

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            run_flow(client)
    finally:
        app.dependency_overrides.clear()


def seed(engine) -> None:
    """Crea paziente, medico e paziente app per il test simulato."""
    with Session(engine) as session:
        session.add(Patient(patient_id="patient-e2e-001", display_name="Paziente E2E"))
        doctor_user = User(email=DOCTOR_EMAIL, password_hash=hash_password(PASSWORD), role="doctor", display_name="Medico E2E")
        patient_user = User(email=PATIENT_EMAIL, password_hash=hash_password(PASSWORD), role="patient", display_name="Paziente E2E")
        session.add_all([doctor_user, patient_user])
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="E2E")
        session.add(doctor)
        session.flush()
        session.add_all(
            [
                DoctorPatient(doctor_id=doctor.id, patient_id="patient-e2e-001"),
                PatientUser(user_id=patient_user.id, patient_id="patient-e2e-001"),
            ]
        )
        session.commit()


def run_flow(client: TestClient) -> None:
    """Verifica login, questionario, risultato, report e audit."""
    doctor_headers = auth_headers(client, DOCTOR_EMAIL)
    patient_headers = auth_headers(client, PATIENT_EMAIL)

    template = post_ok(
        client,
        "/api/v1/questionnaires/templates",
        doctor_headers,
        {
            "template_key": "e2e_checkin",
            "title": "E2E check-in",
            "description": "Check-in simulato.",
            "task_type": "check_in",
            "questions": [{"id": "mood", "type": "scale", "text": "Come ti senti?", "min": 0, "max": 10}],
            "scoring": {"type": "scale_average", "question_ids": ["mood"]},
        },
    )
    schedule = post_ok(
        client,
        "/api/v1/questionnaires/patients/patient-e2e-001/schedules",
        doctor_headers,
        {"template_id": template["template_id"], "frequency": "daily", "next_run_at": "2026-07-16T08:00:00Z"},
    )
    generated = post_ok(
        client,
        f"/api/v1/questionnaires/schedules/{schedule['schedule_id']}/generate-due-task",
        doctor_headers,
        {"now": "2026-07-16T08:00:00Z"},
    )
    task_id = generated["task"]["task_id"]
    result = post_ok(
        client,
        f"/api/v1/tasks/{task_id}/results",
        patient_headers,
        {
            "patient_id": "patient-e2e-001",
            "completed_at": "2026-07-16T08:03:00Z",
            "duration_seconds": 120,
            "device_info": {"device_id": "e2e-device"},
            "answers": [{"question_id": "mood", "value": 8}],
        },
    )
    assert result["score"] == 8

    report = get_ok(client, "/api/v1/patients/patient-e2e-001/report-data", doctor_headers)
    assert report["report_type"] == "patient_triage_summary"
    assert report["sections"]["recent_tasks"][0]["task_id"] == task_id

    audit = get_ok(client, "/api/v1/patients/patient-e2e-001/audit-trail", doctor_headers)
    actions = {item["action"] for item in audit["items"]}
    assert "questionnaire_task.generated" in actions
    assert "task.completed" in actions
    assert "patient_report.exported" in actions
    print("E2E backend simulato completato correttamente.")


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def post_ok(client: TestClient, path: str, headers: dict[str, str], payload: dict) -> dict:
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def get_ok(client: TestClient, path: str, headers: dict[str, str]) -> dict:
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


if __name__ == "__main__":
    main()
