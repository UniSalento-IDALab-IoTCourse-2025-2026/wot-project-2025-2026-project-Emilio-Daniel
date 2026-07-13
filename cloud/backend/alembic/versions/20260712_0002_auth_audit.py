"""Add D7 auth, refresh tokens and audit tables.

Revision ID: 20260712_0002
Revises: 20260710_0001
Create Date: 2026-07-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260712_0002"
down_revision = "20260710_0001"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "patient_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("user_id", "patient_id", name="uq_patient_user_patient"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.String(length=255)),
        *timestamps(),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])
    op.create_index("ix_refresh_tokens_revoked_at", "refresh_tokens", ["revoked_at"])
    op.create_index("ix_refresh_tokens_user_revoked", "refresh_tokens", ["user_id", "revoked_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor_role", sa.String(length=32)),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("patient_id", sa.String(length=64), sa.ForeignKey("patients.patient_id", ondelete="SET NULL")),
        sa.Column("target_type", sa.String(length=64)),
        sa.Column("target_id", sa.String(length=128)),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_patient_id", "audit_logs", ["patient_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_actor_timestamp", "audit_logs", ["actor_user_id", "timestamp"])
    op.create_index("ix_audit_logs_patient_timestamp", "audit_logs", ["patient_id", "timestamp"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("refresh_tokens")
    op.drop_table("patient_users")
