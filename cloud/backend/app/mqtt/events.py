from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class InternalEvent:
    """Evento interno da inoltrare ai client WebSocket collegati."""

    event_type: str
    patient_id: str
    timestamp: datetime
    payload: dict[str, Any]
    event_id: str = ""

    def to_websocket_payload(self) -> dict[str, Any]:
        """Serializza l'evento nel formato concordato con dashboard/app."""
        timestamp = self.timestamp
        if timestamp.tzinfo is None:
            from datetime import timezone

            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return {
            "event_type": self.event_type,
            "event_id": self.event_id or f"event-{uuid4().hex}",
            "patient_id": self.patient_id,
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "payload": self.payload,
        }


class InMemoryEventBus:
    """Raccoglitore eventi in memoria usato dal WebSocket D6."""

    def __init__(self) -> None:
        self.events: list[InternalEvent] = []

    def publish(self, event: InternalEvent) -> None:
        if not event.event_id:
            event = InternalEvent(
                event_type=event.event_type,
                patient_id=event.patient_id,
                timestamp=event.timestamp,
                payload=event.payload,
                event_id=f"event-{uuid4().hex}",
            )
        self.events.append(event)

    def events_after(self, index: int, patient_id: str) -> tuple[int, list[InternalEvent]]:
        """Restituisce gli eventi nuovi per un paziente e il prossimo cursore."""
        next_index = len(self.events)
        return next_index, [
            event for event in self.events[index:] if event.patient_id == patient_id
        ]


event_bus = InMemoryEventBus()
