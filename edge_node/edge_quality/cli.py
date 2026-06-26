from __future__ import annotations

import argparse
import json
from pathlib import Path

from edge_ingest.config import load_config
from edge_quality.checks import report_from_latest_window


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-quality",
        description="Check if the latest edge data window is usable for baseline/training.",
    )
    parser.add_argument("--config", default="config/edge.example.yml")
    parser.add_argument(
        "--input",
        default=None,
        help="Latest window CSV. Defaults to paths.latest_window_csv from config.",
    )
    parser.add_argument(
        "--output",
        default="outputs/last-quality-report.json",
        help="Quality report JSON path.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    latest_window_csv = Path(args.input) if args.input else config.paths.latest_window_csv
    report = report_from_latest_window(config, latest_window_csv)
    payload = report.to_dict()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

