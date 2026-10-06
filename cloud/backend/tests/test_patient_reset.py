from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    Alert,
    AlertEvent,
    AuditLog,
    Decision,
    EdgeCycle,
    EdgeDevice,
    FeatureWindow,
    Notification,
    Patient,
    PatientAppStatus,
    SensorStatus,
    Task,
    TaskResult,
)
from app.services.patient_reset import (
    patient_data_summary,
    patient_telemetry_summary,
    reset_patient_data,
    reset_patient_telemetry,
)


NOW = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed(session: Session) -> None:
    session.add_all(
        [
            Patient(patient_id="patient-001", display_name="Patient One"),
            Patient(patient_id="patient-002", display_name="Patient Two"),
            EdgeDevice(edge_id="edge-001", patient_id="patient-001", status="online", last_seen_at=NOW),
            PatientAppStatus(
                patient_id="patient-001",
                device_id="phone-001",
                status="online",
                last_seen_at=NOW,
                battery_pct=80,
                fcm_token="preserve-me",
                notifications_enabled=True,
            ),
            FeatureWindow(
                message_id="fw-001",
                patient_id="patient-001",
                timestamp=NOW,
                window_start=NOW,
                window_end=NOW + timedelta(minutes=4),
                features={"steps": 10},
            ),
            FeatureWindow(
                message_id="fw-002",
                patient_id="patient-002",
                timestamp=NOW,
                window_start=NOW,
                window_end=NOW + timedelta(minutes=4),
                features={"steps": 20},
            ),
            EdgeCycle(
                message_id="cycle-001",
                patient_id="patient-001",
                edge_id="edge-001",
                event_type="cycle_completed",
                timestamp=NOW,
                payload={},
            ),
            SensorStatus(
                patient_id="patient-001",
                sensor_type="ble",
                status="active",
                last_seen_at=NOW,
                details={},
            ),
            Notification(
                patient_id="patient-001",
                channel="push",
                status="sent",
                title="Old notification",
                payload={},
            ),
            AuditLog(
                action="old.event",
                patient_id="patient-001",
                timestamp=NOW,
                details={},
            ),
        ]
    )
    session.flush()

    decision = Decision(
        message_id="decision-001",
        patient_id="patient-001",
        edge_id="edge-001",
        timestamp=NOW,
        level="green",
        should_publish=False,
        anomaly_score=20,
        payload={},
    )
    task = Task(
        patient_id="patient-001",
        task_type="check_in",
        status="completed",
        title="Old task",
        payload={},
    )
    session.add_all([decision, task])
    session.flush()

    alert = Alert(
        message_id="alert-001",
        patient_id="patient-001",
        decision_id=decision.id,
        level="orange",
        status="resolved",
        title="Old alert",
        opened_at=NOW,
        payload={},
    )
    session.add(alert)
    session.flush()
    session.add_all(
        [
            AlertEvent(alert_id=alert.id, event_type="resolved", timestamp=NOW),
            TaskResult(
                task_id=task.id,
                message_id="result-001",
                patient_id="patient-001",
                completed_at=NOW,
                result={},
            ),
        ]
    )
    session.commit()


def count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_summary_is_a_dry_run() -> None:
    with make_session() as session:
        seed(session)
        payload = patient_data_summary(session, "patient-001")
        assert payload["total_records"] > 0
        assert payload["counts"]["feature_windows"] == 1
        assert count(session, FeatureWindow) == 2


def test_reset_removes_only_target_history_and_preserves_bindings() -> None:
    with make_session() as session:
        seed(session)
        payload = reset_patient_data(session, "patient-001")
        session.commit()

        assert payload["deleted_total"] > 0
        remaining_windows = session.scalars(select(FeatureWindow)).all()
        assert [row.patient_id for row in remaining_windows] == ["patient-002"]
        assert count(session, Alert) == 0
        assert count(session, AlertEvent) == 0
        assert count(session, Task) == 0
        assert count(session, TaskResult) == 0
        assert count(session, Notification) == 0
        assert count(session, AuditLog) == 1

        patient = session.get(Patient, "patient-001")
        edge = session.get(EdgeDevice, "edge-001")
        app_status = session.scalar(
            select(PatientAppStatus).where(PatientAppStatus.patient_id == "patient-001")
        )
        assert patient is not None
        assert edge is not None and edge.status == "unknown" and edge.last_seen_at is None
        assert app_status is not None
        assert app_status.fcm_token == "preserve-me"
        assert app_status.status == "unknown"
        assert app_status.last_seen_at is None
        assert app_status.battery_pct is None


def test_reset_can_include_audit() -> None:
    with make_session() as session:
        seed(session)
        payload = reset_patient_data(session, "patient-001", include_audit=True)
        session.commit()
        assert payload["deleted"]["audit_logs"] == 1
        assert count(session, AuditLog) == 0


def test_telemetry_reset_preserves_tasks_messages_and_device_registration() -> None:
    with make_session() as session:
        seed(session)
        summary = patient_telemetry_summary(session, "patient-001")
        assert summary["counts"]["feature_windows"] == 1

        payload = reset_patient_telemetry(session, "patient-001")
        session.commit()

        assert payload["status"] == "telemetry_reset_completed"
        assert count(session, FeatureWindow) == 1
        assert count(session, EdgeCycle) == 0
        assert count(session, Decision) == 0
        assert count(session, Alert) == 0
        assert count(session, AlertEvent) == 0
        assert count(session, SensorStatus) == 0
        assert count(session, Task) == 1
        assert count(session, TaskResult) == 1
        assert count(session, Notification) == 1
        assert count(session, AuditLog) == 1
        app_status = session.scalar(
            select(PatientAppStatus).where(PatientAppStatus.patient_id == "patient-001")
        )
        assert app_status is not None
        assert app_status.fcm_token == "preserve-me"
