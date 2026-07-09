from __future__ import annotations

import argparse
import json
import os
import time
import warnings
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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

def _load_inconsistent_version_warning() -> type[Warning] | None:
    """Carica il warning di scikit-learn senza dipendere da import statici."""
    try:
        exceptions_module = import_module("sklearn.exceptions")
    except Exception:  # pragma: no cover - sklearn might be unavailable before setup.
        return None

    warning_class = getattr(exceptions_module, "InconsistentVersionWarning", None)
    if isinstance(warning_class, type) and issubclass(warning_class, Warning):
        return warning_class
    return None


InconsistentVersionWarning = _load_inconsistent_version_warning()

# I modelli generici sono artefatti pickle e possono essere stati creati con una
# versione diversa di scikit-learn. Durante i test locali il ciclo e' comunque
# utilizzabile, quindi filtriamo questi warning per lasciare leggibile il JSON.
if InconsistentVersionWarning is not None:
    warnings.filterwarnings("ignore", category=InconsistentVersionWarning)
warnings.filterwarnings(
    "ignore",
    message="Skipping features without any observed values:.*",
    category=UserWarning,
    module="sklearn\\.impute\\._base",
)


def build_parser() -> argparse.ArgumentParser:
    """Definisce la CLI del ciclo edge unico.

    Questo comando riunisce aggregazione, controllo qualita, baseline e
    inferenza. L'obiettivo e' avere un solo punto da schedulare sul Raspberry
    ogni 4 minuti tramite cron o systemd timer.
    """
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
        help=(
            "Backward-compatible alias for --personal-model. "
            "Defaults to models/<patient_id>.pkl."
        ),
    )
    parser.add_argument(
        "--generic-model",
        default=None,
        help=(
            "Backward-compatible alias for --generic-spatial-model. "
            "Defaults to config ai.generic_spatial_model."
        ),
    )
    parser.add_argument(
        "--generic-spatial-model",
        default=None,
        help="Generic spatial model path. Defaults to config ai.generic_spatial_model.",
    )
    parser.add_argument(
        "--generic-wearable-model",
        default=None,
        help="Generic wearable model path. Defaults to config ai.generic_wearable_model.",
    )
    parser.add_argument(
        "--personal-model",
        default=None,
        help="Personal model path. Defaults to config ai.personal_model or models/<patient_id>.pkl.",
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
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Keep the runtime alive and run one edge cycle every interval.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=240,
        help="Seconds between cycles when --loop is enabled. Defaults to 240.",
    )
    return parser


def main() -> None:
    """Punto di ingresso del runtime edge.

    La funzione esegue un ciclo completo e stampa lo stato JSON finale, utile per
    debug locale e per capire rapidamente se modello, qualita e baseline sono
    stati gestiti correttamente.
    """
    args = build_parser().parse_args()
    if args.loop:
        run_loop(args)
        return

    status = run_cycle(args)
    print(json.dumps(status, indent=2))


def run_loop(args: argparse.Namespace) -> None:
    """Esegue il ciclo edge in modo continuo, come un receiver periodico.

    Questa modalita e' pensata per i test manuali su Windows/Raspberry: il
    processo resta aperto nel terminale e ogni 4 minuti richiama Google Health,
    legge i dati BLE gia' ricevuti, aggiorna `latest_window.csv` e produce la
    decisione AI. Si ferma con Ctrl+C.
    """
    interval = max(1, int(args.interval_seconds))
    _log_info(
        "Edge runtime loop started "
        f"(config={args.config}, interval={interval}s, append_baseline={args.append_baseline})"
    )
    _log_info("Press CTRL+C to quit")

    while True:
        cycle_started_at = datetime.now()
        _log_info("Running edge cycle")
        try:
            status = run_cycle(args)
            duration_s = (datetime.now() - cycle_started_at).total_seconds()
            _log_info(
                "Cycle completed "
                f"window={status.get('window_start_local')}..{status.get('window_end_local')} "
                f"quality={status.get('quality_status')} "
                f"inference={status.get('inference')} "
                f"decision={status.get('decision_level')} "
                f"duration={duration_s:.1f}s"
            )
            if status.get("quality_status") != "ok":
                _log_info(
                    "Quality report has "
                    f"{status.get('quality_warning_count')} warning(s), "
                    f"{status.get('quality_error_count')} error(s): "
                    f"{status.get('quality_report')}"
                )
            _log_info(f"Next cycle in {interval} seconds")
        except KeyboardInterrupt:
            _log_info("Edge runtime loop stopped by user")
            return
        except Exception as exc:
            _log_info(
                f"Cycle error {type(exc).__name__}: {exc}. "
                f"Next cycle in {interval} seconds"
            )

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            _log_info("Edge runtime loop stopped by user")
            return


