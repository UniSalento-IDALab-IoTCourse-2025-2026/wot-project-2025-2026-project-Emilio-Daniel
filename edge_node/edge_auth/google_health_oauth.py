from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TOKEN_URL = "https://oauth2.googleapis.com/token"


def refresh_access_token(
    token_file: Path,
    client_file: Path,
    *,
    save: bool = True,
) -> dict[str, Any]:
    """Rinnova l'access token Google usando il refresh token salvato.

    `google_health_token.json` contiene il refresh token ottenuto una volta con
    OAuth Playground. `google_health_client.json` contiene client id e client
    secret del progetto Google Cloud. Questa funzione combina i due file e
    chiama l'endpoint OAuth di Google per ottenere un access token nuovo.
    """
    token_payload = load_json(token_file)
    refresh_token = token_payload.get("refresh_token")
    if not refresh_token:
        raise ValueError(
            f"Missing refresh_token in {token_file}. Generate it with OAuth Playground."
        )

    client = load_json(client_file)
    client_id = str(client.get("client_id") or "").strip()
    client_secret = str(client.get("client_secret") or "").strip()
    token_uri = str(client.get("token_uri") or TOKEN_URL).strip()
    if not client_id or not client_secret:
        raise ValueError(f"Missing client_id/client_secret in {client_file}")

    form = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": str(refresh_token),
    }
    refreshed = _post_token_form(token_uri, form)
    merged = {**token_payload, **refreshed}
    if save:
        return save_token(token_file, merged)
    return _with_expiry_metadata(merged)


def load_valid_access_token(
    token_file: Path,
    client_file: Path,
    *,
    refresh_margin_seconds: int = 120,
) -> str:
    """Restituisce un access token valido per chiamare Google Health API.

    Il runtime chiama questa funzione prima di leggere i dati del Watch. Se il
    token e' assente, scaduto o vicino alla scadenza, viene rinnovato in modo
    automatico usando `refresh_access_token`.
    """
    token_payload = load_json(token_file)
    token = token_payload.get("access_token")
    if not token or token_is_expired(token_payload, margin_seconds=refresh_margin_seconds):
        token_payload = refresh_access_token(token_file, client_file)
        token = token_payload.get("access_token")
    if not token:
        raise ValueError(f"Missing access_token in {token_file}")
    return str(token)


def describe_token(token_file: Path, client_file: Path) -> dict[str, Any]:
    """Mostra lo stato OAuth senza stampare token o client secret.

    Questo alimenta il comando `python -m edge_auth.cli google-health status`.
    Serve a capire se i file locali sono pronti senza rischiare di esporre
    credenziali sensibili nel terminale o nella documentazione.
    """
    token_exists = token_file.exists()
    client_exists = client_file.exists()
    payload: dict[str, Any] = {}
    if token_exists:
        payload = load_json(token_file)
    return {
        "token_file": str(token_file),
        "client_file": str(client_file),
        "token_exists": token_exists,
        "client_exists": client_exists,
        "status": "ready" if token_exists and client_exists else "missing_setup",
        "scope": payload.get("scope"),
        "token_type": payload.get("token_type"),
        "has_access_token": bool(payload.get("access_token")),
        "has_refresh_token": bool(payload.get("refresh_token")),
        "expires_at": payload.get("expires_at"),
        "expired": token_is_expired(payload) if payload else None,
    }


def save_token(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Salva il token aggiornato aggiungendo metadati di scadenza leggibili."""
    enriched = _with_expiry_metadata(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(enriched, handle, indent=2)
    return enriched


def load_json(path: Path) -> dict[str, Any]:
    """Legge un file JSON locale e verifica che contenga un oggetto."""
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def token_is_expired(
    token_payload: dict[str, Any],
    *,
    margin_seconds: int = 120,
) -> bool:
    """Controlla se un token e' scaduto o troppo vicino alla scadenza."""
    expires_at_raw = token_payload.get("expires_at")
    if not expires_at_raw:
        return True
    expires_at = _parse_datetime(str(expires_at_raw))
    return datetime.now(timezone.utc) + timedelta(seconds=margin_seconds) >= expires_at


def _post_token_form(token_url: str, form: dict[str, str]) -> dict[str, Any]:
    """Invia una richiesta OAuth form-encoded all'endpoint token Google."""
    encoded_form = urlencode(form).encode("utf-8")
    request = Request(
        token_url,
        data=encoded_form,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google OAuth HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Google OAuth network error: {exc}") from exc


def _with_expiry_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Aggiunge `updated_at` ed `expires_at` al payload restituito da Google."""
    enriched = dict(payload)
    now = datetime.now(timezone.utc)
    enriched["updated_at"] = _format_datetime(now)
    expires_in = enriched.get("expires_in")
    if expires_in is not None:
        enriched["expires_at"] = _format_datetime(
            now + timedelta(seconds=int(expires_in))
        )
    return enriched


def _format_datetime(value: datetime) -> str:
    """Formatta una data UTC in ISO con suffisso `Z`."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    """Converte una data ISO salvata nel JSON token in `datetime` UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
