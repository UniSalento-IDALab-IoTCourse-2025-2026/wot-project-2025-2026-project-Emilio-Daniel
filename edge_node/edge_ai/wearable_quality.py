from __future__ import annotations

from typing import Any

import pandas as pd


CORE_WEARABLE_FEATURES = (
    "heart_rate_mean",
    "steps",
    "sedentary_minutes",
    "hrv_rmssd",
)


def wearable_signal_summary(record: Any) -> dict[str, Any]:
    """Riassume se una finestra ha segnali wearable dinamici utili al modello.

    Le metriche giornaliere come sonno o SpO2 sono preziose come contesto, ma da
    sole non bastano per valutare una finestra da 4 minuti. Questa funzione
    cerca quindi feature dinamiche, in particolare battito e passi.
    """
    values = _to_mapping(record)
    available = [
        feature
        for feature in CORE_WEARABLE_FEATURES
        if _has_value(values.get(feature))
    ]
    return {
        "has_core_signal": bool(available),
        "available_core_features": available,
        "required_any_of": list(CORE_WEARABLE_FEATURES),
    }


def has_wearable_core_signal(record: Any) -> bool:
    """Restituisce `True` quando il modello wearable puo' essere eseguito."""
    return bool(wearable_signal_summary(record)["has_core_signal"])


def _to_mapping(record: Any) -> dict[str, Any]:
    if isinstance(record, pd.Series):
        return record.to_dict()
    if isinstance(record, dict):
        return record
    return dict(record)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    try:
        return not pd.isna(value)
    except TypeError:
        return bool(str(value).strip())
