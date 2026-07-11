from __future__ import annotations

from dataclasses import dataclass


SUPPORTED_TOPIC_KINDS = {
    "edge/status",
    "telemetry/window",
    "telemetry/decision",
    "alerts/critical",
    "sensors/watch",
    "sensors/ble",
}


@dataclass(frozen=True)
class ParsedTopic:
    """Informazioni normalizzate estratte da un topic MQTT del progetto."""

    raw: str
    patient_id: str
    kind: str


def parse_topic(topic: str) -> ParsedTopic:
    """Legge un topic MQTT del progetto e rifiuta percorsi non supportati."""
    parts = topic.split("/")
    if len(parts) < 5 or parts[:2] != ["iot", "patients"]:
        raise ValueError(f"Unsupported MQTT topic: {topic}")

    patient_id = parts[2]
    kind = "/".join(parts[3:])
    if kind not in SUPPORTED_TOPIC_KINDS:
        raise ValueError(f"Unsupported MQTT topic kind: {kind}")
    if not patient_id:
        raise ValueError("MQTT topic patient_id is missing.")

    return ParsedTopic(raw=topic, patient_id=patient_id, kind=kind)


def subscription_topics() -> list[tuple[str, int]]:
    """Restituisce i topic e i QoS a cui il worker backend deve iscriversi."""
    return [
        ("iot/patients/+/edge/status", 1),
        ("iot/patients/+/telemetry/window", 1),
        ("iot/patients/+/telemetry/decision", 1),
        ("iot/patients/+/alerts/critical", 1),
        ("iot/patients/+/sensors/watch", 1),
        ("iot/patients/+/sensors/ble", 1),
    ]
