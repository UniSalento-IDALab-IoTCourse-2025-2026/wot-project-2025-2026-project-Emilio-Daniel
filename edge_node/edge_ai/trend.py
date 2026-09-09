from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import math


MIN_POINTS_FOR_TREND = 4
SLOPE_DIRECTION_THRESHOLDS = {"in_aumento": 2.0, "in_diminuzione": -2.0}


def linear_slope(points: list[tuple[float, float]]) -> tuple[float | None, int]:
    """Calcola la pendenza (slope) con regressione lineare per minimi quadrati.

    Ogni punto e' una tupla (x, y) dove x rappresenta giorni dall'origine e
    y il valore osservato. Restituisce (slope, n_punti).
    """
    n = len(points)
    if n < 2:
        return None, n
    sum_x = sum(x for x, _ in points)
    sum_y = sum(y for _, y in points)
    sum_xx = sum(x * x for x, _ in points)
    sum_xy = sum(x * y for x, y in points)
    denominator = n * sum_xx - sum_x * sum_x
    if abs(denominator) < 1e-9:
        return 0.0, n
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    return slope, n


def trend_direction(slope_per_day: float | None) -> str:
    """Mappa la pendenza giornaliera alla direzione attesa dalla UI (D26)."""
    if slope_per_day is None or not math.isfinite(slope_per_day):
        return "unknown"
    if slope_per_day > SLOPE_DIRECTION_THRESHOLDS["in_aumento"]:
        return "in_aumento"
    if slope_per_day < SLOPE_DIRECTION_THRESHOLDS["in_diminuzione"]:
        return "in_diminuzione"
    return "stabile"


def trend_dict(
    slope_per_day: float | None,
    n_points: int,
    window_days: int,
) -> dict[str, Any]:
    """Costruisce il dizionario trend compatibile con TrendDriftPanel (D26)."""
    return {
        "score_slope_per_day": (
            round(slope_per_day, 2) if slope_per_day is not None and math.isfinite(slope_per_day) else None
        ),
        "direction": trend_direction(slope_per_day),
        "window_days": window_days if n_points >= MIN_POINTS_FOR_TREND else None,
        "n_points": n_points,
    }


def feature_trend(
    values: list[tuple[float, float]],
    window_days: int,
) -> dict[str, Any]:
    """Calcola il trend di una feature da coppie (giorni_dal_riferimento, valore)."""
    slope, n = linear_slope(values)
    return {
        "slope_per_day": round(slope, 3) if slope is not None and math.isfinite(slope) else None,
        "direction": trend_direction(slope),
        "window_days": window_days if n >= MIN_POINTS_FOR_TREND else None,
        "n_points": n,
    }


def score_trend_from_timestamps(
    timestamp_values: list[tuple[datetime, float]],
    reference: datetime | None = None,
    *,
    windows: tuple[int, ...] = (3, 7, 14),
) -> dict[str, Any]:
    """Calcola il trend dello score AI per diverse finestre temporali.

    Restituisce un dizionario con le trend per ogni finestra e la migliore
    disponibile (quella con piu' dati, preferendo la piu' ampia).
    """
    ref = reference or datetime.now(timezone.utc)
    ref = ref.replace(tzinfo=timezone.utc) if ref.tzinfo is None else ref

    base_points: list[tuple[float, float]] = []
    for ts, value in timestamp_values:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        days_ago = (ref - ts).total_seconds() / 86400.0
        if days_ago >= 0:
            base_points.append((days_ago, value))

    if not base_points:
        return {"best": trend_dict(None, 0, 0), "windows": {}}

    all_points_sorted = sorted(base_points, key=lambda p: p[0], reverse=True)
    x_offset = all_points_sorted[0][0] if all_points_sorted else 0.0
    ascending = [(x_offset - x, y) for x, y in all_points_sorted]
    results: dict[str, dict[str, Any]] = {}
    best: dict[str, Any] | None = None

    for window in sorted(windows, reverse=True):
        cutoff = float(window)
        filtered = [(x, y) for x, y in ascending if (x_offset - x) <= cutoff]
        slope, n = linear_slope(filtered)
        trend = trend_dict(slope, n, window)
        results[str(window)] = trend
        if best is None or n > best.get("_n", 0):
            best = {**trend, "_n": n}

    return {"best": best or trend_dict(None, 0, 0), "windows": results}