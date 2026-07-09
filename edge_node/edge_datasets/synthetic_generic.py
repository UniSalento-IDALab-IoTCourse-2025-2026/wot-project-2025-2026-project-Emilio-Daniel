from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from edge_ai.schema import DATASET_COLUMNS


SPATIAL_FEATURES = [
    "room_changes",
    "night_room_changes",
    "bedroom_minutes",
    "kitchen_minutes",
    "bathroom_minutes",
    "living_room_minutes",
    "longest_single_room_minutes",
]

WEARABLE_FEATURES = [
    "heart_rate_mean",
    "heart_rate_std",
    "hrv_rmssd",
    "spo2_mean",
    "steps",
    "sedentary_minutes",
]


@dataclass(frozen=True)
class SyntheticGenericSummary:
    rows: int
    spatial_csv: str
    wearable_csv: str
    seed: int

    def to_dict(self) -> dict[str, Any]:
        """Converte il riepilogo in JSON serializzabile."""
        return {
            "rows": self.rows,
            "spatial_csv": self.spatial_csv,
            "wearable_csv": self.wearable_csv,
            "seed": self.seed,
        }


def generate_synthetic_generic_datasets(
    output_dir: str | Path,
    rows: int = 300_000,
    seed: int = 20260709,
    window_minutes: int = 4,
) -> SyntheticGenericSummary:
    """Genera dataset sintetici normativi per i modelli generici.

    Questi dataset non sono dataset clinici reali: servono a calibrare il
    comportamento dei modelli generici su finestre normali/standard e a dare
    pesi piu' stabili alle feature prima della baseline personale.
    """
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    starts = pd.date_range(
        "2026-01-01T00:00:00Z",
        periods=rows,
        freq=f"{window_minutes}min",
    )
    ends = starts + pd.Timedelta(minutes=window_minutes)

    spatial = _empty_frame(rows, starts, ends, "synthetic-spatial")
    _fill_spatial_normative(spatial, rng, window_minutes)
    spatial_csv = target_dir / "generic_spatial_synthetic_300k.csv"
    spatial.to_csv(spatial_csv, index=False)

    wearable = _empty_frame(rows, starts, ends, "synthetic-wearable")
    _fill_wearable_normative(wearable, rng, window_minutes)
    wearable_csv = target_dir / "generic_wearable_synthetic_300k.csv"
    wearable.to_csv(wearable_csv, index=False)

    return SyntheticGenericSummary(
        rows=rows,
        spatial_csv=str(spatial_csv),
        wearable_csv=str(wearable_csv),
        seed=seed,
    )


def _empty_frame(
    rows: int,
    starts: pd.DatetimeIndex,
    ends: pd.DatetimeIndex,
    patient_prefix: str,
) -> pd.DataFrame:
    """Crea un DataFrame nello schema completo con feature inizialmente vuote."""
    frame = pd.DataFrame(index=range(rows), columns=pd.Index(DATASET_COLUMNS))
    frame["patient_id"] = [f"{patient_prefix}-{index % 500:03d}" for index in range(rows)]
    frame["window_start"] = starts.astype(str)
    frame["window_end"] = ends.astype(str)
    frame["wearable_present"] = np.nan
    frame["wearable_battery_pct"] = np.nan
    for column in DATASET_COLUMNS:
        if column not in {"patient_id", "window_start", "window_end"}:
            frame[column] = np.nan
    return frame