def _log_info(message: str) -> None:
    """Stampa log compatti in stile Uvicorn/receiver per la modalita loop."""
    if _supports_color():
        print(f"\033[32mINFO\033[0m:     {message}", flush=True)
    else:
        print(f"INFO:     {message}", flush=True)


def _supports_color() -> bool:
    """Rileva se il terminale corrente puo' mostrare colori ANSI."""
    return not os.environ.get("NO_COLOR")


def run_cycle(args: argparse.Namespace) -> dict[str, Any]:
    """Esegue una iterazione completa del processo IoT edge.

    Il ciclo puo' raccogliere BLE, aggregare la finestra, salvare
    `latest_window.csv`, generare il report qualita, aggiornare la baseline e
    lanciare inferenza se il modello esiste. Questa e' la funzione centrale che
    renderemo automatica sul Raspberry.
    """
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

    generic_spatial_model_path = _generic_spatial_model_path(args, config)
    generic_wearable_model_path = (
        Path(args.generic_wearable_model)
        if args.generic_wearable_model
        else Path(config.ai.generic_wearable_model)
    )
    personal_model_path = _personal_model_path(args, config, patient_id)

    baseline_appended = False
    baseline_skipped_reason = None
    baseline_gate_payload: dict[str, Any] | None = None
    if args.append_baseline and quality_report.usable_for_training:
        baseline_gate_payload = _run_baseline_safety_gate(
            config=config,
            generic_model_paths={
                "generic_spatial": generic_spatial_model_path,
                "generic_wearable": generic_wearable_model_path,
            },
            row=row,
        )
        baseline_gate_blocked = bool(baseline_gate_payload.get("blocked"))
        if baseline_gate_blocked and not args.force_baseline_append:
            baseline_skipped_reason = "generic_safety_gate"
        else:
            append_baseline_row(config.paths.baseline_csv, row)
            baseline_appended = True
            if baseline_gate_blocked:
                baseline_skipped_reason = "forced_despite_generic_safety_gate"
    elif args.append_baseline and args.force_baseline_append:
        append_baseline_row(config.paths.baseline_csv, row)
        baseline_appended = True
        baseline_skipped_reason = "forced_despite_quality_errors"
    elif args.append_baseline:
        baseline_skipped_reason = "quality_error"

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

    inference_status = "skipped_all_models_missing"
    decision_payload: dict[str, Any] | None = None
    if (
        generic_spatial_model_path.exists()
        or generic_wearable_model_path.exists()
        or personal_model_path.exists()
    ):
        decision_payload = _run_inference(
            generic_spatial_model_path=generic_spatial_model_path,
            generic_wearable_model_path=generic_wearable_model_path,
            personal_model_path=personal_model_path,
            latest_window_csv=config.paths.latest_window_csv,
            state_path=state_path,
            decision_output=decision_output,
            timezone_name=config.window.timezone,
        )
        inference_status = str(decision_payload.get("inference_status", "completed"))
    elif args.require_model:
        raise FileNotFoundError(
            "No AI model found. Expected at least one of: "
            f"{generic_spatial_model_path}, {generic_wearable_model_path}, "
            f"{personal_model_path}"
        )

    status: dict[str, Any] = {
        "status": "cycle_completed",
        "patient_id": patient_id,
        "config": str(args.config),
        "window_start": row["window_start"],
        "window_end": row["window_end"],
        "window_start_local": _to_local_iso(row["window_start"], config.window.timezone),
        "window_end_local": _to_local_iso(row["window_end"], config.window.timezone),
        "latest_window_csv": str(config.paths.latest_window_csv),
        "baseline_appended": baseline_appended,
        "baseline_csv": str(config.paths.baseline_csv) if baseline_appended else None,
        "baseline_skipped_reason": baseline_skipped_reason,
        "baseline_gate": baseline_gate_payload,
        "baseline_gate_blocked": (
            baseline_gate_payload.get("blocked") if baseline_gate_payload else None
        ),
        "ble_samples_collected": len(ble_samples),
        "received_ble_csv": str(config.ble.raw_csv),
        "google_health_enabled": config.google_health.enabled,
        "google_health_samples_logged": (
            bool(config.google_health.enabled)
            and config.google_health.raw_csv.exists()
        ),
        "received_google_health_csv": (
            str(config.google_health.raw_csv)
            if config.google_health.enabled
            else None
        ),
        "google_health_available_feature_count": quality_payload.get(
            "metrics",
            {},
        ).get("wearable_cloud_available_feature_count"),
        "google_health_available_features": quality_payload.get(
            "metrics",
            {},
        ).get("wearable_cloud_available_features"),
        "quality_status": quality_report.status,
        "quality_usable_for_training": quality_report.usable_for_training,
        "quality_issue_count": len(quality_report.issues),
        "quality_error_count": _count_quality_issues(quality_payload, "error"),
        "quality_warning_count": _count_quality_issues(quality_payload, "warning"),
        "quality_info_count": _count_quality_issues(quality_payload, "info"),
        "quality_report": str(args.quality_output) if args.quality_output else None,
        "generic_model": str(generic_spatial_model_path),
        "generic_model_exists": generic_spatial_model_path.exists(),
        "generic_spatial_model": str(generic_spatial_model_path),
        "generic_spatial_model_exists": generic_spatial_model_path.exists(),
        "generic_wearable_model": str(generic_wearable_model_path),
        "generic_wearable_model_exists": generic_wearable_model_path.exists(),
        "personal_model": str(personal_model_path),
        "personal_model_exists": personal_model_path.exists(),
        "model": str(personal_model_path),
        "inference": inference_status,
        "decision_output": str(decision_output) if decision_payload else None,
        "decision_level": decision_payload.get("level") if decision_payload else None,
        "should_publish": decision_payload.get("should_publish") if decision_payload else None,
        "fusion_mode": _fusion_mode(decision_payload),
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
    generic_spatial_model_path: Path,
    generic_wearable_model_path: Path,
    personal_model_path: Path,
    latest_window_csv: Path,
    state_path: Path,
    decision_output: Path,
    timezone_name: str,
) -> dict[str, Any]:
    """Carica i modelli disponibili, fonde i risultati e salva la decisione.

    La funzione supporta modelli mancanti: durante la baseline possono esserci
    solo i due generici; dopo la baseline si aggiunge quello personale. La
    fusione normalizza automaticamente i pesi sui modelli presenti.
    """
    from edge_ai.fusion import fuse_model_results
    from edge_ai.features import latest_record, load_feature_frame
    from edge_ai.model import EdgeAnomalyDetector

    frame = load_feature_frame(latest_window_csv)
    record = latest_record(frame)

    generic_spatial_result = None
    generic_wearable_result = None
    personal_result = None
    if generic_spatial_model_path.exists():
        generic_spatial_detector = EdgeAnomalyDetector.load(generic_spatial_model_path)
        generic_spatial_result = generic_spatial_detector.predict_record(record)
    if generic_wearable_model_path.exists():
        from edge_ai.wearable_quality import has_wearable_core_signal

        if has_wearable_core_signal(record):
            generic_wearable_detector = EdgeAnomalyDetector.load(generic_wearable_model_path)
            generic_wearable_result = generic_wearable_detector.predict_record(record)
    if personal_model_path.exists():
        personal_detector = EdgeAnomalyDetector.load(personal_model_path)
        personal_result = personal_detector.predict_record(record)

    fused_result = fuse_model_results(
        generic_spatial_result=generic_spatial_result,
        generic_wearable_result=generic_wearable_result,
        personal_result=personal_result,
    )

    debouncer = AlertDebouncer.load(state_path)
    decision = debouncer.update(fused_result)
    debouncer.save(state_path)

    payload = decision_to_json(decision)
    payload["window_start_local"] = _to_local_iso(payload["window_start"], timezone_name)
    payload["window_end_local"] = _to_local_iso(payload["window_end"], timezone_name)
    payload["inference_status"] = _inference_status(
        {
            "generic_spatial": generic_spatial_result,
            "generic_wearable": generic_wearable_result,
            "personal": personal_result,
        }
    )
    _write_json(decision_output, payload)
    return payload


