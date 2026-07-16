from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.api.routes.patients import current_payload, get_patient_or_404
from app.api.routes.utils import dump_event_note, event_note_payload, paginated, utc_iso
from app.auth.dependencies import CurrentUser, authorized_patient_ids, can_access_patient, get_current_user, require_patient_access, write_audit
from app.db.models import Alert, AlertEvent, Decision, FeatureWindow, Notification, Patient, Task, TaskResult
from app.db.session import get_db
from app.mqtt.events import InternalEvent, event_bus

router = APIRouter()
ALERT_ESCALATION_MINUTES = 30


@router.get("/status", summary="Alerts module status")
def alerts_status() -> dict[str, str]:
    """Espone lo stato del modulo alert."""
    return {"status": "implemented", "module": "alerts"}


@router.get("/caregiver", summary="Caregiver alert overview")
def caregiver_alert_overview(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce solo stato sintetico e alert importanti visibili al caregiver."""
    if current_user.role not in {"caregiver", "admin"}:
        raise HTTPException(status_code=403, detail="Only caregiver or admin can access caregiver overview.")
    allowed = authorized_patient_ids(db, current_user)
    patient_query = select(Patient).where(Patient.is_active.is_(True))
    if allowed is not None:
        if not allowed:
            return {"items": []}
        patient_query = patient_query.where(Patient.patient_id.in_(allowed))
    patients = db.execute(patient_query.order_by(Patient.patient_id)).scalars().all()
    return {"items": [caregiver_patient_payload(db, patient) for patient in patients]}


@router.get("/patients/{patient_id}/alerts", summary="Patient alerts")
def patient_alerts(
    patient_id: str,
    _current_user: CurrentUser = Depends(require_patient_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce gli alert del paziente ordinati dai piu' recenti."""
    get_patient_or_404(db, patient_id)
    rows = db.execute(
        select(Alert)
        .where(Alert.patient_id == patient_id)
        .order_by(desc(Alert.opened_at), desc(Alert.id))
    ).scalars().all()
    return paginated([alert_payload(db, row) for row in rows])


@router.get("/{alert_id}/details", summary="Alert workflow details")
def alert_details(
    alert_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restituisce l'alert come caso operativo con contesto, azioni e storico."""
    alert = get_alert_or_404(db, alert_id)
    if not can_access_patient(db, current_user, alert.patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")
    if current_user.role == "patient":
        raise HTTPException(status_code=403, detail="Patients cannot read alert workflow details.")
    return alert_detail_payload(db, alert, current_user)


@router.patch("/{alert_id}/acknowledge", summary="Acknowledge alert")
def acknowledge_alert(
    alert_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Prende in carico un alert in modo idempotente."""
    alert = get_alert_or_404(db, alert_id)
    if current_user.role not in {"doctor", "caregiver", "admin"}:
        raise HTTPException(status_code=403, detail="Role not authorized.")
    if not can_access_patient(db, current_user, alert.patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")
    now = datetime.now(timezone.utc)
    user_id = current_user.display_name or current_user.email
    if alert.status == "new":
        alert.status = "acknowledged"
        db.add(
            AlertEvent(
                alert_id=alert.id,
                event_type="acknowledged",
                timestamp=now,
                note=dump_event_note(user_id=user_id, role=current_user.role, note=payload.get("note")),
            )
        )
        write_audit(
            db,
            actor=current_user,
            action="alert.acknowledged",
            patient_id=alert.patient_id,
            target_type="alert",
            target_id=f"alert-{alert.id}",
            details={"note": payload.get("note")},
        )
        db.commit()
        publish_alert_event("alert_acknowledged", alert, now)
    return alert_payload(db, alert)


@router.patch("/{alert_id}/resolve", summary="Resolve alert")
def resolve_alert(
    alert_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Risolve un alert richiedendo una nota obbligatoria."""
    note = str(payload.get("note") or "").strip()
    if not note:
        raise HTTPException(status_code=422, detail="Resolve note is required.")
    alert = get_alert_or_404(db, alert_id)
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can resolve alerts.")
    if not can_access_patient(db, current_user, alert.patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")
    now = datetime.now(timezone.utc)
    alert.status = "resolved"
    alert.closed_at = now
    db.add(
        AlertEvent(
            alert_id=alert.id,
            event_type="resolved",
            timestamp=now,
            note=dump_event_note(
                user_id=current_user.display_name or current_user.email,
                role=current_user.role,
                note=note,
            ),
        )
    )
    write_audit(
        db,
        actor=current_user,
        action="alert.resolved",
        patient_id=alert.patient_id,
        target_type="alert",
        target_id=f"alert-{alert.id}",
        details={"note": note},
    )
    db.commit()
    publish_alert_event("alert_resolved", alert, now)
    return alert_payload(db, alert)


@router.delete("/{alert_id}", summary="Delete alert permanently")
def delete_alert(
    alert_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Elimina definitivamente un alert dal backend su richiesta del medico."""
    alert = get_alert_or_404(db, alert_id)
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Only doctor or admin can delete alerts.")
    if not can_access_patient(db, current_user, alert.patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")
    if alert.status != "resolved":
        raise HTTPException(status_code=409, detail="Only resolved alerts can be permanently deleted.")

    patient_id = alert.patient_id
    public_alert_id = f"alert-{alert.id}"
    now = datetime.now(timezone.utc)
    write_audit(
        db,
        actor=current_user,
        action="alert.deleted",
        patient_id=patient_id,
        target_type="alert",
        target_id=public_alert_id,
        details={"status": alert.status, "level": alert.level},
    )
    db.execute(delete(AlertEvent).where(AlertEvent.alert_id == alert.id))
    db.delete(alert)
    db.commit()
    event_bus.publish(
        InternalEvent(
            event_type="alert_deleted",
            patient_id=patient_id,
            timestamp=now,
            payload={"alert_id": public_alert_id},
        )
    )
    return {"status": "deleted", "alert_id": public_alert_id, "patient_id": patient_id}


def get_alert_or_404(db: Session, alert_id: str) -> Alert:
    """Carica un alert usando id numerico o formato `alert-<id>`."""
    numeric_id = parse_prefixed_id(alert_id, "alert")
    alert = db.get(Alert, numeric_id) if numeric_id is not None else None
    if alert is None:
        alert = db.execute(select(Alert).where(Alert.message_id == alert_id)).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert not found: {alert_id}")
    return alert


def alert_payload(db: Session, alert: Alert) -> dict[str, Any]:
    """Serializza un alert includendo metadati di presa in carico e risoluzione."""
    acknowledged = latest_event(db, alert.id, "acknowledged")
    resolved = latest_event(db, alert.id, "resolved")
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
        "escalated": is_escalated(alert),
        "escalated_at": utc_iso(alert.escalated_at) or (utc_iso(escalation_time(alert)) if is_escalated(alert) else None),
        "title": alert.title,
        "description": alert.description,
        "opened_at": utc_iso(alert.opened_at),
        "closed_at": utc_iso(alert.closed_at),
        "anomaly_score": anomaly_score(alert),
        "acknowledged_at": utc_iso(acknowledged.timestamp) if acknowledged else None,
        "acknowledged_by": acknowledged_note.get("user_id") if acknowledged_note else None,
        "acknowledged_role": acknowledged_note.get("role") if acknowledged_note else None,
        "resolved_at": utc_iso(resolved.timestamp) if resolved else None,
        "resolved_by": resolved_note.get("user_id") if resolved_note else None,
        "resolved_role": resolved_note.get("role") if resolved_note else None,
        "resolution_note": resolved_note.get("note") if resolved_note else None,
        "message_id": alert.message_id,
    }


def alert_detail_payload(db: Session, alert: Alert, current_user: CurrentUser) -> dict[str, Any]:
    """Costruisce il dettaglio alert usato dalla dashboard per il workflow clinico."""
    base = alert_payload(db, alert)
    decision = db.get(Decision, alert.decision_id) if alert.decision_id else None
    feature_window = feature_window_for_alert(db, alert, decision)
    tasks = related_tasks(db, alert)
    notifications = related_notifications(db, alert)
    history = alert_history(db, alert)
    return {
        **base,
        "context": {
            "decision": decision_context(decision),
            "feature_window": feature_window_context(feature_window),
            "anti_noise": {
                "enabled": True,
                "window_minutes": ALERT_ESCALATION_MINUTES,
                "policy": "similar_open_alerts_are_not_duplicated",
            },
        },
        "related_events": related_alert_events(alert, decision, feature_window, tasks, notifications),
        "workflow": {
            "state": alert.status,
            "available_actions": available_alert_actions(alert, current_user),
            "delete_policy": "permanent_delete_allowed_only_when_resolved",
        },
        "history": history,
    }


def feature_window_for_alert(db: Session, alert: Alert, decision: Decision | None) -> FeatureWindow | None:
    """Trova la finestra feature piu' vicina alla decisione collegata."""
    query = select(FeatureWindow).where(FeatureWindow.patient_id == alert.patient_id)
    if decision is not None:
        if decision.window_end is not None:
            query = query.where(FeatureWindow.window_end <= decision.window_end)
        else:
            query = query.where(FeatureWindow.window_end <= decision.timestamp)
    else:
        query = query.where(FeatureWindow.window_end <= alert.opened_at)
    return db.execute(query.order_by(desc(FeatureWindow.window_end), desc(FeatureWindow.id)).limit(1)).scalar_one_or_none()


def related_tasks(db: Session, alert: Alert) -> list[Task]:
    """Trova task creati come follow-up dell'alert."""
    rows = db.execute(select(Task).where(Task.patient_id == alert.patient_id).order_by(Task.created_at, Task.id)).scalars().all()
    public_id = f"alert-{alert.id}"
    identifiers = {public_id, alert.message_id}
    return [task for task in rows if payload_references_alert(task.payload or {}, identifiers)]


def related_notifications(db: Session, alert: Alert) -> list[Notification]:
    """Trova messaggi/notifiche collegati all'alert quando il payload lo dichiara."""
    rows = db.execute(
        select(Notification)
        .where(Notification.patient_id == alert.patient_id)
        .order_by(Notification.created_at, Notification.id)
    ).scalars().all()
    identifiers = {f"alert-{alert.id}", alert.message_id}
    return [notification for notification in rows if payload_references_alert(notification.payload or {}, identifiers)]


def payload_references_alert(payload: dict[str, Any], identifiers: set[str]) -> bool:
    """Cerca riferimenti alert in payload annidati senza assumere una forma unica."""
    stack: list[Any] = [payload]
    keys = {"alert_id", "source_alert_id", "related_alert_id"}
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if key in keys and str(value) in identifiers:
                    return True
                if isinstance(value, dict | list):
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    return False


def related_alert_events(
    alert: Alert,
    decision: Decision | None,
    feature_window: FeatureWindow | None,
    tasks: list[Task],
    notifications: list[Notification],
) -> list[dict[str, Any]]:
    """Normalizza gli eventi collegati all'alert in ordine cronologico."""
    events: list[dict[str, Any]] = [
        {
            "event_id": f"alert-{alert.id}-created",
            "event_type": "alert_created",
            "timestamp": utc_iso(alert.opened_at),
            "title": "Segnalazione creata",
            "summary": alert.description,
            "linked_resource": {"type": "alert", "id": f"alert-{alert.id}"},
        }
    ]
    if decision is not None:
        events.append(
            {
                "event_id": f"decision-{decision.id}",
                "event_type": "decision_updated",
                "timestamp": utc_iso(decision.timestamp),
                "title": "Decisione AI collegata",
                "summary": f"Livello {decision.level}, score {decision.anomaly_score}",
                "linked_resource": {"type": "decision", "id": f"decision-{decision.id}"},
            }
        )
    if feature_window is not None:
        events.append(
            {
                "event_id": f"window-{feature_window.id}",
                "event_type": "patient_window_updated",
                "timestamp": utc_iso(feature_window.window_end),
                "title": "Finestra dati collegata",
                "summary": f"{len(feature_window.features or {})} feature disponibili",
                "linked_resource": {"type": "feature_window", "id": f"window-{feature_window.id}"},
            }
        )
    for task in tasks:
        events.append(
            {
                "event_id": f"task-{task.id}",
                "event_type": "task_created",
                "timestamp": utc_iso(task.created_at),
                "title": task.title,
                "summary": f"Task {task.task_type} - stato {task.status}",
                "linked_resource": {"type": "task", "id": f"task-{task.id}"},
            }
        )
    for notification in notifications:
        events.append(
            {
                "event_id": f"notification-{notification.id}",
                "event_type": notification_event_type(notification),
                "timestamp": utc_iso(notification.sent_at or notification.created_at),
                "title": notification.title,
                "summary": notification.body,
                "linked_resource": {"type": "notification", "id": f"notification-{notification.id}"},
            }
        )
    events.sort(key=lambda event: event.get("timestamp") or "")
    return events


def alert_history(db: Session, alert: Alert) -> list[dict[str, Any]]:
    """Restituisce lo storico umano delle azioni fatte sull'alert."""
    rows = db.execute(
        select(AlertEvent)
        .where(AlertEvent.alert_id == alert.id)
        .order_by(AlertEvent.timestamp, AlertEvent.id)
    ).scalars().all()
    return [
        {
            "event_id": f"alert-event-{row.id}",
            "event_type": row.event_type,
            "timestamp": utc_iso(row.timestamp),
            "actor": event_note_payload(row.note).get("user_id"),
            "actor_role": event_note_payload(row.note).get("role"),
            "note": event_note_payload(row.note).get("note"),
        }
        for row in rows
    ]


def decision_context(decision: Decision | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    return {
        "decision_id": f"decision-{decision.id}",
        "timestamp": utc_iso(decision.timestamp),
        "window_start": utc_iso(decision.window_start),
        "window_end": utc_iso(decision.window_end),
        "level": decision.level,
        "should_publish": decision.should_publish,
        "anomaly_score": decision.anomaly_score,
        "model_label": decision.model_label,
        "reasons": decision_reasons(decision),
    }


def feature_window_context(window: FeatureWindow | None) -> dict[str, Any] | None:
    if window is None:
        return None
    features = window.features or {}
    return {
        "window_id": f"window-{window.id}",
        "window_start": utc_iso(window.window_start),
        "window_end": utc_iso(window.window_end),
        "available_feature_count": sum(1 for value in features.values() if value is not None),
        "key_features": {
            "heart_rate_mean": features.get("heart_rate_mean"),
            "spo2_mean": features.get("spo2_mean"),
            "room_changes": features.get("room_changes"),
            "night_room_changes": features.get("night_room_changes"),
            "prevalent_room": prevalent_room_from_features(features),
        },
    }


def available_alert_actions(alert: Alert, current_user: CurrentUser) -> list[str]:
    """Elenca azioni UI permesse in base a ruolo e stato."""
    actions: list[str] = []
    if alert.status == "new" and current_user.role in {"doctor", "caregiver", "admin"}:
        actions.append("acknowledge")
    if alert.status in {"new", "acknowledged"} and current_user.role in {"doctor", "admin"}:
        actions.extend(["create_task", "send_message", "resolve"])
    if alert.status == "resolved" and current_user.role in {"doctor", "admin"}:
        actions.append("delete")
    return actions


def decision_reasons(decision: Decision) -> list[str]:
    payload = decision.payload.get("payload", {}) if isinstance(decision.payload, dict) else {}
    reasons = payload.get("reasons") if isinstance(payload, dict) else None
    return [str(reason) for reason in reasons] if isinstance(reasons, list) else []


def prevalent_room_from_features(features: dict[str, Any]) -> str | None:
    rooms = {
        "bedroom": features.get("bedroom_minutes"),
        "kitchen": features.get("kitchen_minutes"),
        "bathroom": features.get("bathroom_minutes"),
        "living_room": features.get("living_room_minutes"),
    }
    numeric_rooms = {room: float(value) for room, value in rooms.items() if isinstance(value, int | float) and not isinstance(value, bool)}
    if not numeric_rooms:
        return None
    room, minutes = max(numeric_rooms.items(), key=lambda item: item[1])
    return room if minutes > 0 else None


def notification_event_type(notification: Notification) -> str:
    payload = notification.payload or {}
    kind = payload.get("kind")
    if kind == "caregiver_message":
        return "caregiver_message_created"
    if kind == "patient_message":
        return "patient_message_created"
    return "notification_created"


def caregiver_patient_payload(db: Session, patient: Patient) -> dict[str, Any]:
    """Crea il payload ridotto per l'app caregiver senza dati clinici grezzi."""
    current = current_payload(db, patient)
    alerts = db.execute(
        select(Alert)
        .where(
            Alert.patient_id == patient.patient_id,
            Alert.level.in_(["orange", "red"]),
            Alert.status != "resolved",
        )
        .order_by(desc(Alert.opened_at), desc(Alert.id))
    ).scalars().all()
    return {
        "patient_id": patient.patient_id,
        "display_name": patient.display_name,
        "level": caregiver_level(current, alerts),
        "last_update": current["last_update"],
        "general_status": caregiver_general_status(current, alerts),
        "technical_status": caregiver_technical_status(current),
        "alerts": [caregiver_alert_payload(db, alert) for alert in alerts],
    }


def caregiver_alert_payload(db: Session, alert: Alert) -> dict[str, Any]:
    """Riduce l'alert ai soli campi utili al caregiver."""
    payload = alert_payload(db, alert)
    return {
        "alert_id": payload["alert_id"],
        "patient_id": payload["patient_id"],
        "level": payload["level"],
        "status": payload["status"],
        "title": payload["title"],
        "description": payload["description"],
        "opened_at": payload["opened_at"],
        "acknowledged_at": payload["acknowledged_at"],
        "acknowledged_by": payload["acknowledged_by"],
        "acknowledged_role": payload["acknowledged_role"],
    }


def caregiver_level(current: dict[str, Any], alerts: list[Alert]) -> str:
    if any(alert.level == "red" for alert in alerts):
        return "red"
    if any(alert.level == "orange" for alert in alerts):
        return "orange"
    if current["signal_type"] == "technical":
        return "technical"
    return "green"


def caregiver_general_status(current: dict[str, Any], alerts: list[Alert]) -> str:
    if alerts:
        return "Serve attenzione: il team ha pubblicato una segnalazione importante."
    if current["signal_type"] == "technical":
        return "Monitoraggio parziale: controllare lo stato tecnico."
    return "Monitoraggio aggiornato, nessuna segnalazione importante."


def caregiver_technical_status(current: dict[str, Any]) -> dict[str, Any]:
    edge = current["edge"]
    watch = current["watch"]
    issues: list[str] = []
    if not edge.get("online"):
        issues.append("Raspberry non risulta online.")
    if watch.get("present") is False:
        issues.append("Wearable non rilevato nell'ultima finestra.")
    return {
        "edge_online": edge.get("online"),
        "watch_present": watch.get("present"),
        "quality_status": edge.get("quality_status"),
        "last_seen_at": edge.get("last_seen_at"),
        "issues": issues,
    }


def latest_event(db: Session, alert_id: int, event_type: str) -> AlertEvent | None:
    return db.execute(
        select(AlertEvent)
        .where(AlertEvent.alert_id == alert_id, AlertEvent.event_type == event_type)
        .order_by(desc(AlertEvent.timestamp), desc(AlertEvent.id))
        .limit(1)
    ).scalar_one_or_none()


def anomaly_score(alert: Alert) -> float | None:
    """Estrae lo score se il publisher lo ha incluso nel payload descrittivo."""
    return None


def escalation_time(alert: Alert) -> datetime:
    return alert.opened_at + timedelta(minutes=ALERT_ESCALATION_MINUTES)


def is_escalated(alert: Alert) -> bool:
    if alert.status != "new":
        return False
    if alert.escalated_at is not None:
        return True
    opened_at = alert.opened_at
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= opened_at + timedelta(minutes=ALERT_ESCALATION_MINUTES)


def parse_prefixed_id(value: str, prefix: str) -> int | None:
    text = value.removeprefix(f"{prefix}-")
    return int(text) if text.isdigit() else None


def publish_alert_event(event_type: str, alert: Alert, timestamp: datetime) -> None:
    """Invia un evento realtime dopo una modifica alert."""
    event_bus.publish(
        InternalEvent(
            event_type=event_type,
            patient_id=alert.patient_id,
            timestamp=timestamp,
            payload={"alert_id": f"alert-{alert.id}", "status": alert.status},
        )
    )
