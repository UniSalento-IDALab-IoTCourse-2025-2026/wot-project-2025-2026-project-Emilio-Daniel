"""Add questionnaire templates and schedules.

Revision ID: 20260716_0005
Revises: 20260714_0004
Create Date: 2026-07-16 10:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260716_0005"
down_revision = "20260714_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "questionnaire_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_key", sa.String(length=96), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("scoring", sa.JSON(), nullable=True),
        sa.Column("default_priority", sa.String(length=32), nullable=False),
        sa.Column("default_payload", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_key", "version", name="uq_questionnaire_templates_key_version"),
    )
    op.create_index("ix_questionnaire_templates_template_key", "questionnaire_templates", ["template_key"])
    op.create_index(
        "ix_questionnaire_templates_active",
        "questionnaire_templates",
        ["is_active", "template_key"],
    )

    op.create_table(
        "questionnaire_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.String(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("frequency", sa.String(length=32), nullable=False),
        sa.Column("interval", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_task_id", sa.Integer(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone_name", sa.String(length=64), nullable=False),
        sa.Column("title_override", sa.String(length=255), nullable=True),
        sa.Column("instructions_override", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=32), nullable=True),
        sa.Column("payload_overrides", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["questionnaire_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_questionnaire_schedules_patient_id", "questionnaire_schedules", ["patient_id"])
    op.create_index("ix_questionnaire_schedules_template_id", "questionnaire_schedules", ["template_id"])
    op.create_index("ix_questionnaire_schedules_status", "questionnaire_schedules", ["status"])
    op.create_index("ix_questionnaire_schedules_next_run_at", "questionnaire_schedules", ["next_run_at"])
    op.create_index(
        "ix_questionnaire_schedules_patient_status_next",
        "questionnaire_schedules",
        ["patient_id", "status", "next_run_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_questionnaire_schedules_patient_status_next", table_name="questionnaire_schedules")
    op.drop_index("ix_questionnaire_schedules_next_run_at", table_name="questionnaire_schedules")
    op.drop_index("ix_questionnaire_schedules_status", table_name="questionnaire_schedules")
    op.drop_index("ix_questionnaire_schedules_template_id", table_name="questionnaire_schedules")
    op.drop_index("ix_questionnaire_schedules_patient_id", table_name="questionnaire_schedules")
    op.drop_table("questionnaire_schedules")

    op.drop_index("ix_questionnaire_templates_active", table_name="questionnaire_templates")
    op.drop_index("ix_questionnaire_templates_template_key", table_name="questionnaire_templates")
    op.drop_table("questionnaire_templates")