def _run_baseline_safety_gate(
    config: Any,
    generic_model_paths: dict[str, Path],
    row: dict[str, Any],
) -> dict[str, Any]:
    """Valuta se una finestra puo' entrare nella baseline personale.

    Durante i primi giorni il modello generico interpreta comunque i dati del
    paziente. Se lo score e' alto, la finestra resta utile per il triage ma non
    viene usata per insegnare al modello personale che quel comportamento e'
    normale.
    """
    payload: dict[str, Any] = {
        "enabled": bool(config.ai.baseline_gate_enabled),
        "models": {
            name: {
                "path": str(path),
                "exists": path.exists(),
            }
            for name, path in generic_model_paths.items()
        },
        "block_score": float(config.ai.baseline_gate_block_score),
        "blocked": False,
    }
    if not config.ai.baseline_gate_enabled:
        payload["reason"] = "baseline_gate_disabled"
        return payload
    existing_model_paths = {
        name: path for name, path in generic_model_paths.items() if path.exists()
    }
    if not existing_model_paths:
        payload["reason"] = "generic_models_missing"
        return payload

    from edge_ai.model import EdgeAnomalyDetector

    model_results: dict[str, dict[str, Any]] = {}
    for name, path in existing_model_paths.items():
        if name == "generic_wearable":
            from edge_ai.wearable_quality import has_wearable_core_signal

            if not has_wearable_core_signal(row):
                model_results[name] = {
                    "score": None,
                    "model_label": "skipped_insufficient_wearable_data",
                }
                continue
        detector = EdgeAnomalyDetector.load(path)
        result = detector.predict_record(row)
        model_results[name] = {
            "score": float(result.anomaly_score),
            "model_label": result.model_label,
        }

    scored_items = [
        item for item in model_results.values() if item.get("score") is not None
    ]
    if not scored_items:
        payload.update(
            {
                "model_results": model_results,
                "blocked": False,
                "blocking_models": [],
                "reason": "generic_models_skipped_insufficient_data",
            }
        )
        return payload

    max_score = max(float(item["score"]) for item in scored_items)
    blocking_models = [
        name
        for name, item in model_results.items()
        if item.get("score") is not None
        and float(item["score"]) >= float(config.ai.baseline_gate_block_score)
    ]
    payload.update(
        {
            "score": max_score,
            "model_results": model_results,
            "blocked": bool(blocking_models),
            "blocking_models": blocking_models,
            "reason": (
                "generic_score_above_baseline_gate"
                if blocking_models
                else "generic_score_allowed"
            ),
        }
    )
    return payload


