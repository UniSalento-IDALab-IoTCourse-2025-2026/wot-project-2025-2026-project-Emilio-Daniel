from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from app.auth.security import hash_password
from app.core.config import get_settings
from app.db.models import (
    Alert,
    AlertEvent,
    AuditLog,
    Decision,
    Doctor,
    Doctor,
    DoctorPatient,
    EdgeCycle,
    EdgeDevice,
    FeatureWindow,
    Notification,
    Patient,
    PatientAppStatus,
    PatientUser,
    QuestionnaireSchedule,
    QuestionnaireTemplate,
    SensorStatus,
    Task,
    TaskResult,
    User,
)
from app.db.session import SessionLocal

DEMO_PATIENTS = ["patient-demo-normal", "patient-demo-alert", "patient-demo-missing"]
DEMO_EMAILS = {
    "doctor": "demo.doctor@localhost.invalid",
    "patient": "demo.patient@localhost.invalid",
    "admin": "demo.admin@localhost.invalid",
}
DEMO_PASSWORD = "DemoPassword001!"


def main() -> None:
    """Gestisce seed/reset demo senza toccare dati reali fuori sviluppo."""
    parser = argparse.ArgumentParser(description="Seed/reset dati demo backend.")
    parser.add_argument("command", choices=["seed", "reset"])
    args = parser.parse_args()
    guard_non_production()
    if args.command == "seed":
        seed_demo_data()
    else:
        reset_demo_data()


def guard_non_production() -> None:
    """Evita uso accidentale degli script demo in produzione."""
    if get_settings().environment == "production":
        raise SystemExit("Gli script demo sono bloccati in production.")


