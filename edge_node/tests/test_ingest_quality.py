from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite, isnan
from pathlib import Path

from edge_ai.schema import FEATURE_COLUMNS
from edge_ingest.aggregator import (
    append_baseline_row,
    build_feature_window,
    write_latest_window,
)
from edge_ingest.config import (
    AIConfig,
    AbsenceConfig,
    BleConfig,
    EdgeIngestConfig,
    FitbitConfig,
    GoogleHealthConfig,
    MqttConfig,
    PathsConfig,
    PatientConfig,
    ShellyConfig,
    WindowConfig,
)

BS = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)
BE = BS + timedelta(minutes=4)


def make_config(ble_enabled: bool = False) -> EdgeIngestConfig:
    return EdgeIngestConfig(
        patient=PatientConfig(patient_id="patient-001"),
        window=WindowConfig(),
        paths=PathsConfig(latest_window_csv=Path("data/latest_window.csv"), baseline_csv=Path("data/baseline.csv")),
        ai=AIConfig(
            generic_model=Path("models/generic.pkl"),
            generic_spatial_model=Path("models/generic_spatial.pkl"),
            generic_wearable_model=Path("models/generic_wearable.pkl"),
        ),
        fitbit=FitbitConfig(),
        google_health=GoogleHealthConfig(),
        ble=BleConfig(enabled=ble_enabled),
        shelly=ShellyConfig(),
        mqtt=MqttConfig(),
        absence=AbsenceConfig(),
    )


def test_build_feature_window_initializes_schema() -> None:
    row = build_feature_window(make_config(), BS, BE)
    assert row["patient_id"] == "patient-001"
    assert row["window_start"] == BS.isoformat()
    assert row["window_end"] == BE.isoformat()
    assert row["wearable_present"] == ""
    for column in FEATURE_COLUMNS:
        assert column in row
        assert isnan(row[column])


def test_write_latest_window_persists_row(tmp_path) -> None:
    path = tmp_path / "latest_window.csv"
    row = build_feature_window(make_config(), BS, BE)
    write_latest_window(path, row)
    content = path.read_text(encoding="utf-8")
    assert "patient_id" in content
    assert "heart_rate_mean" in content
    assert "patient-001" in content


def test_append_baseline_row_accretes_rows(tmp_path) -> None:
    path = tmp_path / "baseline.csv"
    for index in range(3):
        row = build_feature_window(make_config(), BS + timedelta(minutes=4 * index), BE + timedelta(minutes=4 * index))
        append_baseline_row(path, row)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4  # header + 3 rows


def test_quality_accepts_valid_window() -> None:
    from edge_quality.checks import evaluate_quality

    row = build_feature_window(make_config(), BS, BE)
    report = evaluate_quality(make_config(), row, BS, BE, now=BE + timedelta(minutes=10))
    assert report.status == "ok"
    assert report.usable_for_training is True


def test_quality_rejects_future_window() -> None:
    from edge_quality.checks import evaluate_quality

    row = build_feature_window(make_config(), BS, BE)
    report = evaluate_quality(make_config(), row, BS, BE, now=BS - timedelta(hours=1))
    assert report.status == "error"
    assert report.usable_for_training is False
    codes = [issue.code for issue in report.issues]
    assert "window_in_future" in codes


def test_quality_rejects_invalid_window_bounds() -> None:
    from edge_quality.checks import evaluate_quality

    row = build_feature_window(make_config(), BS, BS)
    report = evaluate_quality(make_config(), row, BS, BS, now=BE + timedelta(hours=1))
    assert report.status == "error"
    codes = [issue.code for issue in report.issues]
    assert "invalid_window_bounds" in codes


def test_quality_notes_wearable_absent() -> None:
    from edge_quality.checks import evaluate_quality

    row = build_feature_window(make_config(), BS, BE)
    now = BE + timedelta(minutes=10)
    report = evaluate_quality(make_config(), row, BS, BE, now=now)
    assert report.metrics["fitbit_enabled"] is False
    assert report.metrics["google_health_enabled"] is False
    assert report.status == "ok"


def test_quality_report_survives_nan_features() -> None:
    from edge_quality.checks import evaluate_quality

    row = build_feature_window(make_config(), BS, BE)
    report = evaluate_quality(make_config(), row, BS, BE, now=BE + timedelta(minutes=10))
    payload = report.to_dict()
    assert payload["status"] == "ok"
    assert isinstance(payload["issues"], list)