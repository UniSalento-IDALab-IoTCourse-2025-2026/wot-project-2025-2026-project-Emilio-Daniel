from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    Alert,
    AlertEvent,
    AuditLog,
    Decision,
    EdgeCycle,
    EdgeDevice,
    FeatureWindow,
    ModelRetrainingLog,
    Notification,
    Patient,
    PatientAppStatus,
    PatientModelDrift,
    QuestionnaireSchedule,
    SensorStatus,
    Task,
    TaskResult,
    WeeklyReport,
)


def patient_data_summary(
    db: Session,
    patient_id: str,
    *,
    include_audit: bool = False,
) -> dict[str, Any]:
    """Return the records affected by a patient reset without changing data."""
    _require_patient(db, patient_id)
    alert_ids = select(Alert.id).where(Alert.patient_id == patient_id)
    task_ids = select(Task.id).where(Task.patient_id == patient_id)

    counts = {
        "questionnaire_schedules": _count(db, QuestionnaireSchedule, QuestionnaireSchedule.patient_id == patient_id),
        "task_results": _count(db, TaskResult, TaskResult.task_id.in_(task_ids)),
        "tasks": _count(db, Task, Task.patient_id == patient_id),
        "alert_events": _count(db, AlertEvent, AlertEvent.alert_id.in_(alert_ids)),
        "alerts": _count(db, Alert, Alert.patient_id == patient_id),
        "notifications": _count(db, Notification, Notification.patient_id == patient_id),
        "weekly_reports": _count(db, WeeklyReport, WeeklyReport.patient_id == patient_id),
        "model_retraining_logs": _count(db, ModelRetrainingLog, ModelRetrainingLog.patient_id == patient_id),
        "patient_model_drift": _count(db, PatientModelDrift, PatientModelDrift.patient_id == patient_id),
        "sensor_status": _count(db, SensorStatus, SensorStatus.patient_id == patient_id),
        "feature_windows": _count(db, FeatureWindow, FeatureWindow.patient_id == patient_id),
        "edge_cycles": _count(db, EdgeCycle, EdgeCycle.patient_id == patient_id),
        "decisions": _count(db, Decision, Decision.patient_id == patient_id),
    }
    if include_audit:
        counts["audit_logs"] = _count(db, AuditLog, AuditLog.patient_id == patient_id)

    return {
        "patient_id": patient_id,
        "include_audit": include_audit,
        "counts": counts,
        "total_records": sum(counts.values()),
        "preserved": [
            "patient profile",
            "doctor, caregiver and patient account associations",
            "users and refresh tokens",
            "questionnaire templates",
            "edge and Android device registrations",
        ],
    }


def reset_patient_data(
    db: Session,
    patient_id: str,
    *,
    include_audit: bool = False,
) -> dict[str, Any]:
    """Delete historical data for one patient while preserving identity bindings."""
    before = patient_data_summary(db, patient_id, include_audit=include_audit)
    alert_ids = select(Alert.id).where(Alert.patient_id == patient_id)
    task_ids = select(Task.id).where(Task.patient_id == patient_id)

    operations = [
        ("questionnaire_schedules", delete(QuestionnaireSchedule).where(QuestionnaireSchedule.patient_id == patient_id)),
        ("task_results", delete(TaskResult).where(TaskResult.task_id.in_(task_ids))),
        ("tasks", delete(Task).where(Task.patient_id == patient_id)),
        ("alert_events", delete(AlertEvent).where(AlertEvent.alert_id.in_(alert_ids))),
        ("alerts", delete(Alert).where(Alert.patient_id == patient_id)),
        ("notifications", delete(Notification).where(Notification.patient_id == patient_id)),
        ("weekly_reports", delete(WeeklyReport).where(WeeklyReport.patient_id == patient_id)),
        ("model_retraining_logs", delete(ModelRetrainingLog).where(ModelRetrainingLog.patient_id == patient_id)),
        ("patient_model_drift", delete(PatientModelDrift).where(PatientModelDrift.patient_id == patient_id)),
        ("sensor_status", delete(SensorStatus).where(SensorStatus.patient_id == patient_id)),
        ("feature_windows", delete(FeatureWindow).where(FeatureWindow.patient_id == patient_id)),
        ("edge_cycles", delete(EdgeCycle).where(EdgeCycle.patient_id == patient_id)),
        ("decisions", delete(Decision).where(Decision.patient_id == patient_id)),
    ]
    if include_audit:
        operations.append(("audit_logs", delete(AuditLog).where(AuditLog.patient_id == patient_id)))

    deleted: dict[str, int] = {}
    for name, statement in operations:
        result = db.execute(statement)
        deleted[name] = int(result.rowcount or 0)

    edge_result = db.execute(
        update(EdgeDevice)
        .where(EdgeDevice.patient_id == patient_id)
        .values(status="unknown", last_seen_at=None)
    )
    app_result = db.execute(
        update(PatientAppStatus)
        .where(PatientAppStatus.patient_id == patient_id)
        .values(status="unknown", last_seen_at=None, battery_pct=None)
    )

    return {
        **before,
        "status": "reset_completed",
        "deleted": deleted,
        "deleted_total": sum(deleted.values()),
        "device_rows_reset": {
            "edge_devices": int(edge_result.rowcount or 0),
            "patient_app_status": int(app_result.rowcount or 0),
        },
    }


