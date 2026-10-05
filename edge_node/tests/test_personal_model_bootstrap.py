from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from edge_ai.model import EdgeAnomalyDetector
from edge_ai.schema import DATASET_COLUMNS
from edge_maintenance.personal_model import (
    build_personal_reference_frame,
    train_personal_reference_model,
)


def _baseline() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start = pd.Timestamp("2026-07-14T08:00:00Z")
    for index in range(8):
        row = {column: np.nan for column in DATASET_COLUMNS}
        row.update(
            {
                "patient_id": "patient-001",
                "window_start": start + pd.Timedelta(int(index * 4), unit="min"),
                "window_end": start + pd.Timedelta(int((index + 1) * 4), unit="min"),
                "wearable_present": 1.0,
                "wearable_battery_pct": 94.0,
                "resting_heart_rate": 52.0,
                "hrv_rmssd": 84.65,
                "spo2_mean": 94.0,
                "sleep_minutes": 194.0,
                "awake_minutes": 25.0,
                "room_changes": float(index % 2),
                "night_room_changes": 0.0,
                "bedroom_minutes": 0.0,
                "kitchen_minutes": 3.5 - index * 0.2,
                "bathroom_minutes": index * 0.2,
                "living_room_minutes": 0.0,
                "longest_single_room_minutes": max(3.5 - index * 0.2, index * 0.2),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def test_reference_frame_is_deterministic_and_keeps_room_constraints() -> None:
    first = build_personal_reference_frame(
        _baseline(), patient_id="patient-001", rows=100, seed=7
    )
    second = build_personal_reference_frame(
        _baseline(), patient_id="patient-001", rows=100, seed=7
    )

    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 100
    room_total = first[
        ["bedroom_minutes", "kitchen_minutes", "bathroom_minutes", "living_room_minutes"]
    ].sum(axis=1)
    assert bool((room_total <= 4.0 + 1e-9).all())
    assert first["heart_rate_mean"].isna().all()
    assert first["resting_heart_rate"].nunique() > 1
    assert bool((first["bedroom_minutes"] == 0.0).all())
    assert bool((first["living_room_minutes"] == 0.0).all())


def test_reference_model_can_be_saved_loaded_and_used(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.csv"
    output = tmp_path / "patient-001.pkl"
    _baseline().to_csv(baseline, index=False)

    detector = train_personal_reference_model(
        baseline_csv=baseline,
        model_output=output,
        patient_id="patient-001",
        rows=100,
        seed=9,
    )

    loaded = EdgeAnomalyDetector.load(output)
    result = loaded.predict_record(_baseline().iloc[-1])
    assert detector.metadata.model_scope == "personal"
    assert loaded.metadata.patient_id == "patient-001"
    assert loaded.metadata.training_rows == 100
    assert loaded.metadata.training_source == "synthetic_demo_bootstrap"
    assert 0.0 <= result.anomaly_score <= 100.0
