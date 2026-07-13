from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def utc_iso(value: datetime | None) -> str | None:
    """Converte un datetime in ISO 8601 UTC con suffisso Z."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def paginated(items: list[dict[str, Any]], page: int = 1, page_size: int | None = None) -> dict[str, Any]:
    """Costruisce una risposta paginata compatibile con dashboard e app."""
    effective_page_size = len(items) if page_size is None else max(page_size, 1)
    effective_page = max(page, 1)
    start = (effective_page - 1) * effective_page_size
    end = start + effective_page_size
    page_items = items[start:end] if page_size is not None else items
    return {
        "items": page_items,
        "page": effective_page,
        "page_size": effective_page_size,
        "total": len(items),
    }


def event_note_payload(note: str | None) -> dict[str, Any]:
    """Legge i metadati salvati in `alert_events.note` come JSON leggero."""
    if not note:
        return {}
    try:
        payload = json.loads(note)
    except json.JSONDecodeError:
        return {"note": note}
    return payload if isinstance(payload, dict) else {}


def dump_event_note(**payload: Any) -> str:
    """Serializza piccoli metadati audit senza aggiungere colonne prima di D7."""
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
