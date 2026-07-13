from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any


def hash_password(password: str) -> str:
    """Crea un hash password PBKDF2-SHA256 con salt casuale."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
    return "pbkdf2_sha256$210000$" + b64(salt) + "$" + b64(digest)


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica una password contro il formato PBKDF2 usato dal backend."""
    try:
        algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = b64decode(salt_text)
        expected = b64decode(digest_text)
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def create_access_token(*, secret_key: str, user_id: int, role: str, minutes: int) -> str:
    """Crea un token access firmato e breve, senza salvare dati sensibili."""
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": int(expires_at.timestamp()),
        "typ": "access",
        "jti": secrets.token_urlsafe(12),
    }
    return sign_payload(payload, secret_key)


def decode_access_token(token: str, secret_key: str) -> dict[str, Any]:
    """Valida firma e scadenza di un access token."""
    payload = verify_signed_payload(token, secret_key)
    if payload.get("typ") != "access":
        raise ValueError("Invalid token type.")
    exp = int(payload.get("exp", 0))
    if exp < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Token expired.")
    return payload


def create_refresh_token() -> str:
    """Genera un refresh token opaco da salvare solo come hash."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """Hash stabile del refresh token per revoca e lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sign_payload(payload: dict[str, Any], secret_key: str) -> str:
    body = b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    signature = hmac.new(secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return body + "." + b64(signature)


def verify_signed_payload(token: str, secret_key: str) -> dict[str, Any]:
    try:
        body, signature_text = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Malformed token.") from exc
    expected = hmac.new(secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    actual = b64decode(signature_text)
    if not hmac.compare_digest(actual, expected):
        raise ValueError("Invalid token signature.")
    return json.loads(b64decode(body))


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
