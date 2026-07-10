from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/status", summary="Telemetry module status")
def telemetry_status() -> dict[str, str]:
    """Placeholder endpoint for windows, decisions and sensor data."""
    return {"status": "not_implemented", "module": "telemetry"}
