from __future__ import annotations

import json
import logging
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.core.logging import JsonLogFormatter
from app.core.telemetry import (
    firebase_errors,
    increment_firebase_errors,
    increment_mqtt_messages_received,
    mqtt_messages_received,
)
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Alert, Doctor, DoctorPatient, Patient, User
from app.db.session import get_db
from app.main import app
from app.mqtt.ingest import ingest_mqtt_message

PATIENT_ID = "patient-001"
TEST_PASSWORD = "unit-test-password-not-secret"
ADMIN_EMAIL = "doctor.d33@example.invalid"


def test_mqtt_counter_increments() -> None:
    before = mqtt_messages_received()
    increment_mqtt_messages_received()
    increment_mqtt_messages_received()
    assert mqtt_messages_received() == before + 2


def test_firebase_counter_increments() -> None:
    before = firebase_errors()
    increment_firebase_errors()
    assert firebase_errors() == before + 1


def test_json_log_formatter_redacts_token_and_password() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="auth attempt",
        args=(),
        exc_info=None,
    )
    record.token = "sk-proj-supersecret12345"
    record.password = "letmein123"
    record.access_token = "eyJhbGciOiJIUzI1NiJ9.secret"
    record.safe_field = "visible"
    output = formatter.format(record)
    data = json.loads(output)
    assert data["token"].startswith("sk-") and "***" in data["token"]
    assert "***" in data["password"]
    assert "***" in data["access_token"]
    assert data["safe_field"] == "visible"


def test_json_log_formatter_masks_short_tokens() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord("t", logging.INFO, "", 0, "", (), None)
    record.password = "abc"
    data = json.loads(formatter.format(record))
    assert data["password"] == "***"


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Patient(patient_id=PATIENT_ID, display_name="D33 Patient"))
        user = User(email=ADMIN_EMAIL, password_hash=hash_password(TEST_PASSWORD), role="doctor", display_name="Doctor D33")
        session.add(user)
        session.flush()
        doc = Doctor(user_id=user.id, license_number="D33")
        session.add(doc)
        session.flush()
        session.add(DoctorPatient(doctor_id=doc.id, patient_id=PATIENT_ID))
        session.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_health_and_health_live_return_ok(client: TestClient) -> None:
    for path in ["/health", "/health/live"]:
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_ready_returns_config_status(client: TestClient) -> None:
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["mqtt_configured"] is True


def test_metrics_includes_new_counters(client: TestClient) -> None:
    resp = client.get("/metrics", headers=auth_headers(client))
    assert resp.status_code == 200
    counters = resp.json()["counters"]
    assert "mqtt_messages_received_total" in counters
    assert "firebase_errors_total" in counters
    assert "websocket_clients_connected" in counters
    assert "edge_mqtt_queue_depth" in counters


def test_ops_status_returns_services(client: TestClient) -> None:
    resp = client.get("/ops/status", headers=auth_headers(client))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    services = body["services"]
    assert "backend" in services
    assert "database" in services
    assert "mqtt_configured" in services
    assert "firebase_enabled" in services
    assert "websockets_active" in services


def test_mqtt_counter_increments_on_ingest() -> None:
    import json as _json
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        before = mqtt_messages_received()
        payload = _json.dumps({
            "schema_version": 1,
            "message_id": "metrics-test-001",
            "event_type": "edge_cycle_completed",
            "patient_id": PATIENT_ID,
            "edge_id": "edge-rpi5-001",
            "timestamp": "2026-09-09T12:00:00Z",
            "payload": {"online": True},
        }).encode("utf-8")
        ingest_mqtt_message(session, "iot/patients/patient-001/telemetry/decision", payload)
        assert mqtt_messages_received() > before


def test_ready_requires_no_auth(client: TestClient) -> None:
    resp = client.get("/ready")
    assert resp.status_code == 200