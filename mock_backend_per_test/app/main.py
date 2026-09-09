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
from zoneinfo import ZoneInfo


SCENARIOS = {"normal", "severe_alert", "technical_issue", "missing_data", "absence"}


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
ALERT_OVERRIDES: dict[str, dict[str, Any]] = {}
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
    email = str(payload.get("email") or "")
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


@app.get("/api/v1/patients/{patient_id}/ai/model-metrics")
def patient_ai_model_metrics(patient_id: str) -> dict[str, Any]:
    """Metriche di validazione dei modelli AI per la demo della dashboard."""
    base = {
        "model_id": patient_id,
        "model_scope": "personal",
        "contamination_used": 0.05,
        "training_rows": 1183,
        "validation_rows": 236,
        "precision": 0.91,
        "recall": 0.78,
        "f1": 0.84,
        "accuracy": 0.88,
        "roc_auc": 0.96,
        "true_positives": 41,
        "true_negatives": 167,
        "false_positives": 4,
        "false_negatives": 12,
        "ambiguous_excluded": 12,
        "synthetic_anomalies_added": 50,
        "computed_at": "2026-09-07T07:30:00+00:00",
        "notes": "Model: personal; Training rows: 1183; Contamination: 0.05",
    }
    return {
        "patient_id": patient_id,
        "models": [
            {
                "model": "personal",
                "display_name": f"Modello personale ({patient_id})",
                "model_scope": "personal",
                "model_id": patient_id,
                "f1": 0.84,
                "precision": 0.91,
                "recall": 0.78,
                "accuracy": 0.88,
                "roc_auc": 0.96,
                "validation_rows": 236,
                "training_rows": 1183,
                "computed_at": base["computed_at"],
                "notes": base["notes"],
            },
            {
                "model": "generic_wearable",
                "display_name": "Modello generico wearable",
                "model_scope": "generic_wearable",
                "model_id": "generic_wearable",
                "f1": 0.81,
                "precision": 0.87,
                "recall": 0.76,
                "accuracy": 0.85,
                "roc_auc": 0.93,
                "validation_rows": 4120,
                "training_rows": 30100,
                "computed_at": "2026-08-30T09:00:00+00:00",
                "notes": "Model: generic_wearable; Training rows: 30100",
            },
            {
                "model": "generic_spatial",
                "display_name": "Modello generico spaziale",
                "model_scope": "generic_spatial",
                "model_id": "generic_spatial",
                "f1": 0.82,
                "precision": 0.85,
                "recall": 0.79,
                "accuracy": 0.86,
                "roc_auc": 0.94,
                "validation_rows": 3890,
                "training_rows": 29900,
                "computed_at": "2026-08-28T11:20:00+00:00",
                "notes": "Model: generic_spatial; Training rows: 29900",
            },
        ],
        "last_training_at": base["computed_at"],
        "models_dir": "mock",
        "drift": mock_drift_state(patient_id),
    }


_MOCK_DRIFT_STATES: dict[str, dict[str, Any]] = {}


def mock_drift_state(patient_id: str) -> dict[str, Any]:
    if patient_id not in _MOCK_DRIFT_STATES:
        _MOCK_DRIFT_STATES[patient_id] = {
            "status": "stable",
            "requires_approval": False,
            "baseline_mean": 32.5,
            "baseline_std": 8.2,
            "recent_mean": 34.1,
            "recent_std": 7.8,
            "sample_size": 48,
            "drift_count": 0,
            "drift_since": None,
            "detected_at": None,
            "approved_at": None,
            "retrained_at": None,
            "note": None,
            "log": [
                {
                    "action": "init",
                    "actor_role": "system",
                    "actor_user_id": None,
                    "note": "Inizializzato lo stato di drift del modello personale.",
                    "details": {},
                    "timestamp": "2026-09-08T10:00:00Z",
                }
            ],
        }
    return _MOCK_DRIFT_STATES[patient_id]


@app.get("/api/v1/patients/{patient_id}/ai/drift")
def mock_drift(patient_id: str) -> dict[str, Any]:
    state = mock_drift_state(patient_id)
    return {"patient_id": patient_id, "drift": state, "retraining_log": state.get("log", [])}


