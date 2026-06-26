from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from edge_ai.debounce import AlertDebouncer, decision_to_json
from edge_baseline.session import DEFAULT_BASELINE_STATE, update_session_from_cycle
from edge_ingest.aggregator import (
    append_baseline_row,
    build_feature_window,
    write_latest_window,
)
from edge_ingest.ble_collector import collect_ble_samples
from edge_ingest.config import load_config
from edge_ingest.time_windows import parse_datetime, window_from_end
from edge_quality.checks import evaluate_quality


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-cycle",
        description=(
            "Run one Raspberry Pi edge cycle: aggregate received data, "
            "optionally update baseline, and run inference when a model exists."
        ),
    )
    parser.add_argument("--config", default="config/edge.example.yml")
    parser.add_argument(
        "--window-end",
        default="now",
        help="Window end datetime, or 'now'. Naive values use config timezone.",
    )
    parser.add_argument(
        "--collect-ble",
        action="store_true",
        help="Run the optional Raspberry BLE scanner before aggregation.",
    )
    parser.add_argument(
        "--append-baseline",
        action="store_true",
        help="Append the generated window to the baseline CSV.",
    )
    parser.add_argument(
        "--force-baseline-append",
        action="store_true",
        help="Append baseline rows even when quality checks report errors.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model path. Defaults to models/<patient_id>.pkl.",
    )
    parser.add_argument(
        "--state",
        default=None,
        help="Debounce state path. Defaults to data/state/<patient_id>-debounce.json.",
    )
    parser.add_argument(
        "--decision-output",
        default=None,
        help="Decision JSON path. Defaults to outputs/<patient_id>-decision.json.",
    )
    parser.add_argument(
        "--status-output",
        default="outputs/last-cycle.json",
        help="Runtime status JSON path. Use an empty value to disable.",
    )
    parser.add_argument(
        "--quality-output",
        default="outputs/last-quality-report.json",
        help="Data quality report JSON path. Use an empty value to disable.",
    )
    parser.add_argument(
        "--baseline-state",
        default=str(DEFAULT_BASELINE_STATE),
        help="Baseline session state JSON path.",
    )
    parser.add_argument(
        "--require-model",
        action="store_true",
        help="Fail the cycle if the model file does not exist.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    status = run_cycle(args)
    print(json.dumps(status, indent=2))


def run_cycle(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    patient_id = config.patient.patient_id

    ble_samples = []
    if args.collect_ble:
        ble_samples = collect_ble_samples(config.ble)

    requested_end = parse_datetime(args.window_end, config.window.timezone)
    window_start, window_end = window_from_end(requested_end, config.window.minutes)

    row = build_feature_window(config, window_start, window_end)
    write_latest_window(config.paths.latest_window_csv, row)

    quality_report = evaluate_quality(config, row, window_start, window_end)
    quality_payload = quality_report.to_dict()
    if args.quality_output:
        _write_json(Path(args.quality_output), quality_payload)

    baseline_appended = False
    baseline_skipped_reason = None
    if args.append_baseline and quality_report.usable_for_training:
        append_baseline_row(config.paths.baseline_csv, row)
        baseline_appended = True
    elif args.append_baseline and args.force_baseline_append:
        append_baseline_row(config.paths.baseline_csv, row)
        baseline_appended = True
        baseline_skipped_reason = "forced_despite_quality_errors"
    elif args.append_baseline:
        baseline_skipped_reason = "quality_error"

    model_path = Path(args.model) if args.model else Path("models") / f"{patient_id}.pkl"
    state_path = (
        Path(args.state)
        if args.state
        else Path("data") / "state" / f"{patient_id}-debounce.json"
    )
    decision_output = (
        Path(args.decision_output)
        if args.decision_output
        else Path("outputs") / f"{patient_id}-decision.json"
    )

    inference_status = "skipped_model_missing"
    decision_payload: dict[str, Any] | None = None
    if model_path.exists():
        decision_payload = _run_inference(
            model_path=model_path,
            latest_window_csv=config.paths.latest_window_csv,
            state_path=state_path,
            decision_output=decision_output,
        )
        inference_status = "completed"
    elif args.require_model:
        raise FileNotFoundError(f"Model not found: {model_path}")

    status: dict[str, Any] = {
        "status": "cycle_completed",
        "patient_id": patient_id,
        "config": str(args.config),
        "window_start": row["window_start"],
        "window_end": row["window_end"],
        "latest_window_csv": str(config.paths.latest_window_csv),
        "baseline_appended": baseline_appended,
        "baseline_csv": str(config.paths.baseline_csv) if baseline_appended else None,
        "baseline_skipped_reason": baseline_skipped_reason,
        "ble_samples_collected": len(ble_samples),
        "received_ble_csv": str(config.ble.raw_csv),
        "quality_status": quality_report.status,
        "quality_usable_for_training": quality_report.usable_for_training,
        "quality_issue_count": len(quality_report.issues),
        "quality_error_count": _count_quality_issues(quality_payload, "error"),
        "quality_warning_count": _count_quality_issues(quality_payload, "warning"),
        "quality_info_count": _count_quality_issues(quality_payload, "info"),
        "quality_report": str(args.quality_output) if args.quality_output else None,
        "model": str(model_path),
        "inference": inference_status,
        "decision_output": str(decision_output) if decision_payload else None,
        "decision_level": decision_payload.get("level") if decision_payload else None,
        "should_publish": decision_payload.get("should_publish") if decision_payload else None,
    }

    baseline_session = update_session_from_cycle(
        config=config,
        cycle_status=status,
        quality_report=quality_payload,
        state_path=args.baseline_state,
    )
    if baseline_session is not None:
        status["baseline_session_status"] = baseline_session.status
        status["baseline_session_accepted_windows"] = baseline_session.accepted_windows
        status["baseline_session_rejected_windows"] = baseline_session.rejected_windows
        status["baseline_session_state"] = str(args.baseline_state)

    if args.status_output:
        _write_json(Path(args.status_output), status)
    return status


def _run_inference(
    model_path: Path,
    latest_window_csv: Path,
    state_path: Path,
    decision_output: Path,
) -> dict[str, Any]:
    from edge_ai.features import latest_record, load_feature_frame
    from edge_ai.model import EdgeAnomalyDetector

    detector = EdgeAnomalyDetector.load(model_path)
    frame = load_feature_frame(latest_window_csv)
    result = detector.predict_record(latest_record(frame))

    debouncer = AlertDebouncer.load(state_path)
    decision = debouncer.update(result)
    debouncer.save(state_path)

    payload = decision_to_json(decision)
    _write_json(decision_output, payload)
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _count_quality_issues(payload: dict[str, Any], severity: str) -> int:
    return sum(
        1
        for issue in payload.get("issues", [])
        if issue.get("severity") == severity
    )


if __name__ == "__main__":
    main()
