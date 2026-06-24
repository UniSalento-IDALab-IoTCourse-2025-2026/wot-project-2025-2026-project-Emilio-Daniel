from __future__ import annotations

import csv
from datetime import datetime
from math import nan
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from edge_ai.schema import DATASET_COLUMNS, FEATURE_COLUMNS
from edge_ingest.ble_adapter import BleCsvAdapter
from edge_ingest.config import EdgeIngestConfig
from edge_ingest.fitbit_adapter import FitbitAdapter
from edge_ingest.shelly_adapter import ShellyCsvAdapter


def build_feature_window(
    config: EdgeIngestConfig,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "patient_id": config.patient.patient_id,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "wearable_present": "",
        "wearable_battery_pct": "",
    }
    row.update({column: nan for column in FEATURE_COLUMNS})

    if config.fitbit.enabled:
        local_zone = ZoneInfo(config.window.timezone)
        row.update(
            FitbitAdapter(config.fitbit).collect_window(
                window_start.astimezone(local_zone),
                window_end.astimezone(local_zone),
            )
        )
    if config.ble.enabled:
        row.update(
            BleCsvAdapter(config.ble, config.window.timezone).collect_window(
                window_start,
                window_end,
            )
        )
    if config.shelly.enabled:
        row.update(ShellyCsvAdapter(config.shelly).collect_window(window_start, window_end))

    return row


def write_latest_window(path: str | Path, row: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
        writer.writeheader()
        writer.writerow(_ordered_row(row))


def append_baseline_row(path: str | Path, row: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    file_exists = target.exists() and target.stat().st_size > 0
    with target.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(_ordered_row(row))


def _ordered_row(row: dict[str, Any]) -> dict[str, Any]:
    return {column: row.get(column, "") for column in DATASET_COLUMNS}
