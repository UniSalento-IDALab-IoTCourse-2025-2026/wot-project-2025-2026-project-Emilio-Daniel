from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from edge_ingest.config import EdgeIngestConfig


DEFAULT_BASELINE_STATE = Path("data/state/baseline-session.json")
DEFAULT_DAYS = 6


@dataclass
class BaselineSession:
    patient_id: str
    status: str
    started_at: str
    planned_days: int
    target_end_at: str
    baseline_csv: str
    model_output: str
    total_cycles: int = 0
    accepted_windows: int = 0
    rejected_windows: int = 0
    quality_error_cycles: int = 0
    quality_warning_cycles: int = 0
    quality_info_cycles: int = 0
    last_window_end: str | None = None
    last_quality_status: str | None = None
    last_rejected_reason: str | None = None
    finalized_at: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Converte lo stato della baseline in un dizionario serializzabile.

        Il file di stato viene salvato in JSON, quindi la dataclass deve essere
        trasformata in tipi base. Questo metodo mantiene centralizzata la
        conversione e riduce duplicazioni nel codice CLI e runtime.
        """
        return asdict(self)


def start_session(
    config: EdgeIngestConfig,
    state_path: str | Path = DEFAULT_BASELINE_STATE,
    days: int = DEFAULT_DAYS,
    model_output: str | Path | None = None,
    reset: bool = False,
) -> BaselineSession:
    """Avvia una nuova sessione di raccolta baseline reale.

    La baseline rappresenta la routine personale del paziente e deve essere
    raccolta prima dell'addestramento. La funzione crea il file di stato con
    durata pianificata, percorso del CSV baseline e percorso del modello finale.
    """
    state = Path(state_path)
    if state.exists() and not reset:
        existing = load_session(state)
        if existing.status == "collecting":
            raise RuntimeError(
                f"Baseline session already active at {state}. "
                "Use --reset to start over."
            )

    now = datetime.now(timezone.utc)
    model_path = Path(model_output) if model_output else Path("models") / f"{config.patient.patient_id}.pkl"
    session = BaselineSession(
        patient_id=config.patient.patient_id,
        status="collecting",
        started_at=now.isoformat(),
        planned_days=int(days),
        target_end_at=(now + timedelta(days=int(days))).isoformat(),
        baseline_csv=str(config.paths.baseline_csv),
        model_output=str(model_path),
        notes=[
            "Collect only real routine data.",
            "Windows with quality status error are not appended by default.",
        ],
    )
    save_session(session, state)
    return session


def load_session(state_path: str | Path = DEFAULT_BASELINE_STATE) -> BaselineSession:
    """Legge da disco lo stato corrente della sessione baseline.

    Questa funzione permette al runtime, che viene eseguito periodicamente, di
    sapere se una raccolta baseline e' attiva e quanti cicli sono gia' stati
    accettati o rifiutati.
    """
    source = Path(state_path)
    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return BaselineSession(**payload)


def save_session(
    session: BaselineSession,
    state_path: str | Path = DEFAULT_BASELINE_STATE,
) -> None:
    """Salva su disco lo stato aggiornato della baseline.

    Ogni ciclo edge puo' modificare contatori, ultimo timestamp e qualita dei
    dati. Salvare questi dati rende la procedura robusta anche se il Raspberry
    viene riavviato durante la raccolta.
    """
    target = Path(state_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(session.to_dict(), handle, indent=2)


def update_session_from_cycle(
    config: EdgeIngestConfig,
    cycle_status: dict[str, Any],
    quality_report: dict[str, Any],
    state_path: str | Path = DEFAULT_BASELINE_STATE,
) -> BaselineSession | None:
    """Aggiorna la sessione baseline dopo un ciclo edge.

    Il runtime chiama questa funzione dopo aver aggregato la finestra e valutato
    la qualita. In questo modo il sistema registra quante finestre sono state
    accettate per il training e quante sono state scartate per problemi tecnici.
    """
    state = Path(state_path)
    if not state.exists():
        return None

    session = load_session(state)
    if session.status != "collecting":
        return session

    if session.patient_id != config.patient.patient_id:
        return session

    session.total_cycles += 1
    if cycle_status.get("baseline_appended"):
        session.accepted_windows += 1
    elif cycle_status.get("baseline_skipped_reason"):
        session.rejected_windows += 1

    quality_status = str(quality_report.get("status", "unknown"))
    session.last_quality_status = quality_status
    if quality_status == "error":
        session.quality_error_cycles += 1
    elif quality_status == "warning":
        session.quality_warning_cycles += 1
    elif quality_status == "ok":
        info_count = _count_issues(quality_report, "info")
        if info_count:
            session.quality_info_cycles += 1

    session.last_window_end = str(cycle_status.get("window_end") or "")
    session.last_rejected_reason = cycle_status.get("baseline_skipped_reason")
    save_session(session, state)
    return session


def session_status_payload(
    config: EdgeIngestConfig,
    state_path: str | Path = DEFAULT_BASELINE_STATE,
) -> dict[str, Any]:
    """Costruisce un riepilogo leggibile dello stato della baseline.

    Il payload contiene avanzamento temporale, numero di finestre attese,
    percentuale di completamento e indicazione `ready_for_training`. Serve sia
    per il comando CLI sia per capire se il modello puo' essere addestrato.
    """
    state = Path(state_path)
    if not state.exists():
        return {
            "status": "not_started",
            "state": str(state),
            "patient_id": config.patient.patient_id,
        }

    session = load_session(state)
    now = datetime.now(timezone.utc)
    started = _parse_dt(session.started_at)
    target_end = _parse_dt(session.target_end_at)
    elapsed_days = max(0.0, (now - started).total_seconds() / 86400.0)
    remaining_days = max(0.0, (target_end - now).total_seconds() / 86400.0)
    expected_windows = _expected_windows(elapsed_days, config.window.minutes)
    completion_by_time = min(1.0, elapsed_days / max(1, session.planned_days))

    payload = session.to_dict()
    payload.update(
        {
            "state": str(state),
            "elapsed_days": round(elapsed_days, 3),
            "remaining_days": round(remaining_days, 3),
            "expected_windows_so_far": expected_windows,
            "accepted_ratio": _ratio(session.accepted_windows, expected_windows),
            "rejected_ratio": _ratio(session.rejected_windows, max(1, session.total_cycles)),
            "completion_by_time_pct": round(completion_by_time * 100.0, 2),
            "baseline_row_count": count_baseline_rows(session.baseline_csv),
            "ready_for_training": (
                session.status == "collecting"
                and now >= target_end
                and count_baseline_rows(session.baseline_csv) >= 50
                and session.quality_error_cycles == 0
            ),
        }
    )
    return payload


def finalize_session(
    config: EdgeIngestConfig,
    state_path: str | Path = DEFAULT_BASELINE_STATE,
    allow_early: bool = False,
) -> BaselineSession:
    """Marca la baseline come pronta per l'addestramento.

    La finalizzazione controlla che la raccolta abbia durata e qualita
    sufficienti. L'opzione `allow_early` e' prevista solo per prove tecniche, non
    per il modello finale su dati reali.
    """
    state = Path(state_path)
    session = load_session(state)
    payload = session_status_payload(config, state)
    if not allow_early and not payload["ready_for_training"]:
        raise RuntimeError(
            "Baseline is not ready for finalization. "
            "Use --allow-early only for technical tests."
        )
    session.status = "ready_for_training"
    session.finalized_at = datetime.now(timezone.utc).isoformat()
    save_session(session, state)
    return session


def count_baseline_rows(path: str | Path) -> int:
    """Conta quante finestre aggregate sono presenti nel CSV baseline.

    Il numero di righe e' un indicatore minimo di sufficienza del dataset: senza
    abbastanza finestre reali l'Isolation Forest non puo' costruire una baseline
    affidabile.
    """
    source = Path(path)
    if not source.exists():
        return 0
    with source.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return sum(1 for _ in reader)


def _count_issues(report: dict[str, Any], severity: str) -> int:
    """Conta nel report qualita le issue con una certa severita.

    La funzione e' usata per aggiornare statistiche come errori, warning e info
    durante la raccolta baseline, mantenendo separati problemi bloccanti e
    semplici osservazioni.
    """
    return sum(
        1
        for issue in report.get("issues", [])
        if issue.get("severity") == severity
    )


def _parse_dt(value: str) -> datetime:
    """Converte una stringa ISO in `datetime` UTC.

    Lo stato baseline salva le date come stringhe JSON. Prima di calcolare
    durata e scadenza e' necessario riportarle a oggetti temporali confrontabili.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _expected_windows(elapsed_days: float, window_minutes: int) -> int:
    """Stima quante finestre ci si aspetta dopo un certo tempo di raccolta.

    Questo valore serve per valutare se il sistema sta producendo abbastanza
    dati rispetto alla frequenza prevista, ad esempio una finestra ogni 4 minuti.
    """
    if elapsed_days <= 0:
        return 0
    return int((elapsed_days * 24.0 * 60.0) / max(1, window_minutes))


def _ratio(value: int, total: int) -> float:
    """Calcola un rapporto protetto da divisioni per zero.

    Nei primi istanti della baseline il totale puo' essere nullo. Questa helper
    restituisce 0.0 in modo controllato e arrotonda il risultato per renderlo
    leggibile nei report JSON.
    """
    if total <= 0:
        return 0.0
    return round(value / total, 4)
