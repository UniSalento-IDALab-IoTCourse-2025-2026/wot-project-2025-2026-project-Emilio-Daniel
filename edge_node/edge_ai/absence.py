from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

KITCHEN_ROOMS = {"kitchen", "cucina"}
BATHROOM_ROOMS = {"bathroom", "bagno"}


@dataclass(frozen=True)
class AbsenceConfig:
    """Regole prudenti per l'assenza insolita (D24)."""

    no_movement_hours: float = 4.0
    no_amenity_hours: float = 12.0
    room_stay_multiplier: float = 2.5
    room_stay_min_minutes: float = 120.0
    ble_stale_minutes: float = 30.0
    resend_cooldown_hours: dict[str, float] = field(
        default_factory=lambda: {
            "no_movement": 6.0,
            "no_amenity_access": 12.0,
            "long_room_stay": 12.0,
            "ble_unreliable": 1.0,
        }
    )

    def cooldown_for(self, kind: str) -> timedelta:
        hours = self.resend_cooldown_hours.get(kind, 12.0)
        return timedelta(hours=float(hours))


@dataclass(frozen=True)
class AbsenceIndicators:
    """Indicatori calcolati da BLE e finestre storiche."""

    ble_available: bool
    ble_stale: bool
    ble_quality: str
    current_room: str | None = None
    last_seen_at: datetime | None = None
    last_transition_at: datetime | None = None
    minutes_since_last_room_change: float | None = None
    minutes_since_kitchen: float | None = None
    minutes_since_bathroom: float | None = None
    continuous_stay_minutes: float | None = None
    baseline_longest_stay_minutes: float | None = None


@dataclass(frozen=True)
class AbsenceSignal:
    """Un segnale di assenza insolita pronto per debounce e pubblicazione."""

    kind: str
    level: str
    category: str
    title: str
    description: str
    reason: str
    duration_minutes: float | None
    last_room: str | None
    last_transition_at: datetime | None = None
    ble_quality: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "level": self.level,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "reason": self.reason,
            "duration_minutes": (
                round(self.duration_minutes, 1) if self.duration_minutes is not None else None
            ),
            "no_movement_minutes": (
                round(self.duration_minutes, 1) if self.kind == "no_movement" else None
            ),
            "last_room": self.last_room,
            "last_transition_at": (
                self.last_transition_at.isoformat() if self.last_transition_at is not None else None
            ),
            "ble_quality": self.ble_quality,
        }

    def signature(self) -> str:
        return f"{self.kind}:{self.last_room or '-'}"


def build_absence_indicators(
    ble_csv: str | Path | None,
    now: datetime,
    *,
    ble_stale_minutes: float = 30.0,
    baseline_frame: Any = None,
) -> AbsenceIndicators:
    """Calcola gli indicatori di assenza dalla cronologia BLE e dalle finestre.

    La funzione legge la lista di campioni raw (timestamp + stanza) accumulata
    sul Raspberry e ricava: stanza corrente, ultima transizione, minuti senza
    cambi stanza, minuti senza accesso a cucina/bagno e durata della permanenza
    continua. Per il confronto con la baseline usa la mediana della permanenza
    massima singola delle finestre storiche.
    """
    if ble_csv is None or not Path(ble_csv).exists():
        return AbsenceIndicators(
            ble_available=False,
            ble_stale=True,
            ble_quality="assente",
        )

    frame = _load_ble_frame(Path(ble_csv))
    if frame.empty:
        return AbsenceIndicators(
            ble_available=False,
            ble_stale=True,
            ble_quality="assente",
        )

    last_seen = frame.iloc[-1]["timestamp"]
    current_room = str(frame.iloc[-1]["room"]).strip() or None
    last_seen_age_minutes = (now - last_seen).total_seconds() / 60.0
    ble_stale = last_seen_age_minutes > float(ble_stale_minutes)
    ble_quality = "stale" if ble_stale else "ok"

    if ble_stale:
        return AbsenceIndicators(
            ble_available=True,
            ble_stale=True,
            ble_quality=ble_quality,
            current_room=current_room,
            last_seen_at=last_seen,
        )

    last_transition_at = _last_transition_at(frame)
    minutes_since_last_room_change = (
        (now - last_transition_at).total_seconds() / 60.0 if last_transition_at else None
    )
    minutes_since_kitchen = _minutes_since_room(frame, KITCHEN_ROOMS, now)
    minutes_since_bathroom = _minutes_since_room(frame, BATHROOM_ROOMS, now)
    continuous_stay_minutes = (
        (now - last_transition_at).total_seconds() / 60.0 if last_transition_at else None
    )
    baseline_stay = baseline_longest_stay_minutes(baseline_frame)

    return AbsenceIndicators(
        ble_available=True,
        ble_stale=False,
        ble_quality=ble_quality,
        current_room=current_room,
        last_seen_at=last_seen,
        last_transition_at=last_transition_at,
        minutes_since_last_room_change=minutes_since_last_room_change,
        minutes_since_kitchen=minutes_since_kitchen,
        minutes_since_bathroom=minutes_since_bathroom,
        continuous_stay_minutes=continuous_stay_minutes,
        baseline_longest_stay_minutes=baseline_stay,
    )


