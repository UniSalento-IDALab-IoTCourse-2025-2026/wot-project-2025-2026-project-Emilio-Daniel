from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import CurrentUser, require_patient_access
from app.core.config import get_settings
from app.db.models import Patient, User
from app.db.session import get_db
from app.services.drift import approve_retraining, drift_state_payload, reject_retraining, refresh_patient_drift

router = APIRouter()


def _metrics_dir() -> Path:
    """Restituisce la directory dove i modelli edge salvano le metriche.

    Di default cerca in una directory relativa al backend. In produzione
    questa path viene configurata via variabile d'ambiente IOT_AI_MODELS_DIR.
    """
    settings = get_settings()
    raw = getattr(settings, "ai_models_dir", "")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / "edge_node" / "models"


def _load_patient_metrics(patient_id: str) -> list[dict[str, Any]]:
    """Carica tutti i file *_metrics.json per un paziente specifico.

    I file vengono cercati nella directory dei modelli con naming pattern:
      {patient_id}_*_metrics.json
      generic_*_metrics.json

    Ogni file contiene le metriche di validazione di un singolo modello.
    """
    models_dir = _metrics_dir()
    if not models_dir.exists():
        return []

    metrics: list[dict[str, Any]] = []

    for path in sorted(models_dir.glob("*_metrics.json")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            model_id = data.get("model_id", "")
            if model_id == patient_id or path.name.startswith("generic_"):
                metrics.append(_normalize_metric(data, path.name))
        except (json.JSONDecodeError, OSError):
            continue

    return metrics


def _normalize_metric(data: dict[str, Any], filename: str) -> dict[str, Any]:
    """Normalizza il formato metriche per la dashboard.

    Converte i nomi interni (patient_id, model_scope) in nomi leggibili
    (model, f1, precision, recall, validation_rows) come richiesto da Emilio.
    """
    scope = data.get("model_scope", "unknown")
    model_id = data.get("model_id", "unknown")

    display_name = {
        "personal": f"Modello personale ({model_id})",
        "generic_wearable": "Modello generico wearable",
        "generic_spatial": "Modello generico spaziale",
    }.get(scope, scope)

    return {
        "model": scope,
        "display_name": display_name,
        "model_scope": scope,
        "model_id": model_id,
        "f1": data.get("f1", 0.0),
        "precision": data.get("precision", 0.0),
        "recall": data.get("recall", 0.0),
        "accuracy": data.get("accuracy", 0.0),
        "roc_auc": data.get("roc_auc"),
        "validation_rows": data.get("validation_rows", 0),
        "training_rows": data.get("training_rows", 0),
        "true_positives": data.get("true_positives", 0),
        "true_negatives": data.get("true_negatives", 0),
        "false_positives": data.get("false_positives", 0),
        "false_negatives": data.get("false_negatives", 0),
        "ambiguous_excluded": data.get("ambiguous_excluded", 0),
        "synthetic_anomalies_added": data.get("synthetic_anomalies_added", 0),
        "computed_at": data.get("computed_at"),
        "notes": data.get("notes", ""),
    }


def _last_training_at(metrics: list[dict[str, Any]]) -> str | None:
    """Trova la data di training/valutazione piu' recente tra le metriche."""
    latest: datetime | None = None
    for m in metrics:
        raw = m.get("computed_at")
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if latest is None or dt > latest:
                latest = dt
        except (ValueError, TypeError):
            continue
    if latest is None:
        return None
    return latest.replace(microsecond=0).isoformat().replace("+00:00", "Z")


@router.get("/{patient_id}/ai/model-metrics", summary="AI model validation metrics")
def model_metrics(
    patient_id: str,
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce le metriche di validazione dei modelli AI per un paziente.

    Endpoint atteso dalla Dashboard (E21 - ModelReliabilityPanel).
    Se non esistono metriche, restituisce un array vuoto per permettere
    alla dashboard di mostrare uno stato "in attesa" senza errori.
    """
    models = _load_patient_metrics(patient_id)
    drift = drift_state_payload(db, patient_id, _current_user)
    return {
        "patient_id": patient_id,
        "models": models,
        "last_training_at": drift.get("model_updated_at") or _last_training_at(models),
        "models_dir": str(_metrics_dir()),
        "drift": drift,
    }


@router.get("/{patient_id}/ai/drift", summary="Model drift state (D27)")
def ai_drift_state(
    patient_id: str,
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Rileva lo stato di drift del modello personale e le ultime azioni di retraining."""
    payload = refresh_patient_drift(db, patient_id, _current_user)
    return {
        "patient_id": patient_id,
        "drift": payload,
        "retraining_log": payload.get("log", []),
    }


@router.post("/{patient_id}/ai/retraining/approve", summary="Approva retraining modello (D27)")
def ai_approve_retraining(
    patient_id: str,
    body: dict[str, Any] = {},
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if _current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Solo i medici possono approvare il retraining.")
    note = str(body.get("note") or "").strip() or None
    payload = approve_retraining(db, patient_id, _current_user, note=note)
    return {
        "patient_id": patient_id,
        "status": "retrained",
        "drift": payload,
    }


@router.post("/{patient_id}/ai/retraining/reject", summary="Blocca retraining modello (D27)")
def ai_reject_retraining(
    patient_id: str,
    body: dict[str, Any] = {},
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if _current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Solo i medici possono bloccare il retraining.")
    note = str(body.get("note") or "").strip() or None
    payload = reject_retraining(db, patient_id, _current_user, note=note)
    return {
        "patient_id": patient_id,
        "status": "stable",
        "drift": payload,
    }