def patient_telemetry_summary(db: Session, patient_id: str) -> dict[str, Any]:
    """Return only Edge-derived records affected by a telemetry cleanup."""
    _require_patient(db, patient_id)
    generated_alerts = _generated_alert_ids(patient_id)
    counts = {
        "alert_events": _count(db, AlertEvent, AlertEvent.alert_id.in_(generated_alerts)),
        "generated_alerts": _count(db, Alert, Alert.id.in_(generated_alerts)),
        "alert_notifications": _count(
            db,
            Notification,
            (Notification.patient_id == patient_id)
            & (Notification.payload["type"].as_string() == "alert_created"),
        ),
        "weekly_reports": _count(db, WeeklyReport, WeeklyReport.patient_id == patient_id),
        "patient_model_drift": _count(db, PatientModelDrift, PatientModelDrift.patient_id == patient_id),
        "sensor_status": _count(db, SensorStatus, SensorStatus.patient_id == patient_id),
        "feature_windows": _count(db, FeatureWindow, FeatureWindow.patient_id == patient_id),
        "edge_cycles": _count(db, EdgeCycle, EdgeCycle.patient_id == patient_id),
        "decisions": _count(db, Decision, Decision.patient_id == patient_id),
    }
    return {
        "patient_id": patient_id,
        "scope": "telemetry_only",
        "counts": counts,
        "total_records": sum(counts.values()),
        "preserved": [
            "patient profile and account associations",
            "tasks, task results and questionnaires",
            "doctor and caregiver messages",
            "device registrations and FCM tokens",
            "model files and model retraining audit",
            "manual alerts and audit logs",
        ],
    }


def reset_patient_telemetry(db: Session, patient_id: str) -> dict[str, Any]:
    """Delete captured/derived telemetry while preserving the personal model workflow."""
    before = patient_telemetry_summary(db, patient_id)
    generated_alerts = _generated_alert_ids(patient_id)
    operations = [
        ("alert_events", delete(AlertEvent).where(AlertEvent.alert_id.in_(generated_alerts))),
        (
            "alert_notifications",
            delete(Notification).where(
                Notification.patient_id == patient_id,
                Notification.payload["type"].as_string() == "alert_created",
            ),
        ),
        ("generated_alerts", delete(Alert).where(Alert.id.in_(generated_alerts))),
        ("weekly_reports", delete(WeeklyReport).where(WeeklyReport.patient_id == patient_id)),
        ("patient_model_drift", delete(PatientModelDrift).where(PatientModelDrift.patient_id == patient_id)),
        ("sensor_status", delete(SensorStatus).where(SensorStatus.patient_id == patient_id)),
        ("feature_windows", delete(FeatureWindow).where(FeatureWindow.patient_id == patient_id)),
        ("edge_cycles", delete(EdgeCycle).where(EdgeCycle.patient_id == patient_id)),
        ("decisions", delete(Decision).where(Decision.patient_id == patient_id)),
    ]
    deleted: dict[str, int] = {}
    for name, statement in operations:
        result = db.execute(statement)
        deleted[name] = int(result.rowcount or 0)

    edge_result = db.execute(
        update(EdgeDevice)
        .where(EdgeDevice.patient_id == patient_id)
        .values(status="unknown", last_seen_at=None)
    )
    return {
        **before,
        "status": "telemetry_reset_completed",
        "deleted": deleted,
        "deleted_total": sum(deleted.values()),
        "device_rows_reset": {"edge_devices": int(edge_result.rowcount or 0)},
    }


def _generated_alert_ids(patient_id: str) -> Any:
    return select(Alert.id).where(
        Alert.patient_id == patient_id,
        (Alert.decision_id.is_not(None))
        | (Alert.source.in_(("edge", "ai", "trend", "system"))),
    )


def _require_patient(db: Session, patient_id: str) -> None:
    if db.get(Patient, patient_id) is None:
        raise ValueError(f"Patient not found: {patient_id}")


def _count(db: Session, model: type[Any], condition: Any) -> int:
    value = db.scalar(select(func.count()).select_from(model).where(condition))
    return int(value or 0)