def evaluate_absence(
    indicators: AbsenceIndicators,
    config: AbsenceConfig | None = None,
) -> AbsenceSignal | None:
    """Confronta gli indicatori con le regole prudenti e produce un segnale.

    Precedenza: guasto BLE, poi assenza di movimento, poi mancato accesso a
    bagno/cucina, infine permanenza in camera molto oltre baseline.
    """
    active_config = config or AbsenceConfig()

    if not indicators.ble_available:
        return _technical_signal("Il sensore di movimento (BLE) non ha mai inviato dati.")
    if indicators.ble_stale:
        return _technical_signal(
            f"Dati BLE non aggiornati (ultimo campione oltre "
            f"{active_config.ble_stale_minutes:.0f} minuti fa)."
        )

    no_movement_minutes = indicators.minutes_since_last_room_change or 0.0
    if no_movement_minutes >= active_config.no_movement_hours * 60.0:
        return AbsenceSignal(
            kind="no_movement",
            level="orange",
            category="no_movement",
            title="Assenza di movimento da verificare",
            description="Nessun cambio stanza da oltre 4 ore: verificare lo stato del paziente.",
            reason=f"Nessun movimento per oltre {active_config.no_movement_hours:.0f} ore.",
            duration_minutes=no_movement_minutes,
            last_room=indicators.current_room,
            last_transition_at=indicators.last_transition_at,
            ble_quality=indicators.ble_quality,
        )

    amenity_limit = active_config.no_amenity_hours * 60.0
    if indicators.minutes_since_bathroom is not None and indicators.minutes_since_bathroom >= amenity_limit:
        return AbsenceSignal(
            kind="no_amenity_access",
            level="orange",
            category="absence",
            title="Assenza insolita: nessun accesso al bagno",
            description="Nessun accesso al bagno da oltre 12 ore: un'eventuale disidratazione o "
            "immobilita' va esclusa dal personale.",
            reason=f"Nessun accesso al bagno da oltre {active_config.no_amenity_hours:.0f} ore.",
            duration_minutes=indicators.minutes_since_bathroom,
            last_room=indicators.current_room,
            last_transition_at=indicators.last_transition_at,
            ble_quality=indicators.ble_quality,
        )
    if indicators.minutes_since_kitchen is not None and indicators.minutes_since_kitchen >= amenity_limit:
        return AbsenceSignal(
            kind="no_amenity_access",
            level="orange",
            category="absence",
            title="Assenza insolita: nessun accesso alla cucina",
            description="Nessun accesso alla cucina da oltre 12 ore: igiene e nutrizione vanno "
            "verificate.",
            reason=f"Nessun accesso alla cucina da oltre {active_config.no_amenity_hours:.0f} ore.",
            duration_minutes=indicators.minutes_since_kitchen,
            last_room=indicators.current_room,
            last_transition_at=indicators.last_transition_at,
            ble_quality=indicators.ble_quality,
        )

    if (
        indicators.continuous_stay_minutes is not None
        and indicators.baseline_longest_stay_minutes is not None
        and indicators.continuous_stay_minutes
        >= max(
            indicators.baseline_longest_stay_minutes * active_config.room_stay_multiplier,
            active_config.room_stay_min_minutes,
        )
    ):
        return AbsenceSignal(
            kind="long_room_stay",
            level="yellow",
            category="absence",
            title="Permanenza in una stanza piu' lunga del solito",
            description="Il paziente resta nella stessa stanza molto oltre la sua baseline.",
            reason=f"Permanenza di {indicators.continuous_stay_minutes:.0f} minuti a fronte di una "
            f"mediana di {indicators.baseline_longest_stay_minutes:.0f} minuti.",
            duration_minutes=indicators.continuous_stay_minutes,
            last_room=indicators.current_room,
            last_transition_at=indicators.last_transition_at,
            ble_quality=indicators.ble_quality,
        )

    return None


