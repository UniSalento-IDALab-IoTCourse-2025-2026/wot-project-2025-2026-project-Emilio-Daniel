from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health", summary="Liveness probe")
def health(request: Request) -> dict[str, object]:
    """Return whether the backend process is alive."""
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
    """Return dependencies expected by the next integration steps."""
    settings = request.app.state.settings
    return {
        "status": "ready",
        "checks": {
            "configuration": "ok",
            "mqtt_configured": bool(settings.mqtt_host),
            "database_configured": bool(settings.database_url),
        },
    }
