from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.routes.utils import event_note_payload, paginated, utc_iso
from app.api.routes.task_rules import effective_task_status, validate_task_creation_payload
from app.auth.dependencies import (
    CurrentUser,
    authorized_patient_ids,
    get_current_user,
    require_patient_access,
    write_audit,
)
from app.core.config import get_settings
from app.db.models import Alert, AlertEvent, AuditLog, Decision, EdgeCycle, EdgeDevice, FeatureWindow, ModelRetrainingLog, Notification, Patient, PatientAppStatus, PatientModelDrift, SensorStatus, Task, TaskResult
from app.db.session import get_db
from app.mqtt.events import InternalEvent, event_bus
from app.services.drift import drift_state_payload as compute_drift_state
from app.services.morning_brief import morning_brief_payload
from app.services.push_notifications import notify_caregiver_message, notify_task_created
from app.services.weekly_report import (
    generate_weekly_report,
    week_bounds,
    weekly_reports_payload,
)

router = APIRouter()
ALERT_ESCALATION_MINUTES = 30


@router.get("", summary="List dashboard patients")
def list_patients(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce la lista pazienti sintetica usata dalla sidebar dashboard."""
    allowed = authorized_patient_ids(db, current_user)
    query = select(Patient).where(Patient.is_active.is_(True))
    if allowed is not None:
        if not allowed:
            return paginated([], page_size=20)
        query = query.where(Patient.patient_id.in_(allowed))
    patients = db.execute(query.order_by(Patient.patient_id)).scalars().all()
    items = [patient_summary(db, patient) for patient in patients]
    return paginated(items, page=page, page_size=page_size)


@router.get("/{patient_id}/current", summary="Current patient state")
def patient_current(
    patient_id: str,
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Aggrega ultima finestra, decisione e stato tecnico del paziente."""
    patient = get_patient_or_404(db, patient_id)
    return current_payload(db, patient)


@router.get("/{patient_id}/summary/24h", summary="Patient 24h summary")
def patient_summary_24h(
    patient_id: str,
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce un riepilogo aggregato delle ultime 24 ore per la dashboard."""
    patient = get_patient_or_404(db, patient_id)
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(hours=24)
    previous_start = period_start - timedelta(hours=24)
    windows = feature_windows_between(db, patient.patient_id, period_start, now)
    previous_windows = feature_windows_between(db, patient.patient_id, previous_start, period_start)
    decisions = decisions_between(db, patient.patient_id, period_start, now)
    previous_decisions = decisions_between(db, patient.patient_id, previous_start, period_start)
    latest_cycle = latest_edge_cycle(db, patient.patient_id)
    baseline = baseline_status_from_cycle(latest_edge_cycle_status_payload(latest_cycle))
    return {
        "patient_id": patient.patient_id,
        "generated_at": utc_iso(now),
        "range": {
            "start": utc_iso(period_start),
            "end": utc_iso(now),
            "hours": 24,
        },
        "previous_range": {
            "start": utc_iso(previous_start),
            "end": utc_iso(period_start),
            "hours": 24,
        },
        "counts": {
            "windows": len(windows),
            "decisions": len(decisions),
            "previous_windows": len(previous_windows),
            "previous_decisions": len(previous_decisions),
        },
        "ai": ai_summary(decisions, previous_decisions),
        "spatial": spatial_summary(windows),
        "wearable": wearable_summary(windows),
        "data_completeness": data_completeness_summary(db, patient.patient_id, windows, latest_cycle, now=now),
        "baseline": {
            "available": bool(baseline.get("trained") or baseline.get("status") in {"trained", "ready", "completed"}),
            "status": baseline.get("status"),
            "accepted_windows": baseline.get("accepted_windows"),
            "min_training_windows": baseline.get("min_training_windows"),
            "reason": baseline.get("reason") or ("baseline_not_ready" if not baseline.get("trained") else None),
        },
    }


@router.get("/{patient_id}/spatial-summary", summary="Patient spatial routine summary")
def patient_spatial_summary(
    patient_id: str,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    days: int = Query(default=7, ge=1, le=31),
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Aggrega routine ambientale, qualita' BLE e confronto con riferimento."""
    patient = get_patient_or_404(db, patient_id)
    now = datetime.now(timezone.utc)
    period_end = normalize_aware(date_to) if date_to is not None else now
    period_start = normalize_aware(date_from) if date_from is not None else period_end - timedelta(days=days)
    if period_start >= period_end:
        raise HTTPException(status_code=422, detail="date_from must be before date_to.")
    period_duration = period_end - period_start
    previous_start = period_start - period_duration
    windows = feature_windows_between(db, patient.patient_id, period_start, period_end)
    previous_windows = feature_windows_between(db, patient.patient_id, previous_start, period_start)
    latest_cycle = latest_edge_cycle(db, patient.patient_id)
    cycle_status = latest_edge_cycle_status_payload(latest_cycle)
    baseline = baseline_status_from_cycle(cycle_status)
    current = spatial_summary(windows)
    reference = spatial_reference_summary(cycle_status, previous_windows)
    return {
        "patient_id": patient.patient_id,
        "generated_at": utc_iso(now),
        "range": {
            "start": utc_iso(period_start),
            "end": utc_iso(period_end),
            "days": round(period_duration.total_seconds() / 86400, 3),
        },
        "counts": {
            "windows": len(windows),
            "reference_windows": len(previous_windows),
        },
        "room_minutes": current["room_minutes"],
        "prevalent_room": current["prevalent_room"],
        "transitions": spatial_transition_summary(windows),
        "night": spatial_night_summary(windows),
        "longest_single_room_minutes": current["longest_single_room_minutes"],
        "baseline": {
            "available": bool(baseline.get("trained") or baseline.get("status") in {"trained", "ready", "completed"}),
            "status": baseline.get("status"),
            "source": reference["source"],
            "reason": reference["reason"],
            "comparison": spatial_baseline_comparison(current, reference["summary"]),
        },
        "ble_quality": spatial_ble_quality(db, patient.patient_id, windows, period_start, period_end, now=now),
    }


@router.get("/{patient_id}/report-data", summary="Patient report data")
def patient_report_data(
    patient_id: str,
    days: int = Query(default=7, ge=1, le=31),
    current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce un pacchetto coerente per report stampabile/esportabile."""
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can export patient reports.")
    patient = get_patient_or_404(db, patient_id)
    now = datetime.now(timezone.utc)
    report = report_data_payload(db, patient, current_user, now=now, days=days)
    write_audit(
        db,
        actor=current_user,
        action="patient_report.exported",
        patient_id=patient.patient_id,
        target_type="patient_report",
        target_id=patient.patient_id,
        details={
            "days": days,
            "generated_at": report["generated_at"],
            "sections": list(report["sections"].keys()),
        },
    )
    db.commit()
    return report


@router.get("/{patient_id}/reports/weekly", summary="Weekly automatic reports (D28)")
def patient_weekly_reports(
    patient_id: str,
    limit: int = Query(default=8, ge=1, le=52),
    auto_generate: bool = Query(default=True),
    current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce i riepiloghi settimanali del paziente (dal piu' recente).

    Se `auto_generate` e' true, genera al volo il report della settimana in
    corso quando non e' ancora stato creato, cosi' il medico trova sempre un
    riepilogo pronto senza passare per un job esplicito.
    """
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can read weekly reports.")
    get_patient_or_404(db, patient_id)
    reports = weekly_reports_payload(db, patient_id, limit=limit)
    if auto_generate and (not reports or not _current_week_report_present(reports)):
        report = generate_weekly_report(db, patient_id)
        write_audit(
            db,
            actor=current_user,
            action="weekly_report.generated_auto",
            patient_id=patient_id,
            target_type="weekly_report",
            target_id=report["report_id"],
            details={"week_start": report["week_start"]},
        )
        db.commit()
        reports = weekly_reports_payload(db, patient_id, limit=limit)
    return {
        "patient_id": patient_id,
        "items": reports,
        "reports": reports,
    }


@router.post("/{patient_id}/reports/generate", summary="Generate weekly report manually (D28)")
def patient_generate_weekly_report(
    patient_id: str,
    body: dict[str, Any] = {},
    current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Comando manuale per generare o rigenerare il report della settimana."""
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can generate weekly reports.")
    get_patient_or_404(db, patient_id)
    force = bool(body.get("force", False))
    report = generate_weekly_report(db, patient_id, force=force)
    write_audit(
        db,
        actor=current_user,
        action="weekly_report.generated_manual",
        patient_id=patient_id,
        target_type="weekly_report",
        target_id=report["report_id"],
        details={
            "force": force,
            "week_start": report["week_start"],
        },
    )
    db.commit()
    return {
        "patient_id": patient_id,
        "generated": True,
        "report": report,
    }


def _current_week_report_present(reports: list[dict[str, Any]]) -> bool:
    """Verifica se esiste gia' il report della settimana corrente."""
    if not reports:
        return False
    week_start, _week_end = week_bounds(datetime.now(PATIENT_TIMEZONE))
    target = week_start.isoformat()
    return any(report.get("week_start") == target for report in reports)


@router.get("/{patient_id}/morning-brief", summary="Morning brief (D29)")
def patient_morning_brief(
    patient_id: str,
    current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Riepilogo notturno 22:00-08:00 confrontato con la baseline personale.

    Il medico apre la dashboard al mattino e vede subito come e' andata la
    notte, con una sintesi prudente non diagnostica (E27).
    """
    get_patient_or_404(db, patient_id)
    return morning_brief_payload(db, patient_id)


@router.get("/{patient_id}/audit-trail", summary="Patient readable audit trail")
def patient_audit_trail(
    patient_id: str,
    action: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=200),
    current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Mostra al medico uno storico audit leggibile delle azioni sul paziente."""
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can read patient audit trail.")
    get_patient_or_404(db, patient_id)
    query = select(AuditLog).where(AuditLog.patient_id == patient_id)
    if action:
        query = query.where(AuditLog.action == action)
    if date_from is not None:
        query = query.where(AuditLog.timestamp >= date_from)
    if date_to is not None:
        query = query.where(AuditLog.timestamp <= date_to)
    rows = db.execute(query.order_by(desc(AuditLog.timestamp), desc(AuditLog.id))).scalars().all()
    return paginated([audit_trail_payload(row) for row in rows], page=page, page_size=page_size)


@router.get("/{patient_id}/timeline", summary="Patient normalized timeline")
def patient_timeline(
    patient_id: str,
    event_type: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=200),
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Aggrega eventi eterogenei del paziente in una timeline normalizzata."""
    patient = get_patient_or_404(db, patient_id)
    allowed_types = parse_event_type_filter(event_type)
    events = normalized_timeline_events(db, patient.patient_id, date_from=date_from, date_to=date_to)
    if allowed_types:
        events = [event for event in events if event["event_type"] in allowed_types]
    events = deduplicate_timeline_events(events)
    events.sort(key=lambda event: (parse_datetime(event["timestamp"]) or datetime.min.replace(tzinfo=timezone.utc), event["event_id"]), reverse=True)
    return paginated(events, page=page, page_size=page_size)


@router.get("/{patient_id}/windows", summary="Patient feature windows")
def patient_windows(
    patient_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce le ultime finestre feature del paziente."""
    get_patient_or_404(db, patient_id)
    query = select(FeatureWindow).where(FeatureWindow.patient_id == patient_id)
    if date_from is not None:
        query = query.where(FeatureWindow.window_end >= date_from)
    if date_to is not None:
        query = query.where(FeatureWindow.window_end <= date_to)
    rows = db.execute(query.order_by(desc(FeatureWindow.window_end), desc(FeatureWindow.id)).limit(limit)).scalars().all()
    items = [window_payload(row) for row in reversed(rows)]
    return paginated(items, page=page, page_size=page_size or limit)


@router.get("/{patient_id}/decisions", summary="Patient AI decisions")
def patient_decisions(
    patient_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce le ultime decisioni AI del paziente."""
    get_patient_or_404(db, patient_id)
    query = select(Decision).where(Decision.patient_id == patient_id)
    if date_from is not None:
        query = query.where(Decision.timestamp >= date_from)
    if date_to is not None:
        query = query.where(Decision.timestamp <= date_to)
    rows = db.execute(query.order_by(desc(Decision.timestamp), desc(Decision.id)).limit(limit)).scalars().all()
    patient_trend = compute_patient_trend(db, patient_id)
    items = [decision_payload(row, db, patient_trend=patient_trend) for row in reversed(rows)]
    return paginated(items, page=page, page_size=page_size or limit)


@router.get("/{patient_id}/alerts", summary="Patient alerts")
def patient_alerts(
    patient_id: str,
    level: str | None = Query(default=None),
    status: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce gli alert del paziente nel formato usato dalla dashboard."""
    get_patient_or_404(db, patient_id)
    query = select(Alert).where(Alert.patient_id == patient_id)
    if level:
        query = query.where(Alert.level == level)
    if status:
        query = query.where(Alert.status == status)
    if date_from is not None:
        query = query.where(Alert.opened_at >= date_from)
    if date_to is not None:
        query = query.where(Alert.opened_at <= date_to)
    rows = db.execute(query.order_by(desc(Alert.opened_at), desc(Alert.id))).scalars().all()
    return paginated([alert_payload(db, row) for row in rows], page=page, page_size=page_size)


@router.get("/{patient_id}/day-profile", summary="Day profile today vs yesterday vs baseline")
def patient_day_profile(
    patient_id: str,
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Profilo circadiano pronto per i grafici "oggi vs giornata tipo" (D25).

    Aggrega le finestre storiche del paziente per fascia oraria in tre serie:
    oggi, ieri e giornata tipo (media storica escludendo oggi e ieri). Le fasce
    sono calcolate nel fuso locale del paziente.
    """
    get_patient_or_404(db, patient_id)
    return day_profile_payload(db, patient_id)


@router.get("/{patient_id}/tasks", summary="Patient tasks")
def patient_tasks(
    patient_id: str,
    status: str | None = Query(default=None),
    task_type: str | None = Query(default=None),
    due_before: datetime | None = Query(default=None),
    due_after: datetime | None = Query(default=None),
    priority: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce i task del paziente ordinati dai piu' recenti."""
    get_patient_or_404(db, patient_id)
    query = select(Task).where(Task.patient_id == patient_id)
    if status:
        query = query.where(Task.status == status)
    if task_type:
        query = query.where(Task.task_type == task_type)
    if due_before is not None:
        query = query.where(Task.due_at <= due_before)
    if due_after is not None:
        query = query.where(Task.due_at >= due_after)
    rows = db.execute(query.order_by(desc(Task.created_at), desc(Task.id))).scalars().all()
    items = [task_payload(row, db) for row in rows]
    if not status:
        items = [item for item in items if item.get("status") != "dismissed"]
    if priority:
        items = [item for item in items if item.get("priority") == priority]
    return paginated(items, page=page, page_size=page_size)


@router.post("/{patient_id}/tasks", summary="Create patient task")
def create_patient_task(
    patient_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Crea un task operativo per il paziente."""
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can create patient tasks.")
    get_patient_or_404(db, patient_id)
    title = str(payload.get("title") or "").strip()
    task_type = str(payload.get("type") or payload.get("task_type") or "").strip().lower()
    if not title or not task_type:
        raise HTTPException(status_code=422, detail="Task title and type are required.")
    normalized_task_payload = validate_task_creation_payload(task_type, payload, current_user.role)
    task = Task(
        patient_id=patient_id,
        created_by_user_id=current_user.id,
        task_type=task_type,
        status=str(payload.get("status") or "created"),
        title=title,
        instructions=payload.get("instructions"),
        due_at=parse_datetime(payload.get("due_at") or payload.get("expires_at")),
        payload=normalized_task_payload,
    )
    db.add(task)
    db.flush()
    write_audit(
        db,
        actor=current_user,
        action="task.created",
        patient_id=patient_id,
        target_type="task",
        details={"type": task_type, "title": title},
    )
    notify_task_created(db, task)
    db.commit()
    db.refresh(task)
    event_bus.publish(
        InternalEvent(
            event_type="task_created",
            patient_id=patient_id,
            timestamp=task.created_at,
            payload={"task_id": f"task-{task.id}", "type": task.task_type},
        )
    )
    return task_payload(task, db)


@router.post("/{patient_id}/caregiver-messages", summary="Send caregiver message")
def create_caregiver_message(
    patient_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Invia una comunicazione operativa ai caregiver associati al paziente."""
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can send caregiver messages.")
    get_patient_or_404(db, patient_id)
    title = str(payload.get("title") or "Messaggio dal medico").strip()[:120]
    body = str(payload.get("body") or payload.get("message") or "").strip()
    if not body:
        raise HTTPException(status_code=422, detail="Message body is required.")
    priority = str(payload.get("priority") or "normal").strip().lower()
    if priority not in {"normal", "high", "urgent"}:
        priority = "normal"
    notification = notify_caregiver_message(
        db,
        patient_id=patient_id,
        title=title or "Messaggio dal medico",
        body=body[:1000],
        payload={
            "priority": priority,
            "message": {
                "title": title or "Messaggio dal medico",
                "body": body[:1000],
                "priority": priority,
            },
        },
    )
    write_audit(
        db,
        actor=current_user,
        action="caregiver_message.created",
        patient_id=patient_id,
        target_type="notification",
        target_id=f"notification-{notification.id}",
        details={"priority": priority, "title": title or "Messaggio dal medico"},
    )
    db.commit()
    db.refresh(notification)
    event_bus.publish(
        InternalEvent(
            event_type="caregiver_message_created",
            patient_id=patient_id,
            timestamp=notification.created_at,
            payload={"notification_id": f"notification-{notification.id}", "priority": priority},
        )
    )
    return {
        "notification_id": f"notification-{notification.id}",
        "patient_id": notification.patient_id,
        "title": notification.title,
        "body": notification.body,
        "status": notification.status,
        "priority": priority,
        "created_at": utc_iso(notification.created_at),
    }


@router.get("/{patient_id}/system-status", summary="Current technical status")
def patient_system_status(
    patient_id: str,
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce lo stato tecnico aggregato di Edge, Watch, BLE e Google Health."""
    patient = get_patient_or_404(db, patient_id)
    settings = get_settings()
    now = datetime.now(timezone.utc)
    current = current_payload(db, patient)
    latest_window = latest_feature_window(db, patient.patient_id)
    latest_cycle = latest_edge_cycle(db, patient.patient_id)
    cycle_status = latest_edge_cycle_status_payload(latest_cycle)
    watch_status = sensor_status(db, patient.patient_id, "watch")
    ble_status = sensor_status(db, patient.patient_id, "ble")
    app_status = latest_patient_app_status(db, patient.patient_id)
    edge_payload = system_edge_payload(
        current_edge=current["edge"],
        latest_cycle=latest_cycle,
        cycle_status=cycle_status,
        now=now,
        stale_minutes=settings.edge_stale_minutes,
    )
    watch_last_seen = watch_status.last_seen_at if watch_status else (latest_window.window_end if latest_window else None)
    ble_last_seen = ble_status.last_seen_at if ble_status else (latest_window.window_end if latest_window else None)
    google_health_last_seen = latest_window.window_end if latest_window else None
    return {
        "patient_id": patient.patient_id,
        "updated_at": current["last_update"],
        "mode": current["signal_type"],
        "thresholds_minutes": {
            "edge_stale": settings.edge_stale_minutes,
            "watch_stale": settings.watch_stale_minutes,
            "ble_stale": settings.ble_stale_minutes,
            "google_health_stale": settings.google_health_stale_minutes,
            "patient_app_stale": settings.patient_app_stale_minutes,
        },
        "edge": edge_payload,
        "ai": {
            "fusion_mode": cycle_status.get("fusion_mode"),
            "inference": cycle_status.get("inference"),
            "personal_model_available": cycle_status.get("personal_model_exists"),
            "baseline": baseline_status_from_cycle(cycle_status),
            "confidence": confidence_from_payload(latest_decision(db, patient.patient_id)),
            "trend": compute_patient_trend(db, patient.patient_id),
            "drift": drift_from_db(db, patient.patient_id),
        },
        "sensors": {
            "watch": {
                "status": technical_status(
                    configured_status=watch_status.status if watch_status else None,
                    last_seen_at=watch_last_seen,
                    now=now,
                    stale_minutes=settings.watch_stale_minutes,
                    active_if_present=current["watch"]["present"],
                    missing_status="missing",
                ),
                "present": current["watch"]["present"],
                "battery_pct": current["watch"]["battery_pct"],
                "last_seen_at": utc_iso(watch_last_seen),
            },
            "ble": {
                "status": technical_status(
                    configured_status=ble_status.status if ble_status else None,
                    last_seen_at=ble_last_seen,
                    now=now,
                    stale_minutes=settings.ble_stale_minutes,
                    active_if_present=bool(current["current_room"]),
                    missing_status="stale",
                ),
                "current_room": current["current_room"],
                "last_seen_at": utc_iso(ble_last_seen),
                "samples_collected": cycle_status.get("ble_samples_collected"),
            },
            "google_health": {
                "status": google_health_status(
                    cycle_status,
                    current,
                    last_seen_at=google_health_last_seen,
                    now=now,
                    stale_minutes=settings.google_health_stale_minutes,
                ),
                "enabled": cycle_status.get("google_health_enabled"),
                "samples_logged": cycle_status.get("google_health_samples_logged"),
                "available_feature_count": cycle_status.get("google_health_available_feature_count"),
                "available_features": first_present(
                    cycle_status.get("google_health_available_features"),
                    current["watch"]["available_features"],
                ),
                "last_window_at": utc_iso(latest_window.window_end) if latest_window else None,
                "oauth_error": public_error_message(
                    first_present(
                        cycle_status.get("google_health_oauth_error"),
                        cycle_status.get("google_health_error"),
                        cycle_status.get("oauth_error"),
                    )
                ),
            },
            "patient_app": patient_app_status_payload(
                app_status,
                now=now,
                stale_minutes=settings.patient_app_stale_minutes,
            ),
        },
    }


@router.get("/status", summary="Patients module status")
def patients_status() -> dict[str, str]:
    """Espone lo stato del modulo pazienti."""
    return {"status": "implemented", "module": "patients"}


def get_patient_or_404(db: Session, patient_id: str) -> Patient:
    """Carica un paziente attivo o produce un 404 stabile."""
    patient = db.get(Patient, patient_id)
    if patient is None or not patient.is_active:
        raise HTTPException(status_code=404, detail=f"Patient not found: {patient_id}")
    return patient


def patient_summary(db: Session, patient: Patient) -> dict[str, Any]:
    """Costruisce la riga sintetica mostrata nella lista pazienti."""
    current = current_payload(db, patient)
    open_alert = db.execute(
        select(Alert.id)
        .where(Alert.patient_id == patient.patient_id, Alert.status != "resolved")
        .limit(1)
    ).first()
    return {
        "patient_id": patient.patient_id,
        "display_name": patient.display_name,
        "last_update": current["last_update"],
        "level": current["level"],
        "signal_type": current["signal_type"],
        "current_room": current["current_room"],
        "edge_online": current["edge"]["online"],
        "watch_present": current["watch"]["present"],
        "has_open_alerts": open_alert is not None,
    }


def current_payload(db: Session, patient: Patient) -> dict[str, Any]:
    """Combina gli ultimi record DB in un payload corrente per la dashboard."""
    decision = latest_decision(db, patient.patient_id)
    window = latest_feature_window(db, patient.patient_id)
    edge = latest_edge_device(db, patient.patient_id)
    cycle = latest_edge_cycle(db, patient.patient_id)
    features = window.features if window else {}
    level = decision.level if decision else "green"
    last_update = decision.timestamp if decision else (window.window_end if window else None)
    if last_update is None:
        last_update = edge.last_seen_at if edge else datetime.now(timezone.utc)
    available_features = [key for key, value in features.items() if value is not None]
    current_room = infer_current_room(features)
    settings = get_settings()
    edge_last_seen = cycle.timestamp if cycle else (edge.last_seen_at if edge else None)
    edge_online = is_recent(edge_last_seen, now=datetime.now(timezone.utc), stale_minutes=settings.edge_stale_minutes)
    watch_present = wearable_is_present(features)
    quality_status = quality_status_from_decision(decision)
    return {
        "patient_id": patient.patient_id,
        "edge_id": edge.edge_id if edge else None,
        "last_update": utc_iso(last_update),
        "level": level,
        "signal_type": signal_type(level=level, edge_online=edge_online, features=features),
        "should_publish": bool(decision.should_publish) if decision else False,
        "anomaly_score": decision.anomaly_score if decision else 0.0,
        "ai_explanation": decision_ai_explanation(db, decision, features) if decision else empty_ai_explanation(features),
        "trend": compute_patient_trend(db, patient.patient_id),
        "drift": drift_from_db(db, patient.patient_id),
        "confidence": confidence_from_payload(decision),
        "ai_confidence": confidence_from_payload(decision),
        "feature_importance": feature_importance_from_payload(decision),
        "current_room": current_room,
        "watch": {
            "present": watch_present,
            "battery_pct": features.get("wearable_battery_pct"),
            "available_features": available_features,
        },
        "edge": {
            "online": edge_online,
            "quality_status": quality_status,
            "mqtt_queue_depth": mqtt_queue_depth(decision),
            "last_seen_at": utc_iso(edge_last_seen),
        },
    }


def wearable_is_present(features: dict[str, Any]) -> bool:
    """Interpreta il flag wearable e, se assente, lo deduce dalle misure ricevute."""
    explicit = features.get("wearable_present") if features else None
    if isinstance(explicit, bool):
        return explicit
    if isinstance(explicit, (int, float)):
        return explicit != 0
    if isinstance(explicit, str):
        normalized = explicit.strip().lower()
        if normalized in {"true", "1", "yes", "si", "present", "available"}:
            return True
        if normalized in {"false", "0", "no", "absent", "missing", "unavailable"}:
            return False
    wearable_features = (
        "heart_rate_mean",
        "heart_rate_std",
        "resting_heart_rate",
        "hrv_rmssd",
        "spo2_mean",
        "steps",
        "sleep_minutes",
        "wearable_battery_pct",
    )
    return any(features.get(key) is not None for key in wearable_features)


def feature_windows_between(db: Session, patient_id: str, start: datetime, end: datetime) -> list[FeatureWindow]:
    """Carica finestre feature ordinate in un intervallo temporale chiuso a destra."""
    return list(
        db.execute(
            select(FeatureWindow)
            .where(
                FeatureWindow.patient_id == patient_id,
                FeatureWindow.window_end > start,
                FeatureWindow.window_end <= end,
            )
            .order_by(FeatureWindow.window_end, FeatureWindow.id)
        ).scalars()
    )


def decisions_between(db: Session, patient_id: str, start: datetime, end: datetime) -> list[Decision]:
    """Carica decisioni AI ordinate in un intervallo temporale chiuso a destra."""
    return list(
        db.execute(
            select(Decision)
            .where(
                Decision.patient_id == patient_id,
                Decision.timestamp > start,
                Decision.timestamp <= end,
            )
            .order_by(Decision.timestamp, Decision.id)
        ).scalars()
    )


def ai_summary(decisions: list[Decision], previous_decisions: list[Decision]) -> dict[str, Any]:
    """Calcola statistiche AI essenziali per il riepilogo 24 ore."""
    scores = [float(decision.anomaly_score) for decision in decisions if is_number(decision.anomaly_score)]
    previous_scores = [float(decision.anomaly_score) for decision in previous_decisions if is_number(decision.anomaly_score)]
    last_decision = decisions[-1] if decisions else None
    current_average = average(scores)
    previous_average = average(previous_scores)
    return {
        "average_score": round(current_average, 3) if current_average is not None else None,
        "max_score": round(max(scores), 3) if scores else None,
        "last_score": round(float(last_decision.anomaly_score), 3) if last_decision and is_number(last_decision.anomaly_score) else None,
        "last_level": last_decision.level if last_decision else None,
        "last_decision_at": utc_iso(last_decision.timestamp) if last_decision else None,
        "previous_day_average_score": round(previous_average, 3) if previous_average is not None else None,
        "score_delta_vs_previous_day": round(current_average - previous_average, 3) if current_average is not None and previous_average is not None else None,
    }


def spatial_summary(windows: list[FeatureWindow]) -> dict[str, Any]:
    """Aggrega permanenza stanze e cambi stanza nelle ultime 24 ore."""
    room_minutes = {
        "bedroom": sum_feature_values(windows, "bedroom_minutes"),
        "kitchen": sum_feature_values(windows, "kitchen_minutes"),
        "bathroom": sum_feature_values(windows, "bathroom_minutes"),
        "living_room": sum_feature_values(windows, "living_room_minutes"),
    }
    known_rooms = {room: minutes for room, minutes in room_minutes.items() if minutes is not None}
    prevalent_room = None
    if known_rooms:
        prevalent_room, prevalent_minutes = max(known_rooms.items(), key=lambda item: item[1])
        if prevalent_minutes <= 0:
            prevalent_room = None
    return {
        "room_minutes": {room: round(value, 3) if value is not None else None for room, value in room_minutes.items()},
        "prevalent_room": prevalent_room,
        "room_changes": round(sum_feature_values(windows, "room_changes") or 0, 3) if windows else None,
        "night_room_changes": round(sum_feature_values(windows, "night_room_changes") or 0, 3) if windows else None,
        "longest_single_room_minutes": max_feature_value(windows, "longest_single_room_minutes"),
    }


def spatial_transition_summary(windows: list[FeatureWindow]) -> dict[str, Any]:
    """Aggrega cambi stanza e, se disponibili, transizioni stanza-stanza."""
    matrix: dict[str, dict[str, int]] = {}
    events: list[dict[str, Any]] = []
    for window in windows:
        transitions = window.features.get("room_transitions")
        if isinstance(transitions, list):
            for item in transitions:
                if not isinstance(item, dict):
                    continue
                from_room = str(item.get("from") or item.get("from_room") or "unknown")
                to_room = str(item.get("to") or item.get("to_room") or "unknown")
                count = int(item.get("count") or 1)
                matrix.setdefault(from_room, {})
                matrix[from_room][to_room] = matrix[from_room].get(to_room, 0) + count
                events.append(
                    {
                        "timestamp": utc_iso(window.window_end),
                        "from_room": from_room,
                        "to_room": to_room,
                        "count": count,
                    }
                )
    return {
        "total": round(sum_feature_values(windows, "room_changes") or 0, 3) if windows else None,
        "matrix": matrix,
        "events": events,
        "source": "room_transitions" if matrix else "room_changes",
    }


def spatial_night_summary(windows: list[FeatureWindow]) -> dict[str, Any]:
    """Evidenzia movimenti notturni senza presentarli come diagnosi automatica."""
    events: list[dict[str, Any]] = []
    for window in windows:
        night_changes = numeric_or_none(window.features.get("night_room_changes"))
        room_changes = numeric_or_none(window.features.get("room_changes"))
        window_end_utc = normalize_aware(window.window_end).astimezone(timezone.utc)
        is_night = window_end_utc.hour >= 22 or window_end_utc.hour < 6
        if night_changes is None and not is_night:
            continue
        event_count = night_changes if night_changes is not None else room_changes
        if event_count is None or event_count <= 0:
            continue
        events.append(
            {
                "window_start": utc_iso(window.window_start),
                "window_end": utc_iso(window.window_end),
                "changes": round(event_count, 3),
                "dominant_room": dominant_room_from_window(window),
                "summary": "Movimento notturno da verificare",
            }
        )
    return {
        "room_changes": round(sum_feature_values(windows, "night_room_changes") or 0, 3) if windows else None,
        "event_count": len(events),
        "events": events,
    }


def spatial_reference_summary(cycle_status: dict[str, Any], previous_windows: list[FeatureWindow]) -> dict[str, Any]:
    """Prepara il riferimento per il confronto: baseline Edge se disponibile, altrimenti periodo precedente."""
    baseline_spatial = cycle_status.get("baseline_spatial")
    if isinstance(baseline_spatial, dict):
        return {
            "source": "personal_baseline",
            "reason": None,
            "summary": {
                "room_minutes": baseline_spatial.get("room_minutes") if isinstance(baseline_spatial.get("room_minutes"), dict) else {},
                "room_changes": numeric_or_none(baseline_spatial.get("room_changes")),
                "night_room_changes": numeric_or_none(baseline_spatial.get("night_room_changes")),
                "longest_single_room_minutes": numeric_or_none(baseline_spatial.get("longest_single_room_minutes")),
            },
        }
    if previous_windows:
        return {"source": "previous_period", "reason": "personal_baseline_not_available", "summary": spatial_summary(previous_windows)}
    return {"source": "none", "reason": "reference_not_available", "summary": {}}


def spatial_baseline_comparison(current: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    """Calcola differenze assolute e percentuali tra periodo corrente e riferimento."""
    reference_room_minutes = reference.get("room_minutes") if isinstance(reference.get("room_minutes"), dict) else {}
    current_room_minutes = current.get("room_minutes") if isinstance(current.get("room_minutes"), dict) else {}
    return {
        "room_minutes": {
            room: metric_delta(current_room_minutes.get(room), reference_room_minutes.get(room))
            for room in sorted(set(current_room_minutes) | set(reference_room_minutes))
        },
        "room_changes": metric_delta(current.get("room_changes"), reference.get("room_changes")),
        "night_room_changes": metric_delta(current.get("night_room_changes"), reference.get("night_room_changes")),
        "longest_single_room_minutes": metric_delta(current.get("longest_single_room_minutes"), reference.get("longest_single_room_minutes")),
    }


def spatial_ble_quality(
    db: Session,
    patient_id: str,
    windows: list[FeatureWindow],
    start: datetime,
    end: datetime,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Stima completezza BLE e finestre mancanti nel periodo richiesto."""
    ble_features = ["room_changes", "night_room_changes", "bedroom_minutes", "kitchen_minutes", "bathroom_minutes", "living_room_minutes", "longest_single_room_minutes"]
    available = count_windows_with_any_feature(windows, ble_features)
    expected = expected_window_count(start, end)
    sensor = sensor_status(db, patient_id, "ble")
    ratio = (available / expected) if expected else 0.0
    return {
        "level": reliability_level(ratio),
        "ratio": round(ratio, 3),
        "available_windows": available,
        "total_windows": len(windows),
        "expected_windows": expected,
        "missing_windows_estimate": max(expected - available, 0),
        "last_seen_at": utc_iso(sensor.last_seen_at) if sensor else None,
        "sensor_status": status_from_last_seen(
            sensor.last_seen_at if sensor else None,
            now=now,
            stale_minutes=get_settings().ble_stale_minutes,
            missing_status="missing",
        ),
        "features_checked": ble_features,
    }


def metric_delta(current: Any, reference: Any) -> dict[str, float | None]:
    """Restituisce differenza assoluta e percentuale per una metrica numerica."""
    current_value = numeric_or_none(current)
    reference_value = numeric_or_none(reference)
    absolute = current_value - reference_value if current_value is not None and reference_value is not None else None
    percent = None
    if absolute is not None and reference_value not in {None, 0}:
        percent = (absolute / reference_value) * 100
    return {
        "current": round(current_value, 3) if current_value is not None else None,
        "reference": round(reference_value, 3) if reference_value is not None else None,
        "absolute": round(absolute, 3) if absolute is not None else None,
        "percent": round(percent, 3) if percent is not None else None,
    }


def dominant_room_from_window(window: FeatureWindow) -> str | None:
    """Trova la stanza con piu' minuti nella singola finestra."""
    room_values = {
        "bedroom": numeric_or_none(window.features.get("bedroom_minutes")),
        "kitchen": numeric_or_none(window.features.get("kitchen_minutes")),
        "bathroom": numeric_or_none(window.features.get("bathroom_minutes")),
        "living_room": numeric_or_none(window.features.get("living_room_minutes")),
    }
    known = {room: value for room, value in room_values.items() if value is not None}
    if not known:
        return None
    room, minutes = max(known.items(), key=lambda item: item[1])
    return room if minutes > 0 else None


ROOM_MINUTE_FEATURES = ("bedroom_minutes", "kitchen_minutes", "bathroom_minutes", "living_room_minutes")


def dominant_room_across(windows: list[FeatureWindow]) -> str | None:
    """Stanza prevalente in un gruppo di finestre, in base ai minuti totali."""
    totals: dict[str, float] = {}
    for window in windows:
        for room in ROOM_MINUTE_FEATURES:
            value = numeric_or_none(window.features.get(room))
            if value is None:
                continue
            totals[room] = totals.get(room, 0.0) + value
    if not totals:
        return None
    room, minutes = max(totals.items(), key=lambda item: item[1])
    return room.removesuffix("_minutes") if minutes > 0 else None


from zoneinfo import ZoneInfo  # noqa: E402

PATIENT_TIMEZONE = ZoneInfo("Europe/Rome")
DAY_PROFILE_BANDS = ["00-06", "06-10", "10-14", "14-18", "18-22", "22-24"]
DAY_PROFILE_FEATURES = [
    "heart_rate_mean",
    "steps",
    "sedentary_minutes",
    "room_changes",
    "sleep_minutes",
]
DAY_PROFILE_STALE_DAYS = 90


def drift_from_db(db: Session, patient_id: str) -> dict[str, Any]:
    """Legge lo stato di drift direttamente dalla riga di persistenza (sola lettura)."""
    state = (
        db.execute(select(PatientModelDrift).where(PatientModelDrift.patient_id == patient_id))
        .scalars()
        .first()
    )
    if state is None:
        return {"status": "stable", "requires_approval": False}
    return {
        "status": state.status,
        "requires_approval": state.requires_approval,
        "detected_at": state.detected_at.isoformat() if state.detected_at else None,
        "drift_count": state.drift_count,
        "retrained_at": state.retrained_at.isoformat() if state.retrained_at else None,
        "approved_at": state.approved_at.isoformat() if state.approved_at else None,
        "baseline_available": state.baseline_available,
        "note": state.note,
    }
TREND_MIN_POINTS = 4
TREND_SLOPE_ALERT_THRESHOLD = 3.0
TREND_SLOPE_DIRECTION_THRESHOLDS = {"in_aumento": 2.0, "in_diminuzione": -2.0}
TREND_FEATURES = ["steps", "sedentary_minutes", "sleep_minutes", "bedroom_minutes", "heart_rate_mean"]


def _linear_slope(points: list[tuple[float, float]]) -> tuple[float | None, int]:
    """Regressione lineare per minimi quadrati: restituisce (slope, n_punti)."""
    n = len(points)
    if n < 2:
        return None, n
    sum_x = sum(x for x, _ in points)
    sum_y = sum(y for _, y in points)
    sum_xx = sum(x * x for x, _ in points)
    sum_xy = sum(x * y for x, y in points)
    denominator = n * sum_xx - sum_x * sum_x
    if abs(denominator) < 1e-9:
        return 0.0, n
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    return slope, n


def _trend_direction(slope_per_day: float | None) -> str:
    if slope_per_day is None or not math.isfinite(slope_per_day):
        return "unknown"
    if slope_per_day > TREND_SLOPE_DIRECTION_THRESHOLDS["in_aumento"]:
        return "in_aumento"
    if slope_per_day < TREND_SLOPE_DIRECTION_THRESHOLDS["in_diminuzione"]:
        return "in_diminuzione"
    return "stabile"


def _trend_dict(slope_per_day: float | None, n_points: int, window_days: int) -> dict[str, Any]:
    return {
        "score_slope_per_day": (
            round(slope_per_day, 2) if slope_per_day is not None and math.isfinite(slope_per_day) else None
        ),
        "direction": _trend_direction(slope_per_day),
        "window_days": window_days if n_points >= TREND_MIN_POINTS else None,
        "n_points": n_points,
    }


def _feature_trend_dict(slope_per_day: float | None, n_points: int, window_days: int) -> dict[str, Any]:
    return {
        "slope_per_day": (
            round(slope_per_day, 3) if slope_per_day is not None and math.isfinite(slope_per_day) else None
        ),
        "direction": _trend_direction(slope_per_day),
        "window_days": window_days if n_points >= TREND_MIN_POINTS else None,
        "n_points": n_points,
    }


def compute_feature_trends(
    db: Session,
    patient_id: str,
    *,
    reference: datetime | None = None,
    window_days: int = 14,
) -> dict[str, Any]:
    """Calcola il trend lineare delle principali submetriche del paziente."""
    ref = normalize_aware(reference or datetime.now(timezone.utc))
    since = ref - timedelta(days=window_days + 1)
    windows = (
        db.execute(
            select(FeatureWindow)
            .where(
                FeatureWindow.patient_id == patient_id,
                FeatureWindow.window_end >= since,
            )
            .order_by(FeatureWindow.window_end, FeatureWindow.id)
        )
        .scalars()
        .all()
    )
    buckets: dict[str, list[tuple[float, float]]] = {feature: [] for feature in TREND_FEATURES}
    for row in windows:
        days_ago = (ref - normalize_aware(row.window_start)).total_seconds() / 86400.0
        if days_ago < 0:
            continue
        for feature in TREND_FEATURES:
            value = row.features.get(feature)
            if not is_number(value):
                continue
            buckets[feature].append((days_ago, float(value)))

    results: dict[str, Any] = {}
    for feature, points in buckets.items():
        if not points:
            results[feature] = _feature_trend_dict(None, 0, window_days)
            continue
        ordered = sorted(points, key=lambda p: p[0], reverse=True)
        x_offset = ordered[0][0]
        ascending = [(x_offset - x, y) for x, y in ordered if (x_offset - x) <= window_days]
        slope, n = _linear_slope(ascending)
        results[feature] = _feature_trend_dict(slope, n, window_days)
    return results


def compute_patient_trend(
    db: Session,
    patient_id: str,
    *,
    reference: datetime | None = None,
) -> dict[str, Any]:
    """Calcola il trend dello score AI per le ultime 14 giorni.

    Restituisce il dizionario compatibile con TrendDriftPanel (D26): migliore
    finestra disponibile + slopes per 3, 7, 14 giorni.
    """
    ref = normalize_aware(reference or datetime.now(timezone.utc))
    since = ref - timedelta(days=15)
    decisions = (
        db.execute(
            select(Decision)
            .where(
                Decision.patient_id == patient_id,
                Decision.timestamp >= since,
                Decision.anomaly_score.isnot(None),
            )
            .order_by(Decision.timestamp)
        )
        .scalars()
        .all()
    )
    valid = [(d.timestamp, float(d.anomaly_score)) for d in decisions if is_number(d.anomaly_score)]
    if not valid:
        return _trend_dict(None, 0, 0)

    base_points: list[tuple[float, float]] = []
    for ts, value in valid:
        ts_utc = normalize_aware(ts)
        days_ago = (ref - ts_utc).total_seconds() / 86400.0
        if days_ago >= 0:
            base_points.append((days_ago, value))

    if not base_points:
        return _trend_dict(None, 0, 0)

    all_sorted = sorted(base_points, key=lambda p: p[0], reverse=True)
    x_offset = all_sorted[0][0] if all_sorted else 0.0
    ascending = [(x_offset - x, y) for x, y in all_sorted]
    results: dict[str, dict[str, Any]] = {}
    best: dict[str, Any] | None = None

    for window in (3, 7, 14):
        cutoff = float(window)
        filtered = [(x, y) for x, y in ascending if (x_offset - x) <= cutoff]
        slope, n = _linear_slope(filtered)
        trend = _trend_dict(slope, n, window)
        results[str(window)] = trend
        if best is None or n > best.get("_n", 0):
            best = {**trend, "_n": n}

    best_trend = {k: v for k, v in (best or _trend_dict(None, 0, 0)).items() if k != "_n"}
    return {
        "best": best_trend,
        "windows": results,
        "features": compute_feature_trends(db, patient_id, reference=reference),
    }


def trend_should_trigger_alert(trend: dict[str, Any]) -> bool:
    """Verifica se il trend segnala un peggioramento che merita un alert."""
    best = trend.get("best", {})
    slope = best.get("score_slope_per_day")
    direction = best.get("direction", "unknown")
    window = best.get("window_days")
    if direction not in {"in_aumento"}:
        return False
    if window is None or window < 5:
        return False
    return slope is not None and slope >= TREND_SLOPE_ALERT_THRESHOLD


def day_band_for_local_hour(hour: int) -> str:
    """Mappa un'ora locale alla fascia oraria del profilo circadiano."""
    if hour < 6:
        return "00-06"
    if hour < 10:
        return "06-10"
    if hour < 14:
        return "10-14"
    if hour < 18:
        return "14-18"
    if hour < 22:
        return "18-22"
    return "22-24"


def day_profile_payload(
    db: Session,
    patient_id: str,
    *,
    reference: datetime | None = None,
) -> dict[str, Any]:
    """Costruisce il payload del profilo circadiano per oggi/ieri/baseline."""
    now = normalize_aware(reference or datetime.now(timezone.utc))
    local_now = now.astimezone(PATIENT_TIMEZONE)
    today_date = local_now.strftime("%Y-%m-%d")
    yesterday_date = (local_now - timedelta(days=1)).strftime("%Y-%m-%d")

    since = now - timedelta(days=DAY_PROFILE_STALE_DAYS)
    windows = (
        db.execute(
            select(FeatureWindow)
            .where(
                FeatureWindow.patient_id == patient_id,
                FeatureWindow.window_end >= since,
            )
            .order_by(FeatureWindow.window_end, FeatureWindow.id)
        )
        .scalars()
        .all()
    )
    decisions = (
        db.execute(
            select(Decision)
            .where(
                Decision.patient_id == patient_id,
                Decision.window_start >= since,
            )
            .order_by(Decision.window_start, Decision.id)
        )
        .scalars()
        .all()
    )

    def local_partition(value: datetime) -> tuple[str, str]:
        local = normalize_aware(value).astimezone(PATIENT_TIMEZONE)
        return local.strftime("%Y-%m-%d"), day_band_for_local_hour(local.hour)

    def date_group(local_date: str) -> str:
        if local_date == today_date:
            return "today"
        if local_date == yesterday_date:
            return "yesterday"
        return "baseline"

    groups = ("today", "yesterday", "baseline")
    band_windows: dict[str, dict[str, list[FeatureWindow]]] = {
        group: {band: [] for band in DAY_PROFILE_BANDS} for group in groups
    }
    band_scores: dict[str, dict[str, list[float]]] = {
        group: {band: [] for band in DAY_PROFILE_BANDS} for group in groups
    }

    for window in windows:
        local_date, band = local_partition(window.window_start)
        band_windows[date_group(local_date)][band].append(window)

    for decision in decisions:
        if not is_number(decision.anomaly_score):
            continue
        local_date, band = local_partition(decision.window_start)
        band_scores[date_group(local_date)][band].append(float(decision.anomaly_score))

    def band_row(group: str, band: str) -> dict[str, Any]:
        row: dict[str, Any] = {
            "band": band,
            "ai": average(band_scores[group][band]),
            "dominant_room": dominant_room_across(band_windows[group][band]),
        }
        for feature in DAY_PROFILE_FEATURES:
            row[feature] = average_feature_values(band_windows[group][band], feature)
        return row

    today_rows = [band_row("today", band) for band in DAY_PROFILE_BANDS]
    yesterday_rows = [band_row("yesterday", band) for band in DAY_PROFILE_BANDS]
    baseline_rows = [band_row("baseline", band) for band in DAY_PROFILE_BANDS]

    baseline_available = any(
        band_windows["baseline"][band] or band_scores["baseline"][band] for band in DAY_PROFILE_BANDS
    )

    return {
        "today": today_rows,
        "yesterday": yesterday_rows,
        "baseline_day": baseline_rows,
        "bands": DAY_PROFILE_BANDS,
        "baseline_available": baseline_available,
    }


def expected_window_count(start: datetime, end: datetime, window_minutes: int = 4) -> int:
    """Calcola quante finestre Edge ci si aspetta nel periodo."""
    seconds = max((normalize_aware(end) - normalize_aware(start)).total_seconds(), 0)
    return int(seconds // (window_minutes * 60))


def numeric_or_none(value: Any) -> float | None:
    """Converte numeri JSON in float ignorando booleani e valori mancanti."""
    return float(value) if is_number(value) else None


def wearable_summary(windows: list[FeatureWindow]) -> dict[str, Any]:
    """Aggrega le principali metriche wearable senza trasformare dati assenti in zero."""
    return {
        "heart_rate": numeric_stats(windows, "heart_rate_mean"),
        "heart_rate_std": numeric_stats(windows, "heart_rate_std"),
        "spo2": numeric_stats(windows, "spo2_mean"),
        "steps": {
            "total": round(sum_feature_values(windows, "steps"), 3) if any_feature_value(windows, "steps") else None,
        },
        "sleep_minutes": numeric_stats(windows, "sleep_minutes"),
        "sedentary_minutes": {
            "total": round(sum_feature_values(windows, "sedentary_minutes"), 3) if any_feature_value(windows, "sedentary_minutes") else None,
            "average": round(average_feature_values(windows, "sedentary_minutes"), 3) if any_feature_value(windows, "sedentary_minutes") else None,
        },
        "hrv_rmssd": numeric_stats(windows, "hrv_rmssd"),
    }


def data_completeness_summary(
    db: Session,
    patient_id: str,
    windows: list[FeatureWindow],
    latest_cycle: EdgeCycle | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Calcola quanto sono utilizzabili i dati disponibili nel riepilogo."""
    total = len(windows)
    ble_features = ["room_changes", "bedroom_minutes", "kitchen_minutes", "bathroom_minutes", "living_room_minutes"]
    wearable_features = ["heart_rate_mean", "heart_rate_std", "spo2_mean", "steps", "sleep_minutes", "sedentary_minutes", "hrv_rmssd"]
    ble_count = count_windows_with_any_feature(windows, ble_features)
    wearable_count = count_windows_with_any_feature(windows, wearable_features)
    app_status = latest_patient_app_status(db, patient_id)
    cycle_payload = latest_edge_cycle_status_payload(latest_cycle)
    mqtt_payload = public_mqtt_payload(cycle_payload.get("mqtt_publish")) if cycle_payload else None
    return {
        "overall": completeness_payload(min(ble_count + wearable_count, total), total),
        "ble": completeness_payload(ble_count, total),
        "google_health": completeness_payload(wearable_count, total),
        "patient_app": {
            "status": patient_app_status_payload(app_status, now=now, stale_minutes=get_settings().patient_app_stale_minutes)["status"],
            "last_seen_at": utc_iso(app_status.last_seen_at) if app_status else None,
        },
        "mqtt": {
            "status": mqtt_payload.get("status") if mqtt_payload else None,
            "queue_depth": mqtt_payload.get("queue_depth") if mqtt_payload else None,
            "last_cycle_at": utc_iso(latest_cycle.timestamp) if latest_cycle else None,
        },
    }


def report_data_payload(db: Session, patient: Patient, current_user: CurrentUser, *, now: datetime, days: int) -> dict[str, Any]:
    """Compone i dati necessari a generare un report senza query multiple dal frontend."""
    summary = summary_24h_payload(db, patient, now=now)
    spatial = spatial_report_payload(db, patient.patient_id, now=now, days=days)
    decisions = recent_decisions(db, patient.patient_id, limit=8)
    alerts = recent_alerts(db, patient.patient_id, limit=8)
    tasks = recent_tasks(db, patient.patient_id, limit=8)
    timeline = report_timeline(db, patient.patient_id, now=now, days=days)
    patient_trend = compute_patient_trend(db, patient.patient_id)
    return {
        "schema_version": 1,
        "report_type": "patient_triage_summary",
        "generated_at": utc_iso(now),
        "generated_by": {
            "user_id": f"user-{current_user.id}",
            "role": current_user.role,
            "display_name": current_user.display_name,
        },
        "patient": {
            "patient_id": patient.patient_id,
            "display_name": patient.display_name,
        },
        "range": {
            "start": utc_iso(now - timedelta(days=days)),
            "end": utc_iso(now),
            "days": days,
        },
        "disclaimer": "Report di supporto al triage: la valutazione finale resta al medico.",
        "sections": {
            "current": current_payload(db, patient),
            "summary_24h": summary,
            "spatial_summary": spatial,
            "recent_decisions": [decision_payload(row, db, patient_trend=patient_trend) for row in decisions],
            "recent_alerts": [alert_payload(db, row) for row in alerts],
            "recent_tasks": [task_payload(row, db) for row in tasks],
            "timeline": timeline,
            "medical_notes": report_medical_notes(db, alerts, tasks),
        },
        "privacy": {
            "excluded": ["password_hash", "refresh_token", "access_token", "fcm_token", "google_oauth_token", "client_secret"],
            "contains_raw_sensor_payloads": False,
        },
    }


def summary_24h_payload(db: Session, patient: Patient, *, now: datetime) -> dict[str, Any]:
    """Riusa la logica del riepilogo 24 ore in forma interna al report."""
    period_start = now - timedelta(hours=24)
    previous_start = period_start - timedelta(hours=24)
    windows = feature_windows_between(db, patient.patient_id, period_start, now)
    previous_windows = feature_windows_between(db, patient.patient_id, previous_start, period_start)
    decisions = decisions_between(db, patient.patient_id, period_start, now)
    previous_decisions = decisions_between(db, patient.patient_id, previous_start, period_start)
    latest_cycle = latest_edge_cycle(db, patient.patient_id)
    baseline = baseline_status_from_cycle(latest_edge_cycle_status_payload(latest_cycle))
    return {
        "range": {"start": utc_iso(period_start), "end": utc_iso(now), "hours": 24},
        "counts": {"windows": len(windows), "decisions": len(decisions)},
        "ai": ai_summary(decisions, previous_decisions),
        "spatial": spatial_summary(windows),
        "wearable": wearable_summary(windows),
        "data_completeness": data_completeness_summary(db, patient.patient_id, windows, latest_cycle, now=now),
        "baseline": {
            "available": bool(baseline.get("trained") or baseline.get("status") in {"trained", "ready", "completed"}),
            "status": baseline.get("status"),
            "reason": baseline.get("reason") or ("baseline_not_ready" if not baseline.get("trained") else None),
        },
    }


def spatial_report_payload(db: Session, patient_id: str, *, now: datetime, days: int) -> dict[str, Any]:
    """Produce la stessa sintesi spaziale D17 in forma interna al report."""
    period_end = now
    period_start = now - timedelta(days=days)
    previous_start = period_start - (period_end - period_start)
    windows = feature_windows_between(db, patient_id, period_start, period_end)
    previous_windows = feature_windows_between(db, patient_id, previous_start, period_start)
    latest_cycle = latest_edge_cycle(db, patient_id)
    cycle_status = latest_edge_cycle_status_payload(latest_cycle)
    baseline = baseline_status_from_cycle(cycle_status)
    current = spatial_summary(windows)
    reference = spatial_reference_summary(cycle_status, previous_windows)
    return {
        "range": {"start": utc_iso(period_start), "end": utc_iso(period_end), "days": days},
        "counts": {"windows": len(windows), "reference_windows": len(previous_windows)},
        "room_minutes": current["room_minutes"],
        "prevalent_room": current["prevalent_room"],
        "transitions": spatial_transition_summary(windows),
        "night": spatial_night_summary(windows),
        "longest_single_room_minutes": current["longest_single_room_minutes"],
        "baseline": {
            "available": bool(baseline.get("trained") or baseline.get("status") in {"trained", "ready", "completed"}),
            "status": baseline.get("status"),
            "source": reference["source"],
            "reason": reference["reason"],
            "comparison": spatial_baseline_comparison(current, reference["summary"]),
        },
        "ble_quality": spatial_ble_quality(db, patient_id, windows, period_start, period_end, now=now),
    }


def recent_decisions(db: Session, patient_id: str, *, limit: int) -> list[Decision]:
    return list(
        db.execute(
            select(Decision)
            .where(Decision.patient_id == patient_id)
            .order_by(desc(Decision.timestamp), desc(Decision.id))
            .limit(limit)
        ).scalars()
    )


def recent_alerts(db: Session, patient_id: str, *, limit: int) -> list[Alert]:
    return list(
        db.execute(
            select(Alert)
            .where(Alert.patient_id == patient_id)
            .order_by(desc(Alert.opened_at), desc(Alert.id))
            .limit(limit)
        ).scalars()
    )


def recent_tasks(db: Session, patient_id: str, *, limit: int) -> list[Task]:
    return list(
        db.execute(
            select(Task)
            .where(Task.patient_id == patient_id)
            .order_by(desc(Task.created_at), desc(Task.id))
            .limit(limit)
        ).scalars()
    )


def report_timeline(db: Session, patient_id: str, *, now: datetime, days: int) -> list[dict[str, Any]]:
    """Restituisce una timeline compatta adatta al report."""
    events = normalized_timeline_events(db, patient_id, date_from=now - timedelta(days=days), date_to=now)
    events = deduplicate_timeline_events(events)
    events.sort(key=lambda event: (parse_datetime(event["timestamp"]) or datetime.min.replace(tzinfo=timezone.utc), event["event_id"]), reverse=True)
    return events[:30]


def report_medical_notes(db: Session, alerts: list[Alert], tasks: list[Task]) -> list[dict[str, Any]]:
    """Raccoglie note medico da task e risoluzioni alert senza includere dati sensibili."""
    notes: list[dict[str, Any]] = []
    for task in tasks:
        payload = task.payload or {}
        note = payload.get("medical_note")
        if note:
            notes.append(
                {
                    "source": "task",
                    "resource_id": f"task-{task.id}",
                    "timestamp": payload.get("medical_note_at") or utc_iso(task.updated_at),
                    "author": payload.get("medical_note_by"),
                    "text": note,
                }
            )
    alert_ids = [alert.id for alert in alerts]
    if alert_ids:
        rows = db.execute(
            select(AlertEvent)
            .where(AlertEvent.alert_id.in_(alert_ids), AlertEvent.event_type == "resolved")
            .order_by(desc(AlertEvent.timestamp), desc(AlertEvent.id))
        ).scalars().all()
        alert_by_id = {alert.id: alert for alert in alerts}
        for row in rows:
            note_payload = event_note_payload(row.note)
            note = note_payload.get("note")
            if note:
                notes.append(
                    {
                        "source": "alert",
                        "resource_id": f"alert-{row.alert_id}",
                        "timestamp": utc_iso(row.timestamp),
                        "author": note_payload.get("user_id"),
                        "text": note,
                        "title": alert_by_id.get(row.alert_id).title if row.alert_id in alert_by_id else None,
                    }
                )
    notes.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return notes


def audit_trail_payload(row: AuditLog) -> dict[str, Any]:
    """Trasforma audit tecnico in voce leggibile dalla dashboard medico."""
    title, summary = audit_copy(row.action, row.details or {})
    return {
        "audit_id": f"audit-{row.id}",
        "timestamp": utc_iso(row.timestamp),
        "action": row.action,
        "title": title,
        "summary": summary,
        "actor": {
            "user_id": f"user-{row.actor_user_id}" if row.actor_user_id else None,
            "role": row.actor_role,
        },
        "target": {
            "type": row.target_type,
            "id": row.target_id,
        },
        "patient_id": row.patient_id,
        "details": public_audit_details(row.details or {}),
    }


def audit_copy(action: str, details: dict[str, Any]) -> tuple[str, str]:
    """Restituisce titolo e descrizione italiana per l'audit trail."""
    mapping = {
        "alert.acknowledged": ("Alert preso in carico", "Una segnalazione e' stata assegnata a un operatore."),
        "alert.resolved": ("Alert risolto", "Una segnalazione e' stata chiusa con nota di verifica."),
        "alert.deleted": ("Alert eliminato", "Una segnalazione risolta e' stata eliminata definitivamente."),
        "task.created": ("Attivita' creata", f"Task creato: {details.get('title') or details.get('type') or 'n/d'}."),
        "task.completed": ("Attivita' completata", "Il paziente ha inviato un risultato."),
        "task.cancelled": ("Attivita' annullata", "Un task e' stato annullato dal medico."),
        "task.medical_note_updated": ("Nota medico aggiornata", "Una nota e' stata salvata sul task."),
        "questionnaire_schedule.created": ("Questionario programmato", "E' stata creata una programmazione ricorrente."),
        "questionnaire_schedule.suspended": ("Questionario sospeso", "Una programmazione ricorrente e' stata sospesa."),
        "questionnaire_task.generated": ("Questionario inviato", "La programmazione ha generato un task per il paziente."),
        "patient_report.exported": ("Report esportato", "Il medico ha richiesto i dati per un report paziente."),
        "notification.device_registered": ("Dispositivo app registrato", "L'app paziente ha aggiornato lo stato notifiche."),
    }
    return mapping.get(action, (action.replace("_", " ").replace(".", " ").title(), "Evento registrato dal backend."))


def public_audit_details(details: dict[str, Any]) -> dict[str, Any]:
    """Rimuove eventuali chiavi sensibili dai dettagli audit."""
    blocked = {"password", "password_hash", "token", "access_token", "refresh_token", "fcm_token", "client_secret", "authorization"}
    return {key: value for key, value in details.items() if key.lower() not in blocked}


def completeness_payload(available: int, total: int) -> dict[str, Any]:
    ratio = (available / total) if total else 0.0
    return {
        "available_windows": available,
        "total_windows": total,
        "ratio": round(ratio, 3),
        "level": reliability_level(ratio),
    }


def reliability_level(ratio: float) -> str:
    if ratio >= 0.8:
        return "alta"
    if ratio >= 0.45:
        return "media"
    return "bassa"


def numeric_stats(windows: list[FeatureWindow], feature: str) -> dict[str, float | int | None]:
    values = feature_values(windows, feature)
    return {
        "average": round(average(values), 3) if values else None,
        "min": round(min(values), 3) if values else None,
        "max": round(max(values), 3) if values else None,
        "count": len(values),
    }


def feature_values(windows: list[FeatureWindow], feature: str) -> list[float]:
    return [float(window.features[feature]) for window in windows if is_number(window.features.get(feature))]


def sum_feature_values(windows: list[FeatureWindow], feature: str) -> float | None:
    values = feature_values(windows, feature)
    return sum(values) if values else None


def average_feature_values(windows: list[FeatureWindow], feature: str) -> float | None:
    return average(feature_values(windows, feature))


def max_feature_value(windows: list[FeatureWindow], feature: str) -> float | None:
    values = feature_values(windows, feature)
    return round(max(values), 3) if values else None


def any_feature_value(windows: list[FeatureWindow], feature: str) -> bool:
    return any(is_number(window.features.get(feature)) for window in windows)


def count_windows_with_any_feature(windows: list[FeatureWindow], features: list[str]) -> int:
    return sum(1 for window in windows if any(is_number(window.features.get(feature)) for feature in features))


def average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def normalized_timeline_events(
    db: Session,
    patient_id: str,
    *,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[dict[str, Any]]:
    """Unisce le principali tabelle operative in una timeline unica."""
    events: list[dict[str, Any]] = []
    events.extend(window_timeline_events(timeline_rows(db, FeatureWindow, patient_id, FeatureWindow.window_end, date_from, date_to)))
    events.extend(decision_timeline_events(timeline_rows(db, Decision, patient_id, Decision.timestamp, date_from, date_to)))
    alerts = timeline_rows(db, Alert, patient_id, Alert.opened_at, date_from, date_to)
    events.extend(alert_timeline_events(alerts))
    events.extend(alert_event_timeline_events(db, patient_id, date_from=date_from, date_to=date_to))
    tasks = timeline_rows(db, Task, patient_id, Task.created_at, date_from, date_to)
    events.extend(task_timeline_events(tasks))
    events.extend(task_result_timeline_events(timeline_rows(db, TaskResult, patient_id, TaskResult.completed_at, date_from, date_to)))
    events.extend(notification_timeline_events(timeline_rows(db, Notification, patient_id, Notification.created_at, date_from, date_to)))
    events.extend(edge_cycle_timeline_events(timeline_rows(db, EdgeCycle, patient_id, EdgeCycle.timestamp, date_from, date_to)))
    events.extend(sensor_timeline_events(timeline_rows(db, SensorStatus, patient_id, SensorStatus.last_seen_at, date_from, date_to)))
    return events


def timeline_rows(db: Session, model: Any, patient_id: str, timestamp_column: Any, date_from: datetime | None, date_to: datetime | None) -> list[Any]:
    """Carica righe filtrate per paziente e intervallo temporale."""
    query = select(model).where(model.patient_id == patient_id)
    if date_from is not None:
        query = query.where(timestamp_column >= date_from)
    if date_to is not None:
        query = query.where(timestamp_column <= date_to)
    return list(db.execute(query.order_by(timestamp_column, model.id if hasattr(model, "id") else timestamp_column)).scalars())


def parse_event_type_filter(value: str | None) -> set[str]:
    """Permette filtro singolo o lista separata da virgole."""
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def timeline_event(
    *,
    event_id: str,
    event_type: str,
    timestamp: datetime | None,
    title: str,
    summary: str | None,
    severity: str | None,
    source: str,
    linked_resource: dict[str, Any],
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    """Costruisce il formato comune usato dal frontend per la timeline."""
    return {
        "event_id": event_id,
        "event_type": event_type,
        "timestamp": utc_iso(timestamp),
        "title": title,
        "summary": summary,
        "severity": severity,
        "source": source,
        "linked_resource": linked_resource,
        "dedupe_key": dedupe_key or event_id,
    }


def window_timeline_events(rows: list[FeatureWindow]) -> list[dict[str, Any]]:
    return [
        timeline_event(
            event_id=f"window-{row.id}",
            event_type="patient_window_updated",
            timestamp=row.window_end,
            title="Finestra dati aggiornata",
            summary=window_timeline_summary(row.features),
            severity="info",
            source="edge",
            linked_resource={
                "type": "feature_window",
                "id": f"window-{row.id}",
                "message_id": row.message_id,
                "window_start": utc_iso(row.window_start),
                "window_end": utc_iso(row.window_end),
            },
            dedupe_key=f"window:{row.message_id}",
        )
        for row in rows
    ]


def decision_timeline_events(rows: list[Decision]) -> list[dict[str, Any]]:
    events = []
    for row in rows:
        score = round(row.anomaly_score, 3) if is_number(row.anomaly_score) else None
        event = timeline_event(
            event_id=f"decision-{row.id}",
            event_type="decision_updated",
            timestamp=row.timestamp,
            title=f"Decisione AI {levelLabel_backend(row.level)}",
            summary=f"Score {score}" if score is not None else "Score non disponibile",
            severity=row.level,
            source="ai",
            linked_resource={
                "type": "decision",
                "id": f"decision-{row.id}",
                "message_id": row.message_id,
                "window_start": utc_iso(row.window_start),
                "window_end": utc_iso(row.window_end),
            },
            dedupe_key=f"decision:{row.message_id}",
        )
        confidence = confidence_from_payload(row)
        if confidence is not None:
            event["confidence"] = confidence
        events.append(event)
    return events


def alert_timeline_events(rows: list[Alert]) -> list[dict[str, Any]]:
    return [
        timeline_event(
            event_id=f"alert-{row.id}",
            event_type="alert_created",
            timestamp=row.opened_at,
            title=row.title,
            summary=row.description,
            severity=row.level,
            source=row.source,
            linked_resource={
                "type": "alert",
                "id": f"alert-{row.id}",
                "message_id": row.message_id,
                "status": row.status,
                "category": row.category,
            },
            dedupe_key=f"alert:{row.message_id}",
        )
        for row in rows
    ]


def alert_event_timeline_events(db: Session, patient_id: str, *, date_from: datetime | None, date_to: datetime | None) -> list[dict[str, Any]]:
    query = select(AlertEvent, Alert).join(Alert, Alert.id == AlertEvent.alert_id).where(Alert.patient_id == patient_id)
    if date_from is not None:
        query = query.where(AlertEvent.timestamp >= date_from)
    if date_to is not None:
        query = query.where(AlertEvent.timestamp <= date_to)
    rows = db.execute(query.order_by(AlertEvent.timestamp, AlertEvent.id)).all()
    events = []
    for event, alert in rows:
        note_payload = event_note_payload(event.note)
        events.append(
            timeline_event(
                event_id=f"alert-event-{event.id}",
                event_type=f"alert_{event.event_type}",
                timestamp=event.timestamp,
                title=alert_event_title(event.event_type),
                summary=note_payload.get("note") or alert.title,
                severity=alert.level,
                source="workflow",
                linked_resource={
                    "type": "alert",
                    "id": f"alert-{alert.id}",
                    "event_id": f"alert-event-{event.id}",
                    "actor_role": note_payload.get("role"),
                    "actor": note_payload.get("user_id"),
                },
            )
        )
    return events


def task_timeline_events(rows: list[Task]) -> list[dict[str, Any]]:
    events = []
    for row in rows:
        payload = row.payload or {}
        events.append(
            timeline_event(
                event_id=f"task-{row.id}",
                event_type="task_created",
                timestamp=row.created_at,
                title=row.title,
                summary=row.instructions,
                severity=task_severity(payload.get("priority")),
                source="task",
                linked_resource={
                    "type": "task",
                    "id": f"task-{row.id}",
                    "status": effective_task_status(row.status, row.due_at),
                    "task_type": row.task_type,
                    "assigned_to": payload.get("assigned_to", "patient"),
                },
            )
        )
        if row.seen_at is not None:
            events.append(task_state_event(row, "task_seen", row.seen_at, "Task visualizzato dal paziente"))
        if row.started_at is not None:
            events.append(task_state_event(row, "task_started", row.started_at, "Task iniziato dal paziente"))
        if row.completed_at is not None:
            events.append(task_state_event(row, "task_completed", row.completed_at, "Task completato dal paziente"))
    return events


def task_state_event(row: Task, event_type: str, timestamp: datetime, title: str) -> dict[str, Any]:
    return timeline_event(
        event_id=f"{event_type}-{row.id}",
        event_type=event_type,
        timestamp=timestamp,
        title=title,
        summary=row.title,
        severity=task_severity((row.payload or {}).get("priority")),
        source="task",
        linked_resource={"type": "task", "id": f"task-{row.id}", "status": effective_task_status(row.status, row.due_at)},
    )


def task_result_timeline_events(rows: list[TaskResult]) -> list[dict[str, Any]]:
    events = []
    for row in rows:
        result = row.result or {}
        events.append(
            timeline_event(
                event_id=f"task-result-{row.id}",
                event_type="task_result_received",
                timestamp=row.completed_at,
                title="Risultato task ricevuto",
                summary=task_result_summary(result),
                severity="info",
                source="patient_app",
                linked_resource={
                    "type": "task_result",
                    "id": f"result-{row.id}",
                    "task_id": f"task-{row.task_id}",
                    "message_id": row.message_id,
                },
                dedupe_key=f"task-result:{row.message_id}",
            )
        )
    return events


def notification_timeline_events(rows: list[Notification]) -> list[dict[str, Any]]:
    events = []
    for row in rows:
        payload = row.payload or {}
        kind = payload.get("kind") or payload.get("type") or row.channel
        events.append(
            timeline_event(
                event_id=f"notification-{row.id}",
                event_type=notification_event_type(kind),
                timestamp=row.created_at,
                title=row.title,
                summary=row.body,
                severity=task_severity(payload.get("priority")),
                source="notification",
                linked_resource={
                    "type": "notification",
                    "id": f"notification-{row.id}",
                    "channel": row.channel,
                    "status": row.status,
                    "kind": kind,
                },
            )
        )
    return events


def edge_cycle_timeline_events(rows: list[EdgeCycle]) -> list[dict[str, Any]]:
    return [
        timeline_event(
            event_id=f"edge-cycle-{row.id}",
            event_type=row.event_type,
            timestamp=row.timestamp,
            title="Ciclo Edge completato" if row.event_type == "edge_cycle_completed" else "Evento Edge",
            summary=edge_cycle_summary(row),
            severity=edge_cycle_severity(row),
            source="edge",
            linked_resource={
                "type": "edge_cycle",
                "id": f"edge-cycle-{row.id}",
                "message_id": row.message_id,
                "window_start": utc_iso(row.window_start),
                "window_end": utc_iso(row.window_end),
            },
            dedupe_key=f"edge-cycle:{row.message_id}",
        )
        for row in rows
    ]


def sensor_timeline_events(rows: list[SensorStatus]) -> list[dict[str, Any]]:
    return [
        timeline_event(
            event_id=f"sensor-status-{row.id}",
            event_type=f"sensor_{row.sensor_type}_updated",
            timestamp=row.last_seen_at or row.updated_at,
            title=f"Sensore {row.sensor_type} aggiornato",
            summary=f"Stato {row.status}",
            severity="technical" if row.status in {"error", "offline", "missing", "stale"} else "info",
            source="sensor",
            linked_resource={
                "type": "sensor_status",
                "id": f"sensor-status-{row.id}",
                "sensor_type": row.sensor_type,
                "status": row.status,
            },
        )
        for row in rows
    ]


def deduplicate_timeline_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplica eventi con stessa chiave tecnica mantenendo il piu' recente."""
    by_key: dict[str, dict[str, Any]] = {}
    for event in events:
        key = str(event.get("dedupe_key") or event["event_id"])
        current = by_key.get(key)
        if current is None:
            by_key[key] = event
            continue
        current_ts = parse_datetime(current.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
        new_ts = parse_datetime(event.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
        if new_ts >= current_ts:
            by_key[key] = event
    return [public_timeline_event(event) for event in by_key.values()]


def public_timeline_event(event: dict[str, Any]) -> dict[str, Any]:
    """Rimuove campi interni usati solo dal backend."""
    return {key: value for key, value in event.items() if key != "dedupe_key"}


def window_timeline_summary(features: dict[str, Any]) -> str:
    available = [key for key, value in features.items() if value is not None]
    if not available:
        return "Finestra ricevuta senza feature disponibili"
    return f"{len(available)} feature disponibili"


def levelLabel_backend(level: str | None) -> str:
    return {
        "green": "routine",
        "yellow": "attenzione",
        "orange": "rischio",
        "red": "massima allerta",
        "technical": "tecnica",
    }.get(str(level), str(level or "n/d"))


def alert_event_title(event_type: str) -> str:
    return {
        "acknowledged": "Alert preso in carico",
        "resolved": "Alert risolto",
        "deleted": "Alert eliminato",
    }.get(event_type, f"Alert {event_type}")


def task_severity(priority: Any) -> str:
    return {
        "urgent": "red",
        "high": "orange",
        "normal": "info",
        None: "info",
    }.get(str(priority), "info")


def task_result_summary(result: dict[str, Any]) -> str:
    score = result.get("score")
    if score is not None:
        return f"Score risultato {score}"
    answers = result.get("answers")
    if isinstance(answers, list):
        return f"{len(answers)} risposte ricevute"
    return "Risultato ricevuto dall'app paziente"


def notification_event_type(kind: Any) -> str:
    if kind == "caregiver_message":
        return "caregiver_message_created"
    if kind == "patient_message":
        return "patient_message_created"
    if kind == "task_created":
        return "task_notification_created"
    return "notification_created"


def edge_cycle_summary(row: EdgeCycle) -> str:
    payload = latest_edge_cycle_status_payload(row)
    quality = payload.get("quality_status")
    inference = payload.get("inference")
    parts = [part for part in [f"qualita {quality}" if quality else None, str(inference) if inference else None] if part]
    return " - ".join(parts) if parts else row.event_type


def edge_cycle_severity(row: EdgeCycle) -> str:
    payload = latest_edge_cycle_status_payload(row)
    quality = str(payload.get("quality_status") or "").lower()
    if quality == "error":
        return "technical"
    if quality == "warning":
        return "yellow"
    return "info"


def latest_decision(db: Session, patient_id: str) -> Decision | None:
    return db.execute(
        select(Decision)
        .where(Decision.patient_id == patient_id)
        .order_by(desc(Decision.timestamp), desc(Decision.id))
        .limit(1)
    ).scalar_one_or_none()


def latest_feature_window(db: Session, patient_id: str) -> FeatureWindow | None:
    return db.execute(
        select(FeatureWindow)
        .where(FeatureWindow.patient_id == patient_id)
        .order_by(desc(FeatureWindow.window_end), desc(FeatureWindow.id))
        .limit(1)
    ).scalar_one_or_none()


def latest_edge_cycle(db: Session, patient_id: str) -> EdgeCycle | None:
    return db.execute(
        select(EdgeCycle)
        .where(EdgeCycle.patient_id == patient_id)
        .order_by(desc(EdgeCycle.timestamp), desc(EdgeCycle.id))
        .limit(1)
    ).scalar_one_or_none()


def latest_edge_cycle_status_payload(cycle: EdgeCycle | None) -> dict[str, Any]:
    if cycle is None or not isinstance(cycle.payload, dict):
        return {}
    payload = cycle.payload.get("payload")
    return payload if isinstance(payload, dict) else {}


def baseline_status_from_cycle(cycle_status: dict[str, Any]) -> dict[str, Any]:
    auto_train = cycle_status.get("baseline_auto_train")
    if not isinstance(auto_train, dict):
        auto_train = {}

    accepted = first_present(
        cycle_status.get("baseline_session_accepted_windows"),
        auto_train.get("baseline_row_count"),
    )
    min_training_windows = first_present(
        cycle_status.get("baseline_session_min_training_windows"),
        auto_train.get("min_training_windows"),
        1000,
    )

    return {
        "available": bool(cycle_status),
        "status": first_present(cycle_status.get("baseline_session_status"), auto_train.get("session_status")),
        "started_at": first_present(cycle_status.get("baseline_session_started_at"), auto_train.get("started_at")),
        "planned_days": first_present(cycle_status.get("baseline_session_planned_days"), auto_train.get("planned_days")),
        "target_end_at": first_present(cycle_status.get("baseline_session_target_end_at"), auto_train.get("target_end_at")),
        "accepted_windows": accepted,
        "rejected_windows": cycle_status.get("baseline_session_rejected_windows"),
        "min_training_windows": min_training_windows,
        "ready_by_time": auto_train.get("ready_by_time"),
        "trained": auto_train.get("trained"),
        "reason": auto_train.get("reason"),
    }


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def system_edge_payload(
    *,
    current_edge: dict[str, Any],
    latest_cycle: EdgeCycle | None,
    cycle_status: dict[str, Any],
    now: datetime,
    stale_minutes: int,
) -> dict[str, Any]:
    """Arricchisce lo stato Edge con dati tecnici dell'ultimo ciclo MQTT."""
    edge = dict(current_edge)
    last_seen = latest_cycle.timestamp if latest_cycle else parse_datetime(current_edge.get("last_seen_at"))
    edge["online"] = status_from_last_seen(last_seen, now=now, stale_minutes=stale_minutes, missing_status="offline") == "active"
    edge["status"] = "online" if edge["online"] else ("stale" if last_seen else "offline")
    edge["last_cycle_at"] = utc_iso(latest_cycle.timestamp) if latest_cycle else None
    edge["cycle_status"] = first_present(
        cycle_status.get("status"),
        latest_cycle.event_type if latest_cycle else None,
    )
    edge["window_start"] = first_present(
        cycle_status.get("window_start"),
        utc_iso(latest_cycle.window_start) if latest_cycle else None,
    )
    edge["window_end"] = first_present(
        cycle_status.get("window_end"),
        utc_iso(latest_cycle.window_end) if latest_cycle else None,
    )
    edge["window_minutes"] = window_duration_minutes(
        latest_cycle.window_start if latest_cycle else None,
        latest_cycle.window_end if latest_cycle else None,
    )
    edge["quality_status"] = first_present(
        cycle_status.get("quality_status"),
        current_edge.get("quality_status"),
    )
    edge["quality_issue_count"] = cycle_status.get("quality_issue_count")
    edge["quality_error_count"] = cycle_status.get("quality_error_count")
    edge["quality_warning_count"] = cycle_status.get("quality_warning_count")
    edge["mqtt"] = public_mqtt_payload(cycle_status.get("mqtt_publish"))
    if edge["mqtt"] is not None:
        edge["mqtt_queue_depth"] = first_present(
            edge["mqtt"].get("queue_depth"),
            current_edge.get("mqtt_queue_depth"),
        )
    return edge


def public_mqtt_payload(value: Any) -> dict[str, Any] | None:
    """Espone solo diagnostica MQTT non sensibile."""
    if not isinstance(value, dict):
        return None
    errors = value.get("errors") if isinstance(value.get("errors"), list) else []
    return {
        "enabled": value.get("enabled"),
        "status": value.get("status"),
        "attempted": value.get("attempted"),
        "published": value.get("published"),
        "queued": value.get("queued"),
        "queue_depth": value.get("queue_depth"),
        "errors": [public_error_message(item) for item in errors if item],
    }


def google_health_status(
    cycle_status: dict[str, Any],
    current: dict[str, Any],
    *,
    last_seen_at: datetime | None,
    now: datetime,
    stale_minutes: int,
) -> str:
    """Calcola lo stato Google Health senza esporre dettagli OAuth sensibili."""
    if cycle_status.get("google_health_enabled") is False:
        return "disabled"
    if first_present(
        cycle_status.get("google_health_oauth_error"),
        cycle_status.get("google_health_error"),
        cycle_status.get("oauth_error"),
    ):
        return "error"
    feature_count = cycle_status.get("google_health_available_feature_count")
    has_features = isinstance(feature_count, int | float) and feature_count > 0
    if not has_features:
        has_features = bool(current["watch"]["available_features"])
    if has_features and is_recent(last_seen_at, now=now, stale_minutes=stale_minutes):
        return "active"
    return "stale"


def public_error_message(value: Any) -> str | None:
    """Rimuove token o segreti da errori tecnici prima di mandarli al frontend."""
    if value is None:
        return None
    text = str(value)
    text = re.sub(
        r"(?i)(access_token|refresh_token|client_secret|password|authorization)\s*[:=]\s*[^,\s}\"']+",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(r"(?i)bearer\s+[a-z0-9._\-]+", "Bearer <redacted>", text)
    if len(text) > 240:
        return f"{text[:237]}..."
    return text


def window_duration_minutes(start: datetime | None, end: datetime | None) -> float | None:
    """Calcola la durata dell'ultima finestra Edge in minuti."""
    if start is None or end is None:
        return None
    return round(max(0.0, (end - start).total_seconds() / 60.0), 2)


def latest_edge_device(db: Session, patient_id: str) -> EdgeDevice | None:
    return db.execute(
        select(EdgeDevice)
        .where(EdgeDevice.patient_id == patient_id)
        .order_by(desc(EdgeDevice.last_seen_at))
        .limit(1)
    ).scalar_one_or_none()


def sensor_status(db: Session, patient_id: str, sensor_type: str) -> SensorStatus | None:
    return db.execute(
        select(SensorStatus)
        .where(SensorStatus.patient_id == patient_id, SensorStatus.sensor_type == sensor_type)
        .limit(1)
    ).scalar_one_or_none()


def latest_patient_app_status(db: Session, patient_id: str) -> PatientAppStatus | None:
    return db.execute(
        select(PatientAppStatus)
        .where(PatientAppStatus.patient_id == patient_id)
        .order_by(desc(PatientAppStatus.last_seen_at), desc(PatientAppStatus.id))
        .limit(1)
    ).scalar_one_or_none()


def patient_app_status_payload(row: PatientAppStatus | None, *, now: datetime, stale_minutes: int) -> dict[str, Any]:
    """Espone lo stato tecnico dell'app paziente senza mostrare token FCM."""
    status = status_from_last_seen(row.last_seen_at if row else None, now=now, stale_minutes=stale_minutes, missing_status="missing")
    return {
        "status": status if row is None or row.status == "online" else row.status,
        "device_id": row.device_id if row else None,
        "platform": row.platform if row else None,
        "app_version": row.app_version if row else None,
        "battery_pct": row.battery_pct if row else None,
        "notifications_enabled": row.notifications_enabled if row else False,
        "fcm_registered": bool(row.fcm_token) if row else False,
        "last_seen_at": utc_iso(row.last_seen_at) if row else None,
    }


def technical_status(
    *,
    configured_status: str | None,
    last_seen_at: datetime | None,
    now: datetime,
    stale_minutes: int,
    active_if_present: bool,
    missing_status: str,
) -> str:
    """Combina stato ricevuto e freschezza temporale in active/stale/missing."""
    if configured_status in {"error", "disabled", "offline"}:
        return configured_status
    if not active_if_present and last_seen_at is None:
        return missing_status
    return status_from_last_seen(last_seen_at, now=now, stale_minutes=stale_minutes, missing_status=missing_status)


def status_from_last_seen(
    last_seen_at: datetime | None,
    *,
    now: datetime,
    stale_minutes: int,
    missing_status: str,
) -> str:
    if last_seen_at is None:
        return missing_status
    return "active" if is_recent(last_seen_at, now=now, stale_minutes=stale_minutes) else "stale"


def is_recent(last_seen_at: datetime | None, *, now: datetime, stale_minutes: int) -> bool:
    if last_seen_at is None:
        return False
    return normalize_aware(now) - normalize_aware(last_seen_at) <= timedelta(minutes=stale_minutes)


def normalize_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def window_payload(row: FeatureWindow) -> dict[str, Any]:
    """Serializza una finestra feature in formato dashboard."""
    return {
        "window_id": f"window-{row.id}",
        "patient_id": row.patient_id,
        "edge_id": row.edge_id,
        "window_start": utc_iso(row.window_start),
        "window_end": utc_iso(row.window_end),
        "features": row.features,
        "message_id": row.message_id,
        "created_at": utc_iso(row.created_at),
    }


def decision_payload(row: Decision, db: Session | None = None, *, patient_trend: dict[str, Any] | None = None) -> dict[str, Any]:
    """Serializza una decisione AI in formato dashboard."""
    payload = row.payload or {}
    inner_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    result = {
        "decision_id": f"decision-{row.id}",
        "patient_id": row.patient_id,
        "edge_id": row.edge_id,
        "timestamp": utc_iso(row.timestamp),
        "window_start": utc_iso(row.window_start),
        "window_end": utc_iso(row.window_end),
        "level": row.level,
        "should_publish": row.should_publish,
        "anomaly_score": row.anomaly_score,
        "model_label": row.model_label,
        "reasons": inner_payload.get("reasons", []),
        "evidence": inner_payload.get("evidence", {}),
        "confidence": confidence_from_payload(row),
        "feature_importance": feature_importance_from_payload(row),
        "message_id": row.message_id,
        "created_at": utc_iso(row.created_at),
    }
    if patient_trend is not None:
        result["trend"] = patient_trend
    if db is not None:
        result["ai_explanation"] = decision_ai_explanation(db, row, latest_feature_window_for_decision(db, row))
    return result


def decision_ai_explanation(db: Session, decision: Decision | None, features: dict[str, Any] | FeatureWindow | None) -> dict[str, Any]:
    """Normalizza la spiegazione AI in campi stabili per il frontend."""
    if decision is None:
        return empty_ai_explanation(features if isinstance(features, dict) else features.features if features else {})
    previous = previous_decision(db, decision)
    current_score = float(decision.anomaly_score) if is_number(decision.anomaly_score) else None
    previous_score = float(previous.anomaly_score) if previous and is_number(previous.anomaly_score) else None
    score_delta = round(current_score - previous_score, 3) if current_score is not None and previous_score is not None else None
    normalized_features = normalized_feature_explanations(decision)
    feature_dict = features.features if isinstance(features, FeatureWindow) else (features or {})
    missing_or_imputed = missing_or_imputed_features(feature_dict, normalized_features)
    reliability = data_reliability(feature_dict, normalized_features, decision)
    return {
        "previous_score": round(previous_score, 3) if previous_score is not None else None,
        "score_delta": score_delta,
        "score_direction": score_direction(score_delta),
        "updated_at": utc_iso(decision.timestamp),
        "model_label": decision.model_label,
        "data_reliability": reliability,
        "feature_explanations": normalized_features,
        "positive_factors": positive_factors(normalized_features),
        "negative_factors": negative_factors(normalized_features),
        "missing_or_imputed_features": missing_or_imputed,
        "model_contributions": model_contributions(decision),
        "message": "Supporto al triage: la decisione finale resta al medico.",
    }


def empty_ai_explanation(features: dict[str, Any] | FeatureWindow | None) -> dict[str, Any]:
    feature_dict = features.features if isinstance(features, FeatureWindow) else (features or {})
    return {
        "previous_score": None,
        "score_delta": None,
        "score_direction": "non_disponibile",
        "updated_at": None,
        "model_label": None,
        "data_reliability": data_reliability(feature_dict, [], None),
        "feature_explanations": [],
        "positive_factors": [],
        "negative_factors": [],
        "missing_or_imputed_features": missing_or_imputed_features(feature_dict, []),
        "model_contributions": {},
        "message": "Supporto al triage: la decisione finale resta al medico.",
    }


def previous_decision(db: Session, decision: Decision) -> Decision | None:
    """Trova la decisione precedente dello stesso paziente."""
    return db.execute(
        select(Decision)
        .where(
            Decision.patient_id == decision.patient_id,
            Decision.timestamp < decision.timestamp,
        )
        .order_by(desc(Decision.timestamp), desc(Decision.id))
        .limit(1)
    ).scalar_one_or_none()


def latest_feature_window_for_decision(db: Session, decision: Decision) -> FeatureWindow | None:
    """Associa una finestra alla decisione usando window_end quando disponibile."""
    query = select(FeatureWindow).where(FeatureWindow.patient_id == decision.patient_id)
    if decision.window_end is not None:
        query = query.where(FeatureWindow.window_end <= decision.window_end)
    else:
        query = query.where(FeatureWindow.window_end <= decision.timestamp)
    return db.execute(query.order_by(desc(FeatureWindow.window_end), desc(FeatureWindow.id)).limit(1)).scalar_one_or_none()


def normalized_feature_explanations(decision: Decision) -> list[dict[str, Any]]:
    """Converte le top feature dei modelli in una lista unica e leggibile."""
    fusion = decision_fusion_payload(decision)
    models = fusion.get("models") if isinstance(fusion.get("models"), dict) else {}
    normalized: list[dict[str, Any]] = []
    for model_name, model_payload in models.items():
        if not isinstance(model_payload, dict):
            continue
        explanation = model_payload.get("feature_explanation")
        if not isinstance(explanation, dict):
            continue
        top_features = explanation.get("top_features")
        if not isinstance(top_features, list):
            continue
        for item in top_features:
            if not isinstance(item, dict):
                continue
            feature = str(item.get("feature") or "").strip()
            if not feature:
                continue
            normalized.append(normalized_feature_item(feature, item, str(model_name)))
    normalized.sort(key=lambda item: item["impact"], reverse=True)
    return normalized


def normalized_feature_item(feature: str, item: dict[str, Any], model_name: str) -> dict[str, Any]:
    z_score = parse_float(item.get("z_score"))
    impact = parse_float(item.get("abs_z_score"))
    if impact is None and z_score is not None:
        impact = abs(z_score)
    direction = str(item.get("direction") or "").strip() or direction_from_z_score(z_score)
    return {
        "feature": feature,
        "label": feature_label(feature),
        "unit": feature_unit(feature),
        "model": model_name,
        "value": item.get("value"),
        "model_value": item.get("model_value"),
        "z_score": round(z_score, 3) if z_score is not None else None,
        "impact": round(impact, 3) if impact is not None else 0.0,
        "direction": direction,
        "direction_label": direction_label(direction),
        "effect": effect_from_direction(direction),
        "imputed": bool(item.get("imputed")),
    }


def positive_factors(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fattori sopra il riferimento: utili al frontend come aumento del punteggio."""
    return [factor_summary(item) for item in features if item.get("effect") == "increase"][:6]


def negative_factors(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fattori sotto il riferimento: utili al frontend come riduzione/assenza."""
    return [factor_summary(item) for item in features if item.get("effect") == "decrease"][:6]


def factor_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "feature": item["feature"],
        "label": item["label"],
        "unit": item["unit"],
        "value": item["value"],
        "model_value": item["model_value"],
        "impact": item["impact"],
        "direction": item["direction"],
        "direction_label": item["direction_label"],
        "imputed": item["imputed"],
        "model": item["model"],
    }


def missing_or_imputed_features(feature_values_payload: dict[str, Any], explanations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evidenzia dati mancanti o imputati che riducono l'affidabilita'."""
    tracked = {
        "heart_rate_mean",
        "heart_rate_std",
        "spo2_mean",
        "steps",
        "sleep_minutes",
        "sedentary_minutes",
        "hrv_rmssd",
        "room_changes",
        "night_room_changes",
        "bedroom_minutes",
        "kitchen_minutes",
        "bathroom_minutes",
        "living_room_minutes",
        "longest_single_room_minutes",
    }
    rows: dict[str, dict[str, Any]] = {}
    for feature in tracked:
        if is_missing_feature_value(feature_values_payload.get(feature)):
            rows[feature] = missing_feature_payload(feature, "missing")
    for item in explanations:
        if item.get("imputed"):
            rows[item["feature"]] = missing_feature_payload(item["feature"], "imputed")
    return sorted(rows.values(), key=lambda item: item["label"])


def missing_feature_payload(feature: str, status: str) -> dict[str, Any]:
    return {
        "feature": feature,
        "label": feature_label(feature),
        "unit": feature_unit(feature),
        "status": status,
    }


def data_reliability(feature_values_payload: dict[str, Any], explanations: list[dict[str, Any]], decision: Decision | None) -> dict[str, Any]:
    """Stima leggibile della qualita' dati usata dalla spiegazione AI."""
    expected = [
        "heart_rate_mean",
        "heart_rate_std",
        "spo2_mean",
        "steps",
        "sleep_minutes",
        "sedentary_minutes",
        "room_changes",
        "bedroom_minutes",
        "kitchen_minutes",
        "bathroom_minutes",
        "living_room_minutes",
    ]
    available = sum(1 for feature in expected if not is_missing_feature_value(feature_values_payload.get(feature)))
    ratio = available / len(expected) if expected else 0.0
    imputed_count = len({item["feature"] for item in explanations if item.get("imputed")})
    quality_status = quality_status_from_decision(decision)
    penalty = 0.15 if quality_status == "warning" else 0.3 if quality_status == "error" else 0.0
    adjusted_ratio = max(0.0, ratio - min(0.35, imputed_count * 0.03) - penalty)
    return {
        "level": reliability_level(adjusted_ratio),
        "ratio": round(adjusted_ratio, 3),
        "available_features": available,
        "expected_features": len(expected),
        "imputed_features": imputed_count,
        "quality_status": quality_status,
    }


def model_contributions(decision: Decision) -> dict[str, Any]:
    """Espone contributi dei modelli senza rendere obbligatoria la forma Edge."""
    fusion = decision_fusion_payload(decision)
    models = fusion.get("models") if isinstance(fusion.get("models"), dict) else {}
    result: dict[str, Any] = {}
    for model_name, model_payload in models.items():
        if not isinstance(model_payload, dict):
            continue
        result[str(model_name)] = {
            "available": model_payload.get("available"),
            "score": model_payload.get("score"),
            "label": model_payload.get("label"),
            "decision_value": model_payload.get("decision_value"),
        }
    return result


def decision_fusion_payload(decision: Decision) -> dict[str, Any]:
    payload = decision.payload or {}
    inner_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    evidence = inner_payload.get("evidence") if isinstance(inner_payload.get("evidence"), dict) else {}
    fusion = evidence.get("fusion") if isinstance(evidence.get("fusion"), dict) else {}
    return fusion


FEATURE_LABELS = {
    "heart_rate_mean": ("Frequenza cardiaca media", "bpm"),
    "heart_rate_std": ("Variabilita' frequenza cardiaca", "bpm"),
    "resting_heart_rate": ("Frequenza cardiaca a riposo", "bpm"),
    "hrv_rmssd": ("Variabilita' cardiaca HRV", "ms"),
    "spo2_mean": ("Saturazione media SpO2", "%"),
    "sleep_minutes": ("Minuti di sonno", "min"),
    "awake_minutes": ("Minuti sveglio", "min"),
    "steps": ("Passi", ""),
    "sedentary_minutes": ("Sedentarieta'", "min"),
    "room_changes": ("Cambi stanza", ""),
    "night_room_changes": ("Cambi stanza notturni", ""),
    "bedroom_minutes": ("Permanenza in camera", "min"),
    "kitchen_minutes": ("Permanenza in cucina", "min"),
    "bathroom_minutes": ("Permanenza in bagno", "min"),
    "living_room_minutes": ("Permanenza in soggiorno", "min"),
    "longest_single_room_minutes": ("Permanenza continuativa massima", "min"),
}


def feature_label(feature: str) -> str:
    return FEATURE_LABELS.get(feature, (feature.replace("_", " ").capitalize(), ""))[0]


def feature_unit(feature: str) -> str:
    return FEATURE_LABELS.get(feature, ("", ""))[1]


def score_direction(delta: float | None) -> str:
    if delta is None:
        return "non_disponibile"
    if abs(delta) < 1.0:
        return "stabile"
    return "aumento" if delta > 0 else "diminuzione"


def direction_from_z_score(value: float | None) -> str:
    if value is None:
        return "unknown"
    return "above_training" if value > 0 else "below_training" if value < 0 else "aligned"


def direction_label(direction: str) -> str:
    return {
        "above_training": "Piu' alto del riferimento",
        "below_training": "Piu' basso del riferimento",
        "aligned": "In linea con il riferimento",
    }.get(direction, "Confronto non disponibile")


def effect_from_direction(direction: str) -> str:
    if direction == "above_training":
        return "increase"
    if direction == "below_training":
        return "decrease"
    return "neutral"


def parse_float(value: Any) -> float | None:
    if is_number(value):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_missing_feature_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "nan", "null", "none", "n/d"}:
        return True
    return False


def alert_payload(db: Session, alert: Alert) -> dict[str, Any]:
    """Serializza un alert includendo audit di ack/resolve."""
    acknowledged = latest_alert_event(db, alert.id, "acknowledged")
    resolved = latest_alert_event(db, alert.id, "resolved")
    acknowledged_note = event_note_payload(acknowledged.note if acknowledged else None)
    resolved_note = event_note_payload(resolved.note if resolved else None)
    return {
        "alert_id": f"alert-{alert.id}",
        "patient_id": alert.patient_id,
        "level": alert.level,
        "status": alert.status,
        "category": alert.category,
        "source": alert.source,
        "clinical_severity": alert.clinical_severity,
        "technical_severity": alert.technical_severity,
        "escalated": is_alert_escalated(alert),
        "escalated_at": utc_iso(alert.escalated_at) or (utc_iso(alert.opened_at + timedelta(minutes=ALERT_ESCALATION_MINUTES)) if is_alert_escalated(alert) else None),
        "title": alert.title,
        "description": alert.description,
        "opened_at": utc_iso(alert.opened_at),
        "closed_at": utc_iso(alert.closed_at),
        "anomaly_score": None,
        "acknowledged_at": utc_iso(acknowledged.timestamp) if acknowledged else None,
        "acknowledged_by": acknowledged_note.get("user_id") if acknowledged_note else None,
        "acknowledged_role": acknowledged_note.get("role") if acknowledged_note else None,
        "resolved_at": utc_iso(resolved.timestamp) if resolved else None,
        "resolved_by": resolved_note.get("user_id") if resolved_note else None,
        "resolved_role": resolved_note.get("role") if resolved_note else None,
        "resolution_note": resolved_note.get("note") if resolved_note else None,
        "message_id": alert.message_id,
        "payload": alert.payload or {},
    }


def latest_alert_event(db: Session, alert_id: int, event_type: str) -> AlertEvent | None:
    return db.execute(
        select(AlertEvent)
        .where(AlertEvent.alert_id == alert_id, AlertEvent.event_type == event_type)
        .order_by(desc(AlertEvent.timestamp), desc(AlertEvent.id))
        .limit(1)
    ).scalar_one_or_none()


def is_alert_escalated(alert: Alert) -> bool:
    """Segnala alert rimasti nuovi troppo a lungo senza mutare il DB in lettura."""
    if alert.status != "new":
        return False
    if alert.escalated_at is not None:
        return True
    opened_at = alert.opened_at
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= opened_at + timedelta(minutes=ALERT_ESCALATION_MINUTES)


def task_payload(task: Task, db: Session | None = None) -> dict[str, Any]:
    """Serializza un task nel formato atteso da dashboard/app."""
    payload = task.payload or {}
    result = latest_task_result_payload(db, task) if db is not None else None
    return {
        "task_id": f"task-{task.id}",
        "patient_id": task.patient_id,
        "status": effective_task_status(task.status, task.due_at),
        "type": task.task_type,
        "schema_version": payload.get("schema_version", 1),
        "priority": payload.get("priority", "normal"),
        "assigned_to": payload.get("assigned_to", "patient"),
        "title": task.title,
        "instructions": task.instructions,
        "medical_note": payload.get("medical_note"),
        "due_at": utc_iso(task.due_at),
        "expires_at": payload.get("expires_at") or utc_iso(task.due_at),
        "payload": payload.get("content", payload),
        "scoring": payload.get("scoring"),
        "result": result,
        "seen_at": utc_iso(task.seen_at),
        "started_at": utc_iso(task.started_at),
        "completed_at": utc_iso(task.completed_at),
        "last_device_id": task.last_device_id,
        "created_at": utc_iso(task.created_at),
        "updated_at": utc_iso(task.updated_at),
    }


def latest_task_result_payload(db: Session, task: Task) -> dict[str, Any] | None:
    """Restituisce il risultato piu' recente del task, se il paziente lo ha completato."""
    row = db.execute(
        select(TaskResult)
        .where(TaskResult.task_id == task.id)
        .order_by(desc(TaskResult.completed_at), desc(TaskResult.id))
    ).scalars().first()
    if row is None:
        return None
    result = row.result or {}
    return {
        "result_id": f"result-{row.id}",
        "task_id": f"task-{task.id}",
        "patient_id": row.patient_id,
        "completed_at": utc_iso(row.completed_at),
        "duration_seconds": row.duration_seconds,
        "score": result.get("score"),
        "score_details": result.get("score_details"),
        "answers": result.get("answers", []),
        "result_type": result.get("result_type"),
        "content": result.get("content", {}),
        "note": result.get("note"),
        "device_info": result.get("device_info", {}),
        "received_at": utc_iso(row.created_at),
    }


def parse_datetime(value: Any) -> datetime | None:
    """Converte un timestamp ISO opzionale in datetime."""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def infer_current_room(features: dict[str, Any]) -> str | None:
    """Deduce la stanza prevalente dai minuti per stanza dell'ultima finestra."""
    candidates = {
        "bedroom": features.get("bedroom_minutes"),
        "kitchen": features.get("kitchen_minutes"),
        "bathroom": features.get("bathroom_minutes"),
        "living_room": features.get("living_room_minutes"),
    }
    numeric = {room: float(value) for room, value in candidates.items() if isinstance(value, int | float)}
    if not numeric:
        return None
    room, minutes = max(numeric.items(), key=lambda item: item[1])
    return room if minutes > 0 else None


def signal_type(*, level: str, edge_online: bool, features: dict[str, Any]) -> str:
    if not edge_online:
        return "technical"
    if features and features.get("wearable_present") is False:
        return "technical"
    if level in {"red", "orange", "yellow"}:
        return "clinical"
    if level == "technical":
        return "technical"
    return "routine"


def quality_status_from_decision(decision: Decision | None) -> str:
    if decision is None:
        return "unknown"
    payload = decision.payload or {}
    quality = payload.get("quality_status")
    return str(quality) if quality else "ok"


def mqtt_queue_depth(decision: Decision | None) -> int:
    if decision is None:
        return 0
    payload = decision.payload or {}
    mqtt_payload = payload.get("mqtt_publish")
    if isinstance(mqtt_payload, dict):
        value = mqtt_payload.get("queue_depth")
        return int(value) if isinstance(value, int | float) else 0
    return 0


def confidence_from_payload(decision: Decision | None) -> dict[str, Any] | None:
    """Estrae la confidenza dalla decisione, se presente nel payload edge.

    Il formato atteso e' `{"score": int, "level": str, "reasons": [str]}`.
    Puo' trovarsi sia a livello radice del payload sia dentro una chiave
    `payload` annidata, a seconda della versione dello schema edge.
    """
    if decision is None:
        return None
    raw = decision.payload or {}
    inner = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
    confidence = inner.get("confidence")
    if not isinstance(confidence, dict):
        return None
    return confidence


def feature_importance_from_payload(decision: Decision | None) -> dict[str, Any] | None:
    """Estrae la feature importance dal payload edge, se presente.

    Il formato atteso e' `{"available": bool, "items": [{"feature", "label",
    "impact", "weight", "value", "reference"}]}`.
    """
    if decision is None:
        return None
    raw = decision.payload or {}
    inner = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
    importance = inner.get("feature_importance")
    if not isinstance(importance, dict):
        return None
    return importance
