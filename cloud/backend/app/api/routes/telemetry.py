from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.routes.patients import get_patient_or_404
from app.api.routes.utils import paginated, utc_iso
from app.auth.dependencies import CurrentUser, require_patient_access
from app.db.models import Decision, FeatureWindow
from app.db.session import get_db

router = APIRouter()


@router.get("/status", summary="Telemetry module status")
def telemetry_status() -> dict[str, str]:
    """Espone lo stato del modulo telemetry."""
    return {"status": "implemented", "module": "telemetry"}


@router.get("/patients/{patient_id}/windows", summary="Patient feature windows")
def patient_windows(
    patient_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce le ultime finestre feature salvate dal subscriber MQTT."""
    get_patient_or_404(db, patient_id)
    rows = db.execute(
        select(FeatureWindow)
        .where(FeatureWindow.patient_id == patient_id)
        .order_by(desc(FeatureWindow.window_end), desc(FeatureWindow.id))
        .limit(limit)
    ).scalars().all()
    items = [window_payload(row) for row in reversed(rows)]
    return paginated(items, page_size=limit)


@router.get("/patients/{patient_id}/decisions", summary="Patient decisions")
def patient_decisions(
    patient_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce le ultime decisioni AI salvate dal subscriber MQTT."""
    get_patient_or_404(db, patient_id)
    rows = db.execute(
        select(Decision)
        .where(Decision.patient_id == patient_id)
        .order_by(desc(Decision.timestamp), desc(Decision.id))
        .limit(limit)
    ).scalars().all()
    items = [decision_payload(row) for row in reversed(rows)]
    return paginated(items, page_size=limit)


def window_payload(row: FeatureWindow) -> dict[str, Any]:
    """Serializza una finestra feature in formato dashboard."""
    return {
        "window_id": f"window-{row.id}",
        "patient_id": row.patient_id,
        "edge_id": row.edge_id,
        "window_start": utc_iso(row.window_start),
        "window_end": utc_iso(row.window_end),
        "features": row.features,
        "message_id": row.message_id,
        "created_at": utc_iso(row.created_at),
    }


def decision_payload(row: Decision) -> dict[str, Any]:
    """Serializza una decisione AI in formato dashboard."""
    payload = row.payload or {}
    return {
        "decision_id": f"decision-{row.id}",
        "patient_id": row.patient_id,
        "edge_id": row.edge_id,
        "timestamp": utc_iso(row.timestamp),
        "window_start": utc_iso(row.window_start),
        "window_end": utc_iso(row.window_end),
        "level": row.level,
        "should_publish": row.should_publish,
        "anomaly_score": row.anomaly_score,
        "model_label": row.model_label,
        "reasons": payload.get("payload", {}).get("reasons", payload.get("reasons", [])),
        "evidence": payload.get("payload", {}).get("evidence", payload.get("evidence", {})),
        "message_id": row.message_id,
        "created_at": utc_iso(row.created_at),
    }
