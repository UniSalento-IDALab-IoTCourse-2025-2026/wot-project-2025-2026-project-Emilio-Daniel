from __future__ import annotations

from datetime import datetime

import pandas as pd

from edge_ingest.config import ShellyConfig


class ShellyCsvAdapter:
    """Aggregates real Shelly/NILM samples collected by a separate sampler."""

    def __init__(self, config: ShellyConfig):
        """Inizializza l'adapter Shelly/NILM basato su CSV grezzo.

        In questa fase il collector HTTP reale non e' ancora definitivo, quindi
        l'adapter legge campioni gia' salvati in CSV e li converte in feature
        energetiche compatibili con il modello.
        """
        self.config = config

    def collect_window(self, window_start: datetime, window_end: datetime) -> dict[str, float]:
        """Aggrega consumi ed eventi elettrodomestici nella finestra richiesta.

        La funzione stima energia totale, eventi cucina/caffe/fornelli e minuti
        TV quando tali colonne sono presenti. Se Shelly/NILM non verra' usato,
        queste feature resteranno semplicemente disabilitate.
        """
        if not self.config.raw_csv.exists():
            return {}

        frame = pd.read_csv(self.config.raw_csv)
        if frame.empty:
            return {}
        if "timestamp" not in frame.columns:
            raise ValueError("Shelly CSV must contain a timestamp column")

        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        mask = (frame["timestamp"] >= window_start) & (frame["timestamp"] <= window_end)
        window = frame.loc[mask].sort_values("timestamp").copy()
        if window.empty:
            return {}

        features = {
            "nilm_total_wh": 0.0,
            "nilm_kitchen_events": 0.0,
            "nilm_tv_minutes": 0.0,
            "nilm_coffee_events": 0.0,
            "nilm_stove_events": 0.0,
        }

        if "power_w" in window.columns:
            avg_power_w = float(pd.to_numeric(window["power_w"], errors="coerce").mean())
            hours = (window_end - window_start).total_seconds() / 3600.0
            features["nilm_total_wh"] = max(0.0, avg_power_w * hours)

        if "appliance" in window.columns:
            appliances = window["appliance"].astype(str).str.strip().str.lower()
            features["nilm_kitchen_events"] = float(
                appliances.isin(["kitchen", "cucina"]).sum()
            )
            features["nilm_coffee_events"] = float(
                appliances.isin(["coffee", "macchina_caffe", "caffe"]).sum()
            )
            features["nilm_stove_events"] = float(
                appliances.isin(["stove", "fornelli", "forno"]).sum()
            )

        if "tv_active" in window.columns:
            active = pd.to_numeric(window["tv_active"], errors="coerce").fillna(0)
            features["nilm_tv_minutes"] = float(active.sum())

        return features
