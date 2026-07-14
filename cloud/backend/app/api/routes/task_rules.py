from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

CLINICAL_TASK_TYPES = {"cognitive_test", "mobility_test"}
PATIENT_TASK_TYPES = {"check_in", "medication_reminder", "custom"}
ALLOWED_TASK_TYPES = CLINICAL_TASK_TYPES | PATIENT_TASK_TYPES
ALLOWED_ASSIGNEE_ROLES = {"patient", "caregiver"}


def validate_task_creation_payload(task_type: str, payload: dict[str, Any], role: str) -> dict[str, Any]:
    """Valida il contenuto del task e restituisce il payload normalizzato."""
    normalized_type = task_type.strip().lower()
    if normalized_type not in ALLOWED_TASK_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported task type: {task_type}")
    if normalized_type in CLINICAL_TASK_TYPES and role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can create clinical tasks.")

    content = payload.get("payload", {})
    if content is None:
        content = {}
    if not isinstance(content, dict):
        raise HTTPException(status_code=422, detail="Task payload must be an object.")

    if normalized_type == "cognitive_test":
        questions = content.get("questions")
        if not isinstance(questions, list) or not questions:
            raise HTTPException(status_code=422, detail="cognitive_test requires at least one question.")

    assigned_to = str(payload.get("assigned_to") or payload.get("assignee_role") or "patient").strip().lower()
    if assigned_to not in ALLOWED_ASSIGNEE_ROLES:
        raise HTTPException(status_code=422, detail="assigned_to must be patient or caregiver.")

    return {
        "schema_version": int(payload.get("schema_version") or 1),
        "priority": str(payload.get("priority") or "normal"),
        "expires_at": payload.get("expires_at"),
        "assigned_to": assigned_to,
        "content": content,
        "scoring": payload.get("scoring"),
        "medical_note": payload.get("medical_note") or payload.get("doctor_note"),
    }


def ensure_task_can_be_completed(status: str, due_at: datetime | None, completed_at: datetime) -> None:
    """Blocca risultati duplicati, task risolti o task scaduti."""
    if status == "completed":
        raise HTTPException(status_code=409, detail="Task already completed.")
    if status == "cancelled":
        raise HTTPException(status_code=409, detail="Task cancelled.")
    if status == "expired":
        raise HTTPException(status_code=409, detail="Task already expired.")
    if due_at is not None and normalize_utc(completed_at) > normalize_utc(due_at):
        raise HTTPException(status_code=409, detail="Task expired before completion.")


def score_task_result(task_payload: dict[str, Any], result_payload: dict[str, Any]) -> float | None:
    """Calcola lo score solo quando esiste una regola chiara e verificabile."""
    details = score_task_result_details(task_payload, result_payload)
    return details["score"] if details else None


def score_task_result_details(task_payload: dict[str, Any], result_payload: dict[str, Any]) -> dict[str, Any] | None:
    """Restituisce score e dettagli leggibili per dashboard e storico."""
    scoring = task_payload.get("scoring")
    if not isinstance(scoring, dict):
        return None
    if scoring.get("type") != "exact_match":
        return None
    answers = result_payload.get("answers")
    expected = scoring.get("expected_answers")
    if not isinstance(answers, list) or not isinstance(expected, dict) or not expected:
        return None

    correct = 0
    total = len(expected)
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        question_id = str(answer.get("question_id") or "")
        if question_id in expected and answer.get("value") == expected[question_id]:
            correct += 1
    score = round((correct / total) * 100, 2)
    return {
        "type": "exact_match",
        "score": score,
        "correct": correct,
        "total": total,
        "reason": f"{correct}/{total} risposte corrette",
    }


def effective_task_status(status: str, due_at: datetime | None, now: datetime | None = None) -> str:
    """Calcola lo stato effettivo senza modificare il DB durante le letture."""
    if status in {"completed", "cancelled", "expired", "dismissed"}:
        return status
    current = now or datetime.now(timezone.utc)
    if due_at is not None and normalize_utc(current) > normalize_utc(due_at):
        return "expired"
    return status


def is_patient_message_task(task_type: str, task_payload: dict[str, Any] | None) -> bool:
    """Riconosce i messaggi liberi inviati dal medico al paziente."""
    payload = task_payload or {}
    content = payload.get("content")
    if not isinstance(content, dict):
        content = payload
    return task_type == "custom" and content.get("kind") == "patient_message"


def normalize_utc(value: datetime) -> datetime:
    """Rende confrontabili datetime naive e aware."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
