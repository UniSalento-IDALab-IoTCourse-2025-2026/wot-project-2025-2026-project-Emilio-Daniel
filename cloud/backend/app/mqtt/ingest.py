from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Alert,
    Decision,
    EdgeCycle,
    EdgeDevice,
    FeatureWindow,
    Patient,
    SensorStatus,
)
from app.mqtt.events import InternalEvent, event_bus
from app.mqtt.schemas import EdgeMqttPayload, decode_payload
from app.mqtt.topics import ParsedTopic, parse_topic


@dataclass(frozen=True)
class IngestResult:
    """Risultato restituito dopo l'ingestione di un messaggio MQTT."""

    status: str
    topic: str
    patient_id: str | None = None
    message_id: str | None = None
    reason: str | None = None


def ingest_mqtt_message(db: Session, topic: str, raw_payload: bytes) -> IngestResult:
    """Legge, valida, deduplica e salva un singolo messaggio MQTT."""
    try:
        parsed_topic = parse_topic(topic)
        payload = decode_payload(raw_payload, parsed_topic)
        result = store_payload(db, parsed_topic, payload)
        db.commit()
        if result.status == "stored":
            publish_internal_event(parsed_topic, payload)
        return result
    except IntegrityError as exc:
        db.rollback()
        return IngestResult(status="duplicate", topic=topic, reason=str(exc.orig))
    except Exception as exc:
        db.rollback()
        return IngestResult(status="rejected", topic=topic, reason=str(exc))


def store_payload(db: Session, topic: ParsedTopic, payload: EdgeMqttPayload) -> IngestResult:
    """Salva un payload validato nella tabella corretta in base al topic."""
    ensure_patient(db, payload.patient_id)
    ensure_edge_device(db, payload)

    if topic.kind == "edge/status":
        store_edge_status(db, payload)
    elif topic.kind == "telemetry/window":
        store_feature_window(db, payload)
    elif topic.kind == "telemetry/decision":
        store_decision(db, payload)
    elif topic.kind == "alerts/critical":
        store_alert(db, payload)
    elif topic.kind in {"sensors/watch", "sensors/ble"}:
        store_sensor_status(db, topic, payload)
    else:
        raise ValueError(f"Unsupported topic kind: {topic.kind}")

    return IngestResult(
        status="stored",
        topic=topic.raw,
        patient_id=payload.patient_id,
        message_id=payload.message_id,
    )


def ensure_patient(db: Session, patient_id: str) -> None:
    patient = db.get(Patient, patient_id)
    if patient is None:
        db.add(Patient(patient_id=patient_id, display_name=patient_id))
        db.flush()


def ensure_edge_device(db: Session, payload: EdgeMqttPayload) -> None:
    if not payload.edge_id:
        return
    device = db.get(EdgeDevice, payload.edge_id)
    if device is None:
        db.add(
            EdgeDevice(
                edge_id=payload.edge_id,
                patient_id=payload.patient_id,
                status="unknown",
                last_seen_at=payload.timestamp,
            )
        )
        db.flush()
        return
    if is_newer(payload.timestamp, device.last_seen_at):
        device.patient_id = payload.patient_id
        device.last_seen_at = payload.timestamp


def store_edge_status(db: Session, payload: EdgeMqttPayload) -> None:
    db.add(
        EdgeCycle(
            message_id=payload.message_id,
            patient_id=payload.patient_id,
            edge_id=payload.edge_id,
            event_type=payload.event_type,
            timestamp=payload.timestamp,
            window_start=parse_optional_datetime(payload.payload.get("window_start")),
            window_end=parse_optional_datetime(payload.payload.get("window_end")),
            payload=payload.model_dump(mode="json"),
        )
    )
    if payload.edge_id:
        device = db.get(EdgeDevice, payload.edge_id)
        if device is not None and is_newer(payload.timestamp, device.last_seen_at):
            device.status = edge_status_from_payload(payload)
            device.last_seen_at = payload.timestamp


