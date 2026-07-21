from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.realtime import active_websocket_connections
from app.db.models import Alert, AuditLog, Decision, EdgeCycle, EdgeDevice, FeatureWindow, Notification, PatientAppStatus, SensorStatus
from app.db.session import get_db

router = APIRouter()


@router.get("/health", summary="Liveness probe")
def health(request: Request) -> dict[str, object]:
    """Restituisce lo stato vitale del processo backend."""
    settings = request.app.state.settings
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready", summary="Readiness probe")
def ready(request: Request) -> dict[str, object]:
    """Restituisce lo stato della configurazione richiesta dal backend."""
    settings = request.app.state.settings
    return {
        "status": "ready",
        "checks": {
            "configuration": "ok",
            "mqtt_configured": bool(settings.mqtt_host),
            "database_configured": bool(settings.database_url),
        },
    }


@router.get("/metrics", summary="Operational metrics")
def metrics(db: Session = Depends(get_db)) -> dict[str, object]:
    """Espone metriche minime per controllare che l'infrastruttura lavori."""
    return {
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counters": {
            "edge_cycles_received": count_rows(db, EdgeCycle),
            "feature_windows_received": count_rows(db, FeatureWindow),
            "decisions_received": count_rows(db, Decision),
            "alerts_total": count_rows(db, Alert),
            "alerts_open": count_rows(db, Alert, Alert.status != "resolved"),
            "notifications_total": count_rows(db, Notification),
            "audit_events": count_rows(db, AuditLog),
            "edge_devices": count_rows(db, EdgeDevice),
            "sensor_status_rows": count_rows(db, SensorStatus),
            "patient_app_devices": count_rows(db, PatientAppStatus),
            "websocket_clients_connected": active_websocket_connections(),
        },
    }


def count_rows(db: Session, model: type, *where_clauses: object) -> int:
    """Conta le righe di una tabella applicando eventuali filtri SQLAlchemy."""
    statement = select(func.count()).select_from(model)
    for clause in where_clauses:
        statement = statement.where(clause)
    return int(db.execute(statement).scalar_one())
