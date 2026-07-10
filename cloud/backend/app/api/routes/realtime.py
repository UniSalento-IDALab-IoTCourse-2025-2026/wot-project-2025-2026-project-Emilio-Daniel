from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/status", summary="Realtime module status")
def realtime_status() -> dict[str, str]:
    """Placeholder endpoint for future WebSocket connection state."""
    return {"status": "not_implemented", "module": "realtime"}
