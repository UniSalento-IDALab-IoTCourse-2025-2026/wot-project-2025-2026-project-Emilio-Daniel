from __future__ import annotations

import argparse
import json
from pathlib import Path

from edge_ai.debounce import AlertDebouncer, decision_to_json
from edge_ai.features import latest_record, load_feature_frame
from edge_ai.model import EdgeAnomalyDetector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-ai",
        description="Train and run ADL anomaly detection on the edge node.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    train = subparsers.add_parser("train", help="Train a patient-specific baseline model")
    train.add_argument("--input", required=True, help="CSV/JSON with real baseline windows")
    train.add_argument("--patient-id", required=True, help="Patient identifier in the dataset")
    train.add_argument("--output", required=True, help="Model artifact path")
    train.add_argument("--contamination", type=float, default=0.05)

    infer = subparsers.add_parser("infer", help="Run inference on the latest real window")
    infer.add_argument("--model", required=True, help="Model artifact path")
    infer.add_argument("--input", required=True, help="CSV/JSON with one or more windows")
    infer.add_argument("--state", required=True, help="Debounce state JSON path")
    infer.add_argument("--output", required=True, help="Decision JSON output path")

    return parser


def train_model(args: argparse.Namespace) -> None:
    frame = load_feature_frame(args.input)
    detector = EdgeAnomalyDetector.train(
        frame=frame,
        patient_id=args.patient_id,
        contamination=args.contamination,
    )
    detector.save(args.output)
    print(
        json.dumps(
            {
                "status": "trained",
                "patient_id": detector.metadata.patient_id,
                "training_rows": detector.metadata.training_rows,
                "model": args.output,
            },
            indent=2,
        )
    )


def run_inference(args: argparse.Namespace) -> None:
    detector = EdgeAnomalyDetector.load(args.model)
    frame = load_feature_frame(args.input)
    result = detector.predict_record(latest_record(frame))

    debouncer = AlertDebouncer.load(args.state)
    decision = debouncer.update(result)
    debouncer.save(args.state)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(decision_to_json(decision), handle, indent=2)

    print(json.dumps(decision_to_json(decision), indent=2))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "train":
        train_model(args)
    elif args.command == "infer":
        run_inference(args)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
