from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/status", summary="Alerts module status")
def alerts_status() -> dict[str, str]:
    """Placeholder endpoint for clinical, behavioral and technical alerts."""
    return {"status": "not_implemented", "module": "alerts"}
