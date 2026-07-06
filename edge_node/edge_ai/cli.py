from __future__ import annotations

import argparse
import json
from pathlib import Path

from edge_ai.debounce import AlertDebouncer, decision_to_json
from edge_ai.features import latest_record, load_feature_frame
from edge_ai.model import EdgeAnomalyDetector


def build_parser() -> argparse.ArgumentParser:
    """Costruisce il parser CLI per addestrare il modello o lanciare inferenza.

    Questa funzione concentra in un solo punto tutti gli argomenti disponibili
    da terminale. In questo modo l'uso manuale e l'eventuale automazione su
    Raspberry Pi rimangono coerenti e facilmente documentabili.
    """
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

    train_generic = subparsers.add_parser(
        "train-generic",
        help="Train a generic model from an external or multi-patient dataset",
    )
    train_generic.add_argument("--input", required=True, help="CSV/JSON with generic ADL windows")
    train_generic.add_argument("--output", required=True, help="Generic model artifact path")
    train_generic.add_argument("--model-id", default="generic")
    train_generic.add_argument(
        "--model-kind",
        choices=["generic", "generic_spatial", "generic_wearable"],
        default="generic",
        help="Semantic role of the generic model artifact.",
    )
    train_generic.add_argument("--contamination", type=float, default=0.05)

    infer = subparsers.add_parser("infer", help="Run inference on the latest real window")
    infer.add_argument("--model", required=True, help="Model artifact path")
    infer.add_argument("--input", required=True, help="CSV/JSON with one or more windows")
    infer.add_argument("--state", required=True, help="Debounce state JSON path")
    infer.add_argument("--output", required=True, help="Decision JSON output path")

    return parser


def train_model(args: argparse.Namespace) -> None:
    """Esegue il training del modello paziente-specifico a partire dalla baseline.

    La funzione legge il dataset di finestre reali, filtra il paziente indicato
    e salva su disco l'artefatto `.pkl`. Nel progetto questo comando viene usato
    dopo la fase di baseline, quindi non deve essere alimentato con dati casuali
    o simulati se si vuole ottenere un modello realistico.
    """
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


def train_generic_model(args: argparse.Namespace) -> None:
    """Addestra il modello generico da un dataset esterno o multi-paziente.

    Questo comando serve a creare l'artefatto installabile sul Raspberry prima
    della baseline personale. Il dataset deve gia' essere convertito nello
    stesso schema feature del progetto, per evitare mismatch tra training e
    inferenza reale.
    """
    frame = load_feature_frame(args.input)
    detector = EdgeAnomalyDetector.train_generic(
        frame=frame,
        model_id=args.model_id,
        model_scope=args.model_kind,
        training_source=f"{args.model_kind}_dataset",
        contamination=args.contamination,
    )
    detector.save(args.output)
    print(
        json.dumps(
            {
                "status": "generic_trained",
                "model_id": detector.metadata.patient_id,
                "training_rows": detector.metadata.training_rows,
                "model_scope": detector.metadata.model_scope,
                "training_source": detector.metadata.training_source,
                "model": args.output,
            },
            indent=2,
        )
    )


def run_inference(args: argparse.Namespace) -> None:
    """Esegue una predizione sull'ultima finestra e applica il debounce clinico.

    L'inferenza grezza del modello viene trasformata in una decisione operativa
    tramite `AlertDebouncer`, cosi' una singola finestra sospetta non genera
    necessariamente un allarme. L'output finale e' un JSON pensato per il futuro
    backend o per la dashboard clinica.
    """
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
    """Punto di ingresso della CLI `edge_ai`.

    Interpreta il comando richiesto dall'utente (`train` oppure `infer`) e
    delega alla funzione specifica. Questa separazione rende il codice piu'
    leggibile e permette di testare training e inferenza separatamente.
    """
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "train":
        train_model(args)
    elif args.command == "train-generic":
        train_generic_model(args)
    elif args.command == "infer":
        run_inference(args)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
