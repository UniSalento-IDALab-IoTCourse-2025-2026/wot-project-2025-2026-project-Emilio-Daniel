"""Add auth and alert improvement fields.

Revision ID: 20260713_0003
Revises: 20260712_0002
Create Date: 2026-07-13 09:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260713_0003"
down_revision = "20260712_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_last_login_at", "users", ["last_login_at"])

    op.add_column("alerts", sa.Column("source", sa.String(length=32), nullable=False, server_default="edge"))
    op.add_column("alerts", sa.Column("clinical_severity", sa.String(length=32), nullable=True))
    op.add_column("alerts", sa.Column("technical_severity", sa.String(length=32), nullable=True))
    op.add_column("alerts", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_alerts_source", "alerts", ["source"])
    op.create_index("ix_alerts_escalated_at", "alerts", ["escalated_at"])
    op.alter_column("alerts", "source", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_alerts_escalated_at", table_name="alerts")
    op.drop_index("ix_alerts_source", table_name="alerts")
    op.drop_column("alerts", "escalated_at")
    op.drop_column("alerts", "technical_severity")
    op.drop_column("alerts", "clinical_severity")
    op.drop_column("alerts", "source")

    op.drop_index("ix_users_last_login_at", table_name="users")
    op.drop_column("users", "last_login_at")