def _fill_spatial_normative(
    frame: pd.DataFrame,
    rng: np.random.Generator,
    window_minutes: int,
) -> None:
    """Popola routine spaziali normali: permanenza stabile e pochi cambi stanza."""
    rooms = ["bedroom", "kitchen", "bathroom", "living_room"]
    room_probabilities = [0.30, 0.30, 0.12, 0.28]
    dominant_rooms = rng.choice(rooms, size=len(frame), p=room_probabilities)
    room_changes = np.clip(rng.poisson(0.35, size=len(frame)), 0, 4).astype(float)

    for row_index, dominant_room in enumerate(dominant_rooms):
        total_minutes = float(rng.uniform(window_minutes * 0.92, window_minutes))
        changes = int(room_changes[row_index])
        durations = {room: 0.0 for room in rooms}

        if changes == 0:
            durations[str(dominant_room)] = total_minutes
            longest = total_minutes
        else:
            segment_count = min(changes + 1, len(rooms))
            selected_rooms = [str(dominant_room)]
            remaining_rooms = [room for room in rooms if room != dominant_room]
            selected_rooms.extend(
                rng.choice(remaining_rooms, size=segment_count - 1, replace=False).tolist()
            )
            shares = rng.dirichlet(np.full(segment_count, 2.5))
            longest = 0.0
            for room, share in zip(selected_rooms, shares):
                minutes = float(share * total_minutes)
                durations[room] += minutes
                longest = max(longest, minutes)

        frame.at[row_index, "room_changes"] = float(changes)
        local_hour = ((row_index * window_minutes) // 60) % 24
        frame.at[row_index, "night_room_changes"] = (
            float(changes) if 0 <= local_hour < 6 else 0.0
        )
        frame.at[row_index, "bedroom_minutes"] = durations["bedroom"]
        frame.at[row_index, "kitchen_minutes"] = durations["kitchen"]
        frame.at[row_index, "bathroom_minutes"] = durations["bathroom"]
        frame.at[row_index, "living_room_minutes"] = durations["living_room"]
        frame.at[row_index, "longest_single_room_minutes"] = longest
        frame.at[row_index, "fall_events"] = 0.0


def _fill_wearable_normative(
    frame: pd.DataFrame,
    rng: np.random.Generator,
    window_minutes: int,
) -> None:
    """Popola finestre wearable normali con code fisiologiche controllate."""
    rows = len(frame)
    activity_state = rng.choice(
        ["rest", "light_activity", "borderline"],
        size=rows,
        p=[0.72, 0.23, 0.05],
    )

    heart_rate_mean = np.empty(rows)
    heart_rate_std = np.empty(rows)
    steps = np.empty(rows)
    for index, state in enumerate(activity_state):
        if state == "rest":
            heart_rate_mean[index] = rng.normal(72.0, 7.0)
            heart_rate_std[index] = rng.normal(4.5, 1.8)
            steps[index] = rng.poisson(4)
        elif state == "light_activity":
            heart_rate_mean[index] = rng.normal(92.0, 9.0)
            heart_rate_std[index] = rng.normal(8.0, 3.0)
            steps[index] = rng.poisson(95)
        else:
            heart_rate_mean[index] = rng.normal(102.0, 6.0)
            heart_rate_std[index] = rng.normal(10.0, 3.0)
            steps[index] = rng.poisson(45)

    spo2_state = rng.choice(["healthy", "low_normal"], size=rows, p=[0.88, 0.12])
    spo2_mean = np.where(
        spo2_state == "healthy",
        rng.normal(97.0, 1.0, size=rows),
        rng.normal(93.0, 1.0, size=rows),
    )
    hrv_state = rng.choice(["healthy", "low_normal"], size=rows, p=[0.86, 0.14])
    hrv_rmssd = np.where(
        hrv_state == "healthy",
        rng.normal(45.0, 14.0, size=rows),
        rng.normal(17.0, 3.0, size=rows),
    )

    heart_rate_mean = np.clip(heart_rate_mean, 48.0, 114.0)
    heart_rate_std = np.clip(heart_rate_std, 1.0, 18.0)
    hrv_rmssd = np.clip(hrv_rmssd, 8.0, 110.0)
    spo2_mean = np.clip(spo2_mean, 91.0, 100.0)
    steps = np.clip(steps, 0.0, 450.0)
    sedentary_minutes = np.clip(
        window_minutes - (steps / 120.0),
        0.0,
        float(window_minutes),
    )

    frame["wearable_present"] = True
    frame["wearable_battery_pct"] = rng.uniform(25.0, 100.0, size=rows)
    frame["heart_rate_mean"] = heart_rate_mean
    frame["heart_rate_std"] = heart_rate_std
    frame["resting_heart_rate"] = np.clip(rng.normal(60.0, 7.0, size=rows), 45.0, 80.0)
    frame["hrv_rmssd"] = hrv_rmssd
    frame["spo2_mean"] = spo2_mean
    frame["steps"] = steps
    frame["sedentary_minutes"] = sedentary_minutes
    frame["fall_events"] = 0.0
