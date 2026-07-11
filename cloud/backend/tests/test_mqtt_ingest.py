from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Alert, Decision, EdgeCycle, FeatureWindow, Patient, SensorStatus
from app.mqtt.events import event_bus
from app.mqtt.ingest import ingest_mqtt_message, normalize_utc
from app.mqtt.topics import parse_topic, subscription_topics


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
    timestamp: str = "2026-07-10T10:00:00Z",
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


def test_parse_supported_topic() -> None:
    parsed = parse_topic("iot/patients/patient-001/telemetry/decision")

    assert parsed.patient_id == "patient-001"
    assert parsed.kind == "telemetry/decision"


def test_subscription_topics_cover_edge_inputs() -> None:
    topics = {topic for topic, _ in subscription_topics()}

    assert "iot/patients/+/edge/status" in topics
    assert "iot/patients/+/telemetry/window" in topics
    assert "iot/patients/+/telemetry/decision" in topics
    assert "iot/patients/+/alerts/critical" in topics
    assert "iot/patients/+/sensors/watch" in topics
    assert "iot/patients/+/sensors/ble" in topics


def test_ingest_edge_status_creates_patient_edge_cycle_and_event() -> None:
    event_bus.events.clear()
    with make_session() as session:
        result = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/edge/status",
            payload(message_id="cycle-001", body={"online": True}),
        )

        assert result.status == "stored"
        assert session.get(Patient, "patient-001") is not None
        assert session.execute(select(EdgeCycle)).scalar_one().message_id == "cycle-001"
        assert event_bus.events[-1].event_type == "edge_cycle_completed"


def test_ingest_duplicate_message_id_is_not_stored_twice() -> None:
    with make_session() as session:
        first = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/edge/status",
            payload(message_id="cycle-duplicate"),
        )
        second = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/edge/status",
            payload(message_id="cycle-duplicate"),
        )

        assert first.status == "stored"
        assert second.status == "duplicate"
        assert len(session.execute(select(EdgeCycle)).scalars().all()) == 1


def test_reject_payload_without_required_message_id() -> None:
    data = json.loads(payload().decode("utf-8"))
    data.pop("message_id")

    with make_session() as session:
        result = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/edge/status",
            json.dumps(data).encode("utf-8"),
        )

        assert result.status == "rejected"
        assert "message_id" in (result.reason or "")


def test_reject_topic_patient_mismatch() -> None:
    with make_session() as session:
        result = ingest_mqtt_message(
            session,
            "iot/patients/patient-999/edge/status",
            payload(patient_id="patient-001"),
        )

        assert result.status == "rejected"
        assert "does not match" in (result.reason or "")


def test_reject_string_nan_values() -> None:
    with make_session() as session:
        result = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/telemetry/window",
            payload(
                event_type="patient_window_updated",
                body={
                    "window_start": "2026-07-10T10:00:00Z",
                    "window_end": "2026-07-10T10:04:00Z",
                    "features": {"heart_rate_mean": "nan"},
                },
            ),
        )

        assert result.status == "rejected"
        assert "nan" in (result.reason or "").lower()


def test_ingest_window_decision_alert_and_sensor_status() -> None:
    with make_session() as session:
        window = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/telemetry/window",
            payload(
                message_id="window-001",
                event_type="patient_window_updated",
                body={
                    "window_start": "2026-07-10T10:00:00Z",
                    "window_end": "2026-07-10T10:04:00Z",
                    "features": {"heart_rate_mean": 70.0},
                },
            ),
        )
        decision = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/telemetry/decision",
            payload(
                message_id="decision-001",
                event_type="decision_updated",
                body={
                    "level": "orange",
                    "should_publish": True,
                    "anomaly_score": 72.5,
                    "model_label": "generic_wearable_anomaly_only",
                },
            ),
        )
        alert = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/alerts/critical",
            payload(
                message_id="alert-001",
                event_type="alert_created",
                body={"level": "red", "title": "Critical alert"},
            ),
        )
        sensor = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/sensors/watch",
            payload(
                message_id="watch-001",
                event_type="sensor_watch_updated",
                body={"status": "active", "battery_pct": 80},
            ),
        )

        assert {window.status, decision.status, alert.status, sensor.status} == {"stored"}
        assert session.execute(select(FeatureWindow)).scalar_one().features["heart_rate_mean"] == 70.0
        assert session.execute(select(Decision)).scalar_one().level == "orange"
        assert session.execute(select(Alert)).scalar_one().title == "Critical alert"
        assert session.execute(select(SensorStatus)).scalar_one().status == "active"


def test_out_of_order_sensor_status_does_not_overwrite_newer_state() -> None:
    with make_session() as session:
        newer = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/sensors/ble",
            payload(
                message_id="ble-new",
                event_type="sensor_ble_updated",
                timestamp="2026-07-10T10:10:00Z",
                body={"status": "active"},
            ),
        )
        older = ingest_mqtt_message(
            session,
            "iot/patients/patient-001/sensors/ble",
            payload(
                message_id="ble-old",
                event_type="sensor_ble_updated",
                timestamp="2026-07-10T10:05:00Z",
                body={"status": "stale"},
            ),
        )

        status = session.execute(select(SensorStatus)).scalar_one()
        assert newer.status == "stored"
        assert older.status == "stored"
        assert status.status == "active"
        assert status.last_seen_at is not None
        assert normalize_utc(status.last_seen_at) == datetime(2026, 7, 10, 10, 10, tzinfo=timezone.utc)
