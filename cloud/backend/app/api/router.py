from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import admin, alerts, auth, health, notifications, patients, realtime, tasks, telemetry

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(patients.router, prefix="/patients", tags=["patients"])
api_router.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(realtime.router, prefix="/realtime", tags=["realtime"])

ws_router = APIRouter()
ws_router.include_router(realtime.router, prefix="/ws/v1", tags=["realtime"])
