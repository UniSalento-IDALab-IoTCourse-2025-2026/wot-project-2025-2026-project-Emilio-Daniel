from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/status", summary="Patients module status")
def patients_status() -> dict[str, str]:
    """Placeholder endpoint for patient registry and assignments."""
    return {"status": "not_implemented", "module": "patients"}
