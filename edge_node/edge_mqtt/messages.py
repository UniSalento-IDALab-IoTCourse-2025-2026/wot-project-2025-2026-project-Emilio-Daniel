from __future__ import annotations

import csv
import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MqttMessage:
    """Messaggio pronto per essere pubblicato o accodato su disco."""

    topic: str
    payload: dict[str, Any]
    qos: int = 1
    retain: bool = False

    @property
    def message_id(self) -> str:
        return str(self.payload.get("message_id", "unknown-message"))

    def to_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def build_cycle_messages(
    *,
    patient_id: str,
    edge_id: str,
    status_payload: dict[str, Any],
    latest_window_csv: Path,
    decision_json: Path,
    retain_status: bool,
    absence_json: Path | None = None,
) -> list[MqttMessage]:
    """Costruisce i messaggi MQTT del ciclo Edge coerenti con il backend D4."""
    messages: list[MqttMessage] = [
        _status_message(
            patient_id=patient_id,
            edge_id=edge_id,
            status_payload=status_payload,
            retain=retain_status,
        )
    ]

    if latest_window_csv.exists():
        messages.append(
            _window_message(
                patient_id=patient_id,
                edge_id=edge_id,
                latest_window_csv=latest_window_csv,
            )
        )

    if decision_json.exists():
        decision_message = _decision_message(
            patient_id=patient_id,
            edge_id=edge_id,
            decision_json=decision_json,
        )
        messages.append(decision_message)
        alert_message = _alert_message_from_decision(
            patient_id=patient_id,
            edge_id=edge_id,
            decision_payload=decision_message.payload["payload"],
        )
        if alert_message is not None:
            messages.append(alert_message)

    if absence_json is not None and absence_json.exists():
        try:
            absence_message = _absence_alert_message(
                patient_id=patient_id,
                edge_id=edge_id,
                absence_json=absence_json,
            )
        except (OSError, ValueError):
            absence_message = None
        if absence_message is not None:
            messages.append(absence_message)

    return messages


def _absence_alert_message(
    *,
    patient_id: str,
    edge_id: str,
    absence_json: Path,
) -> MqttMessage:
    """Pubblica un alert di assenza insolita con il message_id stabile dell'episodio.

    Il message_id viene dal file scritto dal runtime (include tipo, stanza ed
    episodio): il backend lo usa per evitare duplicati dello stesso episodio.
    """
    with absence_json.open("r", encoding="utf-8") as handle:
        signal = json.load(handle)

    payload = {
        "level": str(signal.get("level") or "orange"),
        "status": "new",
        "category": str(signal.get("category") or "absence"),
        "source": "edge",
        "title": str(signal.get("title") or "Assenza insolita da verificare"),
        "description": str(signal.get("description") or signal.get("reason") or ""),
        "opened_at": utc_now_iso(),
        "reason": signal.get("reason"),
        "duration_minutes": signal.get("duration_minutes"),
        "no_movement_minutes": signal.get("no_movement_minutes"),
        "last_room": signal.get("last_room"),
        "last_transition_at": signal.get("last_transition_at"),
        "ble_quality": signal.get("ble_quality"),
        "kind": signal.get("kind"),
    }
    message_id = str(signal.get("message_id") or f"absence-{uuid.uuid4().hex}")
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "message_id": message_id,
        "event_type": "alert_created",
        "patient_id": patient_id,
        "edge_id": edge_id,
        "timestamp": utc_now_iso(),
        "payload": clean_for_json(payload),
    }
    return MqttMessage(
        topic=f"iot/patients/{patient_id}/alerts/critical",
        qos=1,
        retain=False,
        payload=envelope,
    )


def build_last_will_message(*, patient_id: str, edge_id: str) -> MqttMessage:
    """Crea il Last Will pubblicato dal broker se l'Edge cade senza disconnettersi."""
    return MqttMessage(
        topic=f"iot/patients/{patient_id}/edge/status",
        qos=1,
        retain=True,
        payload=_envelope(
            patient_id=patient_id,
            edge_id=edge_id,
            event_type="edge_offline_unexpected",
            payload={
                "online": False,
                "reason": "mqtt_last_will",
            },
        ),
    )


