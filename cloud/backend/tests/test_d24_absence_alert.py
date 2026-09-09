from __future__ import annotations

import json
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Alert, Doctor, DoctorPatient, Patient, User
from app.db.session import get_db
from app.main import app
from app.mqtt.ingest import ingest_mqtt_message

TEST_PASSWORD = "unit-test-password-not-secret"
DOCTOR_EMAIL = "doctor.absence.d24@example.invalid"


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def payload(
    *,
    message_id: str = "msg-001",
    event_type: str = "edge_cycle_completed",
    patient_id: str = "patient-001",
    edge_id: str = "edge-rpi5-001",
    timestamp: str = "2026-09-08T10:00:00Z",
    body: dict[str, Any] | None = None,
    **extra: Any,
) -> bytes:
    data = {
        "schema_version": 1,
        "message_id": message_id,
        "event_type": event_type,
        "patient_id": patient_id,
        "edge_id": edge_id,
        "timestamp": timestamp,
        "payload": body or {"online": True},
    }
    data.update(extra)
    return json.dumps(data).encode("utf-8")


def test_absence_alert_store_payload_and_dedupe_by_message_id() -> None:
    with make_session() as session:
        body = {
            "level": "orange",
            "status": "new",
            "category": "no_movement",
            "source": "edge",
            "title": "Assenza di movimento da verificare",
            "description": "Nessun cambio stanza da oltre 4 ore.",
            "reason": "Nessun movimento per oltre 4 ore.",
            "duration_minutes": 305.0,
            "no_movement_minutes": 305.0,
            "last_room": "living_room",
            "last_transition_at": "2026-09-08T07:00:00Z",
            "ble_quality": "ok",
            "kind": "no_movement",
        }
        first = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/alerts/critical",
            payload(message_id="absence-abc123", event_type="alert_created", body=body),
        )
        assert first.status == "stored"

        second = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/alerts/critical",
            payload(message_id="absence-abc123", event_type="alert_created", body=body),
        )
        assert second.status == "stored"

        alerts = session.execute(select(Alert).where(Alert.message_id == "absence-abc123")).scalars().all()
        assert len(alerts) == 1
        stored = alerts[0]
        assert stored.payload is not None
        assert stored.payload["kind"] == "no_movement"
        assert stored.payload["category"] == "no_movement"
        assert stored.payload["last_room"] == "living_room"
        assert stored.payload["duration_minutes"] == 305.0
        assert stored.payload["ble_quality"] == "ok"


def test_absence_technical_fault_stored_as_technical_alert() -> None:
    with make_session() as session:
        body = {
            "level": "technical",
            "status": "new",
            "category": "technical",
            "source": "edge",
            "title": "Sensore di movimento non affidabile",
            "description": "Il BLE non fornisce dati",
            "reason": "Dati BLE non aggiornati (ultimo campione oltre 30 minuti fa).",
            "kind": "ble_unreliable",
        }
        result = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/alerts/critical",
            payload(message_id="absence-tech-1", event_type="alert_created", body=body),
        )
        assert result.status == "stored"
        alert = session.execute(select(Alert).where(Alert.message_id == "absence-tech-1")).scalar_one()
        assert alert.category == "technical"
        assert alert.level == "technical"
        assert alert.payload["kind"] == "ble_unreliable"


def test_decision_derived_alert_keeps_decision_payload() -> None:
    with make_session() as session:
        ingest_mqtt_message(
            session,
            "iot/patients/patient-001/telemetry/decision",
            payload(
                message_id="decision-d24-001",
                event_type="decision_updated",
                body={"level": "red", "should_publish": True, "anomaly_score": 88.0, "model_label": "multi_model_red"},
            ),
        )
        alert = (
            session.execute(select(Alert).where(Alert.message_id.like("alert-from-decision-%")))
            .scalars()
            .first()
        )
        assert alert is not None
        assert alert.payload is not None
        assert alert.payload["payload"]["anomaly_score"] == 88.0


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
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with Session(engine) as session:
        session.add(Patient(patient_id="patient-001", display_name="Paziente D24"))
        doctor_user = User(
            email=DOCTOR_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            role="doctor",
            display_name="Medico D24",
        )
        session.add(doctor_user)
        session.flush()
        doctor = Doctor(user_id=doctor_user.id, license_number="D24")
        session.add(doctor)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id="patient-001"))
        session.add(
            Alert(
                message_id="absence-fixed-id",
                patient_id="patient-001",
                level="orange",
                status="new",
                category="no_movement",
                source="edge",
                clinical_severity="orange",
                title="Assenza di movimento da verificare",
                description="Nessun cambio stanza da oltre 4 ore.",
                opened_at=now - timedelta(minutes=5),
                payload={
                    "kind": "no_movement",
                    "category": "no_movement",
                    "duration_minutes": 320.0,
                    "no_movement_minutes": 320.0,
                    "last_room": "living_room",
                    "last_transition_at": "2026-09-08T07:00:00Z",
                    "ble_quality": "ok",
                },
            )
        )
        session.commit()


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": DOCTOR_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_patient_alerts_expose_absence_payload(client: TestClient) -> None:
    response = client.get("/api/v1/patients/patient-001/alerts", headers=auth_headers(client))
    assert response.status_code == 200

    alerts = response.json()["items"]
    absence = next(alert for alert in alerts if alert["message_id"] == "absence-fixed-id")
    assert absence["category"] == "no_movement"
    assert absence["title"] == "Assenza di movimento da verificare"
    assert absence["payload"]["last_room"] == "living_room"
    assert absence["payload"]["duration_minutes"] == 320.0
    assert absence["payload"]["ble_quality"] == "ok"