def reset_demo_data() -> None:
    """Cancella solo dati demo riconoscibili, lasciando intatti dati manuali/reali."""
    with SessionLocal() as db:
        patient_ids = set(DEMO_PATIENTS)
        task_ids = [row.id for row in db.query(Task).filter(Task.patient_id.in_(patient_ids)).all()]
        alert_ids = [row.id for row in db.query(Alert).filter(Alert.patient_id.in_(patient_ids)).all()]
        template_ids = [row.id for row in db.query(QuestionnaireTemplate).filter(QuestionnaireTemplate.template_key.like("demo_%")).all()]
        db.query(TaskResult).filter(TaskResult.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        if task_ids:
            db.query(Task).filter(Task.id.in_(task_ids)).delete(synchronize_session=False)
        if alert_ids:
            db.query(AlertEvent).filter(AlertEvent.alert_id.in_(alert_ids)).delete(synchronize_session=False)
            db.query(Alert).filter(Alert.id.in_(alert_ids)).delete(synchronize_session=False)
        db.query(Notification).filter(Notification.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        db.query(Decision).filter(Decision.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        db.query(FeatureWindow).filter(FeatureWindow.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        db.query(EdgeCycle).filter(EdgeCycle.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        db.query(EdgeDevice).filter(EdgeDevice.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        db.query(SensorStatus).filter(SensorStatus.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        db.query(PatientAppStatus).filter(PatientAppStatus.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        db.query(DoctorPatient).filter(DoctorPatient.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        db.query(PatientUser).filter(PatientUser.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        db.query(AuditLog).filter(AuditLog.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        db.query(QuestionnaireSchedule).filter(QuestionnaireSchedule.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        if template_ids:
            db.query(QuestionnaireTemplate).filter(QuestionnaireTemplate.id.in_(template_ids)).delete(synchronize_session=False)
        db.query(Patient).filter(Patient.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        demo_user_ids = [row.id for row in db.query(User).filter(User.email.in_(DEMO_EMAILS.values())).all()]
        if demo_user_ids:
            db.query(Doctor).filter(Doctor.user_id.in_(demo_user_ids)).delete(synchronize_session=False)
        db.query(User).filter(User.email.in_(DEMO_EMAILS.values())).delete(synchronize_session=False)
        db.commit()
    print("Dati demo rimossi.")


def seed_demo_data() -> None:
    """Crea tre pazienti demo: normale, alert e dati mancanti."""
    reset_demo_data()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with SessionLocal() as db:
        doctor = User(email=DEMO_EMAILS["doctor"], password_hash=hash_password(DEMO_PASSWORD), role="doctor", display_name="Medico Demo Report")
        patient_user = User(email=DEMO_EMAILS["patient"], password_hash=hash_password(DEMO_PASSWORD), role="patient", display_name="Paziente Demo App")
        admin = User(email=DEMO_EMAILS["admin"], password_hash=hash_password(DEMO_PASSWORD), role="admin", display_name="Admin Demo")
        db.add_all([doctor, patient_user, admin])
        db.flush()
        doctor_row = Doctor(user_id=doctor.id, license_number="DEMO")
        db.add(doctor_row)
        db.flush()
        for patient_id, display_name in [
            ("patient-demo-normal", "Demo Routine"),
            ("patient-demo-alert", "Demo Alert"),
            ("patient-demo-missing", "Demo Dati Mancanti"),
        ]:
            db.add(Patient(patient_id=patient_id, display_name=display_name))
            db.add(DoctorPatient(doctor_id=doctor_row.id, patient_id=patient_id))
        db.add(PatientUser(user_id=patient_user.id, patient_id="patient-demo-alert"))
        db.flush()
        seed_patient_normal(db, now)
        seed_patient_alert(db, doctor, now)
        seed_patient_missing(db, now)
        seed_questionnaire(db, doctor, now)
        db.commit()
    print("Dati demo creati.")
    print(f"Medico demo: {DEMO_EMAILS['doctor']} / {DEMO_PASSWORD}")
    print(f"Paziente demo: {DEMO_EMAILS['patient']} / {DEMO_PASSWORD}")


def seed_patient_normal(db, now: datetime) -> None:
    patient_id = "patient-demo-normal"
    db.add(EdgeDevice(edge_id="edge-demo-normal", patient_id=patient_id, status="online", last_seen_at=now - timedelta(minutes=2)))
    db.add(SensorStatus(patient_id=patient_id, sensor_type="ble", status="active", last_seen_at=now - timedelta(minutes=2), details={"current_room": "living_room"}))
    for index in range(8):
        end = now - timedelta(minutes=4 * index)
        db.add(
            FeatureWindow(
                message_id=f"demo-normal-window-{index}",
                patient_id=patient_id,
                edge_id="edge-demo-normal",
                timestamp=end,
                window_start=end - timedelta(minutes=4),
                window_end=end,
                features={"heart_rate_mean": 68 + index % 3, "spo2_mean": 97, "living_room_minutes": 4.0, "room_changes": 0},
            )
        )
    db.add(
        Decision(
            message_id="demo-normal-decision",
            patient_id=patient_id,
            edge_id="edge-demo-normal",
            timestamp=now - timedelta(minutes=2),
            level="green",
            should_publish=False,
            anomaly_score=12.0,
            model_label="demo-normal",
            payload={"payload": {"reasons": ["Routine compatibile"]}},
        )
    )


def seed_patient_alert(db, doctor: User, now: datetime) -> None:
    patient_id = "patient-demo-alert"
    db.add(EdgeDevice(edge_id="edge-demo-alert", patient_id=patient_id, status="online", last_seen_at=now - timedelta(minutes=1)))
    db.add(SensorStatus(patient_id=patient_id, sensor_type="ble", status="active", last_seen_at=now - timedelta(minutes=1), details={"current_room": "kitchen"}))
    end = now - timedelta(minutes=4)
    db.add(
        FeatureWindow(
            message_id="demo-alert-window",
            patient_id=patient_id,
            edge_id="edge-demo-alert",
            timestamp=end,
            window_start=end - timedelta(minutes=4),
            window_end=end,
            features={"heart_rate_mean": 88, "spo2_mean": 93, "kitchen_minutes": 4.0, "room_changes": 3, "night_room_changes": 1},
        )
    )
    db.flush()
    decision = Decision(
        message_id="demo-alert-decision",
        patient_id=patient_id,
        edge_id="edge-demo-alert",
        timestamp=end,
        window_start=end - timedelta(minutes=4),
        window_end=end,
        level="orange",
        should_publish=True,
        anomaly_score=78.0,
        model_label="demo-alert",
        payload={"payload": {"reasons": ["Battito e routine da verificare"]}},
    )
    db.add(decision)
    db.flush()
    alert = Alert(
        message_id="demo-alert",
        patient_id=patient_id,
        decision_id=decision.id,
        level="orange",
        status="resolved",
        category="behavioral",
        source="ai",
        clinical_severity="orange",
        title="Demo alert comportamentale",
        description="Evento dimostrativo da verificare.",
        opened_at=end,
        closed_at=now - timedelta(minutes=1),
    )
    db.add(alert)
    db.flush()
    db.add(
        AlertEvent(
            alert_id=alert.id,
            user_id=doctor.id,
            event_type="resolved",
            timestamp=now - timedelta(minutes=1),
            note='{"user_id":"Medico Demo Report","role":"doctor","note":"Alert demo risolto dopo verifica."}',
        )
    )
    task = Task(
        patient_id=patient_id,
        created_by_user_id=doctor.id,
        task_type="check_in",
        status="completed",
        title="Check-in demo",
        payload={"priority": "high", "medical_note": "Nota demo per report.", "medical_note_by": "Medico Demo Report"},
        completed_at=now - timedelta(minutes=1),
    )
    db.add(task)
    db.flush()
    db.add(
        TaskResult(
            task_id=task.id,
            patient_id=patient_id,
            message_id="demo-task-result",
            completed_at=now - timedelta(minutes=1),
            duration_seconds=90,
            result={"score": 7, "answers": [{"question_id": "mood", "value": 7}]},
        )
    )


def seed_patient_missing(db, now: datetime) -> None:
    patient_id = "patient-demo-missing"
    db.add(EdgeDevice(edge_id="edge-demo-missing", patient_id=patient_id, status="offline", last_seen_at=now - timedelta(hours=2)))
    db.add(
        Decision(
            message_id="demo-missing-decision",
            patient_id=patient_id,
            edge_id="edge-demo-missing",
            timestamp=now - timedelta(hours=2),
            level="technical",
            should_publish=False,
            anomaly_score=None,
            model_label="technical_missing_data",
            payload={"payload": {"reasons": ["Dati non aggiornati"]}},
        )
    )


def seed_questionnaire(db, doctor: User, now: datetime) -> None:
    template = QuestionnaireTemplate(
        template_key="demo_daily_checkin",
        version=1,
        title="Demo check-in quotidiano",
        description="Domande brevi dimostrative.",
        task_type="check_in",
        questions=[{"id": "mood", "type": "scale", "text": "Come ti senti oggi?", "min": 0, "max": 10}],
        scoring={"type": "scale_average", "question_ids": ["mood"]},
        created_by_user_id=doctor.id,
    )
    db.add(template)
    db.flush()
    db.add(
        QuestionnaireSchedule(
            patient_id="patient-demo-alert",
            template_id=template.id,
            created_by_user_id=doctor.id,
            status="active",
            frequency="daily",
            interval=1,
            next_run_at=now + timedelta(days=1),
        )
    )


if __name__ == "__main__":
    main()
