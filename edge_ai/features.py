from __future__ import annotations

from pathlib import Path

import pandas as pd

from edge_ai.schema import FEATURE_COLUMNS, REQUIRED_COLUMNS


def load_feature_frame(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Input dataset not found: {source}")

    if source.suffix.lower() == ".json":
        frame = pd.read_json(source)
    else:
        frame = pd.read_csv(source)

    return validate_feature_frame(frame)


def validate_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(
            "Missing required columns: " + ", ".join(missing)
        )

    cleaned = frame.copy()
    cleaned["patient_id"] = cleaned["patient_id"].astype(str)
    cleaned["window_start"] = pd.to_datetime(cleaned["window_start"], utc=True)
    cleaned["window_end"] = pd.to_datetime(cleaned["window_end"], utc=True)

    for column in FEATURE_COLUMNS:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    return cleaned


def select_features(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[FEATURE_COLUMNS].copy()


def latest_record(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        raise ValueError("Input dataset contains no records")
    ordered = frame.sort_values("window_end")
    return ordered.iloc[-1]
