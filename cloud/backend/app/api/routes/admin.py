from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, require_roles, write_audit
from app.auth.security import hash_password
from app.db.models import Caregiver, CaregiverPatient, Doctor, DoctorPatient, Patient, PatientUser, User
from app.db.session import get_db

router = APIRouter()
ALLOWED_ROLES = {"doctor", "caregiver", "patient", "admin"}


@router.post("/patients", summary="Admin create patient")
def create_patient(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Crea un paziente da pannello amministrativo."""
    patient_id = str(payload.get("patient_id") or "").strip()
    display_name = str(payload.get("display_name") or patient_id).strip()
    if not patient_id or not display_name:
        raise HTTPException(status_code=422, detail="patient_id and display_name are required.")
    if db.get(Patient, patient_id) is not None:
        raise HTTPException(status_code=409, detail="Patient already exists.")
    patient = Patient(patient_id=patient_id, display_name=display_name, notes=payload.get("notes"))
    db.add(patient)
    write_audit(db, actor=current_user, action="admin.patient_created", patient_id=patient_id, target_type="patient", target_id=patient_id)
    db.commit()
    return {"patient_id": patient.patient_id, "display_name": patient.display_name, "is_active": patient.is_active}


@router.post("/users", summary="Admin create user")
def create_user(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Crea un utente e il relativo profilo ruolo."""
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    role = str(payload.get("role") or "").strip().lower()
    if not email or len(password) < 10 or role not in ALLOWED_ROLES:
        raise HTTPException(status_code=422, detail="Valid email, password and role are required.")
    if db.execute(select(User.id).where(User.email == email)).first() is not None:
        raise HTTPException(status_code=409, detail="User already exists.")
    user = User(
        email=email,
        password_hash=hash_password(password),
        role=role,
        display_name=payload.get("display_name"),
    )
    db.add(user)
    db.flush()
    ensure_role_profile(db, user, payload)
    write_audit(db, actor=current_user, action="admin.user_created", target_type="user", target_id=f"user-{user.id}", details={"role": role})
    db.commit()
    return user_payload(user)


@router.post("/users/{user_id}/patients/{patient_id}", summary="Admin assign user to patient")
def assign_user_to_patient(
    user_id: int,
    patient_id: str,
    current_user: CurrentUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Associa medico, caregiver o paziente a un patient_id."""
    user = db.get(User, user_id)
    patient = db.get(Patient, patient_id)
    if user is None or patient is None:
        raise HTTPException(status_code=404, detail="User or patient not found.")
    association = ensure_patient_assignment(db, user, patient_id)
    write_audit(
        db,
        actor=current_user,
        action="admin.patient_assigned",
        patient_id=patient_id,
        target_type="user",
        target_id=f"user-{user.id}",
        details={"role": user.role},
    )
    db.commit()
    return {"user_id": f"user-{user.id}", "patient_id": patient_id, "role": user.role, "association": association}


def ensure_role_profile(db: Session, user: User, payload: dict[str, Any]) -> None:
    if user.role == "doctor":
        db.add(Doctor(user_id=user.id, license_number=payload.get("license_number")))
    elif user.role == "caregiver":
        db.add(Caregiver(user_id=user.id, relationship=payload.get("relationship")))


def ensure_patient_assignment(db: Session, user: User, patient_id: str) -> str:
    if user.role == "doctor":
        doctor = db.execute(select(Doctor).where(Doctor.user_id == user.id)).scalar_one_or_none()
        if doctor is None:
            doctor = Doctor(user_id=user.id)
            db.add(doctor)
            db.flush()
        if db.execute(select(DoctorPatient.id).where(DoctorPatient.doctor_id == doctor.id, DoctorPatient.patient_id == patient_id)).first() is None:
            db.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient_id))
        return "doctor_patient"
    if user.role == "caregiver":
        caregiver = db.execute(select(Caregiver).where(Caregiver.user_id == user.id)).scalar_one_or_none()
        if caregiver is None:
            caregiver = Caregiver(user_id=user.id)
            db.add(caregiver)
            db.flush()
        if db.execute(select(CaregiverPatient.id).where(CaregiverPatient.caregiver_id == caregiver.id, CaregiverPatient.patient_id == patient_id)).first() is None:
            db.add(CaregiverPatient(caregiver_id=caregiver.id, patient_id=patient_id))
        return "caregiver_patient"
    if user.role == "patient":
        if db.execute(select(PatientUser.id).where(PatientUser.user_id == user.id, PatientUser.patient_id == patient_id)).first() is None:
            db.add(PatientUser(user_id=user.id, patient_id=patient_id))
        return "patient_user"
    if user.role == "admin":
        return "admin_all_patients"
    raise HTTPException(status_code=422, detail="Unsupported role.")


def user_payload(user: User) -> dict[str, Any]:
    return {
        "user_id": f"user-{user.id}",
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "display_name": user.display_name,
        "is_active": user.is_active,
    }


# ── D31: Database retention ─────────────────────────────────────────────────


@router.get("/retention", summary="Retention status (D31)")
def retention_status(
    current_user: CurrentUser = Depends(require_roles("admin", "doctor")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Mostra conteggi record e quanti sarebbero eliminati dalla retention attiva."""
    from app.services.retention import retention_summary
    return retention_summary(db)


@router.post("/retention/purge", summary="Execute retention purge (D31)")
def execute_retention_purge(
    body: dict[str, Any] = {},
    current_user: CurrentUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Esegue il purge completo dei dati piu' vecchi della retention.

    Solo gli admin possono eseguire questa operazione. Viene registrata
    nell'audit trail.
    """
    from app.services.retention import run_full_purge
    from app.auth.dependencies import write_audit
    result = run_full_purge(db)
    write_audit(
        db,
        actor=current_user,
        action="retention.purge_executed",
        patient_id=None,
        target_type="retention",
        target_id="full_purge",
        details=result["deleted"],
    )
    db.commit()
    return result
