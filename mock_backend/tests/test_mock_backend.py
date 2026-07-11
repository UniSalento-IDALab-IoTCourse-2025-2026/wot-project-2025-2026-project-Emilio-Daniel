from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_and_current_patient() -> None:
    assert client.get("/health").status_code == 200
    response = client.get("/api/v1/patients/patient-001/current")
    assert response.status_code == 200
    assert response.json()["patient_id"] == "patient-001"


def test_login_and_task_flow() -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "doctor@example.test", "password": "demo"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "doctor"

    task = client.post(
        "/api/v1/patients/patient-001/tasks",
        json={
            "type": "check_in",
            "priority": "normal",
            "title": "Test mock",
            "payload": {"questions": []},
        },
    )
    assert task.status_code == 200
    assert task.json()["status"] == "created"


def test_resolve_alert_requires_note() -> None:
    response = client.patch("/api/v1/alerts/alert-001/resolve", json={})
    assert response.status_code == 422
