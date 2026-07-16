from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.routes.task_rules import (
    effective_task_status,
    ensure_task_can_be_completed,
    is_patient_message_task,
    score_task_result_details,
    validate_questionnaire_result,
)
from app.api.routes.utils import utc_iso
from app.auth.dependencies import CurrentUser, can_access_patient, get_current_user, write_audit
from app.db.models import Notification, Task, TaskResult
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
    normalized_answers = validate_questionnaire_result(task.payload or {}, payload.get("answers", []))
    normalized_payload = dict(payload)
    normalized_payload["answers"] = normalized_answers
    result_payload = {
        "result_type": task.task_type,
        "started_at": payload.get("started_at"),
        "answers": normalized_answers,
        "device_info": payload.get("device_info", {}),
        "note": payload.get("note"),
        "content": structured_result_content(task.task_type, normalized_payload),
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
    task.completed_at = completed_at
    started_at = parse_optional_datetime(payload.get("started_at"))
    if started_at is not None:
        task.started_at = task.started_at or started_at
        task.seen_at = task.seen_at or started_at
    device_info = payload.get("device_info")
    if isinstance(device_info, dict):
        task.last_device_id = str(device_info.get("device_id") or "").strip() or task.last_device_id
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
    if is_questionnaire_task(task.payload or {}):
        event_bus.publish(
            InternalEvent(
                event_type="questionnaire_completed",
                patient_id=result.patient_id,
                timestamp=result.completed_at,
                payload={
                    "task_id": f"task-{task.id}",
                    "result_id": f"result-{result.id}",
                    "template_key": (task.payload or {}).get("questionnaire", {}).get("template_key"),
                },
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


@router.patch("/{task_id}/state", summary="Update patient task delivery state")
def update_task_state(
    task_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Registra quando l'app autorizzata vede o avvia un task."""
    task = get_task_or_404(db, task_id)
    if current_user.role not in {"patient", "admin"}:
        raise HTTPException(status_code=403, detail="Only patient or admin can update task delivery state.")
    if not can_access_patient(db, current_user, task.patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")
    if task.status in {"completed", "cancelled", "expired"}:
        raise HTTPException(status_code=409, detail=f"Task is already {task.status}.")

    requested_state = str(payload.get("state") or "").strip().lower()
    if requested_state not in {"seen", "started"}:
        raise HTTPException(status_code=422, detail="state must be seen or started.")
    occurred_at = parse_optional_datetime(payload.get("occurred_at")) or datetime.now(timezone.utc)
    device_id = str(payload.get("device_id") or "").strip() or None

    if requested_state == "seen":
        task.seen_at = task.seen_at or occurred_at
        if task.status == "created":
            task.status = "seen"
    else:
        task.seen_at = task.seen_at or occurred_at
        task.started_at = task.started_at or occurred_at
        task.status = "started"
    if device_id:
        task.last_device_id = device_id

    write_audit(
        db,
        actor=current_user,
        action=f"task.{requested_state}",
        patient_id=task.patient_id,
        target_type="task",
        target_id=f"task-{task.id}",
        details={"device_id": device_id},
    )
    db.commit()
    db.refresh(task)
    event_bus.publish(
        InternalEvent(
            event_type=f"task_{requested_state}",
            patient_id=task.patient_id,
            timestamp=occurred_at,
            payload={"task_id": f"task-{task.id}", "state": requested_state},
        )
    )
    return task_state_payload(task)


@router.delete("/{task_id}", summary="Delete task or dismiss patient message")
def dismiss_patient_message_task(
    task_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Archivia lato paziente oppure elimina definitivamente lato medico/admin."""
    task = get_task_or_404(db, task_id)
    if current_user.role in {"doctor", "admin"}:
        if not can_access_patient(db, current_user, task.patient_id):
            raise HTTPException(status_code=403, detail="Patient not authorized.")
        patient_id = task.patient_id
        public_task_id = f"task-{task.id}"
        title = task.title
        status = task.status
        dismiss_task_notifications(db, task)
        write_audit(
            db,
            actor=current_user,
            action="task.deleted",
            patient_id=patient_id,
            target_type="task",
            target_id=public_task_id,
            details={"title": title, "status": status},
        )
        db.execute(delete(TaskResult).where(TaskResult.task_id == task.id))
        db.delete(task)
        db.commit()
        event_bus.publish(
            InternalEvent(
                event_type="task_deleted",
                patient_id=patient_id,
                timestamp=datetime.now(timezone.utc),
                payload={"task_id": public_task_id},
            )
        )
        return {"status": "deleted", "task_id": public_task_id, "patient_id": patient_id}

    if current_user.role not in {"patient", "admin"}:
        raise HTTPException(status_code=403, detail="Only patient or admin can dismiss patient messages.")
    if not can_access_patient(db, current_user, task.patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")
    is_message = is_patient_message_task(task.task_type, task.payload or {})
    is_expired = effective_task_status(task.status, task.due_at) == "expired"
    if not is_message and not is_expired:
        raise HTTPException(
            status_code=409,
            detail="Only patient messages or expired activities can be dismissed from the companion app.",
        )
    if task.status == "dismissed":
        return task_state_payload(task)

    task.status = "dismissed"
    task_payload = dict(task.payload or {})
    task_payload["dismissed_at"] = datetime.now(timezone.utc).isoformat()
    task_payload["dismissed_by"] = current_user.display_name or current_user.email
    task.payload = task_payload
    dismiss_task_notifications(db, task)
    write_audit(
        db,
        actor=current_user,
        action="task.dismissed",
        patient_id=task.patient_id,
        target_type="task",
        target_id=f"task-{task.id}",
    )
    db.commit()
    db.refresh(task)
    event_bus.publish(
        InternalEvent(
            event_type="task_dismissed",
            patient_id=task.patient_id,
            timestamp=task.updated_at,
            payload={"task_id": f"task-{task.id}"},
        )
    )
    return task_state_payload(task)


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


@router.patch("/{task_id}/medical-note", summary="Update task medical note")
def update_task_medical_note(
    task_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Aggiorna la nota del medico associata al task e al risultato mostrato in dashboard."""
    task = get_task_or_404(db, task_id)
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can update task notes.")
    if not can_access_patient(db, current_user, task.patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")

    note = str(payload.get("medical_note") or payload.get("note") or "").strip()
    if not note:
        raise HTTPException(status_code=422, detail="medical_note is required.")

    task_payload = dict(task.payload or {})
    task_payload["medical_note"] = note
    task_payload["medical_note_by"] = current_user.display_name or current_user.email
    task_payload["medical_note_at"] = datetime.now(timezone.utc).isoformat()
    task.payload = task_payload
    write_audit(
        db,
        actor=current_user,
        action="task.medical_note_updated",
        patient_id=task.patient_id,
        target_type="task",
        target_id=f"task-{task.id}",
        details={"has_note": True},
    )
    db.commit()
    db.refresh(task)
    event_bus.publish(
        InternalEvent(
            event_type="task_updated",
            patient_id=task.patient_id,
            timestamp=task.updated_at,
            payload={"task_id": f"task-{task.id}"},
        )
    )
    return {
        "task_id": f"task-{task.id}",
        "patient_id": task.patient_id,
        "status": task.status,
        "medical_note": task_payload.get("medical_note"),
        "medical_note_by": task_payload.get("medical_note_by"),
        "medical_note_at": task_payload.get("medical_note_at"),
        "updated_at": utc_iso(task.updated_at),
    }


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


def is_questionnaire_task(task_payload: dict[str, Any]) -> bool:
    """Riconosce task generati da template questionario o check-in strutturati."""
    questionnaire = task_payload.get("questionnaire")
    content = task_payload.get("content")
    return isinstance(questionnaire, dict) or (isinstance(content, dict) and isinstance(content.get("questions"), list))


def parse_prefixed_id(value: str, prefix: str) -> int | None:
    text = value.removeprefix(f"{prefix}-")
    return int(text) if text.isdigit() else None


def parse_required_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise HTTPException(status_code=422, detail=f"{field_name} is required.")


def parse_optional_datetime(value: Any) -> datetime | None:
    """Converte un timestamp ISO opzionale usato dagli eventi dell'app."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise HTTPException(status_code=422, detail="occurred_at must be an ISO timestamp.")


def task_state_payload(task: Task) -> dict[str, Any]:
    """Restituisce lo stato di consegna senza esporre dati interni."""
    return {
        "task_id": f"task-{task.id}",
        "patient_id": task.patient_id,
        "status": task.status,
        "seen_at": utc_iso(task.seen_at),
        "started_at": utc_iso(task.started_at),
        "completed_at": utc_iso(task.completed_at),
        "device_id": task.last_device_id,
        "updated_at": utc_iso(task.updated_at),
    }


def dismiss_task_notifications(db: Session, task: Task) -> None:
    """Nasconde dall'app le notifiche push collegate al messaggio archiviato."""
    task_ref = f"task-{task.id}"
    notifications = db.execute(
        select(Notification).where(Notification.patient_id == task.patient_id)
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for notification in notifications:
        payload = notification.payload or {}
        if payload.get("task_id") == task_ref:
            notification.status = "dismissed"
            notification.seen_at = notification.seen_at or now