@app.post("/api/v1/patients/{patient_id}/ai/retraining/approve")
def mock_approve_retraining(patient_id: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    state = mock_drift_state(patient_id)
    state["status"] = "retrained"
    state["requires_approval"] = False
    state["approved_at"] = now_iso()
    state["retrained_at"] = now_iso()
    state["drift_count"] = 0
    state["note"] = body.get("note") or state.get("note")
    state["log"].insert(0, {
        "action": "approved",
        "actor_role": "doctor",
        "actor_user_id": None,
        "note": state["note"],
        "details": {},
        "timestamp": now_iso(),
    })
    return {"patient_id": patient_id, "status": "retrained", "drift": state}


@app.post("/api/v1/patients/{patient_id}/ai/retraining/reject")
def mock_reject_retraining(patient_id: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    state = mock_drift_state(patient_id)
    state["status"] = "stable"
    state["requires_approval"] = False
    state["drift_count"] = 0
    state["drift_since"] = None
    state["note"] = body.get("note") or state.get("note")
    state["log"].insert(0, {
        "action": "blocked",
        "actor_role": "doctor",
        "actor_user_id": None,
        "note": state["note"],
        "details": {},
        "timestamp": now_iso(),
    })
    return {"patient_id": patient_id, "status": "stable", "drift": state}


@app.get("/api/v1/patients/{patient_id}/alerts")
def patient_alerts(patient_id: str) -> dict[str, Any]:
    scenario = scenario_payload(patient_id)
    return paginated(scenario["alerts"])


@app.get("/api/v1/patients/{patient_id}/day-profile")
def patient_day_profile(patient_id: str) -> dict[str, Any]:
    scenario = scenario_payload(patient_id)
    return mock_day_profile(scenario)


@app.get("/api/v1/patients/{patient_id}/reports/weekly")
def patient_weekly_reports(patient_id: str, limit: int = 8) -> dict[str, Any]:
    scenario = scenario_payload(patient_id)
    reports = mock_weekly_reports(scenario)[: max(1, int(limit))]
    return {"patient_id": patient_id, "items": reports, "reports": reports}


@app.post("/api/v1/patients/{patient_id}/reports/generate")
def patient_generate_weekly_report(patient_id: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    scenario = scenario_payload(patient_id)
    reports = mock_weekly_reports(scenario)
    return {"patient_id": patient_id, "generated": True, "report": reports[0]}


@app.get("/api/v1/patients/{patient_id}/morning-brief")
def patient_morning_brief(patient_id: str) -> dict[str, Any]:
    scenario = scenario_payload(patient_id)
    return mock_morning_brief(scenario)


@app.patch("/api/v1/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    update = {
        "alert_id": alert_id,
        "status": "acknowledged",
        "acknowledged_at": now_iso(),
        "acknowledged_by": payload.get("user_id", "user-doctor-001"),
    }
    ALERT_OVERRIDES.setdefault(alert_id, {}).update(update)
    return apply_alert_override({"alert_id": alert_id})


@app.patch("/api/v1/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    note = payload.get("note")
    if not note:
        raise HTTPException(status_code=422, detail="Resolve note is required.")
    update = {
        "alert_id": alert_id,
        "status": "resolved",
        "resolved_at": now_iso(),
        "resolved_by": payload.get("user_id", "user-doctor-001"),
        "resolution_note": note,
    }
    ALERT_OVERRIDES.setdefault(alert_id, {}).update(update)
    return apply_alert_override({"alert_id": alert_id})


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
    current = scenario.get("current", {})
    decisions = scenario.get("decisions", [])
    last_decision = decisions[-1] if decisions else {}
    trend = (current.get("ai") or {}).get("trend") or last_decision.get("trend") or {}
    drift = (current.get("ai") or {}).get("drift") or last_decision.get("drift") or {"status": "stable"}
    payload = scenario["system_status"]
    payload["ai"] = {
        "fusion_mode": "mock_generic_plus_personal",
        "inference": "completed",
        "personal_model_available": True,
        "baseline": {"status": "ok", "available": True},
        "confidence": current.get("confidence"),
        "trend": trend,
        "drift": drift,
    }
    return payload


@app.websocket("/ws/v1/patients/{patient_id}")
async def patient_websocket(websocket: WebSocket, patient_id: str) -> None:
    scenario_payload(patient_id)
    await websocket.accept()
    interval = websocket_interval_seconds()
    index = 0
    try:
        while True:
            scenario = scenario_payload(patient_id)
            events = scenario["ws_events"]
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
        scenario = build_scenario(active_scenario())
    else:
        profile = patient_profile(patient_id)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Patient not found: {patient_id}")
        scenario = profile_scenario(profile)
    inject_confidence(scenario)
    inject_feature_importance(scenario)
    inject_trend(scenario)
    return scenario


def feature_importance_for(patient_id: str, level: str) -> dict[str, Any]:
    """Feature importance demo coerente con il livello della decisione."""
    impact_push: list[dict[str, Any]] = []
    if str(level or "green").lower() in {"red", "orange", "yellow"}:
        impact_push = [
            {
                "feature": "heart_rate_mean",
                "label": "Frequenza cardiaca media",
                "category": "wearable",
                "impact": "aumenta_indice",
                "weight": 0.42,
                "value": 108.0,
                "reference": 74.0,
                "score_delta": -38.2,
            },
            {
                "feature": "spo2_mean",
                "label": "Saturazione ossigeno (SpO2)",
                "category": "wearable",
                "impact": "aumenta_indice",
                "weight": 0.27,
                "value": 84.5,
                "reference": 97.5,
                "score_delta": -24.1,
            },
            {
                "feature": "steps",
                "label": "Numero di passi",
                "category": "wearable",
                "impact": "riduce_indice",
                "weight": 0.13,
                "value": 180.0,
                "reference": 3100.0,
                "score_delta": 11.7,
            },
        ]
    else:
        impact_push = [
            {
                "feature": "nilm_kitchen_events",
                "label": "Eventi cucina (NILM)",
                "category": "nilm",
                "impact": "riduce_indice",
                "weight": 0.31,
                "value": 4.0,
                "reference": 1.0,
                "score_delta": 9.4,
            },
            {
                "feature": "room_changes",
                "label": "Cambi di stanza",
                "category": "spaziale",
                "impact": "riduce_indice",
                "weight": 0.22,
                "value": 6.0,
                "reference": 2.0,
                "score_delta": 6.8,
            },
        ]
    return {
        "available": True,
        "method": "leave_one_out_median_replacement",
        "baseline_score": 18.5 if str(level or "green").lower() == "green" else 74.0,
        "items": impact_push,
    }


def inject_feature_importance(scenario: dict[str, Any]) -> None:
    current = scenario.get("current")
    if isinstance(current, dict):
        current["feature_importance"] = feature_importance_for(
            current.get("patient_id", "patient-001"), current.get("level", "green")
        )
    for decision in scenario.get("decisions", []):
        if isinstance(decision, dict):
            decision["feature_importance"] = feature_importance_for(
                decision.get("patient_id", "patient-001"), decision.get("level", "green")
            )


def confidence_for(patient_id: str, level: str) -> dict[str, Any]:
    """Metriche demo di confidenza coerenti con il livello della decisione.

    La confidenza resta separata dallo score AI e replica il formato del
    backend reale (`score`, `level`, `reasons`) consumato dalla dashboard.
    """
    normalized = str(level or "green").lower()
    if normalized in {"red", "orange"}:
        base_score = 41
        notes = ["BLE parziale", "Google Health assente", "modello personale non disponibile"]
    elif normalized in {"technical", "missing", "stale"}:
        base_score = 36
        notes = ["dati mancanti o troppo vecchi", "coda MQTT in attesa", "modello non aggiornato"]
    elif normalized == "yellow":
        base_score = 62
        notes = ["BLE completo", "Google Health parziale", "modello personale disponibile"]
    else:
        base_score = 84
        notes = ["BLE completo", "Google Health completo", "modello personale disponibile"]
    level_label = "bassa" if base_score < 45 else "media" if base_score < 75 else "alta"
    return {
        "score": base_score,
        "level": level_label,
        "reasons": notes,
        "sources": [
            {"source": "google_health", "label": "Google Health", "available": True, "completeness": 0.9 if base_score < 84 else 1.0, "present_features": 7, "total_features": 8},
            {"source": "ble", "label": "BLE", "available": True, "completeness": 1.0, "present_features": 8, "total_features": 8},
            {"source": "shelly", "label": "Shelly/NILM", "available": True, "completeness": 0.8, "present_features": 4, "total_features": 5},
        ],
        "missing_features": [],
        "penalties": {},
    }


def inject_confidence(scenario: dict[str, Any]) -> None:
    current = scenario.get("current")
    if isinstance(current, dict):
        level = current.get("level", "green")
        current["confidence"] = confidence_for(current.get("patient_id", "patient-001"), level)
        current["ai_confidence"] = current["confidence"]
    for decision in scenario.get("decisions", []):
        if isinstance(decision, dict) and "confidence" not in decision:
            decision["confidence"] = confidence_for(decision.get("patient_id", "patient-001"), decision.get("level", "green"))


def inject_trend(scenario: dict[str, Any]) -> None:
    """Aggiunge dati trend (D26) a current e decisions per TrendDriftPanel."""
    level = (scenario.get("current") or {}).get("level", "green")
    slope = 0.3 if level == "green" else 1.2 if level == "yellow" else 3.5 if level == "orange" else 4.8
    direction = "stabile" if slope <= 2 else "in_aumento"
    trend = {
        "best": {"score_slope_per_day": round(slope, 1), "direction": direction, "window_days": 7, "n_points": 12},
        "windows": {
            "3": {"score_slope_per_day": round(slope * 0.8, 1), "direction": direction, "window_days": 3, "n_points": 5},
            "7": {"score_slope_per_day": round(slope, 1), "direction": direction, "window_days": 7, "n_points": 12},
            "14": {"score_slope_per_day": round(slope * 1.1, 1), "direction": direction, "window_days": 14, "n_points": 20},
        },
        "features": {
            "steps": {"slope_per_day": -85.0, "direction": "in_diminuzione", "window_days": 14, "n_points": 120},
            "sedentary_minutes": {"slope_per_day": 12.4, "direction": "in_aumento", "window_days": 14, "n_points": 120},
            "sleep_minutes": {"slope_per_day": -4.0, "direction": "in_diminuzione", "window_days": 14, "n_points": 120},
            "bedroom_minutes": {"slope_per_day": 20.0, "direction": "in_aumento", "window_days": 14, "n_points": 120},
            "heart_rate_mean": {"slope_per_day": 0.4, "direction": "stabile", "window_days": 14, "n_points": 120},
        },
    }
    drift = {"status": "stable", "requires_approval": False}
    current = scenario.get("current")
    if isinstance(current, dict):
        ai = current.setdefault("ai", {})
        ai["trend"] = trend
        ai["drift"] = drift
    for decision in scenario.get("decisions", []):
        if isinstance(decision, dict):
            decision["trend"] = trend
            decision["drift"] = drift


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
    if name == "absence":
        return absence_alert_scenario(base)
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
    if alert is not None:
        alert = apply_alert_override(alert)
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


def apply_alert_override(alert: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(alert)
    override = ALERT_OVERRIDES.get(merged["alert_id"])
    if override:
        merged.update(override)
    return merged


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
    alert = apply_alert_override(alert)
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
    alert = apply_alert_override(
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
    )
    scenario["alerts"] = [alert]
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


def absence_alert_scenario(base: dict[str, Any]) -> dict[str, Any]:
    """Scenario di assenza insolita: alert anche con score AI non critico (D24)."""
    scenario = deepcopy(base)
    patient_id = scenario["patient"]["patient_id"]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    scenario["current"].update(
        {
            "level": "yellow",
            "signal_type": "absence",
            "should_publish": False,
            "anomaly_score": 22.0,
            "current_room": "living_room",
            "watch": {
                "present": True,
                "battery_pct": 71,
                "available_features": ["heart_rate_mean", "hrv_rmssd", "spo2_mean"],
            },
            "edge": {
                "online": True,
                "quality_status": "ok",
                "mqtt_queue_depth": 0,
            },
        }
    )
    scenario["decisions"] = make_decisions(now, patient_id, "yellow", 22.0, False)
    alert = apply_alert_override(
        {
            "alert_id": "alert-absence-001",
            "patient_id": patient_id,
            "level": "orange",
            "status": "new",
            "category": "no_movement",
            "title": "Assenza di movimento da verificare",
            "description": "Il sistema segnala una permanenza o assenza di transizioni superiore all'atteso. Verificare con paziente o caregiver.",
            "opened_at": now.isoformat().replace("+00:00", "Z"),
            "anomaly_score": 22.0,
            "payload": {
                "kind": "no_movement",
                "category": "no_movement",
                "reason": "Nessun movimento per oltre 4 ore.",
                "duration_minutes": 297.0,
                "no_movement_minutes": 297.0,
                "last_room": "living_room",
                "last_transition_at": (now - timedelta(hours=4, minutes=57)).isoformat().replace("+00:00", "Z"),
                "ble_quality": "ok",
            },
        }
    )
    scenario["alerts"] = [alert]
    scenario["system_status"] = system_payload(patient_id, now, scenario["current"], "absence")
    scenario["ws_events"] = ws_events(patient_id, scenario["current"], scenario["decisions"][-1], alert)
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


MOCK_DAY_BANDS = ["00-06", "06-10", "10-14", "14-18", "18-22", "22-24"]
MOCK_DAY_TIMEZONE = ZoneInfo("Europe/Rome")
MOCK_DAY_FEATURES = ["heart_rate_mean", "steps", "sedentary_minutes", "room_changes", "sleep_minutes"]


def mock_hour_band(hour: int) -> str:
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


def mock_parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def mock_numeric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def mock_shift_day(items: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    shifted = []
    for item in deepcopy(items):
        start = mock_parse_iso(item["window_start"])
        item["window_start"] = (start + timedelta(days=days)).isoformat().replace("+00:00", "Z")
        item["window_end"] = (start + timedelta(days=days, minutes=4)).isoformat().replace("+00:00", "Z")
        shifted.append(item)
    return shifted


def mock_dominant_room(windows: list[dict[str, Any]]) -> str | None:
    totals: dict[str, float] = {}
    for window in windows:
        for room in ("bedroom_minutes", "kitchen_minutes", "bathroom_minutes", "living_room_minutes"):
            value = mock_numeric(window["features"].get(room))
            if value is None:
                continue
            totals[room] = totals.get(room, 0.0) + value
    if not totals:
        return None
    room, minutes = max(totals.items(), key=lambda item: item[1])
    return room.removesuffix("_minutes") if minutes > 0 else None


def mock_week_bound(base: datetime, days_back: int) -> tuple[datetime, datetime]:
    local = base.astimezone(MOCK_DAY_TIMEZONE)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = monday - timedelta(days=days_back)
    return start.replace(tzinfo=MOCK_DAY_TIMEZONE), (start + timedelta(days=7)).replace(tzinfo=MOCK_DAY_TIMEZONE)


def _mock_week_items(items: list[dict[str, Any]], week_offset: int) -> list[dict[str, Any]]:
    if week_offset == 0:
        return items
    shiftable = [item for item in items if item.get("window_start")]
    return mock_shift_day(shiftable, -7 * week_offset)


def _mock_week_filtered(items: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    filtered = []
    for item in items:
        raw = item.get("window_start") or item.get("timestamp")
        if not raw:
            continue
        ts = mock_parse_iso(raw)
        if start <= ts < end:
            filtered.append(item)
    return filtered


def _mock_week_aggregate(windows: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    sleep_totals: dict[str, float] = {}
    steps_totals: dict[str, float] = {}
    night_totals: dict[str, float] = {}
    for window in windows:
        local = mock_parse_iso(window["window_start"]).astimezone(MOCK_DAY_TIMEZONE).date().isoformat()
        for key, bucket in (("sleep_minutes", sleep_totals), ("steps", steps_totals), ("night_room_changes", night_totals)):
            value = mock_numeric(window["features"].get(key))
            if value is not None:
                bucket[local] = bucket.get(local, 0.0) + value

    level_rank = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
    scores = []
    day_levels: dict[str, int] = {}
    for decision in decisions:
        value = mock_numeric(decision.get("anomaly_score"))
        if value is not None:
            scores.append(value)
        level = str(decision.get("level") or "green")
        if level_rank.get(level, 0) > 0:
            local = mock_parse_iso(decision.get("window_start") or decision.get("timestamp"))
            day = local.astimezone(MOCK_DAY_TIMEZONE).date().isoformat()
            day_levels[day] = max(day_levels.get(day, 0), level_rank[level])

    def average(bucket: dict[str, float]) -> float | None:
        return round(sum(bucket.values()) / len(bucket), 1) if bucket else None

    return {
        "mean_score": round(sum(scores) / len(scores), 1) if scores else None,
        "max_score": round(max(scores), 1) if scores else None,
        "attention_days": sum(1 for value in day_levels.values() if value == 1),
        "risk_days": sum(1 for value in day_levels.values() if value == 2),
        "alert_days": sum(1 for value in day_levels.values() if value == 3),
        "sleep_mean_minutes": average(sleep_totals),
        "steps_mean": average(steps_totals),
        "night_room_changes": average(night_totals),
        "prevalent_room": mock_dominant_room(windows),
    }


def mock_weekly_reports(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    """Report settimanali mock (D28) coerenti con il payload reale del backend."""
    now = datetime.now(timezone.utc)
    windows = scenario.get("windows", [])
    decisions = scenario.get("decisions", [])
    reports = []
    previous: dict[str, Any] | None = None
    for week_offset in range(4):
        start, end = mock_week_bound(now, 7 * week_offset)
        week_windows = _mock_week_filtered(_mock_week_items(windows, week_offset), start, end)
        week_decisions = _mock_week_filtered(_mock_week_items(decisions, week_offset), start, end)
        aggregate = _mock_week_aggregate(week_windows, week_decisions)

        alerts = scenario.get("alerts", [])
        if week_offset:
            alerts = _mock_week_items(alerts, week_offset)
        week_alerts = _mock_week_filtered(alerts, start, end)
        tasks = scenario.get("tasks", [])
        if week_offset:
            tasks = _mock_week_items(tasks, week_offset)
        week_tasks = _mock_week_filtered(tasks, start, end)

        if aggregate["mean_score"] is None:
            aggregate = dict(aggregate)
            aggregate["mean_score"] = round(max(38.0, 26.0 - week_offset * 3.0), 1)
            aggregate["sleep_mean_minutes"] = 445.0 - week_offset * 10.0
            aggregate["steps_mean"] = 3200.0 - week_offset * 180.0
            aggregate["night_room_changes"] = 2.0 + week_offset * 0.4
            aggregate["attention_days"] = max(0, 2 - week_offset)
            aggregate["prevalent_room"] = aggregate["prevalent_room"] or "living_room"
        if aggregate["max_score"] is None:
            aggregate["max_score"] = round(aggregate["mean_score"] + 18.0, 1)

        created = len(week_alerts)
        resolved = sum(1 for alert in week_alerts if str(alert.get("status")).lower() == "resolved")
        tasks_sent = len(week_tasks)
        tasks_completed = max(0, tasks_sent - 1)

        summary = _mock_weekly_summary(aggregate, previous)
        report: dict[str, Any] = {
            "report_id": f"WeeklyReport:mock-{week_offset}",
            "patient_id": scenario.get("patient_id") or scenario.get("patient", {}).get("patient_id"),
            "title": f"Settimana dal {start:%d/%m/%Y} al {end:%d/%m/%Y}",
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "summary": summary,
            "mean_score": aggregate["mean_score"],
            "max_score": aggregate["max_score"],
            "attention_days": aggregate["attention_days"],
            "risk_days": aggregate["risk_days"],
            "alert_days": aggregate["alert_days"],
            "alerts": {"created": created, "resolved": resolved},
            "tasks": {"sent": tasks_sent, "completed": tasks_completed},
            "sleep": {"mean_minutes": aggregate["sleep_mean_minutes"]},
            "steps": {"mean": aggregate["steps_mean"]},
            "prevalent_room": aggregate["prevalent_room"],
            "night_room_changes": aggregate["night_room_changes"],
            "vs_previous_mean_score": previous["mean_score"] if previous else None,
            "vs_previous_attention_days": previous["attention_days"] if previous else None,
        }
        reports.append(report)
        previous = report
    return reports


def _mock_weekly_summary(aggregate: dict[str, Any], previous: dict[str, Any] | None) -> str:
    score_trend = "stabile"
    if previous and previous["mean_score"]:
        delta = (aggregate["mean_score"] - previous["mean_score"]) / previous["mean_score"]
        score_trend = "in aumento" if delta > 0.1 else ("in diminuzione" if delta < -0.1 else "stabile")
    attention = aggregate["attention_days"]
    sleep = aggregate["sleep_mean_minutes"]
    room = aggregate["prevalent_room"]
    parts = [
        f"Score AI medio {aggregate['mean_score']:.0f} ({score_trend} rispetto alla settimana precedente)",
        f"{attention} giorni con attenzione" if attention else "nessun giorno oltre il livello di attenzione",
        f"sonno medio {sleep:.0f} min/night" if sleep else None,
        f"stanza prevalente: {room}" if room else None,
    ]
    return ". ".join(str(part) for part in parts if part is not None) + "."


def mock_day_profile(scenario: dict[str, Any]) -> dict[str, Any]:
    """Profilo circadiano oggi/ieri/baseline coerente con il payload D25."""
    windows = scenario.get("windows", [])
    decisions = scenario.get("decisions", [])
    now = datetime.now(timezone.utc)
    local_now = now.astimezone(MOCK_DAY_TIMEZONE)
    today = local_now.strftime("%Y-%m-%d")
    yesterday = (local_now - timedelta(days=1)).strftime("%Y-%m-%d")

    groups = {"today": windows, "yesterday": mock_shift_day(windows, -1), "baseline": mock_shift_day(windows, -3)}
    score_lists = {
        "today": decisions,
        "yesterday": mock_shift_day(decisions, -1),
        "baseline": mock_shift_day(decisions, -3),
    }

    def row(group: str, band: str) -> dict[str, Any]:
        rows = groups[group]
        band_windows = [
            w for w in rows if mock_hour_band(mock_parse_iso(w["window_start"]).astimezone(MOCK_DAY_TIMEZONE).hour) == band
        ]
        scores = []
        for decision in score_lists.get(group, []):
            local = mock_parse_iso(decision["window_start"]).astimezone(MOCK_DAY_TIMEZONE)
            if mock_hour_band(local.hour) == band:
                scores.append(mock_numeric(decision.get("anomaly_score")))
        scores = [value for value in scores if value is not None]

        def average(feature: str) -> float | None:
            values = [mock_numeric(w["features"].get(feature)) for w in band_windows]
            values = [value for value in values if value is not None]
            return round(sum(values) / len(values), 2) if values else None

        result: dict[str, Any] = {"band": band, "ai": round(sum(scores) / len(scores), 2) if scores else None}
        for feature in MOCK_DAY_FEATURES:
            result[feature] = average(feature)
        result["dominant_room"] = mock_dominant_room(band_windows)
        return result

    return {
        "today": [row("today", band) for band in MOCK_DAY_BANDS],
        "yesterday": [row("yesterday", band) for band in MOCK_DAY_BANDS],
        "baseline_day": [row("baseline", band) for band in MOCK_DAY_BANDS],
        "bands": MOCK_DAY_BANDS,
        "baseline_available": True,
    }


def _mock_night_items(items: list[dict[str, Any]], offset_days: int = 0) -> list[dict[str, Any]]:
    """Seleziona gli item nella fascia notturna 22-08 (timezone demo)."""
    picked = []
    for item in items:
        raw = item.get("window_end") or item.get("window_start") or item.get("timestamp")
        if not raw:
            continue
        ts = mock_parse_iso(raw).astimezone(MOCK_DAY_TIMEZONE) + timedelta(days=offset_days)
        if ts.hour >= 22 or ts.hour < 8:
            picked.append(item)
    return picked


def mock_morning_brief(scenario: dict[str, Any]) -> dict[str, Any]:
    """Brief del mattino mock (D29) coerente con il payload reale."""
    windows = scenario.get("windows", [])
    decisions = scenario.get("decisions", [])
    now = datetime.now(timezone.utc)
    local_now = now.astimezone(MOCK_DAY_TIMEZONE)
    end_date = local_now.date() if local_now.hour >= 8 else local_now.date() - timedelta(days=1)
    end_local = datetime(end_date.year, end_date.month, end_date.day, 8, 0, tzinfo=MOCK_DAY_TIMEZONE)
    start_local = end_local - timedelta(hours=10)

    night_windows = _mock_night_items(windows)
    night_decisions = _mock_night_items(decisions)

    def total(feature: str) -> float | None:
        values = [mock_numeric(item["features"].get(feature)) for item in night_windows]
        values = [value for value in values if value is not None]
        return round(sum(values), 1) if values else None

    def average(feature: str) -> float | None:
        values = [mock_numeric(item["features"].get(feature)) for item in night_windows]
        values = [value for value in values if value is not None]
        return round(sum(values) / len(values), 1) if values else None

    scores = [mock_numeric(item.get("anomaly_score")) for item in night_decisions]
    scores = [score for score in scores if score is not None]

    sleep_minutes = total("sleep_minutes")
    awake_minutes = total("awake_minutes")
    night_room_changes = total("night_room_changes")
    heart_rate = average("heart_rate_mean")
    spo2 = average("spo2_mean")
    away = sum(
        value
        for room in ("kitchen_minutes", "bathroom_minutes", "living_room_minutes")
        for item in night_windows
        if (value := mock_numeric(item["features"].get(room))) is not None
    )
    max_score = round(max(scores), 1) if scores else None

    baseline_windows = _mock_night_items(windows, -1) + _mock_night_items(windows, -2)
    base_sleep_values = [mock_numeric(item["features"].get("sleep_minutes")) for item in baseline_windows]
    base_sleep_values = [value for value in base_sleep_values if value is not None]
    base_sleep = round(sum(base_sleep_values) / len(base_sleep_values), 1) if base_sleep_values else None

    if max_score is not None and max_score >= 70:
        opening = "Notte con segnali da verificare"
    elif max_score is not None and max_score >= 40:
        opening = "Notte con qualche variazione"
    else:
        opening = "Notte complessivamente stabile"
    room_phrase = "senza movimenti notturni rilevati"
    if night_room_changes is not None and night_room_changes > 0:
        room_phrase = f"con {night_room_changes:.0f} movimenti notturni"
    sleep_phrase = "sonno in linea con la media"
    if sleep_minutes is not None and base_sleep is not None:
        sleep_phrase = "sonno leggermente ridotto" if sleep_minutes - base_sleep <= -30 else "sonno leggermente aumentato" if sleep_minutes - base_sleep >= 30 else "sonno in linea con la media"
    elif sleep_minutes is None:
        sleep_phrase = "dati sonno non disponibili"
    summary = f"{opening}, {room_phrase} e {sleep_phrase}."

    count = len(night_windows)
    confidence = "alta" if count >= 6 else ("media" if count >= 2 else "bassa")
    return {
        "patient_id": scenario.get("patient_id") or scenario.get("patient", {}).get("patient_id"),
        "date": end_local.strftime("%Y-%m-%d"),
        "night": {
            "start": start_local.isoformat(),
            "end": end_local.isoformat(),
        },
        "summary": summary,
        "sleep_minutes": sleep_minutes,
        "awake_minutes": awake_minutes,
        "wakeups": len(night_windows) if awake_minutes else 0,
        "night_heart_rate_mean": heart_rate,
        "spo2_mean": spo2,
        "night_room_changes": night_room_changes,
        "away_from_bedroom_minutes": round(away, 1) if away else None,
        "ai_score": round(sum(scores) / len(scores), 1) if scores else None,
        "max_score": max_score,
        "confidence": confidence,
        "counts": {"windows": count, "decisions": len(night_decisions)},
        "baseline": {
            "available": base_sleep is not None,
            "nights": 2 if base_sleep is not None else 0,
            "sleep_minutes": base_sleep,
            "night_heart_rate_mean": None,
            "night_room_changes": None,
            "ai_score": None,
            "max_score": None,
        },
        "vs_baseline": {
            "sleep_delta_minutes": None if sleep_minutes is None or base_sleep is None else round(sleep_minutes - base_sleep, 1),
            "heart_rate_delta": None,
            "room_changes_delta": None,
            "ai_score_delta": None,
        },
        "disclaimer": "Lettura notturna prudente: utile per orientare il controllo del mattino, non sostituisce valutazioni cliniche.",
    }


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
        alert_event_type = "alert_created"
        if alert.get("status") == "acknowledged":
            alert_event_type = "alert_acknowledged"
        elif alert.get("status") == "resolved":
            alert_event_type = "alert_resolved"
        events.append(
            {
                "event_type": alert_event_type,
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
