from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class Patient(TimestampMixin, Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Doctor(TimestampMixin, Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    license_number: Mapped[str | None] = mapped_column(String(128))


class Caregiver(TimestampMixin, Base):
    __tablename__ = "caregivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    relationship: Mapped[str | None] = mapped_column(String(128))


class DoctorPatient(TimestampMixin, Base):
    __tablename__ = "doctor_patients"
    __table_args__ = (UniqueConstraint("doctor_id", "patient_id", name="uq_doctor_patient"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False)


class CaregiverPatient(TimestampMixin, Base):
    __tablename__ = "caregiver_patients"
    __table_args__ = (UniqueConstraint("caregiver_id", "patient_id", name="uq_caregiver_patient"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    caregiver_id: Mapped[int] = mapped_column(ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False)


class PatientUser(TimestampMixin, Base):
    __tablename__ = "patient_users"
    __table_args__ = (UniqueConstraint("user_id", "patient_id", name="uq_patient_user_patient"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False)


class RefreshToken(TimestampMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        Index("ix_refresh_tokens_user_revoked", "user_id", "revoked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    user_agent: Mapped[str | None] = mapped_column(String(255))


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_actor_timestamp", "actor_user_id", "timestamp"),
        Index("ix_audit_logs_patient_timestamp", "patient_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.patient_id", ondelete="SET NULL"), index=True)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(128))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class EdgeDevice(TimestampMixin, Base):
    __tablename__ = "edge_devices"

    edge_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    app_version: Mapped[str | None] = mapped_column(String(64))


class EdgeCycle(TimestampMixin, Base):
    __tablename__ = "edge_cycles"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_edge_cycles_message_id"),
        Index("ix_edge_cycles_patient_window", "patient_id", "window_start", "window_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    edge_id: Mapped[str | None] = mapped_column(ForeignKey("edge_devices.edge_id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class FeatureWindow(TimestampMixin, Base):
    __tablename__ = "feature_windows"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_feature_windows_message_id"),
        Index("ix_feature_windows_patient_window", "patient_id", "window_start", "window_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    edge_id: Mapped[str | None] = mapped_column(ForeignKey("edge_devices.edge_id", ondelete="SET NULL"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Decision(TimestampMixin, Base):
    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_decisions_message_id"),
        Index("ix_decisions_patient_level_timestamp", "patient_id", "level", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    edge_id: Mapped[str | None] = mapped_column(ForeignKey("edge_devices.edge_id", ondelete="SET NULL"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    should_publish: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    model_label: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_alerts_message_id"),
        Index("ix_alerts_patient_status_level", "patient_id", "status", "level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id", ondelete="SET NULL"))
    level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), default="behavioral", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="edge", nullable=False)
    clinical_severity: Mapped[str | None] = mapped_column(String(32))
    technical_severity: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class AlertEvent(TimestampMixin, Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_alert_timestamp", "alert_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text)


class SensorStatus(TimestampMixin, Base):
    __tablename__ = "sensor_status"
    __table_args__ = (
        UniqueConstraint("patient_id", "sensor_type", name="uq_sensor_status_patient_type"),
        Index("ix_sensor_status_patient_updated", "patient_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False)
    sensor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class PatientAppStatus(TimestampMixin, Base):
    __tablename__ = "patient_app_status"
    __table_args__ = (UniqueConstraint("patient_id", "device_id", name="uq_patient_app_status_device"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    battery_pct: Mapped[float | None] = mapped_column(Float)
    app_version: Mapped[str | None] = mapped_column(String(64))
    platform: Mapped[str] = mapped_column(String(32), default="android", nullable=False)
    fcm_token: Mapped[str | None] = mapped_column(Text)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_patient_status_due", "patient_id", "status", "due_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_device_id: Mapped[str | None] = mapped_column(String(128))


class TaskResult(TimestampMixin, Base):
    __tablename__ = "task_results"
    __table_args__ = (UniqueConstraint("message_id", name="uq_task_results_message_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class QuestionnaireTemplate(TimestampMixin, Base):
    __tablename__ = "questionnaire_templates"
    __table_args__ = (
        UniqueConstraint("template_key", "version", name="uq_questionnaire_templates_key_version"),
        Index("ix_questionnaire_templates_active", "is_active", "template_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(64), default="check_in", nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    scoring: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    default_priority: Mapped[str] = mapped_column(String(32), default="normal", nullable=False)
    default_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class QuestionnaireSchedule(TimestampMixin, Base):
    __tablename__ = "questionnaire_schedules"
    __table_args__ = (
        Index("ix_questionnaire_schedules_patient_status_next", "patient_id", "status", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("questionnaire_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    frequency: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone_name: Mapped[str] = mapped_column(String(64), default="Europe/Rome", nullable=False)
    title_override: Mapped[str | None] = mapped_column(String(255))
    instructions_override: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(String(32))
    payload_overrides: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_patient_status", "patient_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class PatientModelDrift(TimestampMixin, Base):
    """Stato di drift del modello personale (D27).

    Tiene traccia della distribuzione degli score del paziente: media/varianza
    su una finestra baseline e una recente, con stati stable/possible_drift/
    needs_review/retrained e il ciclo di approvazione del medico.
    """

    __tablename__ = "patient_model_drift"
    __table_args__ = (
        Index("ix_patient_model_drift_patient_status", "patient_id", "status"),
        UniqueConstraint("patient_id", name="uq_patient_model_drift_patient"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="stable", nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    drift_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    baseline_mean: Mapped[float | None] = mapped_column(Float)
    baseline_std: Mapped[float | None] = mapped_column(Float)
    recent_mean: Mapped[float | None] = mapped_column(Float)
    recent_std: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    baseline_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    drift_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class ModelRetrainingLog(TimestampMixin, Base):
    """Log delle azioni di retraining del modello personale (D27)."""

    __tablename__ = "model_retraining_logs"
    __table_args__ = (Index("ix_model_retraining_logs_patient", "patient_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_role: Mapped[str | None] = mapped_column(String(32))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class WeeklyReport(TimestampMixin, Base):
    """Report settimanale automatico per paziente (D28).

    Riepilogo clinico-operativo di una settimana: score AI medi/massimi,
    giorni con attenzione/rischio/allerta, alert creati e risolti, task
    inviati e completati, sonno e passi medi, stanza prevalente e cambi
    notturni, sempre confrontati con la settimana precedente quando
    disponibile.
    """

    __tablename__ = "weekly_reports"
    __table_args__ = (
        UniqueConstraint("patient_id", "week_start", name="uq_weekly_reports_patient_week_start"),
        Index("ix_weekly_reports_patient_week_start", "patient_id", "week_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    week_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    mean_score: Mapped[float | None] = mapped_column(Float)
    max_score: Mapped[float | None] = mapped_column(Float)
    attention_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    alert_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    alerts_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    alerts_resolved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sleep_mean_minutes: Mapped[float | None] = mapped_column(Float)
    steps_mean: Mapped[float | None] = mapped_column(Float)
    prevalent_room: Mapped[str | None] = mapped_column(String(64))
    night_room_changes: Mapped[float | None] = mapped_column(Float)
    vs_previous_mean_score: Mapped[float | None] = mapped_column(Float)
    vs_previous_attention_days: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
