from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/status", summary="Auth module status")
def auth_status() -> dict[str, str]:
    """Placeholder endpoint for the D7 authentication module."""
    return {"status": "not_implemented", "module": "auth"}
