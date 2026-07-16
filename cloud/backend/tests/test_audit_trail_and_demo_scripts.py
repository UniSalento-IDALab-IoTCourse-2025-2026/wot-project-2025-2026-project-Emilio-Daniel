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
from app.db.models import AuditLog, Doctor, DoctorPatient, Patient, PatientUser, User
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.audit@example.invalid"
PATIENT_EMAIL = "patient.audit@example.invalid"


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
        patient = Patient(patient_id="patient-001", display_name="Paziente Audit")
        doctor_user = User(email=DOCTOR_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="doctor", display_name="Medico Audit")
        patient_user = User(email=PATIENT_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="patient", display_name="Paziente Audit")
        session.add_all([patient, doctor_user, patient_user])
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="AUDIT")
        session.add(doctor)
        session.flush()
        session.add_all(
            [
                DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"),
                PatientUser(user_id=patient_user.id, patient_id="patient-001"),
                AuditLog(
                    actor_user_id=doctor_user.id,
                    actor_role="doctor",
                    action="patient_report.exported",
                    patient_id="patient-001",
                    target_type="patient_report",
                    target_id="patient-001",
                    timestamp=datetime.now(timezone.utc),
                    details={"days": 7, "access_token": "secret-not-returned"},
                ),
            ]
        )
        session.commit()


def test_audit_trail_is_readable_and_sanitized(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/audit-trail", headers=auth_headers(client, DOCTOR_EMAIL))

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["title"] == "Report esportato"
    assert item["summary"] == "Il medico ha richiesto i dati per un report paziente."
    assert item["details"]["days"] == 7
    assert "access_token" not in item["details"]


def test_patient_cannot_read_audit_trail(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/audit-trail", headers=auth_headers(client, PATIENT_EMAIL))

    assert response.status_code == 403


def test_e2e_backend_demo_script_runs() -> None:
    from scripts.e2e_backend_demo import main

    main()


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
