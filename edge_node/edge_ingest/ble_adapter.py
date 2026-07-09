from __future__ import annotations

from datetime import datetime
from math import isnan
from zoneinfo import ZoneInfo

import pandas as pd

from edge_ingest.config import BleConfig


ROOM_FEATURES = {
    "bedroom": "bedroom_minutes",
    "camera": "bedroom_minutes",
    "kitchen": "kitchen_minutes",
    "cucina": "kitchen_minutes",
    "bathroom": "bathroom_minutes",
    "bagno": "bathroom_minutes",
    "living_room": "living_room_minutes",
    "soggiorno": "living_room_minutes",
}


class BleCsvAdapter:
    """Aggregates real BLE positioning samples previously collected on the Raspberry Pi."""

    def __init__(self, config: BleConfig, timezone_name: str):
        """Inizializza l'adapter BLE CSV con configurazione e fuso orario.

        L'adapter non scansiona direttamente i dispositivi: legge campioni gia'
        salvati in `data/raw/ble_samples.csv` e li trasforma in feature spaziali
        compatibili con il modello AI.
        """
        self.config = config
        self.timezone_name = timezone_name

    def collect_window(self, window_start: datetime, window_end: datetime) -> dict[str, float]:
        """Aggrega i campioni BLE appartenenti alla finestra richiesta.

        La funzione calcola minuti per stanza, cambi stanza, cambi notturni e
        permanenza massima continua. Queste feature permettono di descrivere il
        comportamento spaziale del paziente senza usare telecamere o microfoni.
        """
        if not self.config.raw_csv.exists():
            return {}

        frame = pd.read_csv(self.config.raw_csv)
        if frame.empty:
            return {}
        if "timestamp" not in frame.columns or "room" not in frame.columns:
            raise ValueError("BLE CSV must contain timestamp and room columns")

        frame["timestamp"] = pd.to_datetime(
            frame["timestamp"],
            utc=True,
            errors="coerce",
            format="mixed",
        )
        frame = frame.dropna(subset=["timestamp"])
        if frame.empty:
            return {}
        mask = (frame["timestamp"] >= window_start) & (frame["timestamp"] <= window_end)
        window = frame.loc[mask].sort_values("timestamp").copy()
        if window.empty:
            return {}

        room_sequence = _resolve_room_sequence(window)
        if room_sequence.empty:
            return {}

        features = {
            "bedroom_minutes": 0.0,
            "kitchen_minutes": 0.0,
            "bathroom_minutes": 0.0,
            "living_room_minutes": 0.0,
            "room_changes": 0.0,
            "night_room_changes": 0.0,
            "longest_single_room_minutes": 0.0,
        }

        timestamps = list(room_sequence["timestamp"])
        rooms = list(room_sequence["room_key"])
        durations_by_room: dict[str, float] = {}
        longest_single_room = 0.0

        for index, current_time in enumerate(timestamps):
            next_time = timestamps[index + 1] if index + 1 < len(timestamps) else window_end
            minutes = max(0.0, (next_time - current_time).total_seconds() / 60.0)
            if isnan(minutes):
                continue
            room = rooms[index]
            durations_by_room[room] = durations_by_room.get(room, 0.0) + minutes
            longest_single_room = max(longest_single_room, minutes)

        for room, minutes in durations_by_room.items():
            feature_name = ROOM_FEATURES.get(room)
            if feature_name:
                features[feature_name] += minutes

        changes = sum(1 for before, after in zip(rooms, rooms[1:]) if before != after)
        features["room_changes"] = float(changes)
        local_start = window_start.astimezone(ZoneInfo(self.timezone_name))
        local_end = window_end.astimezone(ZoneInfo(self.timezone_name))
        if 0 <= local_start.hour < 6 or 0 <= local_end.hour < 6:
            features["night_room_changes"] = float(changes)
        features["longest_single_room_minutes"] = longest_single_room
        return features


def _resolve_room_sequence(window: pd.DataFrame) -> pd.DataFrame:
    """Ricostruisce la sequenza stanza-tempo dai campioni BLE grezzi.

    Se sono presenti valori RSSI, per ogni bucket temporale viene scelta la
    stanza con segnale piu' forte, assumendo che corrisponda al beacon/scanner
    piu' vicino. Questo riduce rumore e duplicati prima di calcolare le durate.
    """
    prepared = window.copy()
    prepared["room_key"] = prepared["room"].astype(str).str.strip().str.lower()

    if "rssi" not in prepared.columns:
        return prepared.loc[:, ["timestamp", "room_key"]].sort_values(by=["timestamp"])

    prepared["rssi_value"] = pd.to_numeric(prepared["rssi"], errors="coerce")
    prepared = prepared.dropna(subset=["rssi_value"])
    if prepared.empty:
        return pd.DataFrame(columns=pd.Index(["timestamp", "room_key"]))

    # Multiple fixed scanners can hear the same wearable tag. For each 30-second bucket,
    # keep the room with the strongest RSSI, which is the closest scanner.
    prepared["bucket"] = prepared["timestamp"].dt.floor("30s")
    strongest_indexes = prepared.groupby("bucket")["rssi_value"].idxmax()
    resolved = prepared.loc[strongest_indexes].sort_values(by="timestamp")
    return resolved[["timestamp", "room_key"]]
