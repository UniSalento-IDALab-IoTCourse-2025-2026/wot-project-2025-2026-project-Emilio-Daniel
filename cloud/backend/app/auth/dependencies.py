from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException, Query, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.core.config import get_settings
from app.db.models import AuditLog, Caregiver, CaregiverPatient, Doctor, DoctorPatient, PatientUser, User
from app.db.session import SessionLocal, get_db

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """Utente autenticato usato dalle route REST e WebSocket."""

    id: int
    email: str
    role: str
    display_name: str | None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Legge il bearer token e restituisce l'utente autenticato."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required.")
    token = credentials.credentials.strip()
    try:
        payload = decode_access_token(token, get_settings().auth_secret_key)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")
    return CurrentUser(
        id=user.id,
        email=user.email,
        role=user.role,
        display_name=user.display_name,
    )


def require_roles(*roles: str):
    """Crea una dependency che richiede uno dei ruoli indicati."""
    allowed = set(roles)

    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed:
            raise HTTPException(status_code=403, detail="Role not authorized.")
        return current_user

    return dependency


def require_patient_access(
    patient_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Blocca l'accesso se l'utente non e' associato al paziente."""
    if not can_access_patient(db, current_user, patient_id):
        raise HTTPException(status_code=403, detail="Patient not authorized.")
    return current_user


def can_access_patient(db: Session, user: CurrentUser, patient_id: str) -> bool:
    """Verifica le associazioni utente-paziente in base al ruolo."""
    if user.role == "admin":
        return True
    if user.role == "doctor":
        doctor_id = db.execute(select(Doctor.id).where(Doctor.user_id == user.id)).scalar_one_or_none()
        if doctor_id is None:
            return False
        return db.execute(
            select(DoctorPatient.id).where(
                DoctorPatient.doctor_id == doctor_id,
                DoctorPatient.patient_id == patient_id,
            )
        ).first() is not None
    if user.role == "caregiver":
        caregiver_id = db.execute(select(Caregiver.id).where(Caregiver.user_id == user.id)).scalar_one_or_none()
        if caregiver_id is None:
            return False
        return db.execute(
            select(CaregiverPatient.id).where(
                CaregiverPatient.caregiver_id == caregiver_id,
                CaregiverPatient.patient_id == patient_id,
            )
        ).first() is not None
    if user.role == "patient":
        return db.execute(
            select(PatientUser.id).where(
                PatientUser.user_id == user.id,
                PatientUser.patient_id == patient_id,
            )
        ).first() is not None
    return False


def authorized_patient_ids(db: Session, user: CurrentUser) -> list[str] | None:
    """Restituisce i patient_id visibili; None significa tutti per admin."""
    if user.role == "admin":
        return None
    if user.role == "doctor":
        doctor_id = db.execute(select(Doctor.id).where(Doctor.user_id == user.id)).scalar_one_or_none()
        if doctor_id is None:
            return []
        return list(db.execute(select(DoctorPatient.patient_id).where(DoctorPatient.doctor_id == doctor_id)).scalars())
    if user.role == "caregiver":
        caregiver_id = db.execute(select(Caregiver.id).where(Caregiver.user_id == user.id)).scalar_one_or_none()
        if caregiver_id is None:
            return []
        return list(db.execute(select(CaregiverPatient.patient_id).where(CaregiverPatient.caregiver_id == caregiver_id)).scalars())
    if user.role == "patient":
        return list(db.execute(select(PatientUser.patient_id).where(PatientUser.user_id == user.id)).scalars())
    return []


def get_current_user_from_query(
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Autentica WebSocket quando FastAPI lo usa come dependency HTTP-like."""
    if not token:
        raise HTTPException(status_code=401, detail="WebSocket token required.")
    try:
        payload = decode_access_token(token, get_settings().auth_secret_key)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")
    return CurrentUser(id=user.id, email=user.email, role=user.role, display_name=user.display_name)


async def websocket_current_user(websocket: WebSocket) -> CurrentUser | None:
    """Autentica manualmente una connessione WebSocket usando `?token=`."""
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = decode_access_token(token, get_settings().auth_secret_key)
    except ValueError:
        return None
    with SessionLocal() as db:
        user = db.get(User, int(payload["sub"]))
        if user is None or not user.is_active:
            return None
        return CurrentUser(id=user.id, email=user.email, role=user.role, display_name=user.display_name)


def write_audit(
    db: Session,
    *,
    actor: CurrentUser | None,
    action: str,
    patient_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Scrive un evento audit senza includere token o password."""
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            actor_role=actor.role if actor else None,
            action=action,
            patient_id=patient_id,
            target_type=target_type,
            target_id=target_id,
            timestamp=datetime.now(timezone.utc),
            details=details or {},
        )
    )
