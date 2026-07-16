from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.utils import dump_event_note
from app.auth.security import hash_password
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Alert, AlertEvent, AuditLog, Decision, Doctor, DoctorPatient, FeatureWindow, Patient, PatientUser, Task, User
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.report@example.invalid"
PATIENT_EMAIL = "patient.report@example.invalid"
CAREGIVER_EMAIL = "caregiver.report@example.invalid"


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
        test_client = TestClient(app)
        test_client._engine = engine  # type: ignore[attr-defined]
        yield test_client
    finally:
        app.dependency_overrides.clear()


def seed_database(engine: Any) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with Session(engine) as session:
        session.add(Patient(patient_id="patient-001", display_name="Paziente Report"))
        doctor_user = User(email=DOCTOR_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="doctor", display_name="Medico Report")
        patient_user = User(email=PATIENT_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="patient", display_name="Paziente Report")
        caregiver_user = User(email=CAREGIVER_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="caregiver", display_name="Caregiver Report")
        session.add_all([doctor_user, patient_user, caregiver_user])
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="REPORT")
        session.add(doctor)
        session.flush()
        session.add_all(
            [
                DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"),
                PatientUser(user_id=patient_user.id, patient_id="patient-001"),
            ]
        )
        window_end = now - timedelta(minutes=4)
        session.add(
            FeatureWindow(
                message_id="report-window-001",
                patient_id="patient-001",
                timestamp=window_end,
                window_start=window_end - timedelta(minutes=4),
                window_end=window_end,
                features={
                    "heart_rate_mean": 72.0,
                    "spo2_mean": 96.0,
                    "steps": 12,
                    "kitchen_minutes": 4.0,
                    "room_changes": 1,
                },
            )
        )
        decision = Decision(
            message_id="report-decision-001",
            patient_id="patient-001",
            timestamp=window_end,
            window_start=window_end - timedelta(minutes=4),
            window_end=window_end,
            level="yellow",
            should_publish=False,
            anomaly_score=42.5,
            model_label="report-model",
            payload={"payload": {"reasons": ["Report test"]}},
        )
        session.add(decision)
        session.flush()
        alert = Alert(
            message_id="report-alert-001",
            patient_id="patient-001",
            decision_id=decision.id,
            level="orange",
            status="resolved",
            category="behavioral",
            source="ai",
            clinical_severity="orange",
            title="Alert report",
            description="Alert da includere nel report.",
            opened_at=now - timedelta(minutes=3),
            closed_at=now - timedelta(minutes=1),
        )
        session.add(alert)
        session.flush()
        session.add(
            AlertEvent(
                alert_id=alert.id,
                user_id=doctor_user.id,
                event_type="resolved",
                timestamp=now - timedelta(minutes=1),
                note=dump_event_note(user_id="Medico Report", role="doctor", note="Risolto dopo verifica."),
            )
        )
        task = Task(
            patient_id="patient-001",
            created_by_user_id=doctor_user.id,
            task_type="check_in",
            status="completed",
            title="Check-in report",
            payload={
                "priority": "normal",
                "medical_note": "Nota clinica per report.",
                "medical_note_by": "Medico Report",
                "medical_note_at": now.isoformat(),
            },
            completed_at=now - timedelta(minutes=2),
        )
        session.add(task)
        session.commit()


def test_report_data_returns_compact_sections_and_writes_audit(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/report-data?days=7", headers=auth_headers(client, DOCTOR_EMAIL))

    assert response.status_code == 200
    body = response.json()
    assert body["report_type"] == "patient_triage_summary"
    assert body["patient"]["patient_id"] == "patient-001"
    assert "supporto al triage" in body["disclaimer"].lower()
    sections = body["sections"]
    assert sections["summary_24h"]["ai"]["last_score"] == 42.5
    assert sections["spatial_summary"]["room_minutes"]["kitchen"] == 4.0
    assert sections["recent_decisions"][0]["decision_id"] == "decision-1"
    assert sections["recent_alerts"][0]["alert_id"] == "alert-1"
    assert sections["recent_tasks"][0]["task_id"] == "task-1"
    assert len(sections["timeline"]) >= 3
    notes = sections["medical_notes"]
    assert {note["source"] for note in notes} == {"alert", "task"}
    assert body["privacy"]["contains_raw_sensor_payloads"] is False
    assert "fcm_token" in body["privacy"]["excluded"]

    with Session(client._engine) as session:  # type: ignore[attr-defined]
        audit = session.execute(select(AuditLog).where(AuditLog.action == "patient_report.exported")).scalar_one()
        assert audit.patient_id == "patient-001"
        assert audit.actor_role == "doctor"
        assert audit.details["days"] == 7


def test_report_data_is_doctor_only(client: TestClient) -> None:
    patient_response = client.get("/api/v1/patients/patient-001/report-data", headers=auth_headers(client, PATIENT_EMAIL))
    caregiver_response = client.get("/api/v1/patients/patient-001/report-data", headers=auth_headers(client, CAREGIVER_EMAIL))

    assert patient_response.status_code == 403
    assert caregiver_response.status_code == 403


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
