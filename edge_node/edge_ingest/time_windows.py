from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_datetime(value: str, timezone_name: str) -> datetime:
    """Interpreta una data CLI usando il fuso configurato.

    Il valore speciale `now` indica l'istante corrente. Se l'utente fornisce una
    data senza timezone, viene applicato il fuso del progetto, cosi' le finestre
    restano coerenti con l'abitazione monitorata.
    """
    if value.lower() == "now":
        return datetime.now(ZoneInfo(timezone_name))

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed


def floor_window_end(value: datetime, window_minutes: int) -> datetime:
    """Arrotonda verso il basso la fine finestra al multiplo configurato.

    Per esempio, con finestre da 8 minuti, un orario qualsiasi viene riportato
    all'ultimo confine valido. Questo rende confrontabili i cicli periodici e
    impedisce finestre sovrapposte irregolari.
    """
    local = value
    minute = (local.minute // window_minutes) * window_minutes
    return local.replace(minute=minute, second=0, microsecond=0)


def window_from_end(window_end: datetime, window_minutes: int) -> tuple[datetime, datetime]:
    """Calcola in UTC inizio e fine della finestra da analizzare.

    Il runtime ragiona su una finestra chiusa di durata fissa. Restituire le date
    in UTC semplifica il confronto con timestamp salvati nei CSV grezzi.
    """
    end = floor_window_end(window_end, window_minutes)
    start = end - timedelta(minutes=window_minutes)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
