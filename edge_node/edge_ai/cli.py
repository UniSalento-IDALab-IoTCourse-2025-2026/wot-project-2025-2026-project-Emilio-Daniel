from __future__ import annotations

import argparse
import json
import warnings
from importlib import import_module
from pathlib import Path
from typing import Any

from edge_ai.debounce import AlertDebouncer, decision_to_json
from edge_ai.features import latest_record, load_feature_frame
from edge_ai.model import EdgeAnomalyDetector
from edge_ai.wearable_quality import wearable_signal_summary

def _load_inconsistent_version_warning() -> type[Warning] | None:
    """Carica il warning di scikit-learn senza creare falsi errori nell'IDE."""
    try:
        exceptions_module = import_module("sklearn.exceptions")
    except Exception:  # pragma: no cover - sklearn might be unavailable before setup.
        return None

    warning_class = getattr(exceptions_module, "InconsistentVersionWarning", None)
    if isinstance(warning_class, type) and issubclass(warning_class, Warning):
        return warning_class
    return None


InconsistentVersionWarning = _load_inconsistent_version_warning()

if InconsistentVersionWarning is not None:
    warnings.filterwarnings("ignore", category=InconsistentVersionWarning)
warnings.filterwarnings(
    "ignore",
    message="Skipping features without any observed values:.*",
    category=UserWarning,
    module="sklearn\\.impute\\._base",
)


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
    train.add_argument(
        "--validation-ratio",
        type=float,
        default=0.0,
        help="Temporal holdout fraction (0.0-0.5). When > 0, the most recent "
        "windows are kept out of training and used to compute validation metrics.",
    )
    train.add_argument(
        "--metrics-output",
        default="",
        help="Metrics JSON output path (auto-derived from --output when "
        "--validation-ratio is set and this is omitted).",
    )

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
    train_generic.add_argument(
        "--include-features",
        default="",
        help="Optional comma-separated feature allowlist for training.",
    )
    train_generic.add_argument(
        "--exclude-features",
        default="",
        help="Optional comma-separated feature blocklist for training.",
    )

    infer = subparsers.add_parser("infer", help="Run inference on the latest real window")
    infer.add_argument("--model", required=True, help="Model artifact path")
    infer.add_argument("--input", required=True, help="CSV/JSON with one or more windows")
    infer.add_argument("--state", required=True, help="Debounce state JSON path")
    infer.add_argument("--output", required=True, help="Decision JSON output path")

    evaluate = subparsers.add_parser(
        "evaluate",
        help="Evaluate a trained model and save validation metrics",
    )
    evaluate.add_argument("--model", required=True, help="Trained model artifact path (.pkl)")
    evaluate.add_argument("--input", required=True, help="CSV/JSON dataset for evaluation")
    evaluate.add_argument("--output", required=True, help="Metrics JSON output path")
    evaluate.add_argument(
        "--ambiguous-margin",
        type=float,
        default=15.0,
        help="Margin around the yellow zone to exclude ambiguous records (default: 15)",
    )
    evaluate.add_argument(
        "--no-synthetic",
        action="store_true",
        help="Do not add synthetic anomalies to the test set",
    )
    evaluate.add_argument(
        "--synthetic-count",
        type=int,
        default=100,
        help="Number of synthetic anomalous records to add (default: 100)",
    )

    return parser


