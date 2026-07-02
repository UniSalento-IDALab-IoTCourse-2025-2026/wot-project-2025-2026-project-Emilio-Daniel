from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edge_ingest.ble_collector import BLE_SAMPLE_COLUMNS


@dataclass(frozen=True)
class AndroidBleSample:
    room: str
    rssi: int
    beacon_id: str
    timestamp: datetime | None = None
    beacon_name: str = ""
    phone_id: str = "android-phone"
    tx_power: int | None = None
    distance_m: float | None = None
    service_uuids: list[str] | None = None
    manufacturer_data: dict[str, Any] | None = None


def append_android_ble_sample(path: str | Path, sample: AndroidBleSample) -> dict[str, Any]:
    """Normalizza e salva un campione BLE proveniente dall'app Android.

    La funzione traduce il formato ricevuto via HTTP nello stesso schema CSV
    usato dal collector BLE del Raspberry. In questo modo l'aggregatore puo'
    leggere campioni Android e campioni Raspberry senza logiche separate.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    timestamp = sample.timestamp or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)

    row = {
        "timestamp": timestamp.isoformat(),
        "room": sample.room.strip().lower(),
        "scanner_id": sample.phone_id.strip() or "android-phone",
        "address": sample.beacon_id.strip().upper(),
        "name": sample.beacon_name.strip(),
        "rssi": int(sample.rssi),
        "tx_power": "" if sample.tx_power is None else int(sample.tx_power),
        "distance_m": "" if sample.distance_m is None else float(sample.distance_m),
        "service_uuids": json.dumps(sample.service_uuids or []),
        "manufacturer_data": json.dumps(sample.manufacturer_data or {}),
    }

    file_exists = target.exists() and target.stat().st_size > 0
    with target.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=BLE_SAMPLE_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    return row
