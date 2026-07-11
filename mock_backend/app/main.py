from __future__ import annotations

import asyncio
import os
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


SCENARIOS = {"normal", "severe_alert", "technical_issue", "missing_data"}


class TaskCreate(BaseModel):
    type: str
    priority: str = "normal"
    expires_at: str | None = None
    title: str
    instructions: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskResultCreate(BaseModel):
    patient_id: str
    started_at: str | None = None
    completed_at: str
    answers: list[dict[str, Any]] = Field(default_factory=list)
    score: float | None = None
    duration_seconds: int | None = None
    device_info: dict[str, Any] = Field(default_factory=dict)


app = FastAPI(
    title="IoT Dashboard Mock Backend",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

TASKS: dict[str, list[dict[str, Any]]] = {}
TASK_RESULTS: dict[str, list[dict[str, Any]]] = {}
PATIENT_PROFILES: list[dict[str, Any]] = [
    {
        "patient_id": "patient-001",
        "display_name": "Paziente Demo",
        "level": "green",
        "signal_type": "routine",
        "score": 18.5,
        "current_room": "kitchen",
        "watch_present": True,
        "watch_battery_pct": 74,
        "edge_online": True,
        "quality_status": "ok",
        "mqtt_queue_depth": 0,
        "age_minutes": 0,
    },
    {
        "patient_id": "patient-002",
        "display_name": "Paziente Osservazione",
        "level": "yellow",
        "signal_type": "clinical",
        "score": 42.0,
        "current_room": "bedroom",
        "watch_present": True,
        "watch_battery_pct": 61,
        "edge_online": True,
        "quality_status": "ok",
        "mqtt_queue_depth": 0,
        "age_minutes": 4,
    },
    {
        "patient_id": "patient-003",
        "display_name": "Paziente Rientro",
        "level": "orange",
        "signal_type": "clinical",
        "score": 68.4,
        "current_room": "bathroom",
        "watch_present": True,
        "watch_battery_pct": 49,
        "edge_online": True,
        "quality_status": "warning",
        "mqtt_queue_depth": 1,
        "age_minutes": 8,
    },
    {
        "patient_id": "patient-004",
        "display_name": "Paziente Priorita",
        "level": "red",
        "signal_type": "clinical",
        "score": 87.2,
        "current_room": "bathroom",
        "watch_present": True,
        "watch_battery_pct": 38,
        "edge_online": True,
        "quality_status": "alert",
        "mqtt_queue_depth": 0,
        "age_minutes": 2,
    },
    {
        "patient_id": "patient-005",
        "display_name": "Paziente Tecnico",
        "level": "technical",
        "signal_type": "technical",
        "score": None,
        "current_room": None,
        "watch_present": False,
        "watch_battery_pct": 4,
        "edge_online": False,
        "quality_status": "warning",
        "mqtt_queue_depth": 5,
        "age_minutes": 22,
    },
]


@app.exception_handler(HTTPException)
async def http_exception_handler(_request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "http_error",
                "message": str(exc.detail),
                "details": {},
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed.",
                "details": {"errors": exc.errors()},
            }
        },
    )


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "IoT Dashboard Mock Backend",
        "version": "0.1.0",
        "environment": "mock",
        "scenario": active_scenario(),
        "timestamp": now_iso(),
    }


@app.get("/ready")
def ready() -> dict[str, Any]:
    return {
        "status": "ready",
        "checks": {
            "configuration": "ok",
            "scenario": active_scenario(),
            "database": "mock_memory",
            "mqtt": "not_required",
        },
    }