def train_model(args: argparse.Namespace) -> None:
    """Esegue il training del modello paziente-specifico a partire dalla baseline.

    La funzione legge il dataset di finestre reali, filtra il paziente indicato
    e salva su disco l'artefatto `.pkl`. Con `--validation-ratio` attivo usa un
    holdout temporale: le finestre piu' recenti restano fuori dal training e il
    report metriche viene salvato automaticamente (D21).
    """
    if args.validation_ratio > 0:
        from edge_ai.validation import train_with_validation

        metrics_output = args.metrics_output or str(
            Path(args.output).with_name(
                f"{Path(args.output).stem}_metrics.json"
            )
        )
        detector, metrics = train_with_validation(
            dataset_path=args.input,
            patient_id=args.patient_id,
            model_output=args.output,
            metrics_output=metrics_output,
            validation_ratio=args.validation_ratio,
            contamination=args.contamination,
            add_synthetic_anomalies=True,
        )
        print(
            json.dumps(
                {
                    "status": "trained_with_validation",
                    "patient_id": detector.metadata.patient_id,
                    "training_rows": detector.metadata.training_rows,
                    "validation_rows": metrics.validation_rows,
                    "model": args.output,
                    "metrics": metrics_output,
                    "f1": metrics.f1,
                    "precision": metrics.precision,
                    "recall": metrics.recall,
                    "roc_auc": metrics.roc_auc,
                    "validation_ratio": args.validation_ratio,
                },
                indent=2,
            )
        )
        return

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
    exclude_features = _parse_feature_list(args.exclude_features)

    detector = EdgeAnomalyDetector.train_generic(
        frame=frame,
        model_id=args.model_id,
        model_scope=args.model_kind,
        training_source=f"{args.model_kind}_dataset",
        contamination=args.contamination,
        include_features=_parse_feature_list(args.include_features),
        exclude_features=exclude_features,
    )
    detector.save(args.output)
    print(
        json.dumps(
            {
                "status": "generic_trained",
                "model_id": detector.metadata.patient_id,
                "training_rows": detector.metadata.training_rows,
                "feature_columns": detector.metadata.feature_columns,
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
    record = latest_record(frame)
    wearable_summary = wearable_signal_summary(record)
    if (
        detector.metadata.model_scope == "generic_wearable"
        and not wearable_summary["has_core_signal"]
    ):
        payload = _technical_wearable_skip_payload(record, wearable_summary)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        print(json.dumps(payload, indent=2))
        return

    result = detector.predict_record(record)

    debouncer = AlertDebouncer.load(args.state)
    decision = debouncer.update(result)
    debouncer.save(args.state)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(decision_to_json(decision), handle, indent=2)

    print(json.dumps(decision_to_json(decision), indent=2))


def _technical_wearable_skip_payload(
    record: Any,
    wearable_summary: dict[str, object],
) -> dict[str, object]:
    """Crea un output tecnico quando il wearable generico non ha input minimi."""
    start = record["window_start"]
    end = record["window_end"]
    return {
        "patient_id": str(record.get("patient_id", "patient-001")),
        "window_start": start.isoformat() if hasattr(start, "isoformat") else str(start),
        "window_end": end.isoformat() if hasattr(end, "isoformat") else str(end),
        "level": "technical",
        "should_publish": True,
        "anomaly_score": 0.0,
        "reasons": [
            "Generic wearable model skipped because the window has no core wearable signal"
        ],
        "model_label": "skipped_insufficient_wearable_data",
        "evidence": {
            "wearable_signal": wearable_summary,
        },
    }


def run_evaluate(args: argparse.Namespace) -> None:
    """Esegue la validazione di un modello addestrato su un dataset di test.

    Calcola precision, recall, F1, ROC-AUC e altre metriche. Salva le metriche
    in un file JSON leggibile dalla dashboard e dal backend.
    """
    from edge_ai.validation import evaluate_and_save

    metrics = evaluate_and_save(
        model_path=args.model,
        dataset_path=args.input,
        output_path=args.output,
        ambiguous_margin=args.ambiguous_margin,
        add_synthetic_anomalies=not args.no_synthetic,
        synthetic_count=args.synthetic_count,
    )
    print(json.dumps(metrics.to_dict(), indent=2, ensure_ascii=False))


def _parse_feature_list(value: str) -> list[str] | None:
    """Converte una lista CLI separata da virgole in feature columns."""
    items = [item.strip() for item in str(value or "").split(",") if item.strip()]
    return items or None


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
    elif args.command == "evaluate":
        run_evaluate(args)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
