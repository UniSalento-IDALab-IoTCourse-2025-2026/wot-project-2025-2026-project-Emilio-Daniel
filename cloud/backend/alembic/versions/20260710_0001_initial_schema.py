"""Initial D3 database schema.

Revision ID: 20260710_0001
Revises: 
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260710_0001"
down_revision = None
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "patients",
        sa.Column("patient_id", sa.String(length=64), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
    )

    op.create_table(
        "doctors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("license_number", sa.String(length=128)),
        *timestamps(),
    )
    op.create_table(
        "caregivers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("relationship", sa.String(length=128)),
        *timestamps(),
    )
    op.create_table(
        "doctor_patients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("doctor_id", "patient_id", name="uq_doctor_patient"),
    )
    op.create_table(
        "caregiver_patients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("caregiver_id", sa.Integer(), sa.ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("caregiver_id", "patient_id", name="uq_caregiver_patient"),
    )

    op.create_table(
        "edge_devices",
        sa.Column("edge_id", sa.String(length=128), primary_key=True),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("app_version", sa.String(length=64)),
        *timestamps(),
    )
    op.create_index("ix_edge_devices_status", "edge_devices", ["status"])
    op.create_index("ix_edge_devices_last_seen_at", "edge_devices", ["last_seen_at"])

    op.create_table(
        "edge_cycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("edge_id", sa.String(length=128), sa.ForeignKey("edge_devices.edge_id", ondelete="SET NULL")),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True)),
        sa.Column("window_end", sa.DateTime(timezone=True)),
        sa.Column("payload", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("message_id", name="uq_edge_cycles_message_id"),
    )
    op.create_index("ix_edge_cycles_patient_id", "edge_cycles", ["patient_id"])
    op.create_index("ix_edge_cycles_timestamp", "edge_cycles", ["timestamp"])
    op.create_index("ix_edge_cycles_patient_window", "edge_cycles", ["patient_id", "window_start", "window_end"])

    op.create_table(
        "feature_windows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("edge_id", sa.String(length=128), sa.ForeignKey("edge_devices.edge_id", ondelete="SET NULL")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("message_id", name="uq_feature_windows_message_id"),
    )
    op.create_index("ix_feature_windows_patient_id", "feature_windows", ["patient_id"])
    op.create_index("ix_feature_windows_timestamp", "feature_windows", ["timestamp"])
    op.create_index("ix_feature_windows_patient_window", "feature_windows", ["patient_id", "window_start", "window_end"])

    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("edge_id", sa.String(length=128), sa.ForeignKey("edge_devices.edge_id", ondelete="SET NULL")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True)),
        sa.Column("window_end", sa.DateTime(timezone=True)),
        sa.Column("level", sa.String(length=32), nullable=False),
        sa.Column("should_publish", sa.Boolean(), nullable=False),
        sa.Column("anomaly_score", sa.Float()),
        sa.Column("model_label", sa.String(length=128)),
        sa.Column("payload", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("message_id", name="uq_decisions_message_id"),
    )
    op.create_index("ix_decisions_patient_id", "decisions", ["patient_id"])
    op.create_index("ix_decisions_timestamp", "decisions", ["timestamp"])
    op.create_index("ix_decisions_level", "decisions", ["level"])
    op.create_index("ix_decisions_patient_level_timestamp", "decisions", ["patient_id", "level", "timestamp"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("decisions.id", ondelete="SET NULL")),
        sa.Column("level", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.UniqueConstraint("message_id", name="uq_alerts_message_id"),
    )
    op.create_index("ix_alerts_patient_id", "alerts", ["patient_id"])
    op.create_index("ix_alerts_level", "alerts", ["level"])
    op.create_index("ix_alerts_status", "alerts", ["status"])
    op.create_index("ix_alerts_opened_at", "alerts", ["opened_at"])
    op.create_index("ix_alerts_patient_status_level", "alerts", ["patient_id", "status", "level"])

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_id", sa.Integer(), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text()),
        *timestamps(),
    )
    op.create_index("ix_alert_events_timestamp", "alert_events", ["timestamp"])
    op.create_index("ix_alert_events_alert_timestamp", "alert_events", ["alert_id", "timestamp"])

    op.create_table(
        "sensor_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sensor_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("details", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("patient_id", "sensor_type", name="uq_sensor_status_patient_type"),
    )
    op.create_index("ix_sensor_status_status", "sensor_status", ["status"])
    op.create_index("ix_sensor_status_last_seen_at", "sensor_status", ["last_seen_at"])
    op.create_index("ix_sensor_status_patient_updated", "sensor_status", ["patient_id", "updated_at"])

    op.create_table(
        "patient_app_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("battery_pct", sa.Float()),
        sa.Column("app_version", sa.String(length=64)),
        *timestamps(),
        sa.UniqueConstraint("patient_id", "device_id", name="uq_patient_app_status_device"),
    )
    op.create_index("ix_patient_app_status_patient_id", "patient_app_status", ["patient_id"])
    op.create_index("ix_patient_app_status_status", "patient_app_status", ["status"])
    op.create_index("ix_patient_app_status_last_seen_at", "patient_app_status", ["last_seen_at"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("instructions", sa.Text()),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("payload", sa.JSON(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_tasks_patient_id", "tasks", ["patient_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_due_at", "tasks", ["due_at"])
    op.create_index("ix_tasks_patient_status_due", "tasks", ["patient_id", "status", "due_at"])

    op.create_table(
        "task_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("result", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("message_id", name="uq_task_results_message_id"),
    )
    op.create_index("ix_task_results_task_id", "task_results", ["task_id"])
    op.create_index("ix_task_results_patient_id", "task_results", ["patient_id"])
    op.create_index("ix_task_results_completed_at", "task_results", ["completed_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    op.create_index("ix_notifications_patient_id", "notifications", ["patient_id"])
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_status", "notifications", ["status"])
    op.create_index("ix_notifications_patient_status", "notifications", ["patient_id", "status"])


def downgrade() -> None:
    for table in [
        "notifications",
        "task_results",
        "tasks",
        "patient_app_status",
        "sensor_status",
        "alert_events",
        "alerts",
        "decisions",
        "feature_windows",
        "edge_cycles",
        "edge_devices",
        "caregiver_patients",
        "doctor_patients",
        "caregivers",
        "doctors",
        "patients",
        "users",
    ]:
        op.drop_table(table)
