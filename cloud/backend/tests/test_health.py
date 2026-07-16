from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "IoT Monitoring Cloud Backend"
    assert "timestamp" in body


def test_ready() -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["configuration"] == "ok"


def test_openapi_contains_expected_routes() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/ready" in paths
    assert "/auth/status" in paths
    assert "/patients/status" in paths
    assert "/telemetry/status" in paths
    assert "/alerts/status" in paths
    assert "/tasks/status" in paths
    assert "/questionnaires/status" in paths
    assert "/notifications/status" in paths
    assert "/realtime/status" in paths


def test_error_shape() -> None:
    response = client.get("/missing-route")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "http_error",
            "message": "Not Found",
            "details": {},
        }
    }
