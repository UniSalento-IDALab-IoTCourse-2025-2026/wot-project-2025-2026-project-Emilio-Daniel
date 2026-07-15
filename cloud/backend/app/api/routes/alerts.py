from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.api.routes.patients import current_payload, get_patient_or_404
from app.api.routes.utils import dump_event_note, event_note_payload, paginated, utc_iso
from app.auth.dependencies import CurrentUser, authorized_patient_ids, can_access_patient, get_current_user, require_patient_access, write_audit
from app.db.models import Alert, AlertEvent, Patient
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
