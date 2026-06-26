from __future__ import annotations

import asyncio
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from math import pow
from pathlib import Path
from typing import Any

from edge_ingest.config import BleConfig


BLE_SAMPLE_COLUMNS = [
    "timestamp",
    "room",
    "scanner_id",
    "address",
    "name",
    "rssi",
    "tx_power",
    "distance_m",
    "service_uuids",
    "manufacturer_data",
]


@dataclass(frozen=True)
class BleSample:
    timestamp: str
    room: str
    scanner_id: str
    address: str
    name: str
    rssi: int
    tx_power: int
    distance_m: float
    service_uuids: str
    manufacturer_data: str


class BleTagCollector:
    """Scans a wearable BLE tag and appends raw samples to data/raw/ble_samples.csv."""

    def __init__(self, config: BleConfig):
        self.config = config

    async def scan_once(self) -> list[BleSample]:
        if (
            not self.config.target_addresses
            and not self.config.target_names
            and not self.config.allow_unfiltered_scan
        ):
            raise ValueError(
                "Configure ble.target_addresses or ble.target_names before collecting samples. "
                "Use python -m edge_ingest.ble_cli --discover first."
            )

        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise RuntimeError(
                "Missing BLE dependency. Install requirements with: pip install -r requirements.txt"
            ) from exc

        samples: list[BleSample] = []
        seen: set[tuple[str, int]] = set()

        def on_detection(device: Any, advertisement_data: Any) -> None:
            rssi = int(getattr(advertisement_data, "rssi", getattr(device, "rssi", -127)))
            if rssi < self.config.rssi_min:
                return

            address = str(getattr(device, "address", "")).upper()
            name = str(
                getattr(device, "name", None)
                or getattr(advertisement_data, "local_name", None)
                or ""
            )
            if not self._matches_target(address, name):
                return

            # Keep one sample per device/RSSI value inside the scan window to avoid bloating the CSV.
            key = (address, rssi)
            if key in seen:
                return
            seen.add(key)

            tx_power = getattr(advertisement_data, "tx_power", None)
            if tx_power is None:
                tx_power = self.config.tx_power_at_1m
            tx_power = int(tx_power)

            sample = BleSample(
                timestamp=datetime.now(timezone.utc).isoformat(),
                room=self.config.scanner_room,
                scanner_id=self.config.scanner_id,
                address=address,
                name=name,
                rssi=rssi,
                tx_power=tx_power,
                distance_m=_estimate_distance_m(
                    rssi=rssi,
                    tx_power_at_1m=tx_power,
                    path_loss_exponent=self.config.path_loss_exponent,
                ),
                service_uuids=json.dumps(
                    list(getattr(advertisement_data, "service_uuids", []) or [])
                ),
                manufacturer_data=json.dumps(
                    _stringify_manufacturer_data(
                        getattr(advertisement_data, "manufacturer_data", {}) or {}
                    )
                ),
            )
            samples.append(sample)

        scanner = BleakScanner(detection_callback=on_detection)
        await scanner.start()
        try:
            await asyncio.sleep(self.config.scan_seconds)
        finally:
            await scanner.stop()

        return samples

    def append_samples(self, samples: list[BleSample]) -> None:
        if not samples:
            return

        target = self.config.raw_csv
        target.parent.mkdir(parents=True, exist_ok=True)
        file_exists = target.exists() and target.stat().st_size > 0
        with target.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=BLE_SAMPLE_COLUMNS)
            if not file_exists:
                writer.writeheader()
            for sample in samples:
                writer.writerow(sample.__dict__)

    def _matches_target(self, address: str, name: str) -> bool:
        configured_addresses = {item.upper() for item in self.config.target_addresses}
        if configured_addresses and address not in configured_addresses:
            return False

        configured_names = tuple(item.lower() for item in self.config.target_names)
        if configured_names and not any(item in name.lower() for item in configured_names):
            return False

        if configured_addresses or configured_names:
            return True
        return self.config.allow_unfiltered_scan


def collect_ble_samples(config: BleConfig) -> list[BleSample]:
    collector = BleTagCollector(config)
    samples = asyncio.run(collector.scan_once())
    collector.append_samples(samples)
    return samples


def discover_ble_devices(config: BleConfig) -> list[dict[str, Any]]:
    return asyncio.run(_discover_ble_devices_async(config))


async def _discover_ble_devices_async(config: BleConfig) -> list[dict[str, Any]]:
    try:
        from bleak import BleakScanner
    except ImportError as exc:
        raise RuntimeError(
            "Missing BLE dependency. Install requirements with: pip install -r requirements.txt"
        ) from exc

    devices: dict[str, dict[str, Any]] = {}

    def on_detection(device: Any, advertisement_data: Any) -> None:
        address = str(getattr(device, "address", "")).upper()
        if not address:
            return
        rssi = int(getattr(advertisement_data, "rssi", getattr(device, "rssi", -127)))
        name = str(
            getattr(device, "name", None)
            or getattr(advertisement_data, "local_name", None)
            or ""
        )
        current = devices.get(address)
        if current is None or rssi > int(current["rssi"]):
            devices[address] = {
                "address": address,
                "name": name,
                "rssi": rssi,
                "tx_power": getattr(advertisement_data, "tx_power", None),
            }

    scanner = BleakScanner(detection_callback=on_detection)
    await scanner.start()
    try:
        await asyncio.sleep(config.scan_seconds)
    finally:
        await scanner.stop()

    return sorted(devices.values(), key=lambda item: int(item["rssi"]), reverse=True)


def _estimate_distance_m(rssi: int, tx_power_at_1m: int, path_loss_exponent: float) -> float:
    if path_loss_exponent <= 0:
        return 0.0
    distance = pow(10.0, (tx_power_at_1m - rssi) / (10.0 * path_loss_exponent))
    return round(float(distance), 3)


def _stringify_manufacturer_data(payload: dict[Any, bytes]) -> dict[str, str]:
    return {
        str(company_id): value.hex() if isinstance(value, bytes) else str(value)
        for company_id, value in payload.items()
    }
