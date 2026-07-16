from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.routes.task_rules import QUESTION_TYPES, validate_task_creation_payload
from app.api.routes.utils import paginated, utc_iso
from app.auth.dependencies import CurrentUser, can_access_patient, get_current_user, write_audit
from app.db.models import Patient, QuestionnaireSchedule, QuestionnaireTemplate, Task, TaskResult
from app.db.session import get_db
from app.mqtt.events import InternalEvent, event_bus
from app.services.push_notifications import notify_task_created

router = APIRouter()


@router.get("/status", summary="Questionnaires module status")
def questionnaires_status() -> dict[str, str]:
    """Espone lo stato del modulo questionari."""
    return {"status": "implemented", "module": "questionnaires"}


@router.get("/templates", summary="List questionnaire templates")
def questionnaire_templates(
    active: bool | None = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce i template questionario disponibili per dashboard e app."""
    query = select(QuestionnaireTemplate)
    if active is not None:
        query = query.where(QuestionnaireTemplate.is_active == active)
    rows = db.execute(query.order_by(QuestionnaireTemplate.template_key, desc(QuestionnaireTemplate.version))).scalars().all()
    return paginated([template_payload(row) for row in rows], page=page, page_size=page_size)


@router.post("/templates", summary="Create questionnaire template")
def create_questionnaire_template(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Crea una versione di template questionario usabile per task ripetibili."""
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can create questionnaire templates.")
    template_key = str(payload.get("template_key") or "").strip().lower()
    title = str(payload.get("title") or "").strip()
    questions = validate_questions(payload.get("questions"))
    if not template_key or not title:
        raise HTTPException(status_code=422, detail="template_key and title are required.")
    version = int(payload.get("version") or 1)
    existing = db.execute(
        select(QuestionnaireTemplate).where(
            QuestionnaireTemplate.template_key == template_key,
            QuestionnaireTemplate.version == version,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Template key/version already exists.")

    template = QuestionnaireTemplate(
        template_key=template_key,
        version=version,
        title=title,
        description=payload.get("description"),
        task_type=str(payload.get("task_type") or "check_in").strip().lower(),
        schema_version=int(payload.get("schema_version") or 1),
        questions=questions,
        scoring=payload.get("scoring"),
        default_priority=str(payload.get("default_priority") or payload.get("priority") or "normal").strip().lower(),
        default_payload=payload.get("default_payload") if isinstance(payload.get("default_payload"), dict) else {},
        is_active=bool(payload.get("is_active", True)),
        created_by_user_id=current_user.id,
    )
    db.add(template)
    write_audit(db, actor=current_user, action="questionnaire_template.created", target_type="questionnaire_template", details={"template_key": template_key, "version": version})
    db.commit()
    db.refresh(template)
    return template_payload(template)


@router.get("/patients/{patient_id}/schedules", summary="List patient questionnaire schedules")
def patient_questionnaire_schedules(
    patient_id: str,
    status: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Mostra le programmazioni questionario associate a un paziente."""
    ensure_patient_access(db, current_user, patient_id)
    query = select(QuestionnaireSchedule).where(QuestionnaireSchedule.patient_id == patient_id)
    if status:
        query = query.where(QuestionnaireSchedule.status == status)
    rows = db.execute(query.order_by(desc(QuestionnaireSchedule.created_at), desc(QuestionnaireSchedule.id))).scalars().all()
    return {"items": [schedule_payload(db, row) for row in rows], "total": len(rows)}


@router.post("/patients/{patient_id}/schedules", summary="Create patient questionnaire schedule")
def create_questionnaire_schedule(
    patient_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Programma un questionario giornaliero o settimanale per un paziente."""
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can create questionnaire schedules.")
    ensure_patient_access(db, current_user, patient_id)
    template = get_template_or_404(db, payload.get("template_id") or payload.get("template_key"))
    frequency = str(payload.get("frequency") or "daily").strip().lower()
    if frequency not in {"daily", "weekly"}:
        raise HTTPException(status_code=422, detail="frequency must be daily or weekly.")
    interval = int(payload.get("interval") or 1)
    if interval < 1:
        raise HTTPException(status_code=422, detail="interval must be greater than zero.")
    next_run_at = parse_datetime(payload.get("next_run_at")) or datetime.now(timezone.utc)
    schedule = QuestionnaireSchedule(
        patient_id=patient_id,
        template_id=template.id,
        created_by_user_id=current_user.id,
        status="active",
        frequency=frequency,
        interval=interval,
        next_run_at=next_run_at,
        starts_at=parse_datetime(payload.get("starts_at")),
        ends_at=parse_datetime(payload.get("ends_at")),
        timezone_name=str(payload.get("timezone") or "Europe/Rome"),
        title_override=payload.get("title"),
        instructions_override=payload.get("instructions"),
        priority=payload.get("priority"),
        payload_overrides=payload.get("payload_overrides") if isinstance(payload.get("payload_overrides"), dict) else {},
    )
    db.add(schedule)
    write_audit(
        db,
        actor=current_user,
        action="questionnaire_schedule.created",
        patient_id=patient_id,
        target_type="questionnaire_schedule",
        details={"template_key": template.template_key, "frequency": frequency},
    )
    db.commit()
    db.refresh(schedule)
    return schedule_payload(db, schedule)


@router.patch("/schedules/{schedule_id}/suspend", summary="Suspend questionnaire schedule")
def suspend_questionnaire_schedule(
    schedule_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Sospende una programmazione ricorrente senza cancellarne lo storico."""
    schedule = get_schedule_or_404(db, schedule_id)
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can suspend questionnaire schedules.")
    ensure_patient_access(db, current_user, schedule.patient_id)
    schedule.status = "suspended"
    write_audit(
        db,
        actor=current_user,
        action="questionnaire_schedule.suspended",
        patient_id=schedule.patient_id,
        target_type="questionnaire_schedule",
        target_id=f"schedule-{schedule.id}",
    )
    db.commit()
    db.refresh(schedule)
    return schedule_payload(db, schedule)


@router.post("/schedules/{schedule_id}/generate-due-task", summary="Generate task from due questionnaire schedule")
def generate_due_questionnaire_task(
    schedule_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Genera il task concreto quando una programmazione e' arrivata a scadenza."""
    schedule = get_schedule_or_404(db, schedule_id)
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can generate questionnaire tasks.")
    ensure_patient_access(db, current_user, schedule.patient_id)
    now = parse_datetime(payload.get("now")) or datetime.now(timezone.utc)
    force = bool(payload.get("force", False))
    if schedule.status != "active":
        raise HTTPException(status_code=409, detail="Questionnaire schedule is not active.")
    if schedule.ends_at is not None and now > normalize_utc(schedule.ends_at):
        schedule.status = "completed"
        db.commit()
        return {"status": "completed", "schedule": schedule_payload(db, schedule), "task": None}
    if schedule.last_generated_at is not None and same_schedule_period(schedule, schedule.last_generated_at, now) and not force:
        task = db.get(Task, schedule.last_task_id) if schedule.last_task_id else None
        return {"status": "already_generated", "schedule": schedule_payload(db, schedule), "task": task_payload_light(task) if task else None}
    if now < normalize_utc(schedule.next_run_at) and not force:
        return {"status": "not_due", "schedule": schedule_payload(db, schedule), "task": None}

    template = db.get(QuestionnaireTemplate, schedule.template_id)
    if template is None or not template.is_active:
        raise HTTPException(status_code=409, detail="Questionnaire template is not available.")
    task = build_task_from_schedule(schedule, template, now)
    validate_task_creation_payload(task.task_type, task_creation_validation_payload(task), current_user.role)
    db.add(task)
    db.flush()
    schedule.last_generated_at = now
    schedule.last_task_id = task.id
    schedule.next_run_at = next_run(schedule, now)
    write_audit(
        db,
        actor=current_user,
        action="questionnaire_task.generated",
        patient_id=schedule.patient_id,
        target_type="task",
        target_id=f"task-{task.id}",
        details={"schedule_id": f"schedule-{schedule.id}", "template_key": template.template_key},
    )
    notify_task_created(db, task)
    db.commit()
    db.refresh(task)
    db.refresh(schedule)
    event_bus.publish(
        InternalEvent(
            event_type="task_created",
            patient_id=task.patient_id,
            timestamp=task.created_at,
            payload={"task_id": f"task-{task.id}", "type": task.task_type, "source": "questionnaire_schedule"},
        )
    )
    return {"status": "generated", "schedule": schedule_payload(db, schedule), "task": task_payload_light(task)}


@router.get("/patients/{patient_id}/results", summary="List patient questionnaire results")
def patient_questionnaire_results(
    patient_id: str,
    template_key: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce lo storico punteggi dei questionari completati."""
    ensure_patient_access(db, current_user, patient_id)
    rows = db.execute(
        select(TaskResult, Task)
        .join(Task, Task.id == TaskResult.task_id)
        .where(TaskResult.patient_id == patient_id)
        .order_by(desc(TaskResult.completed_at), desc(TaskResult.id))
    ).all()
    items = []
    for result, task in rows:
        questionnaire = (task.payload or {}).get("questionnaire")
        if not isinstance(questionnaire, dict):
            continue
        if template_key and questionnaire.get("template_key") != template_key:
            continue
        items.append(questionnaire_result_payload(result, task, questionnaire))
    return paginated(items, page=page, page_size=page_size)


def validate_questions(value: Any) -> list[dict[str, Any]]:
    """Valida lo schema minimo delle domande ripetibili."""
    if not isinstance(value, list) or not value:
        raise HTTPException(status_code=422, detail="questions must be a non-empty list.")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="Each question must be an object.")
        question_id = str(item.get("id") or "").strip()
        question_type = str(item.get("type") or "").strip().lower()
        text = str(item.get("text") or "").strip()
        if not question_id or not text:
            raise HTTPException(status_code=422, detail="Each question requires id and text.")
        if question_id in seen_ids:
            raise HTTPException(status_code=422, detail=f"Duplicate question id: {question_id}")
        if question_type not in QUESTION_TYPES:
            raise HTTPException(status_code=422, detail=f"Unsupported question type: {question_type}")
        if question_type == "single_choice" and not isinstance(item.get("options"), list):
            raise HTTPException(status_code=422, detail=f"Question {question_id} requires options.")
        normalized.append({**item, "id": question_id, "type": question_type, "text": text, "required": bool(item.get("required", True))})
        seen_ids.add(question_id)
    return normalized


def ensure_patient_access(db: Session, user: CurrentUser, patient_id: str) -> None:
    """Verifica paziente esistente e autorizzazione dell'utente."""
    if db.get(Patient, patient_id) is None:
        raise HTTPException(status_code=404, detail=f"Patient not found: {patient_id}")
    if not can_access_patient(db, user, patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")


def get_template_or_404(db: Session, value: Any) -> QuestionnaireTemplate:
    """Carica un template per id pubblico/numerico o template_key."""
    if value is None:
        raise HTTPException(status_code=422, detail="template_id or template_key is required.")
    text = str(value).removeprefix("template-")
    if text.isdigit():
        template = db.get(QuestionnaireTemplate, int(text))
    else:
        template = db.execute(
            select(QuestionnaireTemplate)
            .where(QuestionnaireTemplate.template_key == str(value).strip().lower(), QuestionnaireTemplate.is_active == True)  # noqa: E712
            .order_by(desc(QuestionnaireTemplate.version), desc(QuestionnaireTemplate.id))
        ).scalars().first()
    if template is None:
        raise HTTPException(status_code=404, detail=f"Questionnaire template not found: {value}")
    return template


def get_schedule_or_404(db: Session, value: str) -> QuestionnaireSchedule:
    """Carica una programmazione usando id numerico o formato `schedule-<id>`."""
    text = value.removeprefix("schedule-")
    schedule = db.get(QuestionnaireSchedule, int(text)) if text.isdigit() else None
    if schedule is None:
        raise HTTPException(status_code=404, detail=f"Questionnaire schedule not found: {value}")
    return schedule


def build_task_from_schedule(schedule: QuestionnaireSchedule, template: QuestionnaireTemplate, now: datetime) -> Task:
    """Crea il task operativo collegato a una programmazione."""
    content = dict(template.default_payload or {})
    content.update(schedule.payload_overrides or {})
    content["questions"] = template.questions
    task_payload = {
        "schema_version": template.schema_version,
        "priority": schedule.priority or template.default_priority,
        "assigned_to": "patient",
        "content": content,
        "scoring": template.scoring,
        "questionnaire": {
            "template_id": f"template-{template.id}",
            "template_key": template.template_key,
            "template_version": template.version,
            "schedule_id": f"schedule-{schedule.id}",
        },
    }
    return Task(
        patient_id=schedule.patient_id,
        created_by_user_id=schedule.created_by_user_id,
        task_type=template.task_type,
        status="created",
        title=schedule.title_override or template.title,
        instructions=schedule.instructions_override or template.description,
        due_at=now + timedelta(hours=int((schedule.payload_overrides or {}).get("task_due_hours", 24))),
        payload=task_payload,
    )


def task_creation_validation_payload(task: Task) -> dict[str, Any]:
    """Adatta il payload gia' normalizzato alla validazione task esistente."""
    payload = task.payload or {}
    return {
        "schema_version": payload.get("schema_version"),
        "priority": payload.get("priority"),
        "assigned_to": payload.get("assigned_to"),
        "payload": payload.get("content"),
        "scoring": payload.get("scoring"),
    }


def next_run(schedule: QuestionnaireSchedule, now: datetime) -> datetime:
    """Calcola la prossima occorrenza senza introdurre un job scheduler esterno."""
    if schedule.frequency == "weekly":
        return now + timedelta(days=7 * schedule.interval)
    return now + timedelta(days=schedule.interval)


def same_schedule_period(schedule: QuestionnaireSchedule, first: datetime, second: datetime) -> bool:
    """Evita duplicati nella stessa giornata o settimana programmata."""
    first_utc = normalize_utc(first)
    second_utc = normalize_utc(second)
    if schedule.frequency == "weekly":
        return first_utc.isocalendar()[:2] == second_utc.isocalendar()[:2]
    return first_utc.date() == second_utc.date()


def parse_datetime(value: Any) -> datetime | None:
    """Converte timestamp ISO opzionali ricevuti da dashboard o test."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return normalize_utc(value)
    if isinstance(value, str):
        return normalize_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    raise HTTPException(status_code=422, detail="Invalid datetime value.")


def normalize_utc(value: datetime) -> datetime:
    """Rende coerenti date naive e aware."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def template_payload(template: QuestionnaireTemplate) -> dict[str, Any]:
    """Serializza un template questionario."""
    return {
        "template_id": f"template-{template.id}",
        "template_key": template.template_key,
        "version": template.version,
        "title": template.title,
        "description": template.description,
        "task_type": template.task_type,
        "schema_version": template.schema_version,
        "questions": template.questions,
        "scoring": template.scoring,
        "default_priority": template.default_priority,
        "default_payload": template.default_payload,
        "is_active": template.is_active,
        "created_at": utc_iso(template.created_at),
        "updated_at": utc_iso(template.updated_at),
    }


def schedule_payload(db: Session, schedule: QuestionnaireSchedule) -> dict[str, Any]:
    """Serializza una programmazione con il relativo template."""
    template = db.get(QuestionnaireTemplate, schedule.template_id)
    return {
        "schedule_id": f"schedule-{schedule.id}",
        "patient_id": schedule.patient_id,
        "status": schedule.status,
        "frequency": schedule.frequency,
        "interval": schedule.interval,
        "next_run_at": utc_iso(normalize_utc(schedule.next_run_at)),
        "last_generated_at": utc_iso(normalize_utc(schedule.last_generated_at) if schedule.last_generated_at else None),
        "last_task_id": f"task-{schedule.last_task_id}" if schedule.last_task_id else None,
        "starts_at": utc_iso(normalize_utc(schedule.starts_at) if schedule.starts_at else None),
        "ends_at": utc_iso(normalize_utc(schedule.ends_at) if schedule.ends_at else None),
        "timezone": schedule.timezone_name,
        "title": schedule.title_override or (template.title if template else None),
        "instructions": schedule.instructions_override or (template.description if template else None),
        "priority": schedule.priority or (template.default_priority if template else "normal"),
        "template": template_payload(template) if template else None,
        "created_at": utc_iso(schedule.created_at),
        "updated_at": utc_iso(schedule.updated_at),
    }


def task_payload_light(task: Task | None) -> dict[str, Any] | None:
    """Restituisce solo i dati necessari per agganciare il task generato."""
    if task is None:
        return None
    return {
        "task_id": f"task-{task.id}",
        "patient_id": task.patient_id,
        "status": task.status,
        "type": task.task_type,
        "title": task.title,
        "due_at": utc_iso(task.due_at),
        "created_at": utc_iso(task.created_at),
    }


def questionnaire_result_payload(result: TaskResult, task: Task, questionnaire: dict[str, Any]) -> dict[str, Any]:
    """Serializza lo storico punteggi di un questionario completato."""
    stored = result.result or {}
    return {
        "result_id": f"result-{result.id}",
        "task_id": f"task-{task.id}",
        "patient_id": result.patient_id,
        "template_key": questionnaire.get("template_key"),
        "template_version": questionnaire.get("template_version"),
        "schedule_id": questionnaire.get("schedule_id"),
        "title": task.title,
        "completed_at": utc_iso(result.completed_at),
        "duration_seconds": result.duration_seconds,
        "score": stored.get("score"),
        "score_details": stored.get("score_details"),
        "answers": stored.get("answers", []),
        "device_info": stored.get("device_info", {}),
    }
