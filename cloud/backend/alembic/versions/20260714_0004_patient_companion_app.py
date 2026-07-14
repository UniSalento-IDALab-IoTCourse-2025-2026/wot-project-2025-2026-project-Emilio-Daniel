"""Add patient companion device and task-delivery fields.

Revision ID: 20260714_0004
Revises: 20260713_0003
Create Date: 2026-07-14 12:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260714_0004"
down_revision = "20260713_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patient_app_status",
        sa.Column("platform", sa.String(length=32), nullable=False, server_default="android"),
    )
    op.add_column("patient_app_status", sa.Column("fcm_token", sa.Text(), nullable=True))
    op.add_column(
        "patient_app_status",
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("patient_app_status", "platform", server_default=None)
    op.alter_column("patient_app_status", "notifications_enabled", server_default=None)

    op.add_column("tasks", sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("last_device_id", sa.String(length=128), nullable=True))
    op.create_index("ix_tasks_seen_at", "tasks", ["seen_at"])
    op.create_index("ix_tasks_started_at", "tasks", ["started_at"])
    op.create_index("ix_tasks_completed_at", "tasks", ["completed_at"])

    op.add_column("notifications", sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_notifications_seen_at", "notifications", ["seen_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_seen_at", table_name="notifications")
    op.drop_column("notifications", "seen_at")

    op.drop_index("ix_tasks_completed_at", table_name="tasks")
    op.drop_index("ix_tasks_started_at", table_name="tasks")
    op.drop_index("ix_tasks_seen_at", table_name="tasks")
    op.drop_column("tasks", "last_device_id")
    op.drop_column("tasks", "completed_at")
    op.drop_column("tasks", "started_at")
    op.drop_column("tasks", "seen_at")

    op.drop_column("patient_app_status", "notifications_enabled")
    op.drop_column("patient_app_status", "fcm_token")
    op.drop_column("patient_app_status", "platform")
