from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/status", summary="Tasks module status")
def tasks_status() -> dict[str, str]:
    """Placeholder endpoint for cognitive tests and patient tasks."""
    return {"status": "not_implemented", "module": "tasks"}
