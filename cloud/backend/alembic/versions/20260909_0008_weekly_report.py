"""Add weekly report table (D28).

Revision ID: 20260909_0008
Revises: 20260908_0007
Create Date: 2026-09-09 09:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260909_0008"
down_revision = "20260908_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String(), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("week_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mean_score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("attention_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("risk_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("alert_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("alerts_created", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("alerts_resolved", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tasks_sent", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tasks_completed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sleep_mean_minutes", sa.Float(), nullable=True),
        sa.Column("steps_mean", sa.Float(), nullable=True),
        sa.Column("prevalent_room", sa.String(length=64), nullable=True),
        sa.Column("night_room_changes", sa.Float(), nullable=True),
        sa.Column("vs_previous_mean_score", sa.Float(), nullable=True),
        sa.Column("vs_previous_attention_days", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("patient_id", "week_start", name="uq_weekly_reports_patient_week_start"),
    )
    op.create_index(
        "ix_weekly_reports_patient_week_start", "weekly_reports", ["patient_id", "week_start"]
    )


def downgrade() -> None:
    op.drop_index("ix_weekly_reports_patient_week_start", table_name="weekly_reports")
    op.drop_table("weekly_reports")