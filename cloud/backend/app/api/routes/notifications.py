from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/status", summary="Notifications module status")
def notifications_status() -> dict[str, str]:
    """Placeholder endpoint for push notifications and delivery state."""
    return {"status": "not_implemented", "module": "notifications"}
