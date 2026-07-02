from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen


AUTHORIZATION_URL = "https://www.fitbit.com/oauth2/authorize"
TOKEN_URL = "https://api.fitbit.com/oauth2/token"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8765/callback"
DEFAULT_SCOPES = (
    "activity",
    "heartrate",
    "sleep",
    "profile",
    "settings",
    "oxygen_saturation",
    "respiratory_rate",
)


@dataclass(frozen=True)
class FitbitClientCredentials:
    client_id: str
    client_secret: str | None
    redirect_uri: str
    token_url: str = TOKEN_URL


@dataclass(frozen=True)
class OAuthSetupResult:
    token_file: Path
    client_file: Path
    user_id: str | None
    scope: str | None
    expires_at: str | None


def run_authorization_setup(
    *,
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    scopes: tuple[str, ...],
    token_file: Path,
    client_file: Path,
    host: str,
    port: int,
    timeout_seconds: int,
    open_browser: bool,
) -> OAuthSetupResult:
    """Esegue il setup completo OAuth Fitbit con Authorization Code e PKCE.

    La funzione genera stato e code verifier, apre la pagina di consenso Fitbit,
    riceve il callback locale, scambia il codice con i token e salva tutto nei
    file di configurazione locali. E' pensata per essere eseguita una volta
    durante la preparazione del Raspberry o del PC di test.
    """
    state = secrets.token_urlsafe(24)
    code_verifier = _generate_code_verifier()
    code_challenge = _code_challenge(code_verifier)
    authorization_url = build_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        state=state,
        code_challenge=code_challenge,
    )

    _save_client_credentials(
        client_file,
        FitbitClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        ),
    )

    print("Apri questo URL nel browser se non si apre automaticamente:")
    print(authorization_url)
    if open_browser:
        webbrowser.open(authorization_url)

    callback = wait_for_callback(
        expected_state=state,
        host=host,
        port=port,
        timeout_seconds=timeout_seconds,
    )
    token_payload = exchange_authorization_code(
        client=FitbitClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        ),
        code=callback["code"],
        code_verifier=code_verifier,
    )
    saved_token = save_token(token_file, token_payload)

    return OAuthSetupResult(
        token_file=token_file,
        client_file=client_file,
        user_id=_optional_str(saved_token.get("user_id")),
        scope=_optional_str(saved_token.get("scope")),
        expires_at=_optional_str(saved_token.get("expires_at")),
    )


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: tuple[str, ...],
    state: str,
    code_challenge: str,
) -> str:
    """Costruisce l'URL di autorizzazione da aprire nel browser.

    L'URL contiene client id, scope, redirect URI, stato anti-CSRF e code
    challenge PKCE. In questo modo l'utente puo' concedere esplicitamente al
    progetto l'accesso ai dati Fitbit necessari.
    """
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": " ".join(scopes),
            "state": state,
            "redirect_uri": redirect_uri,
        },
        quote_via=quote,
    )
    return f"{AUTHORIZATION_URL}?{query}"


