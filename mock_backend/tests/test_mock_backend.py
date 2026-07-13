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
        json={"email": "doctor.unit.test@example.invalid", "password": "unit-test-password-not-secret"},
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


def test_alert_acknowledge_and_resolve_are_visible_in_patient_alerts() -> None:
    alerts = client.get("/api/v1/patients/patient-004/alerts")
    assert alerts.status_code == 200
    alert_id = alerts.json()["items"][0]["alert_id"]

    acknowledge = client.patch(
        f"/api/v1/alerts/{alert_id}/acknowledge",
        json={"user_id": "doctor-test"},
    )
    assert acknowledge.status_code == 200

    acknowledged_alerts = client.get("/api/v1/patients/patient-004/alerts")
    acknowledged = acknowledged_alerts.json()["items"][0]
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledged_by"] == "doctor-test"

    resolve = client.patch(
        f"/api/v1/alerts/{alert_id}/resolve",
        json={"user_id": "doctor-test", "note": "Controllo completato."},
    )
    assert resolve.status_code == 200

    resolved_alerts = client.get("/api/v1/patients/patient-004/alerts")
    resolved = resolved_alerts.json()["items"][0]
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by"] == "doctor-test"
    assert resolved["resolution_note"] == "Controllo completato."
