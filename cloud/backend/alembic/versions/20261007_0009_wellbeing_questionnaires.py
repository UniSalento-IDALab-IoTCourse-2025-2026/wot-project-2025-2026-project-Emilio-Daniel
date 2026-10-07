"""Seed wellbeing-oriented questionnaire templates.

Revision ID: 20261007_0009
Revises: 20260909_0008
Create Date: 2026-10-07 16:00:00.000000
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "20261007_0009"
down_revision = "20260909_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    templates = sa.table(
        "questionnaire_templates",
        sa.column("template_key", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("title", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("task_type", sa.String()),
        sa.column("schema_version", sa.Integer()),
        sa.column("questions", sa.JSON()),
        sa.column("scoring", sa.JSON()),
        sa.column("default_priority", sa.String()),
        sa.column("default_payload", sa.JSON()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_by_user_id", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    common = {
        "version": 2,
        "task_type": "check_in",
        "schema_version": 1,
        "scoring": None,
        "default_priority": "normal",
        "default_payload": {},
        "is_active": True,
        "created_by_user_id": None,
        "created_at": now,
        "updated_at": now,
    }
    op.bulk_insert(
        templates,
        [
            {
                **common,
                "template_key": "short_wellbeing_checkin",
                "title": "Test cognitivo breve - benessere",
                "description": "Breve autovalutazione quotidiana di benessere, umore e bisogno di contatto, senza punteggio diagnostico.",
                "questions": [
                    {"id": "overall", "type": "scale", "text": "Come valuti il tuo benessere generale oggi?", "options": ["Molto basso", "Basso", "Discreto", "Buono", "Molto buono"], "required": True},
                    {"id": "mood", "type": "single_choice", "text": "Quale descrizione rappresenta meglio il tuo umore?", "options": ["Sereno", "Abbastanza sereno", "Preoccupato", "Triste", "Irritabile"], "required": True},
                    {"id": "contact", "type": "yes_no", "text": "Vorresti essere contattato dal team di cura?", "required": True},
                ],
            },
            {
                **common,
                "template_key": "mmse_wellbeing_checkin",
                "title": "MMSE - check-in benessere",
                "description": "Autovalutazione di umore, lucidita percepita e difficolta insolite. Non sostituisce un test MMSE clinico.",
                "questions": [
                    {"id": "mood", "type": "scale", "text": "Come descriveresti il tuo umore oggi?", "options": ["Molto negativo", "Negativo", "Neutro", "Positivo", "Molto positivo"], "required": True},
                    {"id": "clarity", "type": "scale", "text": "Quanto ti senti lucido e orientato nelle attivita di oggi?", "options": ["Per niente", "Poco", "Abbastanza", "Molto", "Completamente"], "required": True},
                    {"id": "worry", "type": "yes_no", "text": "Ti senti piu confuso o preoccupato del solito?", "required": True},
                    {"id": "note", "type": "text", "text": "Vuoi aggiungere qualcosa su come ti senti?", "required": False},
                ],
            },
            {
                **common,
                "template_key": "moca_daily_checkin",
                "title": "MoCA - check-in quotidiano",
                "description": "Autovalutazione di energia, sonno e autonomia quotidiana. Non sostituisce un test MoCA clinico.",
                "questions": [
                    {"id": "energy", "type": "scale", "text": "Quanta energia senti di avere oggi?", "options": ["Nessuna", "Poca", "Moderata", "Buona", "Molta"], "required": True},
                    {"id": "daily_tasks", "type": "single_choice", "text": "Come sono andate le normali attivita quotidiane?", "options": ["Senza difficolta", "Con qualche difficolta", "Con molta difficolta", "Non sono riuscito a svolgerle"], "required": True},
                    {"id": "sleep", "type": "single_choice", "text": "Come hai dormito?", "options": ["Molto bene", "Bene", "Cosi cosi", "Male", "Molto male"], "required": True},
                    {"id": "help", "type": "yes_no", "text": "Hai avuto bisogno di piu aiuto del solito?", "required": True},
                ],
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM questionnaire_templates "
            "WHERE version = 2 AND template_key IN "
            "('short_wellbeing_checkin', 'mmse_wellbeing_checkin', 'moca_daily_checkin')"
        )
    )
