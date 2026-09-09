from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from edge_runtime.cli import _run_absence_check

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def _cool_config(tmp_path):
    now = datetime.now(timezone.utc)
    latest = tmp_path / "latest_window.csv"
    latest.write_text(
        "patient_id,window_start,window_end\npatient-001,2026-09-08T11:00:00Z,2026-09-08T11:04:00Z\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.csv"
    baseline.write_text(
        "patient_id,window_start,window_end,longest_single_room_minutes\n"
        "patient-001,2026-09-08T09:00:00Z,2026-09-08T09:04:00Z,30.0\n",
        encoding="utf-8",
    )
    ble = tmp_path / "ble_samples.csv"
    start = now - timedelta(hours=5)
    rows = "\n".join(
        f"{(start + timedelta(minutes=m)).isoformat()},living_room" for m in range(0, 300, 30)
    )
    rows += f"\n{(now - timedelta(minutes=2)).isoformat()},living_room"
    ble.write_text(f"timestamp,room\n{rows}\n", encoding="utf-8")

    absence = SimpleNamespace(
        enabled=True,
        no_movement_hours=4.0,
        no_amenity_hours=12.0,
        room_stay_multiplier=2.5,
        room_stay_min_minutes=120.0,
        ble_stale_minutes=30.0,
    )
    return SimpleNamespace(
        paths=SimpleNamespace(latest_window_csv=latest, baseline_csv=baseline),
        ble=SimpleNamespace(raw_csv=ble),
        absence=absence,
    )


def test_run_absence_check_writes_signal_and_state(tmp_path):
    config = _cool_config(tmp_path)
    args = argparse.Namespace(
        absence_output=str(tmp_path / "absence.json"),
        absence_state=str(tmp_path / "state.json"),
    )
    result = _run_absence_check(config, "patient-001", args)

    assert result["checked"] is True
    signal = result["signal"]
    assert signal is not None
    assert signal["kind"] == "no_movement"
    assert signal["patient_id"] == "patient-001"
    assert signal["message_id"].startswith("absence-")
    assert (tmp_path / "absence.json").exists()

    with (tmp_path / "absence.json").open("r", encoding="utf-8") as handle:
        written = json.load(handle)
    assert written["kind"] == "no_movement"
    assert written["duration_minutes"] >= 4 * 60

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["episode"] == 1
    assert state["last_signature"] == "no_movement:living_room"


def test_run_absence_check_second_cycle_deduped(tmp_path):
    config = _cool_config(tmp_path)
    args = argparse.Namespace(
        absence_output=str(tmp_path / "absence.json"),
        absence_state=str(tmp_path / "state.json"),
    )
    first = _run_absence_check(config, "patient-001", args)
    second = _run_absence_check(config, "patient-001", args)
    assert second["signal"] is not None
    assert (tmp_path / "absence.json").exists()
    assert first["signal"]["message_id"] == second["signal"]["message_id"]


def test_run_absence_check_cleanup_when_active(tmp_path):
    config = _cool_config(tmp_path)
    args = argparse.Namespace(
        absence_output=str(tmp_path / "absence.json"),
        absence_state=str(tmp_path / "state.json"),
    )
    _run_absence_check(config, "patient-001", args)
    assert (tmp_path / "absence.json").exists()


def test_run_absence_check_disabled(tmp_path):
    config = _cool_config(tmp_path)
    config.absence.enabled = False
    args = argparse.Namespace(
        absence_output=str(tmp_path / "absence.json"),
        absence_state=str(tmp_path / "state.json"),
    )
    result = _run_absence_check(config, "patient-001", args)
    assert result["checked"] is False
    assert result["signal"] is None


def test_run_absence_check_ble_missing_technical(tmp_path):
    config = _cool_config(tmp_path)
    missing = tmp_path / "missing-ble.csv"
    config.ble = SimpleNamespace(raw_csv=missing)
    args = argparse.Namespace(
        absence_output=str(tmp_path / "absence.json"),
        absence_state=str(tmp_path / "state.json"),
    )
    result = _run_absence_check(config, "patient-001", args)
    signal = result["signal"]
    assert signal is not None
    assert signal["kind"] == "ble_unreliable"
    assert signal["category"] == "technical"