@app.post("/api/v1/auth/login")
def login(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    email = str(payload.get("email") or "doctor@example.test")
    role = "doctor" if "caregiver" not in email else "caregiver"
    return {
        "access_token": f"mock-access-{uuid.uuid4().hex}",
        "refresh_token": f"mock-refresh-{uuid.uuid4().hex}",
        "token_type": "bearer",
        "expires_in": 900,
        "user": {
            "user_id": f"user-{role}-001",
            "role": role,
            "display_name": "Dr. Rossi" if role == "doctor" else "Caregiver Demo",
        },
    }


@app.get("/api/v1/patients")
def list_patients() -> dict[str, Any]:
    return {
        "items": patient_summaries(),
        "page": 1,
        "page_size": 20,
        "total": len(PATIENT_PROFILES),
    }


@app.get("/api/v1/patients/{patient_id}/current")
def patient_current(patient_id: str) -> dict[str, Any]:
    scenario = scenario_payload(patient_id)
    return scenario["current"]


@app.get("/api/v1/patients/{patient_id}/windows")
def patient_windows(patient_id: str, limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    scenario = scenario_payload(patient_id)
    items = scenario["windows"][-limit:]
    return paginated(items)


@app.get("/api/v1/patients/{patient_id}/decisions")
def patient_decisions(patient_id: str, limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    scenario = scenario_payload(patient_id)
    items = scenario["decisions"][-limit:]
    return paginated(items)


@app.get("/api/v1/patients/{patient_id}/alerts")
def patient_alerts(patient_id: str) -> dict[str, Any]:
    scenario = scenario_payload(patient_id)
    return paginated(scenario["alerts"])


@app.patch("/api/v1/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return {
        "alert_id": alert_id,
        "status": "acknowledged",
        "acknowledged_at": now_iso(),
        "acknowledged_by": payload.get("user_id", "user-doctor-001"),
    }


@app.patch("/api/v1/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    note = payload.get("note")
    if not note:
        raise HTTPException(status_code=422, detail="Resolve note is required.")
    return {
        "alert_id": alert_id,
        "status": "resolved",
        "resolved_at": now_iso(),
        "resolved_by": payload.get("user_id", "user-doctor-001"),
        "note": note,
    }


@app.post("/api/v1/patients/{patient_id}/tasks")
def create_task(patient_id: str, payload: TaskCreate) -> dict[str, Any]:
    scenario_payload(patient_id)
    task = {
        "task_id": f"task-{uuid.uuid4().hex[:8]}",
        "patient_id": patient_id,
        "status": "created",
        "type": payload.type,
        "priority": payload.priority,
        "expires_at": payload.expires_at,
        "title": payload.title,
        "instructions": payload.instructions,
        "payload": payload.payload,
        "created_at": now_iso(),
    }
    TASKS.setdefault(patient_id, []).append(task)
    return task


@app.get("/api/v1/patients/{patient_id}/tasks")
def list_tasks(patient_id: str) -> dict[str, Any]:
    scenario = scenario_payload(patient_id)
    items = scenario["tasks"] + TASKS.get(patient_id, [])
    return paginated(items)


@app.post("/api/v1/tasks/{task_id}/results")
def create_task_result(task_id: str, payload: TaskResultCreate) -> dict[str, Any]:
    result = {
        "result_id": f"result-{uuid.uuid4().hex[:8]}",
        "task_id": task_id,
        "patient_id": payload.patient_id,
        "status": "received",
        "completed_at": payload.completed_at,
        "duration_seconds": payload.duration_seconds,
        "score": payload.score,
        "answers": payload.answers,
        "device_info": payload.device_info,
        "received_at": now_iso(),
    }
    TASK_RESULTS.setdefault(task_id, []).append(result)
    return result


@app.post("/api/v1/devices/push-token")
def register_push_token(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return {
        "status": "registered",
        "device_id": payload.get("device_id", "device-demo"),
        "registered_at": now_iso(),
    }


@app.post("/api/v1/patients/{patient_id}/app-status")
def app_status(patient_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return {
        "patient_id": patient_id,
        "status": payload.get("status", "active"),
        "battery_pct": payload.get("battery_pct"),
        "updated_at": now_iso(),
    }


@app.get("/api/v1/patients/{patient_id}/system-status")
def system_status(patient_id: str) -> dict[str, Any]:
    scenario = scenario_payload(patient_id)
    return scenario["system_status"]


@app.websocket("/ws/v1/patients/{patient_id}")
async def patient_websocket(websocket: WebSocket, patient_id: str) -> None:
    scenario = scenario_payload(patient_id)
    await websocket.accept()
    interval = websocket_interval_seconds()
    index = 0
    events = scenario["ws_events"]
    try:
        while True:
            event = deepcopy(events[index % len(events)])
            event["event_id"] = f"mock-event-{uuid.uuid4().hex[:10]}"
            event["timestamp"] = now_iso()
            await websocket.send_json(event)
            index += 1
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        return


def active_scenario() -> str:
    requested = os.environ.get("MOCK_SCENARIO", "normal").strip()
    return requested if requested in SCENARIOS else "normal"


def websocket_interval_seconds() -> float:
    try:
        return max(1.0, float(os.environ.get("MOCK_WS_INTERVAL_SECONDS", "5")))
    except ValueError:
        return 5.0


def scenario_payload(patient_id: str = "patient-001") -> dict[str, Any]:
    if patient_id == "patient-001":
        return build_scenario(active_scenario())
    profile = patient_profile(patient_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Patient not found: {patient_id}")
    return profile_scenario(profile)


def patient_summaries() -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for profile in PATIENT_PROFILES:
        scenario = scenario_payload(profile["patient_id"])
        current = scenario["current"]
        summaries.append(
            {
                "patient_id": scenario["patient"]["patient_id"],
                "display_name": scenario["patient"]["display_name"],
                "last_update": current["last_update"],
                "level": current["level"],
                "signal_type": current["signal_type"],
                "current_room": current["current_room"],
                "edge_online": current["edge"]["online"],
                "watch_present": current["watch"]["present"],
                "has_open_alerts": bool(scenario["alerts"]),
            }
        )
    return summaries


def patient_profile(patient_id: str) -> dict[str, Any] | None:
    for profile in PATIENT_PROFILES:
        if profile["patient_id"] == patient_id:
            return profile
    return None


def build_scenario(name: str) -> dict[str, Any]:
    base = base_scenario()
    if name == "normal":
        return base
    if name == "severe_alert":
        return severe_alert_scenario(base)
    if name == "technical_issue":
        return technical_issue_scenario(base)
    if name == "missing_data":
        return missing_data_scenario(base)
    return base


def base_scenario(patient_id: str = "patient-001", display_name: str = "Paziente Demo") -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    windows = make_windows(now, patient_id)
    decisions = make_decisions(now, patient_id, "green", 18.5, False)
    current = {
        "patient_id": patient_id,
        "edge_id": edge_id_for(patient_id),
        "last_update": now.isoformat().replace("+00:00", "Z"),
        "level": "green",
        "signal_type": "routine",
        "should_publish": False,
        "anomaly_score": 18.5,
        "current_room": "kitchen",
        "watch": {
            "present": True,
            "battery_pct": 74,
            "available_features": ["heart_rate_mean", "hrv_rmssd", "spo2_mean"],
        },
        "edge": {
            "online": True,
            "quality_status": "ok",
            "mqtt_queue_depth": 0,
        },
    }
    return {
        "patient": {
            "patient_id": patient_id,
            "display_name": display_name,
        },
        "current": current,
        "windows": windows,
        "decisions": decisions,
        "alerts": [],
        "tasks": default_tasks(patient_id, now),
        "system_status": system_payload(patient_id, now, current, "ok"),
        "ws_events": ws_events(patient_id, current, decisions[-1], None),
    }


def profile_scenario(profile: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    updated_at = now - timedelta(minutes=int(profile["age_minutes"]))
    patient_id = profile["patient_id"]
    level = profile["level"]
    score = profile["score"]
    should_publish = level == "red"
    scenario = base_scenario(patient_id, profile["display_name"])
    scenario["windows"] = make_windows(updated_at, patient_id)
    scenario["decisions"] = make_decisions(updated_at, patient_id, level, score or 0.0, should_publish)
    scenario["current"].update(
        {
            "patient_id": patient_id,
            "edge_id": edge_id_for(patient_id),
            "last_update": updated_at.isoformat().replace("+00:00", "Z"),
            "level": level,
            "signal_type": profile["signal_type"],
            "should_publish": should_publish,
            "anomaly_score": score,
            "current_room": profile["current_room"],
            "watch": {
                "present": profile["watch_present"],
                "battery_pct": profile["watch_battery_pct"],
                "available_features": ["heart_rate_mean", "hrv_rmssd", "spo2_mean"]
                if profile["watch_present"]
                else [],
            },
            "edge": {
                "online": profile["edge_online"],
                "quality_status": profile["quality_status"],
                "mqtt_queue_depth": profile["mqtt_queue_depth"],
            },
        }
    )
    alert = alert_for_profile(profile, updated_at)
    scenario["alerts"] = [] if alert is None else [alert]
    scenario["system_status"] = system_payload(patient_id, updated_at, scenario["current"], profile["signal_type"])
    scenario["ws_events"] = ws_events(patient_id, scenario["current"], scenario["decisions"][-1], alert)
    return scenario


def edge_id_for(patient_id: str) -> str:
    suffix = patient_id.rsplit("-", maxsplit=1)[-1]
    return f"edge-rpi5-{suffix}"


def alert_for_profile(profile: dict[str, Any], opened_at: datetime) -> dict[str, Any] | None:
    level = profile["level"]
    if level not in {"orange", "red", "technical"}:
        return None
    category = "technical" if profile["signal_type"] == "technical" else "behavioral"
    title = "Problema tecnico da verificare" if category == "technical" else "Anomalia comportamentale da revisionare"
    description = (
        "Watch o Edge non risultano disponibili con dati recenti."
        if category == "technical"
        else "Pattern spaziale e comportamentale fuori dalla routine attesa."
    )
    return {
        "alert_id": f"alert-{profile['patient_id']}",
        "patient_id": profile["patient_id"],
        "level": level,
        "status": "new",
        "category": category,
        "title": title,
        "description": description,
        "opened_at": opened_at.isoformat().replace("+00:00", "Z"),
        "anomaly_score": profile["score"],
    }


def severe_alert_scenario(base: dict[str, Any]) -> dict[str, Any]:
    scenario = deepcopy(base)
    patient_id = scenario["patient"]["patient_id"]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    alert = {
        "alert_id": "alert-red-001",
        "patient_id": patient_id,
        "level": "red",
        "status": "new",
        "category": "behavioral",
        "title": "Anomalia severa confermata",
        "description": "Wandering notturno e stress fisiologico elevato.",
        "opened_at": now.isoformat().replace("+00:00", "Z"),
        "anomaly_score": 87.2,
    }
    scenario["current"].update(
        {
            "level": "red",
            "signal_type": "clinical",
            "should_publish": True,
            "anomaly_score": 87.2,
            "current_room": "bathroom",
        }
    )
    scenario["decisions"] = make_decisions(now, patient_id, "red", 87.2, True)
    scenario["alerts"] = [alert]
    scenario["system_status"] = system_payload(patient_id, now, scenario["current"], "alert")
    scenario["ws_events"] = ws_events(patient_id, scenario["current"], scenario["decisions"][-1], alert)
    return scenario


def technical_issue_scenario(base: dict[str, Any]) -> dict[str, Any]:
    scenario = deepcopy(base)
    patient_id = scenario["patient"]["patient_id"]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    scenario["current"].update(
        {
            "level": "technical",
            "signal_type": "technical",
            "should_publish": False,
            "anomaly_score": None,
            "current_room": None,
            "watch": {
                "present": False,
                "battery_pct": 4,
                "available_features": [],
            },
            "edge": {
                "online": True,
                "quality_status": "warning",
                "mqtt_queue_depth": 3,
            },
        }
    )
    scenario["system_status"] = system_payload(patient_id, now, scenario["current"], "technical")
    scenario["alerts"] = [
        {
            "alert_id": "alert-tech-001",
            "patient_id": patient_id,
            "level": "technical",
            "status": "new",
            "category": "technical",
            "title": "Wearable non disponibile",
            "description": "Google Health non sta inviando dati recenti.",
            "opened_at": now.isoformat().replace("+00:00", "Z"),
            "anomaly_score": None,
        }
    ]
    scenario["ws_events"] = ws_events(
        patient_id,
        scenario["current"],
        scenario["decisions"][-1],
        scenario["alerts"][0],
    )
    return scenario


def missing_data_scenario(base: dict[str, Any]) -> dict[str, Any]:
    scenario = deepcopy(base)
    patient_id = scenario["patient"]["patient_id"]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    scenario["current"].update(
        {
            "level": "yellow",
            "signal_type": "clinical",
            "should_publish": False,
            "anomaly_score": 41.0,
            "watch": {
                "present": True,
                "battery_pct": None,
                "available_features": ["spo2_mean"],
            },
            "edge": {
                "online": True,
                "quality_status": "warning",
                "mqtt_queue_depth": 0,
            },
        }
    )
    for item in scenario["windows"]:
        item["features"]["heart_rate_mean"] = None
        item["features"]["heart_rate_std"] = None
        item["features"]["steps"] = None
    scenario["decisions"] = make_decisions(now, patient_id, "yellow", 41.0, False)
    scenario["system_status"] = system_payload(patient_id, now, scenario["current"], "missing_data")
    scenario["ws_events"] = ws_events(patient_id, scenario["current"], scenario["decisions"][-1], None)
    return scenario


def make_windows(now: datetime, patient_id: str) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for index in range(12, 0, -1):
        end = now - timedelta(minutes=4 * (index - 1))
        start = end - timedelta(minutes=4)
        kitchen = 3.5 if index % 3 else 1.2
        bedroom = 0.0 if index % 4 else 2.1
        bathroom = 0.2 if index % 5 else 1.1
        windows.append(
            {
                "window_id": f"window-{index:03d}",
                "patient_id": patient_id,
                "window_start": start.isoformat().replace("+00:00", "Z"),
                "window_end": end.isoformat().replace("+00:00", "Z"),
                "features": {
                    "wearable_present": True,
                    "wearable_battery_pct": 74,
                    "heart_rate_mean": 72 + (index % 4),
                    "heart_rate_std": 5.2,
                    "resting_heart_rate": 51,
                    "hrv_rmssd": 55.0,
                    "spo2_mean": 96.0,
                    "sleep_minutes": 400,
                    "awake_minutes": 35,
                    "steps": 12 * index,
                    "sedentary_minutes": 2.0,
                    "room_changes": 1 if index % 3 == 0 else 0,
                    "night_room_changes": 0,
                    "bedroom_minutes": bedroom,
                    "kitchen_minutes": kitchen,
                    "bathroom_minutes": bathroom,
                    "living_room_minutes": max(0.0, 4.0 - kitchen - bedroom - bathroom),
                    "longest_single_room_minutes": max(kitchen, bedroom, bathroom),
                    "fall_events": 0,
                },
            }
        )
    return windows


def make_decisions(
    now: datetime,
    patient_id: str,
    level: str,
    score: float,
    should_publish: bool,
) -> list[dict[str, Any]]:
    return [
        {
            "decision_id": f"decision-{index:03d}",
            "patient_id": patient_id,
            "timestamp": (now - timedelta(minutes=4 * (4 - index))).isoformat().replace("+00:00", "Z"),
            "window_start": (now - timedelta(minutes=4 * (5 - index))).isoformat().replace("+00:00", "Z"),
            "window_end": (now - timedelta(minutes=4 * (4 - index))).isoformat().replace("+00:00", "Z"),
            "level": level if index == 4 else "green",
            "should_publish": should_publish if index == 4 else False,
            "anomaly_score": score if index == 4 else 20.0 + index,
            "model_label": "mock_fusion",
            "reasons": ["Scenario mock per sviluppo frontend"],
            "evidence": {
                "fusion": {
                    "mode": "mock_generic_plus_personal",
                    "score": score if index == 4 else 20.0 + index,
                    "weights": {
                        "generic_spatial": 0.15,
                        "generic_wearable": 0.15,
                        "personal": 0.70,
                    },
                    "models": {
                        "generic_spatial": {"available": True, "score": 22.0},
                        "generic_wearable": {"available": True, "score": 18.0},
                        "personal": {"available": True, "score": score},
                    },
                }
            },
        }
        for index in range(1, 5)
    ]


def default_tasks(patient_id: str, now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "task_id": "task-checkin-001",
            "patient_id": patient_id,
            "status": "created",
            "type": "check_in",
            "priority": "normal",
            "title": "Controllo benessere",
            "instructions": "Rispondi a queste brevi domande.",
            "due_at": (now + timedelta(hours=8)).isoformat().replace("+00:00", "Z"),
            "payload": {
                "questions": [
                    {
                        "id": "q1",
                        "type": "single_choice",
                        "text": "Come ti senti adesso?",
                        "options": ["bene", "cosi_cosi", "male"],
                    }
                ]
            },
            "created_at": now.isoformat().replace("+00:00", "Z"),
        }
    ]


def system_payload(patient_id: str, now: datetime, current: dict[str, Any], mode: str) -> dict[str, Any]:
    return {
        "patient_id": patient_id,
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "edge": {
            "online": current["edge"]["online"],
            "quality_status": current["edge"]["quality_status"],
            "mqtt_queue_depth": current["edge"]["mqtt_queue_depth"],
            "last_cycle_at": current["last_update"],
        },
        "sensors": {
            "watch": {
                "status": "active" if current["watch"]["present"] else "missing",
                "battery_pct": current["watch"]["battery_pct"],
            },
            "ble": {
                "status": "active" if current["current_room"] else "stale",
                "current_room": current["current_room"],
            },
            "google_health": {
                "status": "active" if current["watch"]["available_features"] else "stale",
                "available_features": current["watch"]["available_features"],
            },
        },
    }


def ws_events(
    patient_id: str,
    current: dict[str, Any],
    decision: dict[str, Any],
    alert: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    events = [
        {
            "event_type": "system_status_updated",
            "event_id": "mock-event-system",
            "patient_id": patient_id,
            "timestamp": now_iso(),
            "payload": {"current": current},
        },
        {
            "event_type": "decision_updated",
            "event_id": "mock-event-decision",
            "patient_id": patient_id,
            "timestamp": now_iso(),
            "payload": decision,
        },
    ]
    if alert is not None:
        events.append(
            {
                "event_type": "alert_created",
                "event_id": "mock-event-alert",
                "patient_id": patient_id,
                "timestamp": now_iso(),
                "payload": alert,
            }
        )
    return events


def assert_patient(patient_id: str, scenario: dict[str, Any]) -> None:
    if patient_id != scenario["patient"]["patient_id"]:
        raise HTTPException(status_code=404, detail=f"Patient not found: {patient_id}")


def paginated(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "items": items,
        "page": 1,
        "page_size": len(items),
        "total": len(items),
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
