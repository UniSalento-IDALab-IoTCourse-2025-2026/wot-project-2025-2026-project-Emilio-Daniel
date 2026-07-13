from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes.utils import utc_iso
from app.auth.dependencies import CurrentUser, can_access_patient, get_current_user, write_audit
from app.db.models import Task, TaskResult
from app.db.session import get_db
from app.mqtt.events import InternalEvent, event_bus

router = APIRouter()


@router.get("/status", summary="Tasks module status")
def tasks_status() -> dict[str, str]:
    """Espone lo stato del modulo task."""
    return {"status": "implemented", "module": "tasks"}


@router.post("/{task_id}/results", summary="Create task result")
def create_task_result(
    task_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Salva il risultato di un task completato dall'app paziente."""
    task = get_task_or_404(db, task_id)
    if current_user.role not in {"patient", "admin"}:
        raise HTTPException(status_code=403, detail="Only patient or admin can submit task results.")
    completed_at = parse_required_datetime(payload.get("completed_at"), "completed_at")
    patient_id = str(payload.get("patient_id") or task.patient_id)
    if patient_id != task.patient_id:
        raise HTTPException(status_code=422, detail="Task result patient_id does not match task.")
    if not can_access_patient(db, current_user, patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")
    result = TaskResult(
        task_id=task.id,
        patient_id=patient_id,
        message_id=str(payload.get("message_id") or f"task-result-{uuid.uuid4().hex}"),
        completed_at=completed_at,
        duration_seconds=payload.get("duration_seconds"),
        result={
            "started_at": payload.get("started_at"),
            "answers": payload.get("answers", []),
            "score": payload.get("score"),
            "device_info": payload.get("device_info", {}),
        },
    )
    task.status = "completed"
    db.add(result)
    write_audit(
        db,
        actor=current_user,
        action="task.completed",
        patient_id=patient_id,
        target_type="task",
        target_id=f"task-{task.id}",
        details={"score": payload.get("score")},
    )
    db.commit()
    db.refresh(result)
    event_bus.publish(
        InternalEvent(
            event_type="task_completed",
            patient_id=result.patient_id,
            timestamp=result.completed_at,
            payload={"task_id": f"task-{task.id}", "result_id": f"result-{result.id}"},
        )
    )
    return {
        "result_id": f"result-{result.id}",
        "task_id": f"task-{task.id}",
        "patient_id": result.patient_id,
        "status": "received",
        "completed_at": utc_iso(result.completed_at),
        "duration_seconds": result.duration_seconds,
        "score": result.result.get("score"),
        "answers": result.result.get("answers", []),
        "device_info": result.result.get("device_info", {}),
        "received_at": utc_iso(result.created_at),
    }


def get_task_or_404(db: Session, task_id: str) -> Task:
    """Carica un task usando id numerico o formato `task-<id>`."""
    numeric_id = parse_prefixed_id(task_id, "task")
    task = db.get(Task, numeric_id) if numeric_id is not None else None
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task


def parse_prefixed_id(value: str, prefix: str) -> int | None:
    text = value.removeprefix(f"{prefix}-")
    return int(text) if text.isdigit() else None


def parse_required_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise HTTPException(status_code=422, detail=f"{field_name} is required.")
