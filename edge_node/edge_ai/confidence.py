from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Union

SOURCE_FEATURES: dict[str, list[str]] = {
    "google_health": [
        "heart_rate_mean",
        "heart_rate_std",
        "resting_heart_rate",
        "hrv_rmssd",
        "spo2_mean",
        "sleep_minutes",
        "awake_minutes",
        "steps",
    ],
    "ble": [
        "room_changes",
        "night_room_changes",
        "bedroom_minutes",
        "kitchen_minutes",
        "bathroom_minutes",
        "living_room_minutes",
        "longest_single_room_minutes",
        "sedentary_minutes",
    ],
    "shelly": [
        "nilm_total_wh",
        "nilm_kitchen_events",
        "nilm_tv_minutes",
        "nilm_coffee_events",
        "nilm_stove_events",
    ],
    "patient_app": ["fall_events"],
}

SOURCE_LABELS: dict[str, str] = {
    "google_health": "Google Health",
    "ble": "BLE",
    "shelly": "Shelly/NILM",
    "patient_app": "app paziente",
}

ALL_CONFIDENCE_FEATURES: list[str] = [
    feature for feature in SOURCE_FEATURES.values() for feature in feature
]

HIGH_CONFIDENCE: int = 75
MEDIUM_CONFIDENCE: int = 45

WEARABLE_ABSENT_PENALTY: float = 15.0
PERSONAL_MODEL_MISSING_PENALTY: float = 10.0
LOW_BLE_SAMPLES_PENALTY: float = 10.0
MQTT_QUEUE_DEEP_PENALTY: float = 10.0

LOW_BLE_SAMPLE_THRESHOLD: int = 5
MQTT_QUEUE_DEPTH_THRESHOLD: int = 20


@dataclass(frozen=True)
class SourceCompleteness:
    """Completezza dei dati per una singola sorgente."""

    source: str
    available: bool
    completeness: float
    present_features: int
    total_features: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "label": SOURCE_LABELS.get(self.source, self.source),
            "available": self.available,
            "completeness": round(self.completeness, 4),
            "present_features": self.present_features,
            "total_features": self.total_features,
        }


@dataclass(frozen=True)
class ConfidenceResult:
    """Indice di affidabilita' separato dallo score AI."""

    score: int
    level: str
    reasons: list[str]
    sources: list[SourceCompleteness] = field(default_factory=list)
    missing_features: list[str] = field(default_factory=list)
    penalties: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level,
            "reasons": self.reasons,
            "sources": [source.to_dict() for source in self.sources],
            "missing_features": self.missing_features,
            "penalties": dict(self.penalties),
        }


