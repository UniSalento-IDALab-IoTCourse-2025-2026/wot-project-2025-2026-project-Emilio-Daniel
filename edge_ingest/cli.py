from __future__ import annotations

import argparse
import json

from edge_ingest.aggregator import (
    append_baseline_row,
    build_feature_window,
    write_latest_window,
)
from edge_ingest.config import load_config
from edge_ingest.time_windows import parse_datetime, window_from_end


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-ingest",
        description="Collect real edge data and aggregate it into AI feature windows.",
    )
    parser.add_argument("--config", default="config/edge.example.yml")
    parser.add_argument(
        "--window-end",
        default="now",
        help="Window end datetime, or 'now'. Naive values use config timezone.",
    )
    parser.add_argument(
        "--append-baseline",
        action="store_true",
        help="Also append the generated window to the baseline CSV.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    requested_end = parse_datetime(args.window_end, config.window.timezone)
    window_start, window_end = window_from_end(requested_end, config.window.minutes)

    row = build_feature_window(config, window_start, window_end)
    write_latest_window(config.paths.latest_window_csv, row)
    if args.append_baseline:
        append_baseline_row(config.paths.baseline_csv, row)

    print(
        json.dumps(
            {
                "status": "collected",
                "patient_id": row["patient_id"],
                "window_start": row["window_start"],
                "window_end": row["window_end"],
                "latest_window_csv": str(config.paths.latest_window_csv),
                "baseline_appended": bool(args.append_baseline),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
