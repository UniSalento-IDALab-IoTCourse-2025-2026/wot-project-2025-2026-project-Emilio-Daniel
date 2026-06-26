from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from math import isnan
from pathlib import Path
from typing import Any

import pandas as pd

from edge_ai.schema import parse_timestamp
from edge_ingest.config import EdgeIngestConfig


FITBIT_FEATURES = [
    "heart_rate_mean",
    "heart_rate_std",
    "resting_heart_rate",
    "hrv_rmssd",
    "spo2_mean",
    "sleep_minutes",
    "awake_minutes",
    "steps",
    "sedentary_minutes",
]


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityReport:
    generated_at: str
    patient_id: str
    window_start: str
    window_end: str
    status: str
    usable_for_training: bool
    issues: list[QualityIssue]
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [asdict(issue) for issue in self.issues]
        return payload


def evaluate_quality(
    config: EdgeIngestConfig,
    row: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    now: datetime | None = None,
) -> QualityReport:
    now_utc = _as_utc(now or datetime.now(timezone.utc))
    start_utc = _as_utc(window_start)
    end_utc = _as_utc(window_end)
    issues: list[QualityIssue] = []
    metrics: dict[str, Any] = {}

    _check_window_bounds(start_utc, end_utc, now_utc, issues, metrics)
    _check_ble(config, start_utc, end_utc, now_utc, issues, metrics)
    _check_fitbit(config, row, issues, metrics)
    _check_shelly(config, start_utc, end_utc, issues, metrics)

    status = _overall_status(issues)
    return QualityReport(
        generated_at=now_utc.isoformat(),
        patient_id=str(row.get("patient_id", config.patient.patient_id)),
        window_start=start_utc.isoformat(),
        window_end=end_utc.isoformat(),
        status=status,
        usable_for_training=status != "error",
        issues=issues,
        metrics=metrics,
    )


def _check_window_bounds(
    window_start: datetime,
    window_end: datetime,
    now: datetime,
    issues: list[QualityIssue],
    metrics: dict[str, Any],
) -> None:
    duration_minutes = (window_end - window_start).total_seconds() / 60.0
    metrics["window_duration_minutes"] = round(duration_minutes, 3)
    if duration_minutes <= 0:
        issues.append(
            QualityIssue(
                code="invalid_window_bounds",
                severity="error",
                message="Window end must be after window start.",
            )
        )
    if window_end > now + timedelta(minutes=10):
        issues.append(
            QualityIssue(
                code="window_in_future",
                severity="error",
                message="Window end is too far in the future.",
                details={"now": now.isoformat()},
            )
        )