def compute_confidence(
    record: Union[dict[str, Any], object],
    *,
    personal_model_available: bool = False,
    ble_samples: int | None = None,
    mqtt_queue_depth: int | None = None,
) -> ConfidenceResult:
    """Calcola l'affidabilita' della decisione per una singola finestra.

    La confidenza e' separata dallo score AI: misura la qualita' del dato e del
    contesto, non la gravita' dell'anomalia. Il punteggio parte dal 100 e viene
    scalato in base alla percentuale di feature realmente disponibili nella
    finestra, poi applica penalita' esplicite (wearable assente, modello
    personale mancante, campioni BLE scarsi, coda MQTT lunga).

    I livelli seguono le convenzioni usate dalla dashboard di Emilio:
    `alta` >= 75, `media` >= 45, altrimenti `bassa`.
    """
    row = _row_from_record(record)
    sources: list[SourceCompleteness] = []
    missing: list[str] = []
    reasons: list[str] = []

    present_total = 0
    available_total = 0
    for source, features in SOURCE_FEATURES.items():
        present = [feature for feature in features if _is_present(row.get(feature))]
        absent = [feature for feature in features if feature not in present]
        missing.extend(absent)
        present_total += len(present)
        available_total += len(features)
        completeness = len(present) / len(features) if features else 0.0
        sources.append(
            SourceCompleteness(
                source=source,
                available=bool(present),
                completeness=round(completeness, 4),
                present_features=len(present),
                total_features=len(features),
            )
        )

    feature_ratio = present_total / available_total if available_total else 0.0
    score = round(100.0 * feature_ratio)
    penalties: dict[str, float] = {}
    for source in sources:
        if not source.available:
            reasons.append(f"{SOURCE_LABELS[source.source]} assente")
        elif source.completeness >= 0.999:
            reasons.append(f"{SOURCE_LABELS[source.source]} completo")
        else:
            label = "parziale" if source.completeness >= 0.5 else "quasi assente"
            reasons.append(f"{SOURCE_LABELS[source.source]} {label}")

    wearable_present = _parse_bool(row.get("wearable_present"))
    if wearable_present is False:
        score, applied = _apply_penalty(
            score, WEARABLE_ABSENT_PENALTY, "wearable assente", penalties, reasons
        )
        _ = applied  # penalty applicata

    if not personal_model_available:
        score, _ = _apply_penalty(
            score,
            PERSONAL_MODEL_MISSING_PENALTY,
            "modello personale non disponibile",
            penalties,
            reasons,
        )
    else:
        reasons.append("modello personale disponibile")

    if ble_samples is not None and ble_samples < LOW_BLE_SAMPLE_THRESHOLD:
        score, _ = _apply_penalty(
            score,
            LOW_BLE_SAMPLES_PENALTY,
            f"campioni BLE scarsi ({ble_samples})",
            penalties,
            reasons,
        )

    if mqtt_queue_depth is not None and mqtt_queue_depth > MQTT_QUEUE_DEPTH_THRESHOLD:
        score, _ = _apply_penalty(
            score,
            MQTT_QUEUE_DEEP_PENALTY,
            f"coda MQTT in attesa ({mqtt_queue_depth} messaggi)",
            penalties,
            reasons,
        )

    score = int(max(0, min(100, round(score))))
    return ConfidenceResult(
        score=score,
        level=confidence_level_from_score(score),
        reasons=reasons,
        sources=sources,
        missing_features=sorted(set(missing)),
        penalties=penalties,
    )


def confidence_level_from_score(score: float) -> str:
    """Mappa uno score 0-100 su un livello compatibile con la dashboard."""
    if not math.isfinite(score):
        return "media"
    if score >= HIGH_CONFIDENCE:
        return "alta"
    if score >= MEDIUM_CONFIDENCE:
        return "media"
    return "bassa"


def _apply_penalty(
    score: int,
    amount: float,
    reason: str,
    penalties: dict[str, float],
    reasons: list[str],
) -> tuple[int, float]:
    applied = min(amount, score)
    if reason not in reasons:
        reasons.append(reason)
    penalties[reason] = applied
    return int(score - applied), applied


def _is_present(value: Any) -> bool:
    """Considera un valore presente se non e' null, NaN o stringa vuota."""
    if value is None:
        return False
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in {"nan", "null", "none", "-", "n/d"}:
            return False
        return True
    if isinstance(value, float) and math.isnan(value):
        return False
    return True


def _row_from_record(record: Union[dict[str, Any], object]) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    if hasattr(record, "to_dict"):
        try:
            converted = record.to_dict()
            if isinstance(converted, dict):
                return converted
        except Exception:
            pass
    getter = getattr(record, "get", None)
    if callable(getter):
        try:
            data = getter()
        except TypeError:
            keys = getattr(record, "keys", None)
            if not callable(keys):
                return {}
            try:
                return {key: getter(key, None) for key in keys()}
            except Exception:
                return {}
        if isinstance(data, dict):
            return data
    return {}


def _parse_bool(value: Any) -> Union[bool, None]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "si", "sì", "presente"}:
        return True
    if normalized in {"0", "false", "no", "assente", "absent", ""}:
        return False
    return None