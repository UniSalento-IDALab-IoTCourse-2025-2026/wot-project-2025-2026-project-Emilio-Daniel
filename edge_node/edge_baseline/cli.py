from __future__ import annotations

import argparse
import json
from pathlib import Path

from edge_ai.features import load_feature_frame
from edge_ai.model import EdgeAnomalyDetector
from edge_baseline.session import (
    DEFAULT_BASELINE_STATE,
    DEFAULT_DAYS,
    finalize_session,
    save_session,
    session_status_payload,
    start_session,
)
from edge_ingest.config import load_config


def build_parser() -> argparse.ArgumentParser:
    """Definisce i comandi disponibili per gestire la baseline reale.

    La CLI espone le quattro fasi operative principali: avvio, controllo stato,
    finalizzazione e training. Questa struttura rispecchia il workflow che
    useremo sul Raspberry quando i sensori reali saranno disponibili.
    """
    parser = argparse.ArgumentParser(
        prog="edge-baseline",
        description="Manage the real-data baseline collection workflow.",
    )
    parser.add_argument("--config", default="config/edge.example.yml")
    parser.add_argument("--state", default=str(DEFAULT_BASELINE_STATE))

    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Start a baseline collection session")
    start.add_argument("--days", type=int, default=DEFAULT_DAYS)
    start.add_argument("--model-output", default=None)
    start.add_argument("--reset", action="store_true")

    subparsers.add_parser("status", help="Show baseline collection status")

    finalize = subparsers.add_parser("finalize", help="Mark baseline as ready for training")
    finalize.add_argument("--allow-early", action="store_true")

    train = subparsers.add_parser("train", help="Train the patient model from baseline CSV")
    train.add_argument("--allow-early", action="store_true")
    train.add_argument(
        "--provisional",
        action="store_true",
        help=(
            "Mark an early model as provisional. Requires --allow-early and "
            "still requires at least 50 real patient windows."
        ),
    )
    train.add_argument("--contamination", type=float, default=0.05)

    return parser


def main() -> None:
    """Punto di ingresso della CLI `edge_baseline`.

    La funzione carica la configurazione dell'edge node, interpreta il comando
    richiesto e produce un JSON leggibile. Il JSON e' utile sia per debug umano
    sia per eventuali script di automazione.
    """
    args = build_parser().parse_args()
    config = load_config(args.config)
    state_path = Path(args.state)

    if args.command == "start":
        session = start_session(
            config=config,
            state_path=state_path,
            days=args.days,
            model_output=args.model_output,
            reset=args.reset,
        )
        print(json.dumps(session.to_dict(), indent=2))
        return

    if args.command == "status":
        print(json.dumps(session_status_payload(config, state_path), indent=2))
        return

    if args.command == "finalize":
        session = finalize_session(config, state_path, allow_early=args.allow_early)
        print(json.dumps(session.to_dict(), indent=2))
        return

    if args.command == "train":
        if args.provisional and not args.allow_early:
            raise ValueError("--provisional requires --allow-early")
        session = finalize_session(config, state_path, allow_early=args.allow_early)
        frame = load_feature_frame(session.baseline_csv)
        detector = EdgeAnomalyDetector.train(
            frame=frame,
            patient_id=session.patient_id,
            contamination=args.contamination,
            training_source=(
                "patient_baseline_provisional"
                if args.provisional
                else "patient_baseline"
            ),
        )
        detector.save(session.model_output)
        session.status = "trained"
        session.notes.append(
            f"Manual {'provisional ' if args.provisional else ''}model trained "
            f"with {detector.metadata.training_rows} windows."
        )
        save_session(session, state_path)
        payload = session.to_dict()
        payload.update(
            {
                "status": "trained",
                "training_rows": detector.metadata.training_rows,
                "model": session.model_output,
                "provisional": bool(args.provisional),
                "training_source": detector.metadata.training_source,
            }
        )
        print(json.dumps(payload, indent=2))
        return

    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
