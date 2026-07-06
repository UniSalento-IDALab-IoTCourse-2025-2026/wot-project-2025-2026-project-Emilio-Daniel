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
class AIConfig:
    generic_model: Path
    generic_spatial_model: Path
    generic_wearable_model: Path
    personal_model: Path | None = None
    baseline_gate_enabled: bool = True
    baseline_gate_block_score: float = 60.0


@dataclass(frozen=True)
class FitbitConfig:
    enabled: bool = False
    token_file: Path = Path("config/fitbit_token.json")
    client_file: Path = Path("config/fitbit_client.json")
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
    ai: AIConfig
    fitbit: FitbitConfig
    ble: BleConfig
    shelly: ShellyConfig


def load_config(path: str | Path) -> EdgeIngestConfig:
    """Carica il file YAML dell'edge node e costruisce configurazioni tipizzate.

    Il progetto usa un solo file YAML per paziente, finestre temporali, percorsi
    dati e sorgenti hardware. Trasformarlo in dataclass rende il resto del codice
    piu' chiaro e riduce errori dovuti a chiavi mancanti.
    """
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
        ai=AIConfig(
            generic_model=Path(
                _section(payload, "ai").get(
                    "generic_model",
                    "models/generic.pkl",
                )
            ),
            generic_spatial_model=Path(
                _section(payload, "ai").get(
                    "generic_spatial_model",
                    _section(payload, "ai").get(
                        "generic_model",
                        "models/generic_spatial.pkl",
                    ),
                )
            ),
            generic_wearable_model=Path(
                _section(payload, "ai").get(
                    "generic_wearable_model",
                    "models/generic_wearable.pkl",
                )
            ),
            personal_model=_optional_path(
                _section(payload, "ai").get("personal_model")
            ),
            baseline_gate_enabled=bool(
                _section(payload, "ai").get("baseline_gate_enabled", True)
            ),
            baseline_gate_block_score=float(
                _section(payload, "ai").get("baseline_gate_block_score", 60.0)
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
            client_file=Path(
                _section(payload, "fitbit").get(
                    "client_file",
                    "config/fitbit_client.json",
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
    """Restituisce una sezione YAML come dizionario, anche se assente o invalida.

    Questa helper permette di usare valori di default quando una sezione non e'
    presente nel file, evitando controlli ripetuti in `load_config`.
    """
    value = payload.get(key, {})
    if isinstance(value, dict):
        return value
    return {}


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    """Normalizza un valore YAML in una tupla di stringhe.

    Alcuni campi, come target BLE, possono essere scritti come stringa singola o
    come lista. La funzione produce sempre una tupla pulita, piu' comoda da usare
    nei filtri runtime.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _optional_path(value: Any) -> Path | None:
    """Converte un valore YAML opzionale in `Path` solo quando e' presente.

    Il modello personale puo' essere lasciato vuoto nel file di configurazione:
    in quel caso il runtime usera' automaticamente `models/<patient_id>.pkl`.
    Questa helper evita di confondere una stringa vuota con un percorso reale.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(text)
