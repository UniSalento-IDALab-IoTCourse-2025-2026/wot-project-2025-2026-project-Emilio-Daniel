from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from edge_ai.features import load_feature_frame
from edge_ai.model import EdgeAnomalyDetector
from edge_ai.schema import FEATURE_COLUMNS


DEFAULT_BOOTSTRAP_ROWS = 1000

_CONTINUOUS_JITTER: dict[str, tuple[float, float]] = {
    "resting_heart_rate": (0.015, 0.5),
    "hrv_rmssd": (0.02, 0.5),
    "spo2_mean": (0.004, 0.15),
    "sleep_minutes": (0.01, 0.5),
    "awake_minutes": (0.02, 0.25),
    "bedroom_minutes": (0.03, 0.02),
    "kitchen_minutes": (0.03, 0.02),
    "bathroom_minutes": (0.03, 0.02),
    "living_room_minutes": (0.03, 0.02),
}

_LOWER_UPPER_BOUNDS: dict[str, tuple[float, float]] = {
    "resting_heart_rate": (30.0, 220.0),
    "hrv_rmssd": (0.0, 300.0),
    "spo2_mean": (70.0, 100.0),
    "sleep_minutes": (0.0, 1440.0),
    "awake_minutes": (0.0, 1440.0),
}

_ROOM_COLUMNS = (
    "bedroom_minutes",
    "kitchen_minutes",
    "bathroom_minutes",
    "living_room_minutes",
)


def build_personal_reference_frame(
    frame: pd.DataFrame,
    *,
    patient_id: str,
    rows: int = DEFAULT_BOOTSTRAP_ROWS,
    seed: int = 42,
    window_minutes: int = 4,
) -> pd.DataFrame:
    """Estende le finestre osservate mantenendo valori e vincoli del paziente."""
    source = frame.loc[frame["patient_id"].astype(str) == str(patient_id)].copy()
    if source.empty:
        raise ValueError(f"No rows found for patient_id={patient_id}")
    if rows < 50:
        raise ValueError("At least 50 output rows are required for model training")

    rng = np.random.default_rng(seed)
    sampled = source.iloc[rng.integers(0, len(source), size=rows)].reset_index(drop=True)
    sampled["patient_id"] = str(patient_id)

    for column, (relative_scale, minimum_scale) in _CONTINUOUS_JITTER.items():
        observed = pd.to_numeric(source[column], errors="coerce").dropna()
        if observed.empty:
            continue
        if column in _ROOM_COLUMNS and float(observed.max()) <= 0.0:
            continue
        median = float(observed.median())
        empirical_scale = float(observed.std(ddof=0))
        scale = max(empirical_scale * 0.08, abs(median) * relative_scale, minimum_scale)
        values = pd.to_numeric(sampled[column], errors="coerce")
        finite = values.notna()
        sampled.loc[finite, column] = (
            values.loc[finite].to_numpy(dtype=float)
            + rng.normal(0.0, scale, size=int(finite.sum()))
        )

    for column, (lower, upper) in _LOWER_UPPER_BOUNDS.items():
        sampled[column] = pd.to_numeric(sampled[column], errors="coerce").clip(lower, upper)

    _normalize_room_durations(sampled, window_minutes=float(window_minutes))

    start = pd.to_datetime(source["window_start"], utc=True).min()
    duration = timedelta(minutes=max(1, int(window_minutes)))
    sampled["window_start"] = [start + index * duration for index in range(rows)]
    sampled["window_end"] = sampled["window_start"] + duration
    return sampled


def train_personal_reference_model(
    *,
    baseline_csv: str | Path,
    model_output: str | Path,
    patient_id: str,
    rows: int = DEFAULT_BOOTSTRAP_ROWS,
    seed: int = 42,
    window_minutes: int = 4,
    contamination: float = 0.05,
) -> EdgeAnomalyDetector:
    """Crea e salva il modello personale a partire dalle finestre disponibili."""
    frame = load_feature_frame(baseline_csv)
    training_frame = build_personal_reference_frame(
        frame,
        patient_id=patient_id,
        rows=rows,
        seed=seed,
        window_minutes=window_minutes,
    )
    detector = EdgeAnomalyDetector.train(
        frame=training_frame,
        patient_id=patient_id,
        contamination=contamination,
        random_state=seed,
        model_scope="personal",
        training_source="synthetic_demo_bootstrap",
    )
    detector.save(model_output)
    return detector


def _normalize_room_durations(frame: pd.DataFrame, *, window_minutes: float) -> None:
    available = [column for column in _ROOM_COLUMNS if column in frame.columns]
    if not available:
        return
    room_values = frame.loc[:, available].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    room_values = room_values.clip(lower=0.0)
    totals = room_values.sum(axis=1)
    overflow = totals > window_minutes
    if overflow.any():
        room_values.loc[overflow] = room_values.loc[overflow].div(
            totals.loc[overflow], axis=0
        ) * window_minutes
    frame.loc[:, available] = room_values
    frame["longest_single_room_minutes"] = room_values.max(axis=1)

    for column in FEATURE_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
