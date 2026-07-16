from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

CLINICAL_TASK_TYPES = {"cognitive_test", "mobility_test"}
PATIENT_TASK_TYPES = {"check_in", "medication_reminder", "custom"}
ALLOWED_TASK_TYPES = CLINICAL_TASK_TYPES | PATIENT_TASK_TYPES
ALLOWED_ASSIGNEE_ROLES = {"patient", "caregiver"}
QUESTION_TYPES = {"yes_no", "scale", "single_choice", "text"}


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
    if scoring.get("type") == "scale_average":
        return score_scale_average(scoring, result_payload)
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


def validate_questionnaire_result(task_payload: dict[str, Any], answers: Any) -> list[dict[str, Any]]:
    """Valida risposte strutturate per check-in/questionari brevi."""
    questions = questionnaire_questions(task_payload)
    if not questions:
        return answers if isinstance(answers, list) else []
    if not isinstance(answers, list):
        raise HTTPException(status_code=422, detail="answers must be a list.")

    question_map = {str(question.get("id")): question for question in questions if isinstance(question, dict)}
    normalized_answers: list[dict[str, Any]] = []
    answered_ids: set[str] = set()
    for answer in answers:
        if not isinstance(answer, dict):
            raise HTTPException(status_code=422, detail="Each answer must be an object.")
        question_id = str(answer.get("question_id") or answer.get("id") or "").strip()
        if question_id not in question_map:
            raise HTTPException(status_code=422, detail=f"Unknown question_id: {question_id}")
        question = question_map[question_id]
        value = validate_answer_value(question, answer.get("value"))
        answered_ids.add(question_id)
        normalized_answers.append({"question_id": question_id, "value": value})

    missing_required = [
        str(question.get("id"))
        for question in questions
        if isinstance(question, dict) and question.get("required", True) and str(question.get("id")) not in answered_ids
    ]
    if missing_required:
        raise HTTPException(status_code=422, detail=f"Missing required answers: {', '.join(missing_required)}")
    return normalized_answers


def questionnaire_questions(task_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Estrae le domande dal payload normalizzato di un task/questionario."""
    content = task_payload.get("content")
    if not isinstance(content, dict):
        content = task_payload
    questions = content.get("questions")
    return questions if isinstance(questions, list) else []


def validate_answer_value(question: dict[str, Any], value: Any) -> Any:
    """Controlla una singola risposta in base al tipo domanda."""
    question_type = str(question.get("type") or "").strip().lower()
    if question_type not in QUESTION_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported question type: {question_type}")
    if question_type == "yes_no":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"yes", "no", "si", "sì", "true", "false"}:
            return value.strip().lower() in {"yes", "si", "sì", "true"}
        raise HTTPException(status_code=422, detail=f"Question {question.get('id')} requires yes/no value.")
    if question_type == "scale":
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Question {question.get('id')} requires numeric scale value.") from exc
        minimum = float(question.get("min", 0))
        maximum = float(question.get("max", 10))
        if numeric_value < minimum or numeric_value > maximum:
            raise HTTPException(status_code=422, detail=f"Question {question.get('id')} must be between {minimum:g} and {maximum:g}.")
        return int(numeric_value) if numeric_value.is_integer() else numeric_value
    if question_type == "single_choice":
        allowed_values = choice_values(question.get("options"))
        if value not in allowed_values:
            raise HTTPException(status_code=422, detail=f"Question {question.get('id')} value is not an allowed option.")
        return value
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"Question {question.get('id')} requires text value.")
    return value.strip()


def choice_values(options: Any) -> set[Any]:
    """Normalizza opzioni testuali o oggetti con campo value."""
    if not isinstance(options, list) or not options:
        raise HTTPException(status_code=422, detail="single_choice questions require options.")
    values: set[Any] = set()
    for option in options:
        if isinstance(option, dict):
            values.add(option.get("value"))
        else:
            values.add(option)
    return values


def score_scale_average(scoring: dict[str, Any], result_payload: dict[str, Any]) -> dict[str, Any] | None:
    """Calcola una media semplice per domande a scala quando il template la richiede."""
    answers = result_payload.get("answers")
    if not isinstance(answers, list):
        return None
    selected_ids = scoring.get("question_ids")
    selected = {str(item) for item in selected_ids} if isinstance(selected_ids, list) else None
    values: list[float] = []
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        question_id = str(answer.get("question_id") or "")
        if selected is not None and question_id not in selected:
            continue
        value = answer.get("value")
        if isinstance(value, (int, float)):
            values.append(float(value))
    if not values:
        return None
    score = round(sum(values) / len(values), 2)
    return {
        "type": "scale_average",
        "score": score,
        "count": len(values),
        "reason": f"Media di {len(values)} risposte su scala",
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