def wait_for_callback(
    *,
    expected_state: str,
    host: str,
    port: int,
    timeout_seconds: int,
) -> dict[str, str]:
    """Attende sul computer locale il redirect di ritorno da Fitbit.

    Durante il setup OAuth viene avviato un piccolo server HTTP su localhost. Il
    server riceve il parametro `code`, verifica lo `state` e restituisce una
    pagina semplice che comunica all'utente che puo' tornare al terminale.
    """
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            """Gestisce la richiesta GET inviata dal browser al redirect locale.

            Il metodo legge i parametri della query, distingue successo ed
            errore OAuth e salva nel dizionario condiviso il codice temporaneo
            da scambiare con i token.
            """
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            state = _first(query.get("state"))
            code = _first(query.get("code"))
            error = _first(query.get("error"))
            error_description = _first(query.get("error_description"))

            if error:
                result["error"] = error
                if error_description:
                    result["error_description"] = error_description
                self._send_page(
                    "Autorizzazione Fitbit non completata. Puoi chiudere questa finestra."
                )
                return

            if state != expected_state:
                result["error"] = "invalid_state"
                self._send_page(
                    "Stato OAuth non valido. Puoi chiudere questa finestra."
                )
                return

            if not code:
                result["error"] = "missing_code"
                self._send_page(
                    "Codice OAuth mancante. Puoi chiudere questa finestra."
                )
                return

            result["code"] = code
            self._send_page(
                "Autorizzazione Fitbit completata. Puoi tornare al terminale."
            )

        def log_message(self, format: str, *args: object) -> None:
            """Disabilita il logging standard del server HTTP locale.

            Il setup deve rimanere pulito nel terminale: stampiamo solo le
            informazioni utili all'utente e non ogni richiesta HTTP del browser.
            """
            return

        def _send_page(self, message: str) -> None:
            """Invia al browser una piccola pagina HTML di esito.

            La pagina non contiene dati sensibili; serve solo a confermare se il
            consenso Fitbit e' stato completato oppure se c'e' stato un errore.
            """
            body = (
                "<!doctype html><html><head><title>Fitbit OAuth</title></head>"
                f"<body><h1>{message}</h1></body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer((host, port), CallbackHandler)
    server.timeout = 1
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline and not result:
            server.handle_request()
    finally:
        server.server_close()

    if not result:
        raise TimeoutError(
            f"Timeout OAuth Fitbit dopo {timeout_seconds} secondi."
        )
    if "error" in result:
        detail = result.get("error_description", result["error"])
        raise RuntimeError(f"Autorizzazione Fitbit fallita: {detail}")
    return result


def exchange_authorization_code(
    *,
    client: FitbitClientCredentials,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    """Scambia il codice OAuth temporaneo con access token e refresh token.

    Questo passaggio avviene dopo il consenso dell'utente. Il `code_verifier`
    completa il controllo PKCE e dimostra che chi scambia il codice e' lo stesso
    client che ha generato l'authorization URL.
    """
    return _post_token_form(
        client=client,
        form={
            "client_id": client.client_id,
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": client.redirect_uri,
        },
    )


def refresh_access_token(
    token_file: Path,
    client_file: Path,
    *,
    save: bool = True,
) -> dict[str, Any]:
    """Aggiorna l'access token Fitbit usando il refresh token salvato.

    Gli access token hanno durata limitata; il refresh token permette al
    Raspberry di continuare il polling senza chiedere login manuale ogni volta.
    Il nuovo token viene salvato subito per non perdere eventuali refresh token
    ruotati dal provider.
    """
    token_payload = load_json(token_file)
    refresh_token = token_payload.get("refresh_token")
    if not refresh_token:
        raise ValueError(
            f"Missing refresh_token in {token_file}. Run Fitbit setup again."
        )

    client = load_client_credentials(client_file)
    refreshed = _post_token_form(
        client=client,
        form={
            "client_id": client.client_id,
            "grant_type": "refresh_token",
            "refresh_token": str(refresh_token),
        },
    )
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
    """Restituisce un access token valido, rinfrescandolo se necessario.

    L'adapter Fitbit chiama questa funzione prima delle API. Se il token e'
    scaduto o sta per scadere, viene eseguito automaticamente il refresh usando
    i file locali prodotti dal setup OAuth.
    """
    token_payload = load_json(token_file)
    token = token_payload.get("access_token")
    if not token:
        raise ValueError(f"Missing access_token in {token_file}")

    if token_is_expired(token_payload, margin_seconds=refresh_margin_seconds):
        token_payload = refresh_access_token(token_file, client_file)
        token = token_payload.get("access_token")
        if not token:
            raise ValueError(f"Missing access_token after refresh in {token_file}")

    return str(token)


def token_is_expired(
    token_payload: dict[str, Any],
    *,
    margin_seconds: int = 120,
) -> bool:
    """Verifica se un token e' scaduto o troppo vicino alla scadenza.

    Il margine evita di iniziare una chiamata API con un token che potrebbe
    scadere durante la richiesta. Se manca `expires_at`, il token viene trattato
    come scaduto per sicurezza.
    """
    expires_at_raw = token_payload.get("expires_at")
    if not expires_at_raw:
        return True

    expires_at = _parse_datetime(str(expires_at_raw))
    return datetime.now(timezone.utc) + timedelta(seconds=margin_seconds) >= expires_at


def save_token(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Salva su disco il payload token arricchito con metadati temporali.

    Oltre ai campi restituiti da Fitbit, vengono aggiunti `updated_at` ed
    eventualmente `expires_at`, cosi' il runtime puo' sapere quando rinnovare
    l'access token.
    """
    enriched = _with_expiry_metadata(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(enriched, handle, indent=2)
    return enriched


def load_client_credentials(path: Path) -> FitbitClientCredentials:
    """Carica client id, client secret e redirect URI dal file locale.

    Queste informazioni identificano l'app OAuth registrata sul portale Fitbit.
    Il file e' separato dal token per distinguere credenziali applicative e
    credenziali utente.
    """
    payload = load_json(path)
    client_id = str(payload.get("client_id") or "").strip()
    if not client_id:
        raise ValueError(f"Missing client_id in {path}")
    return FitbitClientCredentials(
        client_id=client_id,
        client_secret=_optional_str(payload.get("client_secret")),
        redirect_uri=str(payload.get("redirect_uri") or DEFAULT_REDIRECT_URI),
        token_url=str(payload.get("token_url") or TOKEN_URL),
    )


def load_json(path: Path) -> dict[str, Any]:
    """Legge un file JSON e verifica che contenga un oggetto.

    Centralizzare la lettura permette di produrre errori chiari quando mancano i
    file di setup o quando il contenuto non e' nel formato atteso.
    """
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def describe_token(token_file: Path, client_file: Path) -> dict[str, Any]:
    """Restituisce un riepilogo sicuro dello stato OAuth Fitbit.

    Il dizionario indica presenza dei file, scadenza e disponibilita' dei token,
    ma non espone mai il valore effettivo di access token, refresh token o client
    secret. E' pensato per debug e documentazione.
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
        "user_id": payload.get("user_id"),
        "scope": payload.get("scope"),
        "token_type": payload.get("token_type"),
        "has_access_token": bool(payload.get("access_token")),
        "has_refresh_token": bool(payload.get("refresh_token")),
        "expires_at": payload.get("expires_at"),
        "expired": token_is_expired(payload) if payload else None,
    }


def _post_token_form(
    *,
    client: FitbitClientCredentials,
    form: dict[str, str],
) -> dict[str, Any]:
    """Invia una richiesta form-encoded all'endpoint token Fitbit.

    La stessa funzione viene usata sia per lo scambio del codice sia per il
    refresh. Quando e' presente il client secret, viene costruita l'intestazione
    Basic Auth richiesta dal flusso OAuth.
    """
    encoded_form = urlencode(form).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if client.client_secret:
        credentials = f"{client.client_id}:{client.client_secret}"
        basic_token = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {basic_token}"

    request = Request(
        client.token_url,
        data=encoded_form,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Fitbit OAuth HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Fitbit OAuth network error: {exc}") from exc


def _save_client_credentials(path: Path, client: FitbitClientCredentials) -> None:
    """Scrive su disco le credenziali client dell'app OAuth Fitbit.

    Il file viene creato durante il setup e riutilizzato nei refresh futuri. Non
    deve essere versionato perche' puo' contenere il client secret.
    """
    payload = {
        "client_id": client.client_id,
        "redirect_uri": client.redirect_uri,
        "token_url": client.token_url,
    }
    if client.client_secret:
        payload["client_secret"] = client.client_secret

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _with_expiry_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Aggiunge al payload token le informazioni di aggiornamento e scadenza.

    Fitbit restituisce normalmente `expires_in` in secondi. Convertirlo in una
    data assoluta facilita i controlli successivi e rende il file token piu'
    leggibile anche manualmente.
    """
    enriched = dict(payload)
    now = datetime.now(timezone.utc)
    enriched["updated_at"] = _format_datetime(now)
    expires_in = enriched.get("expires_in")
    if expires_in is not None:
        enriched["expires_at"] = _format_datetime(
            now + timedelta(seconds=int(expires_in))
        )
    return enriched


def _generate_code_verifier() -> str:
    """Genera il code verifier casuale richiesto da PKCE.

    Il verifier rimane solo in memoria durante il setup e viene usato per
    dimostrare che la richiesta token appartiene alla stessa sessione OAuth.
    """
    return secrets.token_urlsafe(64)[:128]


def _code_challenge(code_verifier: str) -> str:
    """Calcola il code challenge S256 a partire dal code verifier.

    Il challenge viene mandato nell'authorization URL, mentre il verifier viene
    usato successivamente nello scambio del codice. Questa coppia protegge il
    flusso da intercettazioni del codice temporaneo.
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _first(values: list[str] | None) -> str | None:
    """Restituisce il primo valore di una lista di parametri query.

    `parse_qs` produce liste anche quando un parametro compare una sola volta.
    Questa helper rende piu' chiara la lettura di `code`, `state` ed eventuali
    errori OAuth.
    """
    if not values:
        return None
    return values[0]


def _optional_str(value: Any) -> str | None:
    """Converte un valore opzionale in stringa non vuota.

    Serve per salvare o mostrare campi opzionali evitando di propagare stringhe
    composte solo da spazi.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_datetime(value: datetime) -> str:
    """Formatta una data in ISO UTC con suffisso `Z`.

    Usare sempre UTC nei file token evita ambiguita di fuso orario tra PC di
    sviluppo, Raspberry e servizi cloud.
    """
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    """Converte una stringa ISO, anche con suffisso `Z`, in `datetime` UTC.

    La funzione e' usata per verificare la scadenza del token indipendentemente
    dal formato ISO specifico salvato nel JSON.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
