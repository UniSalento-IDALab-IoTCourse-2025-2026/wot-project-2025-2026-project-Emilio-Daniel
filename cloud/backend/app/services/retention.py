from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Alert,
    AlertEvent,
    AuditLog,
    Decision,
    EdgeCycle,
    FeatureWindow,
    ModelRetrainingLog,
    Notification,
    SensorStatus,
    Task,
    TaskResult,
    WeeklyReport,
)

# ── Retention policies ──────────────────────────────────────────────────────
# Short:  feature windows, decisions (high-volume telemetry)
# Medium: edge cycles, sensor status (operational logs)
# Long:   alerts, tasks, audit, reports (clinical/audit data — never auto-purge)

DEFAULT_RETENTION = {
    "feature_windows_days": 30,
    "decisions_days": 30,
    "edge_cycles_days": 180,
    "sensor_status_days": 180,
}


def retention_summary(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Conteggia record per categoria e quanti sarebbero eliminati con la retention attiva."""
    now = now or datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    for label, model, cutoff_days in [
        ("feature_windows", FeatureWindow, DEFAULT_RETENTION["feature_windows_days"]),
        ("decisions", Decision, DEFAULT_RETENTION["decisions_days"]),
        ("edge_cycles", EdgeCycle, DEFAULT_RETENTION["edge_cycles_days"]),
        ("sensor_status", SensorStatus, DEFAULT_RETENTION["sensor_status_days"]),
        ("alerts", Alert, None),
        ("tasks", Task, None),
        ("audit_logs", AuditLog, None),
        ("weekly_reports", WeeklyReport, None),
    ]:
        total = db.execute(select(func.count(model.id))).scalar() or 0
        purgable = 0
        if cutoff_days is not None:
            cutoff = now - timedelta(days=cutoff_days)
            purgable = db.execute(select(func.count(model.id)).where(model.created_at < cutoff)).scalar() or 0
        counts[label] = {"total": total, "purgable": purgable}
    return {
        "generated_at": now.isoformat(),
        "retention_days": dict(DEFAULT_RETENTION),
        "counts": counts,
    }


def purge_old_feature_windows(db: Session, *, retention_days: int | None = None, now: datetime | None = None) -> int:
    """Elimina feature windows piu' vecchie della retention. Restituisce il numero di righe eliminate."""
    days = retention_days if retention_days is not None else DEFAULT_RETENTION["feature_windows_days"]
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    result = db.execute(delete(FeatureWindow).where(FeatureWindow.created_at < cutoff))
    db.flush()
    return result.rowcount or 0


def purge_old_decisions(db: Session, *, retention_days: int | None = None, now: datetime | None = None) -> int:
    days = retention_days if retention_days is not None else DEFAULT_RETENTION["decisions_days"]
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    result = db.execute(delete(Decision).where(Decision.created_at < cutoff))
    db.flush()
    return result.rowcount or 0


def purge_old_edge_cycles(db: Session, *, retention_days: int | None = None, now: datetime | None = None) -> int:
    days = retention_days if retention_days is not None else DEFAULT_RETENTION["edge_cycles_days"]
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    result = db.execute(delete(EdgeCycle).where(EdgeCycle.created_at < cutoff))
    db.flush()
    return result.rowcount or 0


def purge_old_sensor_status(db: Session, *, retention_days: int | None = None, now: datetime | None = None) -> int:
    days = retention_days if retention_days is not None else DEFAULT_RETENTION["sensor_status_days"]
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    result = db.execute(delete(SensorStatus).where(SensorStatus.created_at < cutoff))
    db.flush()
    return result.rowcount or 0


def run_full_purge(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Esegue il purge completo di tutti i dati soggetti a retention."""
    now = now or datetime.now(timezone.utc)
    deleted = {
        "feature_windows": purge_old_feature_windows(db, now=now),
        "decisions": purge_old_decisions(db, now=now),
        "edge_cycles": purge_old_edge_cycles(db, now=now),
        "sensor_status": purge_old_sensor_status(db, now=now),
    }
    db.commit()
    deleted["total"] = sum(deleted.values())
    return {
        "executed_at": now.isoformat(),
        "deleted": deleted,
    }