def _check_ble(
    config: EdgeIngestConfig,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
    issues: list[QualityIssue],
    metrics: dict[str, Any],
) -> None:
    if not config.ble.enabled:
        metrics["ble_enabled"] = False
        return

    metrics["ble_enabled"] = True
    raw_csv = config.ble.raw_csv
    metrics["ble_raw_csv"] = str(raw_csv)
    if not raw_csv.exists():
        metrics["ble_current_window_samples"] = 0
        issues.append(
            QualityIssue(
                code="ble_raw_missing",
                severity="error",
                message="BLE is enabled but the raw BLE CSV does not exist.",
                details={"path": str(raw_csv)},
            )
        )
        return

    try:
        frame = pd.read_csv(raw_csv)
    except Exception as exc:
        issues.append(
            QualityIssue(
                code="ble_raw_unreadable",
                severity="error",
                message="BLE raw CSV cannot be read.",
                details={"path": str(raw_csv), "error": str(exc)},
            )
        )
        return

    metrics["ble_total_rows"] = int(len(frame))
    if frame.empty:
        metrics["ble_current_window_samples"] = 0
        issues.append(
            QualityIssue(
                code="ble_raw_empty",
                severity="error",
                message="BLE is enabled but the raw BLE CSV is empty.",
                details={"path": str(raw_csv)},
            )
        )
        return

    missing_columns = [column for column in ("timestamp", "room") if column not in frame.columns]
    if missing_columns:
        issues.append(
            QualityIssue(
                code="ble_raw_missing_columns",
                severity="error",
                message="BLE raw CSV is missing required columns.",
                details={"missing_columns": missing_columns},
            )
        )
        return

    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    invalid_count = int(timestamps.isna().sum())
    metrics["ble_invalid_timestamps"] = invalid_count
    if invalid_count == len(frame):
        issues.append(
            QualityIssue(
                code="ble_all_timestamps_invalid",
                severity="error",
                message="All BLE timestamps are invalid.",
            )
        )
        return
    if invalid_count:
        issues.append(
            QualityIssue(
                code="ble_some_timestamps_invalid",
                severity="warning",
                message="Some BLE rows have invalid timestamps.",
                details={"invalid_rows": invalid_count},
            )
        )

    prepared = frame.copy()
    prepared["timestamp"] = timestamps
    prepared = prepared.dropna(subset=["timestamp"])
    future_count = int((prepared["timestamp"] > pd.Timestamp(now + timedelta(minutes=10))).sum())
    metrics["ble_future_timestamps"] = future_count
    if future_count:
        issues.append(
            QualityIssue(
                code="ble_future_timestamps",
                severity="error",
                message="BLE CSV contains timestamps too far in the future.",
                details={"future_rows": future_count},
            )
        )

    duplicate_count = int(prepared["timestamp"].duplicated().sum())
    metrics["ble_duplicate_timestamps"] = duplicate_count
    if duplicate_count:
        issues.append(
            QualityIssue(
                code="ble_duplicate_timestamps",
                severity="warning",
                message="BLE CSV contains duplicated timestamps.",
                details={"duplicate_rows": duplicate_count},
            )
        )

    current_mask = (
        (prepared["timestamp"] >= pd.Timestamp(window_start))
        & (prepared["timestamp"] <= pd.Timestamp(window_end))
    )
    current = prepared.loc[current_mask].copy()
    current_count = int(len(current))
    metrics["ble_current_window_samples"] = current_count
    recommended_samples = max(3, int(config.window.minutes / 2))
    metrics["ble_recommended_window_samples"] = recommended_samples
    if current_count == 0:
        latest_ts = prepared["timestamp"].max()
        issues.append(
            QualityIssue(
                code="ble_no_samples_in_window",
                severity="error",
                message="No BLE samples were found in the current window.",
                details={"latest_ble_timestamp": latest_ts.isoformat()},
            )
        )
    elif current_count < recommended_samples:
        issues.append(
            QualityIssue(
                code="ble_few_samples_in_window",
                severity="warning",
                message="Few BLE samples were found in the current window.",
                details={
                    "samples": current_count,
                    "recommended_minimum": recommended_samples,
                },
            )
        )

    empty_room_count = int(current["room"].astype(str).str.strip().eq("").sum()) if current_count else 0
    metrics["ble_empty_room_values"] = empty_room_count
    if empty_room_count:
        issues.append(
            QualityIssue(
                code="ble_empty_room_values",
                severity="warning",
                message="Some BLE samples in the current window have an empty room.",
                details={"empty_room_rows": empty_room_count},
            )
        )

    _check_static_room(prepared, window_end, issues, metrics)


def _check_static_room(
    frame: pd.DataFrame,
    window_end: datetime,
    issues: list[QualityIssue],
    metrics: dict[str, Any],
) -> None:
    lookback_start = pd.Timestamp(window_end - timedelta(hours=4))
    recent = frame.loc[frame["timestamp"] >= lookback_start].copy()
    if recent.empty:
        metrics["ble_static_room_lookback_samples"] = 0
        return

    recent["room_key"] = recent["room"].astype(str).str.strip().str.lower()
    recent = recent[recent["room_key"] != ""]
    metrics["ble_static_room_lookback_samples"] = int(len(recent))
    if len(recent) < 10:
        return

    unique_rooms = sorted(recent["room_key"].unique())
    metrics["ble_static_room_unique_rooms"] = unique_rooms
    span_minutes = (
        recent["timestamp"].max() - recent["timestamp"].min()
    ).total_seconds() / 60.0
    metrics["ble_static_room_span_minutes"] = round(span_minutes, 3)
    if len(unique_rooms) == 1 and span_minutes >= 120:
        issues.append(
            QualityIssue(
                code="ble_prolonged_same_room_observed",
                severity="info",
                message=(
                    "BLE has reported the same room for multiple hours. "
                    "This is a behavioral observation, not a data quality error."
                ),
                details={
                    "room": unique_rooms[0],
                    "span_minutes": round(span_minutes, 1),
                    "samples": int(len(recent)),
                },
            )
        )


