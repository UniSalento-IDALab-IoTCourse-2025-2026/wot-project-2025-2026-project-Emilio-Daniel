from __future__ import annotations

import csv
from datetime import datetime, timedelta
from math import nan
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from edge_ai.schema import DATASET_COLUMNS, FEATURE_COLUMNS
from edge_ingest.ble_adapter import BleCsvAdapter
from edge_ingest.config import EdgeIngestConfig
from edge_ingest.fitbit_adapter import FitbitAdapter
from edge_ingest.google_health_adapter import GoogleHealthAdapter
from edge_ingest.shelly_adapter import ShellyCsvAdapter


def build_feature_window(
    config: EdgeIngestConfig,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    """Costruisce una singola riga feature fondendo tutte le sorgenti attive.

    La finestra temporale e' l'unita minima che il modello AI analizza. La
    funzione inizializza tutte le colonne previste dallo schema e poi aggiorna i
    valori con i dati disponibili da Fitbit legacy, Google Health, BLE e Shelly,
    lasciando `nan` dove una sorgente non e' abilitata o non ha prodotto dati.
    """
    row: dict[str, Any] = {
        "patient_id": config.patient.patient_id,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "wearable_present": "",
        "wearable_battery_pct": "",
    }
    row.update({column: nan for column in FEATURE_COLUMNS})

    if config.fitbit.enabled:
        # Adapter legacy: resta utile solo per vecchie credenziali Fitbit Web API.
        local_zone = ZoneInfo(config.window.timezone)
        row.update(
            FitbitAdapter(config.fitbit).collect_window(
                window_start.astimezone(local_zone),
                window_end.astimezone(local_zone),
            )
        )
    if config.google_health.enabled:
        # Percorso attuale per Pixel Watch 2: legge dati cloud Google Health.
        # Il delay e' solo per questa sorgente: BLE/Shelly restano sulla
        # finestra corrente, mentre il Watch usa una finestra cloud consolidata.
        google_delay = timedelta(minutes=max(0, config.google_health.data_delay_minutes))
        row.update(
            GoogleHealthAdapter(config.google_health).collect_window(
                window_start - google_delay,
                window_end - google_delay,
            )
        )
    if config.ble.enabled:
        row.update(
            BleCsvAdapter(config.ble, config.window.timezone).collect_window(
                window_start,
                window_end,
            )
        )
    if config.shelly.enabled:
        row.update(ShellyCsvAdapter(config.shelly).collect_window(window_start, window_end))

    return row


def write_latest_window(path: str | Path, row: dict[str, Any]) -> None:
    """Scrive su CSV l'ultima finestra aggregata.

    Questo file rappresenta l'input diretto dell'inferenza edge. Viene riscritto
    a ogni ciclo per contenere sempre la finestra piu' recente, evitando di far
    crescere inutilmente il file usato dal modello in tempo reale.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
        writer.writeheader()
        writer.writerow(_ordered_row(row))


def append_baseline_row(path: str | Path, row: dict[str, Any]) -> None:
    """Aggiunge una finestra valida al dataset baseline.

    Durante la fase di calibrazione le finestre accettate vengono accumulate in
    `baseline.csv`. Quel file diventera' il dataset di training personale del
    paziente.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    file_exists = target.exists() and target.stat().st_size > 0
    with target.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(_ordered_row(row))


def _ordered_row(row: dict[str, Any]) -> dict[str, Any]:
    """Riordina la riga secondo lo schema ufficiale del dataset.

    Usare sempre `DATASET_COLUMNS` garantisce che CSV di baseline e latest
    window abbiano colonne stabili, requisito importante per training,
    inferenza e documentazione del progetto.
    """
    return {column: row.get(column, "") for column in DATASET_COLUMNS}
