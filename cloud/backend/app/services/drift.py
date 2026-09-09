from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Decision, ModelRetrainingLog, PatientModelDrift

DRIFT_BASELINE_START_DAYS = 35
DRIFT_BASELINE_END_DAYS = 15
DRIFT_RECENT_DAYS = 14
DRIFT_MEAN_SHIFT_THRESHOLD = 8.0
DRIFT_STD_MULTIPLIER = 1.5
DRIFT_MIN_POINTS = 3


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def personal_score_stats(
    db: Session,
    patient_id: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Media, deviazione standard e conteggio degli score del paziente in un periodo."""
    rows = (
        db.execute(
            select(Decision.anomaly_score).where(
                Decision.patient_id == patient_id,
                Decision.timestamp >= start,
                Decision.timestamp <= end,
                Decision.anomaly_score.isnot(None),
            )
        )
        .scalars()
        .all()
    )
    values = [float(value) for value in rows if isinstance(value, (int, float)) and not isinstance(value, bool)]
    return {
        "mean": _mean(values),
        "std": round(_std(values), 3),
        "count": len(values),
        "values": values,
    }


def _drift_detected(baseline: dict[str, Any], recent: dict[str, Any]) -> bool:
    """Verifica se la media recente si e' spostata in modo stabile dalla baseline."""
    if not baseline.get("values") or not recent.get("values"):
        return False
    baseline_mean = baseline["mean"]
    recent_mean = recent["mean"]
    if baseline_mean is None or recent_mean is None:
        return False
    if baseline["count"] < DRIFT_MIN_POINTS or recent["count"] < DRIFT_MIN_POINTS:
        return False
    threshold = max(DRIFT_MEAN_SHIFT_THRESHOLD, DRIFT_STD_MULTIPLIER * baseline["std"])
    return abs(recent_mean - baseline_mean) >= threshold


def log_retraining_action(
    db: Session,
    patient_id: str,
    action: str,
    *,
    actor_role: str | None = None,
    actor_user_id: int | None = None,
    note: str | None = None,
    details: dict[str, Any] | None = None,
) -> ModelRetrainingLog:
    entry = ModelRetrainingLog(
        patient_id=patient_id,
        action=action,
        actor_role=actor_role,
        actor_user_id=actor_user_id,
        note=note,
        details=details or {},
    )
    db.add(entry)
    return entry


def drift_state_payload(
    db: Session,
    patient_id: str,
    user: Any,
) -> dict[str, Any]:
    """Restituisce lo stato di drift del modello personale per la dashboard.

    Non modifica lo stato: legge (e se serve inizializza) la riga di drift.
    """
    _ensure_patient_drift_row(db, patient_id, user)
    state = _fetch_drift_row(db, patient_id)
    recent = _recent_stats(db, patient_id)
    state_payload = _state_to_payload(state)
    state_payload["recent_mean"] = recent
    state_payload["log"] = _retraining_log_payload(db, patient_id, limit=10)
    state_payload["model_updated_at"] = _latest_retrained_at(state)
    return state_payload


def _latest_retrained_at(state: PatientModelDrift | None) -> str | None:
    if state is None or state.retrained_at is None:
        return None
    return state.retrained_at.isoformat()


def _recent_stats(db: Session, patient_id: str) -> dict[str, Any]:
    now = _now_utc()
    recent = personal_score_stats(
        db, patient_id, now - timedelta(days=DRIFT_RECENT_DAYS), now
    )
    return {
        "mean": recent["mean"],
        "std": recent["std"],
        "count": recent["count"],
    }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hour_ago_utc() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=1)


def _ensure_patient_drift_row(db: Session, patient_id: str, user: Any) -> PatientModelDrift:
    """Inizializza lo stato di drift se non esiste ancora."""
    state = _fetch_drift_row(db, patient_id)
    if state is not None:
        return state
    state = PatientModelDrift(
        patient_id=patient_id,
        status="stable",
        requires_approval=False,
        drift_count=0,
        baseline_available=False,
        note="Attesa di dati per la prima valutazione di drift.",
    )
    db.add(state)
    db.flush()
    log_retraining_action(
        db, patient_id, "init",
        actor_role=getattr(user, "role", None),
        actor_user_id=getattr(user, "id", None) if getattr(user, "id", None) else None,
        note="Inizializzato lo stato di drift del modello personale.",
    )
    return state


def _fetch_drift_row(db: Session, patient_id: str) -> PatientModelDrift | None:
    return (
        db.execute(
            select(PatientModelDrift).where(PatientModelDrift.patient_id == patient_id)
        )
        .scalars()
        .first()
    )


def _state_to_payload(state: PatientModelDrift) -> dict[str, Any]:
    return {
        "status": state.status,
        "requires_approval": state.requires_approval,
        "overrides": True,
        "baseline": {
            "available": state.baseline_available,
            "mean": state.baseline_mean,
            "std": state.baseline_std,
        },
        "recent": {
            "mean": state.recent_mean,
            "std": state.recent_std,
        },
        "sample_size": state.sample_size,
        "drift_count": state.drift_count,
        "drift_since": state.drift_since.isoformat() if state.drift_since else None,
        "detected_at": state.detected_at.isoformat() if state.detected_at else None,
        "approved_at": state.approved_at.isoformat() if state.approved_at else None,
        "retrained_at": state.retrained_at.isoformat() if state.retrained_at else None,
        "note": state.note,
    }


