from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db import models  # noqa: F401
from app.db.base import utc_now
from app.db.models import EdgeCycle, Patient


def build_sqlite_schema():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, inspect(engine)


def test_d3_tables_exist() -> None:
    _, inspector = build_sqlite_schema()

    expected_tables = {
        "users",
        "patients",
        "doctors",
        "caregivers",
        "doctor_patients",
        "caregiver_patients",
        "edge_devices",
        "edge_cycles",
        "feature_windows",
        "decisions",
        "alerts",
        "alert_events",
        "sensor_status",
        "patient_app_status",
        "tasks",
        "task_results",
        "notifications",
    }
    assert expected_tables.issubset(set(inspector.get_table_names()))


def test_message_id_uniqueness_for_deduplication() -> None:
    _, inspector = build_sqlite_schema()

    expected_constraints = {
        "edge_cycles": "uq_edge_cycles_message_id",
        "feature_windows": "uq_feature_windows_message_id",
        "decisions": "uq_decisions_message_id",
        "alerts": "uq_alerts_message_id",
        "task_results": "uq_task_results_message_id",
    }
    for table, constraint_name in expected_constraints.items():
        constraints = {item["name"] for item in inspector.get_unique_constraints(table)}
        assert constraint_name in constraints


def test_patient_timestamp_level_status_indexes_exist() -> None:
    _, inspector = build_sqlite_schema()

    expected_indexes = {
        "edge_cycles": {"ix_edge_cycles_patient_window", "ix_edge_cycles_timestamp"},
        "feature_windows": {"ix_feature_windows_patient_window", "ix_feature_windows_timestamp"},
        "decisions": {"ix_decisions_patient_level_timestamp"},
        "alerts": {"ix_alerts_patient_status_level"},
        "tasks": {"ix_tasks_patient_status_due"},
        "notifications": {"ix_notifications_patient_status"},
    }
    for table, index_names in expected_indexes.items():
        indexes = {item["name"] for item in inspector.get_indexes(table)}
        assert index_names.issubset(indexes)


def test_role_and_auth_columns_exist() -> None:
    _, inspector = build_sqlite_schema()
    user_columns = {column["name"] for column in inspector.get_columns("users")}

    assert {"email", "password_hash", "role", "is_active"}.issubset(user_columns)


def test_message_id_duplicate_is_rejected() -> None:
    engine, _ = build_sqlite_schema()
    now = utc_now()

    with Session(engine) as session:
        session.add(Patient(patient_id="patient-001", display_name="Test Patient"))
        session.commit()
        session.add(
            EdgeCycle(
                message_id="duplicate-message",
                patient_id="patient-001",
                event_type="edge_cycle_completed",
                timestamp=now,
                payload={"ok": True},
            )
        )
        session.commit()
        session.add(
            EdgeCycle(
                message_id="duplicate-message",
                patient_id="patient-001",
                event_type="edge_cycle_completed",
                timestamp=now,
                payload={"ok": True},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
