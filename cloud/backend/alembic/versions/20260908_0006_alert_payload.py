"""Add structured payload column to alerts (D24).

Revision ID: 20260908_0006
Revises: 20260716_0005
Create Date: 2026-09-08 12:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260908_0006"
down_revision = "20260716_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "payload")