def baseline_longest_stay_minutes(frame: Any) -> float | None:
    """Restituisce la mediana della permanenza massima singola delle finestre."""
    if frame is None:
        return None
    try:
        values = list(frame["longest_single_room_minutes"].dropna())
    except (KeyError, AttributeError, TypeError):
        return None
    if not values:
        return None
    return float(pd.Series(values).median())


class AbsenceDebouncer:
    """Debounce dedicato agli alert di assenza per evitare duplicati.

    Un segnale viene pubblicato quando cambia tipo/stanza o quando e' scaduto il
    cooldown (nuovo episodio di escalation). Se il paziente torna attivo, lo
    stato viene resettato cosi' un episodio successivo puo' essere segnalato.
    L'id dell'episodio corrente e' esposto per costruire un `message_id` stabile
    per il backend.
    """

    def __init__(self, config: AbsenceConfig | None = None):
        self.config = config or AbsenceConfig()
        self.last_signature: str | None = None
        self.last_emitted_at: datetime | None = None
        self.episode: int = 0

    @classmethod
    def load(cls, path: str | Path, config: AbsenceConfig | None = None) -> "AbsenceDebouncer":
        debouncer = cls(config)
        target = Path(path)
        if not target.exists():
            return debouncer
        try:
            with target.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            debouncer.last_signature = str(data.get("last_signature") or "") or None
            debouncer.episode = int(data.get("episode") or 0)
            emitted_at = parse_timestamp(data.get("last_emitted_at"))
            debouncer.last_emitted_at = emitted_at if emitted_at else None
        except (OSError, ValueError, TypeError):
            pass
        return debouncer

    def update(self, signal: AbsenceSignal | None, now: datetime) -> AbsenceSignal | None:
        """Aggiorna lo stato e restituisce il segnale da pubblicare, se presente.

        `None` in ingresso significa paziente tornato attivo: resetta lo stato.
        Il ritorno `None` indica che il segnale non va pubblicato ora (cooldown
        dello stesso episodio).
        """
        if signal is None:
            self.last_signature = None
            return None

        cooldown_expired = False
        if self.last_emitted_at is not None:
            cooldown = self.config.cooldown_for(signal.kind)
            cooldown_expired = (now - self.last_emitted_at) >= cooldown

        if self.last_signature != signal.signature() or cooldown_expired:
            self.episode += 1
            self.last_signature = signal.signature()
            self.last_emitted_at = now
            return signal
        return None

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_signature": self.last_signature,
            "episode": self.episode,
            "last_emitted_at": (
                self.last_emitted_at.isoformat() if self.last_emitted_at is not None else None
            ),
        }
        with target.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)


def absence_message_id(patient_id: str, signal: AbsenceSignal, episode: int) -> str:
    """Genera un message_id stabile per lo stesso episodio di assenza."""
    from hashlib import sha1

    detail = signal.signature().replace(":", "-")
    digest = sha1(f"{patient_id}:{detail}:{episode}".encode("utf-8")).hexdigest()[:10]
    return f"absence-{digest}"


def _load_ble_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if frame.empty:
        return frame
    if "timestamp" not in frame.columns or "room" not in frame.columns:
        raise ValueError("BLE CSV must contain timestamp and room columns")
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"],
        utc=True,
        errors="coerce",
        format="mixed",
    )
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    frame["room"] = frame["room"].astype(str).str.strip().str.lower()
    return frame


def _last_transition_at(frame: pd.DataFrame) -> datetime | None:
    """Timestamp di inizio della permanenza continua attuale.

    Se nella cronologia c'e' una sola stanza, la permanenza parte dal primo
    campione. In caso contrario, parte dalla prima occorrenza della stanza
    attuale dopo l'ultimo cambio.
    """
    rooms = list(frame["room"])
    current_room = rooms[-1]
    run_start = len(rooms) - 1
    for index in range(len(rooms) - 2, -1, -1):
        if rooms[index] != current_room:
            break
        run_start = index
    return frame.iloc[run_start]["timestamp"].to_pydatetime()


def _minutes_since_room(frame: pd.DataFrame, rooms: set[str], now: datetime) -> float | None:
    matching = frame.loc[frame["room"].isin(rooms)]
    if matching.empty:
        return None
    last = matching.iloc[-1]["timestamp"]
    return (now - last).total_seconds() / 60.0


def _technical_signal(reason: str) -> AbsenceSignal:
    return AbsenceSignal(
        kind="ble_unreliable",
        level="technical",
        category="technical",
        title="Sensore di movimento non affidabile",
        description="Il BLE non fornisce dati:\n" + reason,
        reason=reason,
        duration_minutes=None,
        last_room=None,
        ble_quality="assente",
    )


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if parsed is None or parsed is pd.NaT:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(timezone.utc)
    return parsed.to_pydatetime()