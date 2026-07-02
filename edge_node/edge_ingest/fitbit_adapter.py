from __future__ import annotations

import json
from datetime import datetime
from statistics import mean, pstdev
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from edge_auth.fitbit_oauth import load_valid_access_token, refresh_access_token
from edge_ingest.config import FitbitConfig


class FitbitAdapter:
    """Collects real biometrics from Fitbit Web API using an OAuth access token."""

    def __init__(self, config: FitbitConfig):
        """Inizializza l'adapter Fitbit con i percorsi token e API.

        L'adapter non parla direttamente con il Pixel Watch via BLE: interroga
        le API Fitbit usando i token OAuth salvati localmente dal modulo
        `edge_auth`.
        """
        self.config = config

    def collect_window(self, window_start: datetime, window_end: datetime) -> dict[str, float | str]:
        """Raccoglie le metriche Fitbit disponibili per una finestra temporale.

        La funzione scarica frequenza cardiaca intraday e metriche giornaliere
        opzionali, poi restituisce solo le feature compatibili con lo schema del
        modello. Se alcune API non forniscono dati, le colonne resteranno vuote
        o `nan` nell'aggregatore.
        """
        token = self._load_access_token()
        patient = quote(self.config.user_id, safe="-")
        start_date = window_start.date().isoformat()
        end_date = window_end.date().isoformat()
        start_time = window_start.strftime("%H:%M")
        end_time = window_end.strftime("%H:%M")

        features: dict[str, float | str] = {}

        heart_payload = self._get_json(
            token,
            f"/1/user/{patient}/activities/heart/date/{start_date}/{end_date}/1min/time/{start_time}/{end_time}.json",
        )
        heart_values = [
            float(item["value"])
            for item in heart_payload.get("activities-heart-intraday", {}).get("dataset", [])
            if "value" in item
        ]
        if heart_values:
            features["heart_rate_mean"] = mean(heart_values)
            features["heart_rate_std"] = pstdev(heart_values) if len(heart_values) > 1 else 0.0

        daily_heart = heart_payload.get("activities-heart", [])
        if daily_heart:
            resting = daily_heart[0].get("value", {}).get("restingHeartRate")
            if resting is not None:
                features["resting_heart_rate"] = float(resting)

        features.update(self._collect_optional_daily_metrics(token, patient, start_date))
        features.update(self._collect_device_status(token, patient))
        return features

    def _collect_optional_daily_metrics(
        self,
        token: str,
        patient: str,
        date: str,
    ) -> dict[str, float]:
        """Recupera metriche Fitbit giornaliere non sempre disponibili.

        HRV, SpO2 e sonno possono dipendere da dispositivo, consenso OAuth,
        qualita della misura e disponibilita API. Per questo vengono interrogati
        in modo tollerante: se mancano, l'adapter continua senza fallire.
        """
        metrics: dict[str, float] = {}

        hrv = self._try_get_json(token, f"/1/user/{patient}/hrv/date/{date}.json")
        if hrv:
            values = hrv.get("hrv", [])
            if values:
                rmssd = values[0].get("value", {}).get("dailyRmssd")
                if rmssd is not None:
                    metrics["hrv_rmssd"] = float(rmssd)

        spo2 = self._try_get_json(token, f"/1/user/{patient}/spo2/date/{date}.json")
        if spo2:
            values = spo2.get("spo2", [])
            if values:
                avg = values[0].get("value", {}).get("avg")
                if avg is not None:
                    metrics["spo2_mean"] = float(avg)

        sleep = self._try_get_json(token, f"/1.2/user/{patient}/sleep/date/{date}.json")
        if sleep:
            summary = sleep.get("summary", {})
            total_minutes_asleep = summary.get("totalMinutesAsleep")
            total_time_in_bed = summary.get("totalTimeInBed")
            if total_minutes_asleep is not None:
                metrics["sleep_minutes"] = float(total_minutes_asleep)
            if total_minutes_asleep is not None and total_time_in_bed is not None:
                metrics["awake_minutes"] = max(
                    0.0,
                    float(total_time_in_bed) - float(total_minutes_asleep),
                )

        return metrics

    def _collect_device_status(self, token: str, patient: str) -> dict[str, float | str]:
        """Recupera informazioni tecniche sul wearable associato all'account.

        Presenza e livello batteria servono soprattutto per distinguere problemi
        tecnici da anomalie cliniche. Un watch scarico o non indossato non deve
        essere interpretato come comportamento anomalo del paziente.
        """
        payload = self._try_get_json(token, f"/1/user/{patient}/devices.json")
        if not isinstance(payload, list) or not payload:
            return {}

        tracker = payload[0]
        status: dict[str, float | str] = {"wearable_present": "true"}
        battery_level = tracker.get("batteryLevel")
        if battery_level is not None:
            status["wearable_battery_pct"] = float(battery_level)
        return status

    def _get_json(self, token: str, path: str, *, allow_refresh: bool = True) -> Any:
        """Esegue una richiesta GET alle API Fitbit e restituisce il JSON.

        Se Fitbit risponde 401, la funzione prova una sola volta a rinnovare il
        token e ripetere la chiamata. Questo rende il polling piu' robusto senza
        entrare in loop nel caso di credenziali errate.
        """
        url = f"{self.config.api_base_url}{path}"
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 401 and allow_refresh:
                refreshed = refresh_access_token(
                    self.config.token_file,
                    self.config.client_file,
                )
                refreshed_token = str(refreshed["access_token"])
                return self._get_json(
                    refreshed_token,
                    path,
                    allow_refresh=False,
                )
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Fitbit API HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Fitbit API network error: {exc}") from exc

    def _try_get_json(self, token: str, path: str) -> Any:
        """Esegue una richiesta opzionale alle API Fitbit.

        Alcune metriche non sono sempre disponibili. Questa helper intercetta gli
        errori runtime e restituisce `None`, cosi' il resto della finestra puo'
        essere comunque costruito.
        """
        try:
            return self._get_json(token, path)
        except RuntimeError:
            return None

    def _load_access_token(self) -> str:
        """Ottiene un access token valido dal modulo OAuth.

        Il token viene letto da `fitbit_token.json` e, se necessario, rinnovato
        usando `fitbit_client.json`. L'adapter rimane quindi concentrato sulla
        raccolta dati e non sulla gestione OAuth di basso livello.
        """
        return load_valid_access_token(
            self.config.token_file,
            self.config.client_file,
        )
