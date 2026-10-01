from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edge_ai.model import EdgeAnomalyDetector
from edge_baseline.session import (
    DEFAULT_BASELINE_STATE,
    count_baseline_rows,
    session_status_payload,
    start_session,
)
from edge_ingest.config import load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain patient Edge runtime data safely.")
    parser.add_argument("--config", default="config/edge.rpi.yml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show baseline and personal-model status")

    reset = subparsers.add_parser(
        "reset",
        help="Archive generated data and start a fresh baseline",
    )
    reset.add_argument("--confirm", required=True)
    reset.add_argument("--days", type=int, default=7)
    reset.add_argument("--archive-root", default="data/archive")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    patient_id = config.patient.patient_id

    if args.command == "status":
        print(json.dumps(_status(config), indent=2, default=str))
        return

    if args.confirm != patient_id:
        raise SystemExit("Reset refused: --confirm must match the configured patient_id.")
    payload = archive_and_reset(
        config,
        archive_root=Path(args.archive_root),
        days=max(1, int(args.days)),
    )
    print(json.dumps(payload, indent=2, default=str))


def archive_and_reset(config: Any, *, archive_root: Path, days: int) -> dict[str, Any]:
    """Move generated patient data to an archive and initialize a clean baseline."""
    edge_root = Path.cwd().resolve()
    archive_root_abs = _inside_edge_root(archive_root, edge_root)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive_dir = archive_root_abs / config.patient.patient_id / stamp
    archive_dir.mkdir(parents=True, exist_ok=False)

    personal_model = config.ai.personal_model or Path("models") / f"{config.patient.patient_id}.pkl"
    candidates = {
        Path(config.paths.baseline_csv),
        Path(config.paths.latest_window_csv),
        Path(config.ble.raw_csv),
        Path(config.google_health.raw_csv),
        Path(config.shelly.raw_csv),
        Path(personal_model),
    }
    candidates.update(_generated_children(Path("data/state")))
    candidates.update(_generated_children(Path("outputs")))

    archived: list[str] = []
    for candidate in sorted(candidates, key=lambda value: str(value)):
        source = _inside_edge_root(candidate, edge_root)
        if not source.exists() or source.name == ".gitkeep":
            continue
        try:
            relative = source.relative_to(edge_root)
        except ValueError as exc:  # pragma: no cover - guarded by _inside_edge_root.
            raise ValueError(f"Refusing to archive path outside Edge root: {source}") from exc
        target = archive_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        archived.append(str(relative))

    session = start_session(
        config=config,
        state_path=DEFAULT_BASELINE_STATE,
        days=days,
        model_output=personal_model,
        reset=True,
    )
    payload = {
        "status": "reset_completed",
        "patient_id": config.patient.patient_id,
        "archive": str(archive_dir.relative_to(edge_root)),
        "archived": archived,
        "baseline_status": session.status,
        "baseline_days": session.planned_days,
        "minimum_provisional_windows": 50,
        "minimum_final_windows": 1000,
    }
    (archive_dir / "reset-manifest.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    return payload


def _status(config: Any) -> dict[str, Any]:
    personal_model = config.ai.personal_model or Path("models") / f"{config.patient.patient_id}.pkl"
    baseline = session_status_payload(config, DEFAULT_BASELINE_STATE)
    model_payload: dict[str, Any] = {
        "path": str(personal_model),
        "exists": Path(personal_model).exists(),
    }
    if Path(personal_model).exists():
        detector = EdgeAnomalyDetector.load(personal_model)
        model_payload.update(
            {
                "training_rows": detector.metadata.training_rows,
                "training_source": detector.metadata.training_source,
                "provisional": detector.metadata.training_source.endswith("_provisional"),
            }
        )
    return {
        "patient_id": config.patient.patient_id,
        "baseline_rows": count_baseline_rows(config.paths.baseline_csv),
        "baseline": baseline,
        "personal_model": model_payload,
    }


def _generated_children(directory: Path) -> set[Path]:
    if not directory.exists():
        return set()
    return {item for item in directory.iterdir() if item.name != ".gitkeep"}


def _inside_edge_root(path: Path, edge_root: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (edge_root / path).resolve()
    try:
        resolved.relative_to(edge_root)
    except ValueError as exc:
        raise ValueError(f"Refusing path outside Edge root: {resolved}") from exc
    return resolved
