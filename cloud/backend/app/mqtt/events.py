from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class InternalEvent:
    """Evento emesso dopo l'ingestione MQTT per il futuro gestore WebSocket."""

    event_type: str
    patient_id: str
    timestamp: datetime
    payload: dict[str, Any]


class InMemoryEventBus:
    """Raccoglitore eventi temporaneo usato finche' non sara' pronta la D6."""

    def __init__(self) -> None:
        self.events: list[InternalEvent] = []

    def publish(self, event: InternalEvent) -> None:
        self.events.append(event)


event_bus = InMemoryEventBus()
