from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.routes.realtime import active_websocket_connections
from app.core.config import get_settings
from app.core.telemetry import firebase_errors, mqtt_messages_received
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


@router.get("/health/live", summary="Liveness probe alias (D33)")
def health_live(request: Request) -> dict[str, object]:
    """Alias di liveness per chi utilizza il percorso `/health/live` convenzionale."""
    return health(request)


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


@router.get("/ops/status", summary="Operational status (D33)")
def operational_status(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    """Strato operativo unico: salute backend, database, MQTT, Firebase e WebSocket.

    Non espone mai token, password o certificati.
    """
    settings = request.app.state.settings
    database_ok = True
    database_error: str | None = None
    try:
        db.execute(select(func.count()).select_from(EdgeCycle))
    except Exception as exc:  # noqa: BLE001 - health check deve segnalare, non fallire.
        database_ok = False
        database_error = str(exc.__class__.__name__)
    mqtt_ok = bool(settings.mqtt_host) and mqtt_messages_received() > 0
    return {
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "services": {
            "backend": "ok",
            "database": "ok" if database_ok else "error",
            "mqtt_configured": bool(settings.mqtt_host),
            "mqtt_active": mqtt_ok,
            "firebase_enabled": settings.firebase_enabled or settings.firebase_fake_enabled,
            "firebase_errors": firebase_errors(),
            "websockets_active": active_websocket_connections(),
        },
        "errors": [f"database:{database_error}"] if database_error else [],
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
            "mqtt_messages_received_total": mqtt_messages_received(),
            "firebase_errors_total": firebase_errors(),
            "edge_mqtt_queue_depth": latest_global_mqtt_queue_depth(db),
        },
    }


def latest_global_mqtt_queue_depth(db: Session) -> int:
    """Ultima profondita' di coda MQTT locale segnalata dall'Edge (fiore all'occhiello del monitoring)."""
    latest = db.execute(
        select(Decision)
        .where(Decision.payload.is_not(None))
        .order_by(desc(Decision.timestamp), desc(Decision.id))
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return 0
    mqtt_payload = (latest.payload or {}).get("mqtt_publish")
    if isinstance(mqtt_payload, dict):
        value = mqtt_payload.get("queue_depth")
        return int(value) if isinstance(value, int | float) else 0
    return 0


def count_rows(db: Session, model: type, *where_clauses: object) -> int:
    """Conta le righe di una tabella applicando eventuali filtri SQLAlchemy."""
    statement = select(func.count()).select_from(model)
    for clause in where_clauses:
        statement = statement.where(clause)
    return int(db.execute(statement).scalar_one())