def _generic_spatial_model_path(args: argparse.Namespace, config: Any) -> Path:
    """Determina il percorso del modello generico spaziale.

    `--generic-model` resta come alias del vecchio schema a un solo modello
    generico, ma la configurazione nuova usa `generic_spatial_model`.
    """
    if args.generic_spatial_model:
        return Path(args.generic_spatial_model)
    if args.generic_model:
        return Path(args.generic_model)
    return Path(config.ai.generic_spatial_model)


def _personal_model_path(
    args: argparse.Namespace,
    config: Any,
    patient_id: str,
) -> Path:
    """Determina il percorso del modello personale mantenendo compatibilita CLI.

    `--model` era il vecchio argomento unico; da ora equivale al modello
    personale. Se nel file YAML e' presente `ai.personal_model`, viene usato
    quello. Altrimenti il default resta `models/<patient_id>.pkl`.
    """
    if args.personal_model:
        return Path(args.personal_model)
    if args.model:
        return Path(args.model)
    if config.ai.personal_model is not None:
        return Path(config.ai.personal_model)
    return Path("models") / f"{patient_id}.pkl"


def _inference_status(results: dict[str, Any]) -> str:
    """Restituisce una stringa breve sul tipo di inferenza eseguita."""
    available = [name for name, result in results.items() if result is not None]
    if available:
        return "completed_" + "_plus_".join(available)
    return "skipped_all_models_missing"


def _fusion_mode(payload: dict[str, Any] | None) -> str | None:
    """Legge dal JSON decisionale la modalita di fusione usata."""
    if not payload:
        return None
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        return None
    fusion = evidence.get("fusion")
    if not isinstance(fusion, dict):
        return None
    mode = fusion.get("mode")
    return str(mode) if mode is not None else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Scrive un payload JSON creando prima la cartella di destinazione.

    Il runtime produce vari file di stato; centralizzare la scrittura evita
    duplicazioni e garantisce che le directory vengano create automaticamente.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _to_local_iso(value: Any, timezone_name: str) -> str:
    """Converte un timestamp UTC/ISO nel fuso configurato per output leggibili."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(ZoneInfo(timezone_name)).isoformat()


def _count_quality_issues(payload: dict[str, Any], severity: str) -> int:
    """Conta quante issue di una certa severita compaiono nel report qualita.

    Questi contatori vengono inseriti in `last-cycle.json` per avere un riassunto
    immediato senza aprire manualmente il report completo.
    """
    return sum(
        1
        for issue in payload.get("issues", [])
        if issue.get("severity") == severity
    )


if __name__ == "__main__":
    main()
