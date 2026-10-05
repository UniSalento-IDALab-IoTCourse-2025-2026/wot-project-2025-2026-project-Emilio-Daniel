from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from edge_mqtt.messages import MqttMessage


@dataclass(frozen=True)
class QueuedMessage:
    """Messaggio MQTT persistito localmente quando il broker non e' disponibile."""

    path: Path
    message: MqttMessage


class DiskMqttQueue:
    """Coda FIFO su filesystem per non perdere eventi quando Internet non c'e'."""

    def __init__(self, queue_dir: Path) -> None:
        self.queue_dir = queue_dir
        self.last_quarantined: list[Path] = []

    def enqueue(self, message: MqttMessage) -> Path:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        target = self.queue_dir / self._file_name(message)
        temporary = target.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "topic": message.topic,
                    "qos": message.qos,
                    "retain": message.retain,
                    "payload": message.payload,
                },
                handle,
                indent=2,
                ensure_ascii=True,
                allow_nan=False,
            )
        temporary.replace(target)
        return target

    def iter_messages(self, limit: int) -> list[QueuedMessage]:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.last_quarantined = []
        queued: list[QueuedMessage] = []
        for path in sorted(self.queue_dir.glob("*.json"))[: max(0, limit)]:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                queued.append(
                    QueuedMessage(
                        path=path,
                        message=MqttMessage(
                            topic=str(payload["topic"]),
                            qos=int(payload.get("qos", 1)),
                            retain=bool(payload.get("retain", False)),
                            payload=dict(payload["payload"]),
                        ),
                    )
                )
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                self.last_quarantined.append(self._quarantine(path))
        return queued

    def remove(self, queued: QueuedMessage) -> None:
        queued.path.unlink(missing_ok=True)

    def depth(self) -> int:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        return len(list(self.queue_dir.glob("*.json")))

    def _file_name(self, message: MqttMessage) -> str:
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", message.message_id)[:96]
        return f"{now}-{safe_id}.json"

    def _quarantine(self, path: Path) -> Path:
        quarantine_dir = self.queue_dir / "quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        target = quarantine_dir / path.name
        counter = 1
        while target.exists():
            target = quarantine_dir / f"{path.stem}-{counter}{path.suffix}"
            counter += 1
        path.replace(target)
        return target
