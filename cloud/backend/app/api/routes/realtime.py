from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import desc, select

from app.auth.dependencies import can_access_patient, websocket_current_user
from app.db.models import Alert, Decision, FeatureWindow, SensorStatus, Task
from app.db.session import SessionLocal
from app.mqtt.events import InternalEvent, event_bus

router = APIRouter()


@dataclass(frozen=True)
class PatientRealtimeSnapshot:
    """Firma sintetica degli ultimi dati noti per un paziente."""

    latest_window_id: int | None = None
    latest_decision_id: int | None = None
    latest_alert_id: int | None = None
    latest_task_id: int | None = None
    latest_sensor_update: str | None = None


@router.websocket("/patients/{patient_id}")
async def patient_websocket(websocket: WebSocket, patient_id: str) -> None:
    """Connessione WebSocket realtime per un singolo paziente."""
    current_user = await websocket_current_user(websocket)
    if current_user is None:
        await websocket.close(code=1008)
        return
    with SessionLocal() as db:
        if not can_access_patient(db, current_user, patient_id):
            await websocket.close(code=1008)
            return
    await websocket.accept()
    cursor = len(event_bus.events)
    snapshot = load_patient_snapshot(patient_id)
    await websocket.send_json(
        websocket_event(
            event_type="system_status_updated",
            patient_id=patient_id,
            payload={"reason": "websocket_connected"},
        )
    )

    try:
        while True:
            cursor = await flush_memory_events(websocket, patient_id, cursor)
            new_snapshot = load_patient_snapshot(patient_id)
            for event in events_from_snapshot_change(patient_id, snapshot, new_snapshot):
                await websocket.send_json(event.to_websocket_payload())
            snapshot = new_snapshot

            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
            except TimeoutError:
                continue
    except WebSocketDisconnect:
        return


@router.get("/status", summary="Realtime module status")
def realtime_status() -> dict[str, str]:
    """Espone lo stato del modulo WebSocket realtime."""
    return {"status": "implemented", "module": "realtime"}


async def flush_memory_events(websocket: WebSocket, patient_id: str, cursor: int) -> int:
    """Invia gli eventi in memoria prodotti dallo stesso processo FastAPI."""
    next_cursor, events = event_bus.events_after(cursor, patient_id)
    for event in events:
        await websocket.send_json(event.to_websocket_payload())
    return next_cursor


def load_patient_snapshot(patient_id: str) -> PatientRealtimeSnapshot:
    """Legge dal DB una firma leggera degli ultimi aggiornamenti del paziente."""
    with SessionLocal() as db:
        latest_window = db.execute(
            select(FeatureWindow.id)
            .where(FeatureWindow.patient_id == patient_id)
            .order_by(desc(FeatureWindow.window_end), desc(FeatureWindow.id))
            .limit(1)
        ).scalar_one_or_none()
        latest_decision = db.execute(
            select(Decision.id)
            .where(Decision.patient_id == patient_id)
            .order_by(desc(Decision.timestamp), desc(Decision.id))
            .limit(1)
        ).scalar_one_or_none()
        latest_alert = db.execute(
            select(Alert.id)
            .where(Alert.patient_id == patient_id)
            .order_by(desc(Alert.updated_at), desc(Alert.id))
            .limit(1)
        ).scalar_one_or_none()
        latest_task = db.execute(
            select(Task.id)
            .where(Task.patient_id == patient_id)
            .order_by(desc(Task.updated_at), desc(Task.id))
            .limit(1)
        ).scalar_one_or_none()
        latest_sensor_update = db.execute(
            select(SensorStatus.updated_at)
            .where(SensorStatus.patient_id == patient_id)
            .order_by(desc(SensorStatus.updated_at), desc(SensorStatus.id))
            .limit(1)
        ).scalar_one_or_none()
    return PatientRealtimeSnapshot(
        latest_window_id=latest_window,
        latest_decision_id=latest_decision,
        latest_alert_id=latest_alert,
        latest_task_id=latest_task,
        latest_sensor_update=latest_sensor_update.isoformat() if latest_sensor_update else None,
    )


def events_from_snapshot_change(
    patient_id: str,
    old: PatientRealtimeSnapshot,
    new: PatientRealtimeSnapshot,
) -> list[InternalEvent]:
    """Converte cambiamenti DB in eventi WebSocket compatibili con la dashboard."""
    now = datetime.now(timezone.utc)
    events: list[InternalEvent] = []
    if old.latest_window_id != new.latest_window_id:
        events.append(
            InternalEvent(
                event_type="system_status_updated",
                patient_id=patient_id,
                timestamp=now,
                payload={"source": "feature_window", "id": new.latest_window_id},
            )
        )
    if old.latest_decision_id != new.latest_decision_id:
        events.append(
            InternalEvent(
                event_type="decision_updated",
                patient_id=patient_id,
                timestamp=now,
                payload={"source": "decision", "id": new.latest_decision_id},
            )
        )
    if old.latest_alert_id != new.latest_alert_id:
        events.append(
            InternalEvent(
                event_type="alert_created",
                patient_id=patient_id,
                timestamp=now,
                payload={"source": "alert", "id": new.latest_alert_id},
            )
        )
    if old.latest_task_id != new.latest_task_id:
        events.append(
            InternalEvent(
                event_type="task_created",
                patient_id=patient_id,
                timestamp=now,
                payload={"source": "task", "id": new.latest_task_id},
            )
        )
    if old.latest_sensor_update != new.latest_sensor_update:
        events.append(
            InternalEvent(
                event_type="system_status_updated",
                patient_id=patient_id,
                timestamp=now,
                payload={"source": "sensor_status"},
            )
        )
    return events


def websocket_event(event_type: str, patient_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Crea un evento WebSocket immediato senza passare dal bus."""
    return InternalEvent(
        event_type=event_type,
        patient_id=patient_id,
        timestamp=datetime.now(timezone.utc),
        payload=payload,
    ).to_websocket_payload()
