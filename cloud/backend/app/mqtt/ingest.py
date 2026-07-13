from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

ALERT_LEVELS_FROM_DECISION = {"orange", "red"}
ALERT_SPAM_WINDOW_MINUTES = 30


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

    decision = Decision(
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
    db.add(decision)
    db.flush()
    create_alert_from_decision_if_needed(db, decision)


def create_alert_from_decision_if_needed(db: Session, decision: Decision) -> None:
    """Crea un alert automatico solo per decisioni pubblicabili e importanti."""
    level = decision.level.lower()
    if not decision.should_publish or level not in ALERT_LEVELS_FROM_DECISION:
        return
    message_id = alert_message_id_from_decision(decision.message_id)
    existing = db.execute(select(Alert.id).where(Alert.message_id == message_id)).first()
    if existing is not None:
        return
    category = alert_category_from_decision(decision)
    source = alert_source_from_decision(decision)
    if has_similar_open_alert(db, decision.patient_id, decision.level, category, source, decision.timestamp):
        return

    db.add(
        Alert(
            message_id=message_id,
            patient_id=decision.patient_id,
            decision_id=decision.id,
            level=level,
            status="new",
            category=category,
            source=source,
            clinical_severity=decision.level if category in {"clinical", "behavioral"} else None,
            technical_severity=decision.level if category == "technical" else None,
            title=alert_title_from_decision(decision),
            description=alert_description_from_decision(decision),
            opened_at=decision.timestamp,
        )
    )


def alert_message_id_from_decision(decision_message_id: str) -> str:
    """Deriva un id stabile per deduplicare l'alert generato dalla decisione."""
    digest = hashlib.sha256(decision_message_id.encode("utf-8")).hexdigest()[:24]
    return f"alert-from-decision-{digest}"


def alert_category_from_decision(decision: Decision) -> str:
    """Classifica l'alert mantenendo separati tecnico, clinico e comportamentale."""
    payload = decision.payload.get("payload", {}) if isinstance(decision.payload, dict) else {}
    explicit = str(payload.get("category") or "").strip().lower()
    if explicit in {"clinical", "behavioral", "technical"}:
        return explicit
    model_label = (decision.model_label or "").lower()
    serialized = str(payload).lower()
    if any(token in serialized for token in {"edge_offline", "oauth", "battery", "sensor", "stale"}):
        return "technical"
    if any(token in f"{model_label} {serialized}" for token in {"wearable", "heart", "spo2", "health", "watch"}):
        return "clinical"
    return "behavioral"


def alert_source_from_decision(decision: Decision) -> str:
    payload = decision.payload.get("payload", {}) if isinstance(decision.payload, dict) else {}
    source = str(payload.get("source") or "ai").strip().lower()
    return source if source in {"ai", "edge", "manual", "system"} else "ai"


def has_similar_open_alert(
    db: Session,
    patient_id: str,
    level: str,
    category: str,
    source: str,
    opened_at: datetime,
) -> bool:
    window_start = normalize_utc(opened_at) - timedelta(minutes=ALERT_SPAM_WINDOW_MINUTES)
    return db.execute(
        select(Alert.id)
        .where(
            Alert.patient_id == patient_id,
            Alert.status != "resolved",
            Alert.level == level,
            Alert.category == category,
            Alert.source == source,
            Alert.opened_at >= window_start,
        )
        .limit(1)
    ).first() is not None


def alert_title_from_decision(decision: Decision) -> str:
    if decision.level.lower() == "red":
        return "Alert severo AI"
    return "Alert importante AI"


def alert_description_from_decision(decision: Decision) -> str:
    payload = decision.payload.get("payload", {}) if isinstance(decision.payload, dict) else {}
    reasons = payload.get("reasons") if isinstance(payload, dict) else None
    parts = [f"Decisione AI {decision.level}"]
    if decision.anomaly_score is not None:
        parts.append(f"score {decision.anomaly_score:.1f}")
    if isinstance(reasons, list) and reasons:
        parts.append("; ".join(str(reason) for reason in reasons[:3]))
    return " - ".join(parts)


def store_alert(db: Session, payload: EdgeMqttPayload) -> None:
    level = str(payload.payload.get("level") or payload.model_extra.get("level") or "red")
    category = str(payload.payload.get("category") or "behavioral")
    db.add(
        Alert(
            message_id=payload.message_id,
            patient_id=payload.patient_id,
            level=level,
            status=str(payload.payload.get("status") or "new"),
            category=category,
            source=str(payload.payload.get("source") or "edge"),
            clinical_severity=payload.payload.get("clinical_severity") or (level if category in {"clinical", "behavioral"} else None),
            technical_severity=payload.payload.get("technical_severity") or (level if category == "technical" else None),
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
