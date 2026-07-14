from __future__ import annotations

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
from app.db.models import Alert, AlertEvent, Decision, EdgeCycle, EdgeDevice, FeatureWindow, Patient, PatientAppStatus, SensorStatus, Task, TaskResult
from app.db.session import get_db
from app.mqtt.events import InternalEvent, event_bus
from app.services.push_notifications import notify_task_created

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
    items = [decision_payload(row) for row in reversed(rows)]
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
    features = window.features if window else {}
    level = decision.level if decision else "green"
    last_update = decision.timestamp if decision else (window.window_end if window else None)
    if last_update is None:
        last_update = edge.last_seen_at if edge else datetime.now(timezone.utc)
    available_features = [key for key, value in features.items() if value is not None]
    current_room = infer_current_room(features)
    edge_online = edge.status == "online" if edge else False
    quality_status = quality_status_from_decision(decision)
    return {
        "patient_id": patient.patient_id,
        "edge_id": edge.edge_id if edge else None,
        "last_update": utc_iso(last_update),
        "level": level,
        "signal_type": signal_type(level=level, edge_online=edge_online, features=features),
        "should_publish": bool(decision.should_publish) if decision else False,
        "anomaly_score": decision.anomaly_score if decision else 0.0,
        "current_room": current_room,
        "watch": {
            "present": bool(features.get("wearable_present")) if features else False,
            "battery_pct": features.get("wearable_battery_pct"),
            "available_features": available_features,
        },
        "edge": {
            "online": edge_online,
            "quality_status": quality_status,
            "mqtt_queue_depth": mqtt_queue_depth(decision),
            "last_seen_at": utc_iso(edge.last_seen_at) if edge else None,
        },
    }


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


def decision_payload(row: Decision) -> dict[str, Any]:
    """Serializza una decisione AI in formato dashboard."""
    payload = row.payload or {}
    inner_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    return {
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
        "message_id": row.message_id,
        "created_at": utc_iso(row.created_at),
    }


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
