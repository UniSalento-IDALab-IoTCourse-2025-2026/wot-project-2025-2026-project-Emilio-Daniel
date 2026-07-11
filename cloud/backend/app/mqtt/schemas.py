from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.mqtt.topics import ParsedTopic


class EdgeMqttPayload(BaseModel):
    """Schema comune dei messaggi MQTT pubblicati dai Raspberry Edge."""

    schema_version: int = Field(..., ge=1)
    message_id: str = Field(..., min_length=1, max_length=128)
    event_type: str = Field(..., min_length=1, max_length=64)
    patient_id: str = Field(..., min_length=1, max_length=64)
    edge_id: str | None = Field(default=None, max_length=128)
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include timezone.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def reject_nan_strings_and_values(self) -> "EdgeMqttPayload":
        reject_nan_like_values(self.model_dump(mode="python"))
        return self


def decode_payload(raw_payload: bytes, topic: ParsedTopic) -> EdgeMqttPayload:
    """Decodifica e valida un payload MQTT usando il contratto condiviso."""
    try:
        data = json.loads(raw_payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("Payload is not valid UTF-8.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Payload is not valid JSON.") from exc

    payload = EdgeMqttPayload.model_validate(data)
    if payload.patient_id != topic.patient_id:
        raise ValueError("patient_id in payload does not match MQTT topic.")
    return payload


def reject_nan_like_values(value: Any) -> None:
    """Rifiuta stringhe 'nan' e valori NaN annidati nei payload."""
    if isinstance(value, str) and value.lower() == "nan":
        raise ValueError("Missing values must be null, not string 'nan'.")
    if isinstance(value, float) and math.isnan(value):
        raise ValueError("Missing values must be null, not NaN.")
    if isinstance(value, dict):
        for item in value.values():
            reject_nan_like_values(item)
    elif isinstance(value, list):
        for item in value:
            reject_nan_like_values(item)
