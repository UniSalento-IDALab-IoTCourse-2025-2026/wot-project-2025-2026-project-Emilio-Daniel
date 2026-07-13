from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, get_current_user, write_audit
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.core.config import Settings, get_settings
from app.db.models import Caregiver, CaregiverPatient, Doctor, DoctorPatient, Patient, PatientUser, RefreshToken, User
from app.db.session import get_db

router = APIRouter()


@router.post("/login", summary="Login")
def login(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Autentica l'utente, crea access token breve e refresh token revocabile."""
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    if not email or not password:
        raise HTTPException(status_code=422, detail="Email and password are required.")

    ensure_demo_identity(db, email, settings)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    access_token = create_access_token(
        secret_key=settings.auth_secret_key,
        user_id=user.id,
        role=user.role,
        minutes=settings.access_token_minutes,
    )
    refresh_token = create_refresh_token()
    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(refresh_record)
    write_audit(
        db,
        actor=CurrentUser(id=user.id, email=user.email, role=user.role, display_name=user.display_name),
        action="auth.login",
        details={"email": user.email},
    )
    db.commit()
    return session_payload(user, access_token, refresh_token, settings)


@router.post("/refresh", summary="Refresh access token")
def refresh(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Rinnova l'access token usando un refresh token non revocato."""
    refresh_token = str(payload.get("refresh_token") or "")
    if not refresh_token:
        raise HTTPException(status_code=422, detail="refresh_token is required.")
    token_hash = hash_refresh_token(refresh_token)
    token_row = db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    expires_at = ensure_aware(token_row.expires_at) if token_row is not None else now
    if token_row is None or token_row.revoked_at is not None or expires_at <= now:
        raise HTTPException(status_code=401, detail="Refresh token is invalid or expired.")
    user = db.get(User, token_row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")
    access_token = create_access_token(
        secret_key=settings.auth_secret_key,
        user_id=user.id,
        role=user.role,
        minutes=settings.access_token_minutes,
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
        "user": user_payload(user),
    }


@router.post("/logout", summary="Logout")
def logout(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Revoca il refresh token indicato, lasciando scadere l'access token breve."""
    refresh_token = str(payload.get("refresh_token") or "")
    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        token_row = db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).scalar_one_or_none()
        if token_row is not None and token_row.user_id == current_user.id and token_row.revoked_at is None:
            token_row.revoked_at = datetime.now(timezone.utc)
    write_audit(db, actor=current_user, action="auth.logout", details={"email": current_user.email})
    db.commit()
    return {"status": "logged_out"}


@router.get("/status", summary="Auth module status")
def auth_status() -> dict[str, str]:
    """Espone lo stato del modulo auth."""
    return {"status": "implemented", "module": "auth"}


def session_payload(user: User, access_token: str, refresh_token: str, settings: Settings) -> dict[str, Any]:
    """Costruisce la risposta di login compatibile con la dashboard."""
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
        "user": user_payload(user),
    }


def user_payload(user: User) -> dict[str, Any]:
    """Serializza l'utente senza esporre hash o segreti."""
    return {
        "user_id": f"user-{user.id}",
        "email": user.email,
        "role": user.role,
        "display_name": user.display_name,
    }


def ensure_demo_identity(db: Session, email: str, settings: Settings) -> None:
    """In sviluppo crea identita' demo solo se abilitate tramite `.env` locale."""
    demo_users = demo_user_map(settings)
    if settings.environment == "production" or not settings.demo_auth_enabled:
        return
    if not settings.demo_auth_password or email not in demo_users:
        return
    if db.execute(select(User.id).where(User.email == email)).first() is not None:
        return

    role, display_name = demo_users[email]
    patient = db.get(Patient, "patient-001")
    if patient is None:
        patient = Patient(patient_id="patient-001", display_name="Paziente Demo")
        db.add(patient)
        db.flush()

    user = User(email=email, password_hash=hash_password(settings.demo_auth_password), role=role, display_name=display_name)
    db.add(user)
    db.flush()

    if role == "doctor":
        doctor = Doctor(user_id=user.id, license_number="DEMO-001")
        db.add(doctor)
        db.flush()
        db.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.patient_id))
    elif role == "caregiver":
        caregiver = Caregiver(user_id=user.id, relationship="familiare")
        db.add(caregiver)
        db.flush()
        db.add(CaregiverPatient(caregiver_id=caregiver.id, patient_id=patient.patient_id))
    elif role == "patient":
        db.add(PatientUser(user_id=user.id, patient_id=patient.patient_id))

    db.commit()


def ensure_aware(value: datetime) -> datetime:
    """Normalizza le date SQLite/Postgres prima del confronto."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def demo_user_map(settings: Settings) -> dict[str, tuple[str, str]]:
    """Legge gli utenti demo dalla configurazione senza hardcodare credenziali."""
    users: dict[str, tuple[str, str]] = {}
    if settings.demo_doctor_email:
        users[settings.demo_doctor_email.lower()] = ("doctor", "Medico Demo")
    if settings.demo_caregiver_email:
        users[settings.demo_caregiver_email.lower()] = ("caregiver", "Caregiver Demo")
    if settings.demo_patient_email:
        users[settings.demo_patient_email.lower()] = ("patient", "Paziente Demo")
    if settings.demo_admin_email:
        users[settings.demo_admin_email.lower()] = ("admin", "Admin Demo")
    return users
