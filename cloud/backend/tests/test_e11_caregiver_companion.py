from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Alert, AlertEvent, Caregiver, CaregiverPatient, Patient, PatientAppStatus, User
from app.db.session import get_db
from app.main import app

PASSWORD = "caregiver-test-password"
CAREGIVER_EMAIL = "caregiver.companion@example.invalid"


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                Patient(patient_id="patient-001", display_name="Paziente Uno"),
                Patient(patient_id="patient-002", display_name="Paziente Due"),
            ]
        )
        user = User(
            email=CAREGIVER_EMAIL,
            password_hash=hash_password(PASSWORD),
            role="caregiver",
            display_name="Caregiver Uno",
        )
        db.add(user)
        db.flush()
        caregiver = Caregiver(user_id=user.id, relationship="familiare")
        db.add(caregiver)
        db.flush()
        db.add(CaregiverPatient(caregiver_id=caregiver.id, patient_id="patient-001"))
        db.add_all(
            [
                Alert(
                    message_id="caregiver-red",
                    patient_id="patient-001",
                    level="red",
                    status="new",
                    category="behavioral",
                    title="Segnalazione importante",
                    description="Contattare il team se richiesto.",
                    opened_at=datetime.now(timezone.utc),
                ),
                Alert(
                    message_id="caregiver-yellow-hidden",
                    patient_id="patient-001",
                    level="yellow",
                    status="new",
                    category="behavioral",
                    title="Segnalazione non pubblicabile",
                    description="Non deve arrivare al caregiver.",
                    opened_at=datetime.now(timezone.utc),
                ),
                Alert(
                    message_id="caregiver-other-patient-hidden",
                    patient_id="patient-002",
                    level="red",
                    status="new",
                    category="behavioral",
                    title="Altro paziente",
                    description="Non autorizzato.",
                    opened_at=datetime.now(timezone.utc),
                ),
            ]
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.state.e11_engine = engine
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "e11_engine"):
            delattr(app.state, "e11_engine")


def test_caregiver_login_sees_only_associated_patient(client: TestClient) -> None:
    headers = auth_headers(client)

    patients = client.get("/api/v1/patients", headers=headers)

    assert patients.status_code == 200
    assert [item["patient_id"] for item in patients.json()["items"]] == ["patient-001"]


def test_caregiver_overview_contains_only_publishable_alerts_without_ai_raw_data(client: TestClient) -> None:
    headers = auth_headers(client)

    overview = client.get("/api/v1/alerts/caregiver", headers=headers)

    assert overview.status_code == 200
    items = overview.json()["items"]
    assert len(items) == 1
    assert items[0]["patient_id"] == "patient-001"
    assert items[0]["level"] == "red"
    alerts = items[0]["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["title"] == "Segnalazione importante"
    assert alerts[0]["level"] == "red"
    assert "anomaly_score" not in alerts[0]
    assert "feature_explanation" not in alerts[0]


def test_caregiver_can_acknowledge_authorized_alert_and_others_see_owner(client: TestClient) -> None:
    headers = auth_headers(client)
    alert = client.get("/api/v1/alerts/caregiver", headers=headers).json()["items"][0]["alerts"][0]

    acknowledged = client.patch(f"/api/v1/alerts/{alert['alert_id']}/acknowledge", headers=headers)

    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "acknowledged"
    overview = client.get("/api/v1/alerts/caregiver", headers=headers).json()
    acknowledged_alert = overview["items"][0]["alerts"][0]
    assert acknowledged_alert["acknowledged_by"] == "Caregiver Uno"
    assert acknowledged_alert["acknowledged_role"] == "caregiver"


def test_caregiver_device_registration_is_patient_bound_and_hides_fcm_token(client: TestClient) -> None:
    headers = auth_headers(client)

    registered = client.post(
        "/api/v1/notifications/caregiver/devices/register",
        headers=headers,
        json={
            "patient_id": "patient-001",
            "device_id": "android-caregiver-001",
            "platform": "android_caregiver",
            "app_version": "0.2.0",
            "fcm_token": "private-caregiver-token",
            "notifications_enabled": True,
        },
    )
    blocked = client.post(
        "/api/v1/notifications/caregiver/devices/status",
        headers=headers,
        json={"patient_id": "patient-002", "device_id": "android-caregiver-001", "battery_pct": 70},
    )

    assert registered.status_code == 200
    assert registered.json()["platform"] == "android_caregiver"
    assert registered.json()["device_id"].startswith("caregiver-")
    assert registered.json()["fcm_registered"] is True
    assert "private-caregiver-token" not in str(registered.json())
    assert blocked.status_code == 403


def test_patient_tasks_are_not_pushed_to_caregiver_devices(client: TestClient) -> None:
    headers = auth_headers(client)
    response = client.post(
        "/api/v1/notifications/caregiver/devices/register",
        headers=headers,
        json={
            "patient_id": "patient-001",
            "device_id": "android-caregiver-001",
            "fcm_token": "private-caregiver-token",
            "notifications_enabled": True,
        },
    )
    assert response.status_code == 200

    with Session(app.state.e11_engine) as db:
        devices = db.execute(select(PatientAppStatus)).scalars().all()
        assert len(devices) == 1
        assert devices[0].platform == "android_caregiver"


def test_acknowledge_event_is_written_without_exposing_token(client: TestClient) -> None:
    headers = auth_headers(client)
    alert = client.get("/api/v1/alerts/caregiver", headers=headers).json()["items"][0]["alerts"][0]

    response = client.patch(f"/api/v1/alerts/{alert['alert_id']}/acknowledge", headers=headers)

    assert response.status_code == 200
    with Session(app.state.e11_engine) as db:
        event = db.execute(select(AlertEvent).where(AlertEvent.event_type == "acknowledged")).scalar_one()
        assert "Caregiver Uno" in (event.note or "")
        assert "token" not in (event.note or "").lower()


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": CAREGIVER_EMAIL, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
