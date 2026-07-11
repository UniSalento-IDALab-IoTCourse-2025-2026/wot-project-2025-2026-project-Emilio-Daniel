from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

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