def store_feature_window(db: Session, payload: EdgeMqttPayload) -> None:
    window_start = parse_required_datetime(payload.payload.get("window_start"), "payload.window_start")
    window_end = parse_required_datetime(payload.payload.get("window_end"), "payload.window_end")
    features = payload.payload.get("features")
    if features is None:
        features = {key: value for key, value in payload.payload.items() if key not in {"window_start", "window_end"}}
    if not isinstance(features, dict):
        raise ValueError("payload.features must be an object when present.")

    db.add(
        FeatureWindow(
            message_id=payload.message_id,
            patient_id=payload.patient_id,
            edge_id=payload.edge_id,
            timestamp=payload.timestamp,
            window_start=window_start,
            window_end=window_end,
            features=features,
        )
    )


def store_decision(db: Session, payload: EdgeMqttPayload) -> None:
    extra = payload.model_extra or {}
    level = str(payload.payload.get("level") or extra.get("level") or "")
    if not level:
        raise ValueError("decision payload requires level.")

    db.add(
        Decision(
            message_id=payload.message_id,
            patient_id=payload.patient_id,
            edge_id=payload.edge_id,
            timestamp=payload.timestamp,
            window_start=parse_optional_datetime(payload.payload.get("window_start")),
            window_end=parse_optional_datetime(payload.payload.get("window_end")),
            level=level,
            should_publish=bool(payload.payload.get("should_publish", extra.get("should_publish", False))),
            anomaly_score=parse_optional_float(payload.payload.get("anomaly_score")),
            model_label=optional_str(payload.payload.get("model_label")),
            payload=payload.model_dump(mode="json"),
        )
    )


def store_alert(db: Session, payload: EdgeMqttPayload) -> None:
    level = str(payload.payload.get("level") or payload.model_extra.get("level") or "red")
    db.add(
        Alert(
            message_id=payload.message_id,
            patient_id=payload.patient_id,
            level=level,
            status=str(payload.payload.get("status") or "new"),
            category=str(payload.payload.get("category") or "behavioral"),
            title=str(payload.payload.get("title") or "Edge alert"),
            description=optional_str(payload.payload.get("description")),
            opened_at=parse_optional_datetime(payload.payload.get("opened_at")) or payload.timestamp,
        )
    )


def store_sensor_status(db: Session, topic: ParsedTopic, payload: EdgeMqttPayload) -> None:
    sensor_type = topic.kind.split("/", 1)[1]
    status = str(payload.payload.get("status") or "unknown")
    existing = db.execute(
        select(SensorStatus).where(
            SensorStatus.patient_id == payload.patient_id,
            SensorStatus.sensor_type == sensor_type,
        )
    ).scalar_one_or_none()
    if existing and not is_newer(payload.timestamp, existing.last_seen_at):
        return
    if existing is None:
        db.add(
            SensorStatus(
                patient_id=payload.patient_id,
                sensor_type=sensor_type,
                status=status,
                last_seen_at=payload.timestamp,
                details=payload.model_dump(mode="json"),
            )
        )
    else:
        existing.status = status
        existing.last_seen_at = payload.timestamp
        existing.details = payload.model_dump(mode="json")


def publish_internal_event(topic: ParsedTopic, payload: EdgeMqttPayload) -> None:
    event_bus.publish(
        InternalEvent(
            event_type=payload.event_type,
            patient_id=payload.patient_id,
            timestamp=payload.timestamp,
            payload={
                "topic": topic.raw,
                "message_id": payload.message_id,
                "topic_kind": topic.kind,
            },
        )
    )


def parse_required_datetime(value: Any, field_name: str) -> datetime:
    parsed = parse_optional_datetime(value)
    if parsed is None:
        raise ValueError(f"{field_name} is required.")
    return parsed


def parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"Invalid datetime value: {value!r}")


def parse_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def edge_status_from_payload(payload: EdgeMqttPayload) -> str:
    if payload.event_type == "edge_offline_unexpected":
        return "offline"
    online = payload.payload.get("online")
    if online is True:
        return "online"
    if online is False:
        return "offline"
    return "unknown"


def is_newer(candidate: datetime, current: datetime | None) -> bool:
    if current is None:
        return True
    return normalize_utc(candidate) >= normalize_utc(current)


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
