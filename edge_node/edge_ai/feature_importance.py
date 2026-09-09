from __future__ import annotations

import math
from typing import Any

FEATURE_LABELS: dict[str, str] = {
    "heart_rate_mean": "Frequenza cardiaca media",
    "heart_rate_std": "Variabilita' frequenza cardiaca",
    "resting_heart_rate": "Frequenza cardiaca a riposo",
    "hrv_rmssd": "Variabilita' cardiaca (HRV)",
    "spo2_mean": "Saturazione ossigeno (SpO2)",
    "sleep_minutes": "Minuti di sonno",
    "awake_minutes": "Minuti da sveglio",
    "steps": "Numero di passi",
    "sedentary_minutes": "Minuti sedentari",
    "room_changes": "Cambi di stanza",
    "night_room_changes": "Cambi di stanza notturni",
    "bedroom_minutes": "Minuti in camera",
    "kitchen_minutes": "Minuti in cucina",
    "bathroom_minutes": "Minuti in bagno",
    "living_room_minutes": "Minuti in soggiorno",
    "longest_single_room_minutes": "Permanenza piu' lunga in una stanza",
    "nilm_total_wh": "Consumo energia totale (Wh)",
    "nilm_kitchen_events": "Eventi cucina (NILM)",
    "nilm_tv_minutes": "Minuti TV (NILM)",
    "nilm_coffee_events": "Eventi caffe' (NILM)",
    "nilm_stove_events": "Eventi fornelli (NILM)",
    "fall_events": "Eventi caduta",
}

FEATURE_CATEGORIES: dict[str, str] = {
    "heart_rate_mean": "wearable",
    "heart_rate_std": "wearable",
    "resting_heart_rate": "wearable",
    "hrv_rmssd": "wearable",
    "spo2_mean": "wearable",
    "sleep_minutes": "wearable",
    "awake_minutes": "wearable",
    "steps": "wearable",
    "sedentary_minutes": "wearable",
    "room_changes": "spaziale",
    "night_room_changes": "spaziale",
    "bedroom_minutes": "spaziale",
    "kitchen_minutes": "spaziale",
    "bathroom_minutes": "spaziale",
    "living_room_minutes": "spaziale",
    "longest_single_room_minutes": "spaziale",
    "nilm_total_wh": "nilm",
    "nilm_kitchen_events": "nilm",
    "nilm_tv_minutes": "nilm",
    "nilm_coffee_events": "nilm",
    "nilm_stove_events": "nilm",
    "fall_events": "personale",
}

MIN_SCORE_DELTA: float = 0.5


def feature_label(feature: str) -> str:
    """Restituisce l'etichetta clinica leggibile per una feature."""
    if feature in FEATURE_LABELS:
        return FEATURE_LABELS[feature]
    return feature.replace("_", " ").strip().capitalize()


def feature_category(feature: str, model_scope: str = "personal") -> str:
    """Classifica una feature come spaziale, wearable, NILM o personale."""
    if feature in FEATURE_CATEGORIES:
        return FEATURE_CATEGORIES[feature]
    return "personale" if model_scope == "personal" else "altro"


def compute_feature_importance(
    detector: Any,
    record: Any,
    *,
    top_k: int = 6,
) -> dict[str, Any]:
    """Calcola l'importanza delle feature per la decisione corrente.

    Isolation Forest non offre un'importanza nativa. Usiamo quindi una versione
    "leave-one-out" controllata: per ogni feature sostituiamo il valore della
    finestra con la mediana del training e misuriamo quanto cambia lo score AI.
    La feature che fa scendere di piu' lo score e' quella che ha spinto l'indice
    verso l'alto (`aumenta_indice`); al contrario, se sostituirla con la mediana
    fa salire lo score, la feature stava tenendo l'indice basso
    (`riduce_indice`).
    """
    medians = _model_medians(detector)
    if not medians:
        return {"available": False, "reason": "feature_medians_missing"}

    row = _record_dict(record)
    baseline_score = float(detector.predict_record(row).anomaly_score)
    if not math.isfinite(baseline_score):
        return {"available": False, "reason": "baseline_score_not_finite"}

    deltas: list[dict[str, Any]] = []
    for feature in detector.metadata.feature_columns:
        if feature not in medians:
            continue
        replaced = dict(row)
        replaced[feature] = medians[feature]
        try:
            replacement_score = float(detector.predict_record(replaced).anomaly_score)
        except Exception:
            continue
        delta = replacement_score - baseline_score
        if not math.isfinite(delta) or abs(delta) < MIN_SCORE_DELTA:
            continue
        deltas.append(
            {
                "feature": feature,
                "value": _round_value(row.get(feature)),
                "reference": _round_value(medians[feature]),
                "delta": round(delta, 3),
            }
        )

    deltas.sort(key=lambda item: abs(float(item["delta"])), reverse=True)
    deltas = deltas[: max(1, top_k)]

    total = sum(abs(float(item["delta"])) for item in deltas) or 1.0
    items: list[dict[str, Any]] = []
    for item in deltas:
        delta = float(item["delta"])
        items.append(
            {
                "feature": item["feature"],
                "label": feature_label(item["feature"]),
                "category": feature_category(item["feature"], detector.metadata.model_scope),
                "impact": "aumenta_indice" if delta < 0 else "riduce_indice",
                "weight": round(abs(delta) / total, 4),
                "value": item["value"],
                "reference": item["reference"],
                "score_delta": item["delta"],
            }
        )

    return {
        "available": True,
        "method": "leave_one_out_median_replacement",
        "baseline_score": round(baseline_score, 3),
        "items": items,
    }


def _model_medians(detector: Any) -> dict[str, float]:
    medians = getattr(getattr(detector, "metadata", None), "feature_medians", None) or {}
    if not medians:
        return {}
    return {
        feature: float(value)
        for feature, value in medians.items()
        if math.isfinite(float(value))
    }


def _record_dict(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return dict(record)
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
            if isinstance(data, dict):
                return data
        except TypeError:
            pass
    return {}


def _round_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, 4)