def _retraining_log_payload(db: Session, patient_id: str, *, limit: int) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(ModelRetrainingLog)
            .where(ModelRetrainingLog.patient_id == patient_id)
            .order_by(ModelRetrainingLog.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "action": row.action,
            "actor_role": row.actor_role,
            "actor_user_id": row.actor_user_id,
            "note": row.note,
            "details": row.details,
            "timestamp": row.created_at.isoformat(),
        }
        for row in rows
    ]


def refresh_patient_drift(
    db: Session,
    patient_id: str,
    user: Any,
) -> dict[str, Any]:
    """Rileva e applica le transizioni di stato di drift (D27).

    Confronta la distribuzione recente (ultimi 14 giorni) con una baseline
    storica (15-35 giorni fa). Se la media si e' spostata in modo stabile,
    avanza nello stato: stable -> possible_drift -> needs_review. Se il
    paziente torna nella norma, riporta lo stato a stable.
    """
    now = _now_utc()
    state = _ensure_patient_drift_row(db, patient_id, user)

    baseline = personal_score_stats(
        db,
        patient_id,
        now - timedelta(days=DRIFT_BASELINE_START_DAYS),
        now - timedelta(days=DRIFT_BASELINE_END_DAYS),
    )
    recent = personal_score_stats(
        db, patient_id, now - timedelta(days=DRIFT_RECENT_DAYS), now
    )

    state.baseline_available = baseline["count"] >= DRIFT_MIN_POINTS
    state.baseline_mean = baseline["mean"]
    state.baseline_std = baseline["std"]
    state.recent_mean = recent["mean"]
    state.recent_std = recent["std"]
    state.sample_size = recent["count"]

    had_drift = _drift_detected(baseline, recent)
    previous_status = state.status
    now_status = state.status

    if state.status in {"not_detected", "stable"} or state.status is None:
        if had_drift:
            state.status = "possible_drift"
            state.drift_count = 1
            state.requires_approval = True
            state.drift_since = now
            state.detected_at = now
            log_retraining_action(
                db, patient_id, "detected",
                actor_role=getattr(user, "role", None),
                actor_user_id=getattr(user, "id", None),
                note="Possibile drift rilevato: media recente diversa dalla baseline.",
                details={"baseline_mean": baseline["mean"], "recent_mean": recent["mean"]},
            )
    elif state.status == "possible_drift":
        if had_drift:
            state.status = "needs_review"
            state.drift_count = state.drift_count + 1
            state.requires_approval = True
            state.detected_at = now
            log_retraining_action(
                db, patient_id, "needs_review",
                actor_role=getattr(user, "role", None),
                actor_user_id=getattr(user, "id", None),
                note="Drift confermato: attesa approvazione del medico per il retraining.",
            )
        else:
            state.status = "stable"
            state.drift_count = 0
            state.requires_approval = False
            state.drift_since = None
            log_retraining_action(
                db, patient_id, "stable",
                actor_role=getattr(user, "role", None),
                actor_user_id=getattr(user, "id", None),
                note="Distribuzione di nuovo nella norma: stato riportato a stabile.",
            )
    elif state.status == "needs_review":
        if not had_drift:
            state.status = "stable"
            state.drift_count = 0
            state.requires_approval = False
            state.drift_since = None

    db.flush()
    payload = _state_to_payload(state)
    payload["recent_mean"] = _recent_stats(db, patient_id)
    payload["log"] = _retraining_log_payload(db, patient_id, limit=10)
    return payload


def approve_retraining(
    db: Session,
    patient_id: str,
    user: Any,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    """Approva il retraining e marca il modello come aggiornato (D27)."""
    state = _fetch_drift_row(db, patient_id)
    if state is None:
        state = _ensure_patient_drift_row(db, patient_id, user)
    now = _now_utc()
    actor_id = getattr(user, "id", None)
    state.status = "retrained"
    state.requires_approval = False
    state.approved_by_user_id = actor_id
    state.approved_at = now
    state.retrained_at = now
    state.drift_count = 0
    state.note = note or state.note
    db.flush()
    log_retraining_action(
        db,
        patient_id,
        "approved",
        actor_role=getattr(user, "role", None),
        actor_user_id=actor_id,
        note=note or "Approvazione retraining da parte del medico.",
    )
    return drift_state_payload(db, patient_id, user)


def reject_retraining(
    db: Session,
    patient_id: str,
    user: Any,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    """Blocca il retraining e riporta lo stato a stabile (D27)."""
    state = _fetch_drift_row(db, patient_id)
    if state is None:
        state = _ensure_patient_drift_row(db, patient_id, user)
    state.status = "stable"
    state.requires_approval = False
    state.drift_count = 0
    state.drift_since = None
    state.note = note or state.note
    db.flush()
    log_retraining_action(
        db,
        patient_id,
        "blocked",
        actor_role=getattr(user, "role", None),
        actor_user_id=getattr(user, "id", None),
        note=note or "Retraining bloccato dal medico.",
    )
    return drift_state_payload(db, patient_id, user)