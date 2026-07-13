from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes.task_rules import ensure_task_can_be_completed, score_task_result_details
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
    ensure_task_can_be_completed(task.status, task.due_at, completed_at)
    result_payload = {
        "result_type": task.task_type,
        "started_at": payload.get("started_at"),
        "answers": payload.get("answers", []),
        "device_info": payload.get("device_info", {}),
        "note": payload.get("note"),
        "content": structured_result_content(task.task_type, payload),
    }
    score_details = score_task_result_details(task.payload or {}, result_payload)
    result_payload["score"] = score_details["score"] if score_details else None
    result_payload["score_details"] = score_details
    result = TaskResult(
        task_id=task.id,
        patient_id=patient_id,
        message_id=str(payload.get("message_id") or f"task-result-{uuid.uuid4().hex}"),
        completed_at=completed_at,
        duration_seconds=payload.get("duration_seconds"),
        result=result_payload,
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
        details={"score": result_payload.get("score"), "score_details": score_details},
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
        "score_details": result.result.get("score_details"),
        "answers": result.result.get("answers", []),
        "result_type": result.result.get("result_type"),
        "content": result.result.get("content", {}),
        "note": result.result.get("note"),
        "device_info": result.result.get("device_info", {}),
        "received_at": utc_iso(result.created_at),
    }


@router.patch("/{task_id}/cancel", summary="Cancel task")
def cancel_task(
    task_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Annulla un task non ancora completato."""
    task = get_task_or_404(db, task_id)
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can cancel tasks.")
    if not can_access_patient(db, current_user, task.patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")
    if task.status == "completed":
        raise HTTPException(status_code=409, detail="Completed task cannot be cancelled.")
    if task.status == "cancelled":
        return task_cancel_payload(task)

    note = str(payload.get("note") or "").strip()
    task.status = "cancelled"
    task_payload = dict(task.payload or {})
    task_payload["cancelled_note"] = note or None
    task_payload["cancelled_by"] = current_user.display_name or current_user.email
    task.payload = task_payload
    write_audit(
        db,
        actor=current_user,
        action="task.cancelled",
        patient_id=task.patient_id,
        target_type="task",
        target_id=f"task-{task.id}",
        details={"note": note or None},
    )
    db.commit()
    db.refresh(task)
    event_bus.publish(
        InternalEvent(
            event_type="task_cancelled",
            patient_id=task.patient_id,
            timestamp=task.updated_at,
            payload={"task_id": f"task-{task.id}"},
        )
    )
    return task_cancel_payload(task)


def get_task_or_404(db: Session, task_id: str) -> Task:
    """Carica un task usando id numerico o formato `task-<id>`."""
    numeric_id = parse_prefixed_id(task_id, "task")
    task = db.get(Task, numeric_id) if numeric_id is not None else None
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task


def task_cancel_payload(task: Task) -> dict[str, Any]:
    payload = task.payload or {}
    return {
        "task_id": f"task-{task.id}",
        "patient_id": task.patient_id,
        "status": task.status,
        "cancelled_note": payload.get("cancelled_note"),
        "cancelled_by": payload.get("cancelled_by"),
        "updated_at": utc_iso(task.updated_at),
    }


def structured_result_content(task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Mantiene i risultati organizzati in modo diverso per tipo test."""
    if task_type == "cognitive_test":
        return {"answers": payload.get("answers", []), "test_metadata": payload.get("test_metadata", {})}
    if task_type == "mobility_test":
        return {
            "duration_seconds": payload.get("duration_seconds"),
            "steps": payload.get("steps"),
            "distance_meters": payload.get("distance_meters"),
            "fall_detected": payload.get("fall_detected"),
        }
    if task_type == "medication_reminder":
        return {"taken": payload.get("taken"), "taken_at": payload.get("taken_at"), "note": payload.get("note")}
    return {"answers": payload.get("answers", []), "note": payload.get("note")}


def parse_prefixed_id(value: str, prefix: str) -> int | None:
    text = value.removeprefix(f"{prefix}-")
    return int(text) if text.isdigit() else None


def parse_required_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise HTTPException(status_code=422, detail=f"{field_name} is required.")
