from __future__ import annotations

import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import ai as ai_routes
from app.auth.security import hash_password
from app.db.base import Base
from app.db.models import Doctor, DoctorPatient, Patient, User
from app.db.session import get_db
from app.main import app

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.ai.test@example.invalid"

SAMPLE_METRICS = {
    "model_id": "patient-001",
    "model_scope": "personal",
    "contamination_used": 0.05,
    "training_rows": 500,
    "validation_rows": 100,
    "precision": 0.85,
    "recall": 0.79,
    "f1": 0.82,
    "accuracy": 0.88,
    "roc_auc": 0.91,
    "true_positives": 40,
    "true_negatives": 48,
    "false_positives": 7,
    "false_negatives": 5,
    "ambiguous_excluded": 10,
    "synthetic_anomalies_added": 50,
    "computed_at": "2026-09-01T10:00:00+00:00",
    "notes": "Model: personal",
}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(Patient(patient_id="patient-001", display_name="Paziente Demo"))
        session.add(Patient(patient_id="patient-999", display_name="Paziente Non Autorizzato"))
        doctor_user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico AI Test",
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

    # Puntiamo la directory metriche verso la tmp del test
    monkeypatch.setattr(ai_routes, "_metrics_dir", lambda: tmp_path)

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str, patient_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "patient_id": patient_id}


def test_model_metrics_empty_when_no_files(client: TestClient) -> None:
    token = _login(client)
    response = client.get(
        f"/api/v1/patients/patient-001/ai/model-metrics",
        headers=_auth(token, "patient-001"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == "patient-001"
    assert body["models"] == []
    assert body["last_training_at"] is None


def test_model_metrics_reads_patient_metrics_file(client: TestClient, tmp_path) -> None:
    metrics_file = tmp_path / "patient-001_personal_metrics.json"
    with metrics_file.open("w", encoding="utf-8") as f:
        json.dump(SAMPLE_METRICS, f)

    token = _login(client)
    response = client.get(
        "/api/v1/patients/patient-001/ai/model-metrics",
        headers=_auth(token, "patient-001"),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["models"]) == 1
    metric = body["models"][0]
    assert metric["model_scope"] == "personal"
    assert metric["model"] == "personal"
    assert metric["display_name"] == "Modello personale (patient-001)"
    assert metric["f1"] == 0.82
    assert metric["precision"] == 0.85
    assert metric["recall"] == 0.79
    assert metric["validation_rows"] == 100
    assert body["last_training_at"] is not None


def test_model_metrics_reads_generic_and_patient(client: TestClient, tmp_path) -> None:
    patient_file = tmp_path / "patient-001_personal_metrics.json"
    generic_file = tmp_path / "generic_wearable_metrics.json"

    patient_metrics = dict(SAMPLE_METRICS)
    generic_metrics = dict(SAMPLE_METRICS)
    generic_metrics["model_id"] = "generic-wearable"
    generic_metrics["model_scope"] = "generic_wearable"
    generic_metrics["model"] = "Modello generico wearable"

    with patient_file.open("w", encoding="utf-8") as f:
        json.dump(patient_metrics, f)
    with generic_file.open("w", encoding="utf-8") as f:
        json.dump(generic_metrics, f)

    # File non pertinente: deve essere ignorato
    other_patient_file = tmp_path / "patient-999_personal_metrics.json"
    other_metrics = dict(SAMPLE_METRICS)
    other_metrics["model_id"] = "patient-999"
    with other_patient_file.open("w", encoding="utf-8") as f:
        json.dump(other_metrics, f)

    token = _login(client)
    response = client.get(
        "/api/v1/patients/patient-001/ai/model-metrics",
        headers=_auth(token, "patient-001"),
    )
    assert response.status_code == 200
    body = response.json()
    scopes = sorted(m["model_scope"] for m in body["models"])
    assert scopes == ["generic_wearable", "personal"]
    assert len(body["models"]) == 2


def test_model_metrics_denied_for_unauthorized_patient(client: TestClient) -> None:
    token = _login(client)
    response = client.get(
        "/api/v1/patients/patient-999/ai/model-metrics",
        headers=_auth(token, "patient-999"),
    )
    assert response.status_code == 403


def test_model_metrics_requires_auth(client: TestClient) -> None:
    response = client.get(
        "/api/v1/patients/patient-001/ai/model-metrics",
        headers=_auth("invalid-token", "patient-001"),
    )
    assert response.status_code in (401, 403)