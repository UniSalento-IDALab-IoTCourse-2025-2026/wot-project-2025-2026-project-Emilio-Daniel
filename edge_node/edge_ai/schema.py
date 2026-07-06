from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


FEATURE_COLUMNS: list[str] = [
    "heart_rate_mean",
    "heart_rate_std",
    "resting_heart_rate",
    "hrv_rmssd",
    "spo2_mean",
    "sleep_minutes",
    "awake_minutes",
    "steps",
    "sedentary_minutes",
    "room_changes",
    "night_room_changes",
    "bedroom_minutes",
    "kitchen_minutes",
    "bathroom_minutes",
    "living_room_minutes",
    "longest_single_room_minutes",
    "nilm_total_wh",
    "nilm_kitchen_events",
    "nilm_tv_minutes",
    "nilm_coffee_events",
    "nilm_stove_events",
    "fall_events",
]

OPTIONAL_CONTEXT_COLUMNS: list[str] = [
    "patient_id",
    "window_start",
    "window_end",
    "wearable_present",
    "wearable_battery_pct",
]

REQUIRED_COLUMNS: list[str] = OPTIONAL_CONTEXT_COLUMNS[:3] + FEATURE_COLUMNS
DATASET_COLUMNS: list[str] = OPTIONAL_CONTEXT_COLUMNS + FEATURE_COLUMNS


@dataclass(frozen=True)
class InferenceResult:
    patient_id: str
    window_start: datetime
    window_end: datetime
    anomaly_score: float
    model_decision_value: float
    model_label: str
    feature_values: dict[str, float]
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TriageDecision:
    patient_id: str
    window_start: datetime
    window_end: datetime
    level: str
    should_publish: bool
    anomaly_score: float
    reasons: list[str]
    model_label: str
    evidence: dict[str, Any] = field(default_factory=dict)


def parse_timestamp(value: Any) -> datetime:
    """Normalizza un timestamp in un oggetto `datetime` UTC.

    I dati possono arrivare da CSV, JSON o pandas con formati leggermente
    diversi. Questa funzione rende uniforme la rappresentazione temporale, cosi'
    inferenza e debounce confrontano sempre finestre nello stesso fuso logico.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
