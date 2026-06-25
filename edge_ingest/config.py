from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PatientConfig:
    patient_id: str


@dataclass(frozen=True)
class WindowConfig:
    minutes: int = 8
    timezone: str = "Europe/Rome"


@dataclass(frozen=True)
class PathsConfig:
    latest_window_csv: Path
    baseline_csv: Path


@dataclass(frozen=True)
class FitbitConfig:
    enabled: bool = False
    token_file: Path = Path("config/fitbit_token.json")
    user_id: str = "-"
    api_base_url: str = "https://api.fitbit.com"


@dataclass(frozen=True)
class BleConfig:
    enabled: bool = False
    raw_csv: Path = Path("data/raw/ble_samples.csv")
    scanner_room: str = "living_room"
    scanner_id: str = "rpi-main"
    target_addresses: tuple[str, ...] = ()
    target_names: tuple[str, ...] = ()
    allow_unfiltered_scan: bool = False
    scan_seconds: float = 30.0
    rssi_min: int = -95
    tx_power_at_1m: int = -59
    path_loss_exponent: float = 2.0


@dataclass(frozen=True)
class ShellyConfig:
    enabled: bool = False
    raw_csv: Path = Path("data/raw/shelly_samples.csv")


@dataclass(frozen=True)
class EdgeIngestConfig:
    patient: PatientConfig
    window: WindowConfig
    paths: PathsConfig
    fitbit: FitbitConfig
    ble: BleConfig
    shelly: ShellyConfig


def load_config(path: str | Path) -> EdgeIngestConfig:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    return EdgeIngestConfig(
        patient=PatientConfig(
            patient_id=str(_section(payload, "patient").get("id", "patient-001")),
        ),
        window=WindowConfig(
            minutes=int(_section(payload, "window").get("minutes", 8)),
            timezone=str(_section(payload, "window").get("timezone", "Europe/Rome")),
        ),
        paths=PathsConfig(
            latest_window_csv=Path(
                _section(payload, "paths").get(
                    "latest_window_csv",
                    "data/processed/latest_window.csv",
                )
            ),
            baseline_csv=Path(
                _section(payload, "paths").get(
                    "baseline_csv",
                    "data/processed/baseline.csv",
                )
            ),
        ),
        fitbit=FitbitConfig(
            enabled=bool(_section(payload, "fitbit").get("enabled", False)),
            token_file=Path(
                _section(payload, "fitbit").get(
                    "token_file",
                    "config/fitbit_token.json",
                )
            ),
            user_id=str(_section(payload, "fitbit").get("user_id", "-")),
            api_base_url=str(
                _section(payload, "fitbit").get(
                    "api_base_url",
                    "https://api.fitbit.com",
                )
            ).rstrip("/"),
        ),
        ble=BleConfig(
            enabled=bool(_section(payload, "ble").get("enabled", False)),
            raw_csv=Path(
                _section(payload, "ble").get(
                    "raw_csv",
                    "data/raw/ble_samples.csv",
                )
            ),
            scanner_room=str(_section(payload, "ble").get("scanner_room", "living_room")),
            scanner_id=str(_section(payload, "ble").get("scanner_id", "rpi-main")),
            target_addresses=_tuple_of_strings(
                _section(payload, "ble").get("target_addresses", [])
            ),
            target_names=_tuple_of_strings(
                _section(payload, "ble").get("target_names", [])
            ),
            allow_unfiltered_scan=bool(
                _section(payload, "ble").get("allow_unfiltered_scan", False)
            ),
            scan_seconds=float(_section(payload, "ble").get("scan_seconds", 30.0)),
            rssi_min=int(_section(payload, "ble").get("rssi_min", -95)),
            tx_power_at_1m=int(_section(payload, "ble").get("tx_power_at_1m", -59)),
            path_loss_exponent=float(
                _section(payload, "ble").get("path_loss_exponent", 2.0)
            ),
        ),
        shelly=ShellyConfig(
            enabled=bool(_section(payload, "shelly").get("enabled", False)),
            raw_csv=Path(
                _section(payload, "shelly").get(
                    "raw_csv",
                    "data/raw/shelly_samples.csv",
                )
            ),
        ),
    )


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if isinstance(value, dict):
        return value
    return {}


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item).strip())
    return ()