def _status_message(
    *,
    patient_id: str,
    edge_id: str,
    status_payload: dict[str, Any],
    retain: bool,
) -> MqttMessage:
    payload = clean_for_json(status_payload)
    payload["online"] = True
    return MqttMessage(
        topic=f"iot/patients/{patient_id}/edge/status",
        qos=1,
        retain=retain,
        payload=_envelope(
            patient_id=patient_id,
            edge_id=edge_id,
            event_type="edge_cycle_completed",
            payload=payload,
        ),
    )


def _window_message(*, patient_id: str, edge_id: str, latest_window_csv: Path) -> MqttMessage:
    row = _latest_csv_row(latest_window_csv)
    row_patient_id = str(row.get("patient_id") or patient_id)
    window_start = str(row.get("window_start") or "")
    window_end = str(row.get("window_end") or "")
    features = {
        key: normalize_csv_value(value)
        for key, value in row.items()
        if key not in {"patient_id", "window_start", "window_end"}
    }
    return MqttMessage(
        topic=f"iot/patients/{row_patient_id}/telemetry/window",
        qos=1,
        retain=False,
        payload=_envelope(
            patient_id=row_patient_id,
            edge_id=edge_id,
            event_type="patient_window_updated",
            payload={
                "window_start": window_start,
                "window_end": window_end,
                "features": features,
            },
        ),
    )


def _decision_message(*, patient_id: str, edge_id: str, decision_json: Path) -> MqttMessage:
    with decision_json.open("r", encoding="utf-8") as handle:
        decision_payload = clean_for_json(json.load(handle))
    row_patient_id = str(decision_payload.get("patient_id") or patient_id)
    return MqttMessage(
        topic=f"iot/patients/{row_patient_id}/telemetry/decision",
        qos=1,
        retain=False,
        payload=_envelope(
            patient_id=row_patient_id,
            edge_id=edge_id,
            event_type="decision_updated",
            payload=decision_payload,
        ),
    )


def _alert_message_from_decision(
    *,
    patient_id: str,
    edge_id: str,
    decision_payload: dict[str, Any],
) -> MqttMessage | None:
    if not bool(decision_payload.get("should_publish")):
        return None

    level = str(decision_payload.get("level") or "red")
    reasons = decision_payload.get("reasons")
    if isinstance(reasons, list) and reasons:
        description = " | ".join(str(item) for item in reasons)
    else:
        description = "Decisione Edge pubblicabile."

    return MqttMessage(
        topic=f"iot/patients/{patient_id}/alerts/critical",
        qos=1,
        retain=False,
        payload=_envelope(
            patient_id=patient_id,
            edge_id=edge_id,
            event_type="alert_created",
            payload={
                "level": level,
                "status": "new",
                "category": "behavioral",
                "title": f"Allarme Edge {level}",
                "description": description,
                "opened_at": utc_now_iso(),
                "anomaly_score": decision_payload.get("anomaly_score"),
                "model_label": decision_payload.get("model_label"),
                "decision": decision_payload,
            },
        ),
    )


def _envelope(
    *,
    patient_id: str,
    edge_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "message_id": f"{event_type}-{uuid.uuid4().hex}",
        "event_type": event_type,
        "patient_id": patient_id,
        "edge_id": edge_id,
        "timestamp": utc_now_iso(),
        "payload": clean_for_json(payload),
    }


def _latest_csv_row(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"CSV senza righe dati: {path}")
    return rows[-1]


def normalize_csv_value(value: Any) -> Any:
    """Converte valori CSV in JSON pulito: numeri, booleani e null reali."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return None
        if text.lower() == "true":
            return True
        if text.lower() == "false":
            return False
        try:
            number = float(text)
        except ValueError:
            return text
        if math.isnan(number):
            return None
        if number.is_integer():
            return int(number)
        return number
    return clean_for_json(value)


def clean_for_json(value: Any) -> Any:
    """Rimuove NaN e normalizza ricorsivamente i payload prima di MQTT."""
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, str) and value.strip().lower() == "nan":
        return None
    if isinstance(value, dict):
        return {str(key): clean_for_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_for_json(item) for item in value]
    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