def _check_fitbit(
    config: EdgeIngestConfig,
    row: dict[str, Any],
    issues: list[QualityIssue],
    metrics: dict[str, Any],
) -> None:
    if not config.fitbit.enabled:
        metrics["fitbit_enabled"] = False
        return

    metrics["fitbit_enabled"] = True
    metrics["fitbit_token_file"] = str(config.fitbit.token_file)
    if not config.fitbit.token_file.exists():
        issues.append(
            QualityIssue(
                code="fitbit_token_missing",
                severity="error",
                message="Fitbit is enabled but the token file does not exist.",
                details={"path": str(config.fitbit.token_file)},
            )
        )

    present = str(row.get("wearable_present", "")).strip().lower()
    metrics["wearable_present"] = present
    if present in {"false", "0", "no"}:
        issues.append(
            QualityIssue(
                code="wearable_not_present",
                severity="error",
                message="Wearable is reported as missing or not worn.",
            )
        )

    available_features = [
        feature
        for feature in FITBIT_FEATURES
        if not _is_missing(row.get(feature))
    ]
    metrics["fitbit_available_feature_count"] = len(available_features)
    metrics["fitbit_available_features"] = available_features
    if not available_features:
        issues.append(
            QualityIssue(
                code="fitbit_no_biometrics",
                severity="error",
                message="Fitbit is enabled but no biometric features are available.",
            )
        )
    elif "heart_rate_mean" not in available_features:
        issues.append(
            QualityIssue(
                code="fitbit_missing_heart_rate",
                severity="warning",
                message="Fitbit data is present but heart_rate_mean is missing.",
            )
        )


def _check_shelly(
    config: EdgeIngestConfig,
    window_start: datetime,
    window_end: datetime,
    issues: list[QualityIssue],
    metrics: dict[str, Any],
) -> None:
    if not config.shelly.enabled:
        metrics["shelly_enabled"] = False
        return

    metrics["shelly_enabled"] = True
    raw_csv = config.shelly.raw_csv
    metrics["shelly_raw_csv"] = str(raw_csv)
    if not raw_csv.exists():
        issues.append(
            QualityIssue(
                code="shelly_raw_missing",
                severity="warning",
                message="Shelly/NILM is enabled but the raw CSV does not exist.",
                details={"path": str(raw_csv)},
            )
        )
        return

    try:
        frame = pd.read_csv(raw_csv)
    except Exception as exc:
        issues.append(
            QualityIssue(
                code="shelly_raw_unreadable",
                severity="warning",
                message="Shelly/NILM raw CSV cannot be read.",
                details={"path": str(raw_csv), "error": str(exc)},
            )
        )
        return

    if frame.empty or "timestamp" not in frame.columns:
        issues.append(
            QualityIssue(
                code="shelly_no_timestamped_samples",
                severity="warning",
                message="Shelly/NILM raw CSV has no timestamped samples.",
            )
        )
        return

    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    mask = (
        (timestamps >= pd.Timestamp(window_start))
        & (timestamps <= pd.Timestamp(window_end))
    )
    current_count = int(mask.sum())
    metrics["shelly_current_window_samples"] = current_count
    if current_count == 0:
        issues.append(
            QualityIssue(
                code="shelly_no_samples_in_window",
                severity="warning",
                message="Shelly/NILM is enabled but no samples were found in the current window.",
            )
        )


def _overall_status(issues: list[QualityIssue]) -> str:
    severities = {issue.severity for issue in issues}
    if "error" in severities:
        return "error"
    if "warning" in severities:
        return "warning"
    return "ok"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip().lower()
        return stripped in {"", "nan", "none", "null"}
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return isnan(numeric)


def report_from_latest_window(
    config: EdgeIngestConfig,
    latest_window_csv: str | Path,
) -> QualityReport:
    frame = pd.read_csv(latest_window_csv)
    if frame.empty:
        raise ValueError(f"Latest window CSV is empty: {latest_window_csv}")
    row = frame.sort_values("window_end").iloc[-1].to_dict()
    window_start = parse_timestamp(row["window_start"])
    window_end = parse_timestamp(row["window_end"])
    return evaluate_quality(config, row, window_start, window_end)
