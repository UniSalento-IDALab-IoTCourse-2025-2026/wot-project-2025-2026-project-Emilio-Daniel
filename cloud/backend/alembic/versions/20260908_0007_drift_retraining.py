"""Add model drift and retraining log tables (D27).

Revision ID: 20260908_0007
Revises: 20260908_0006
Create Date: 2026-09-08 16:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260908_0007"
down_revision = "20260908_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patient_model_drift",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String(), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="stable"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("drift_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("baseline_mean", sa.Float(), nullable=True),
        sa.Column("baseline_std", sa.Float(), nullable=True),
        sa.Column("recent_mean", sa.Float(), nullable=True),
        sa.Column("recent_std", sa.Float(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("baseline_available", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("drift_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("patient_id", name="uq_patient_model_drift_patient"),
    )
    op.create_index(
        "ix_patient_model_drift_patient_status", "patient_model_drift", ["patient_id", "status"]
    )
    op.create_table(
        "model_retraining_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String(), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_retraining_logs_patient", "model_retraining_logs", ["patient_id"])


def downgrade() -> None:
    op.drop_index("ix_model_retraining_logs_patient", table_name="model_retraining_logs")
    op.drop_table("model_retraining_logs")
    op.drop_index("ix_patient_model_drift_patient_status", table_name="patient_model_drift")
    op.drop_table("patient_model_drift")