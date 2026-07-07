from __future__ import annotations

import json
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from edge_auth.google_health_oauth import load_valid_access_token, refresh_access_token
from edge_ingest.config import GoogleHealthConfig


class GoogleHealthAdapter:
    """Raccoglie feature wearable da Google Health API.

    L'adapter traduce le risposte Google Health nello schema del progetto
    (`heart_rate_mean`, `steps`, `sleep_minutes`, ecc.). Non parla direttamente
    con il Watch via Bluetooth: legge i dati gia' sincronizzati nel cloud Google.
    """

    def __init__(self, config: GoogleHealthConfig):
        """Memorizza percorsi token/client e base URL della API."""
        self.config = config

    def collect_window(self, window_start: datetime, window_end: datetime) -> dict[str, float | str]:
        """Costruisce le feature wearable disponibili per una finestra.

        Il runtime passa finestre da 4 minuti. Per quella finestra leggiamo dati
        intraday come frequenza cardiaca e passi; poi aggiungiamo anche metriche
        giornaliere/notturne, quando disponibili, per completare il vettore AI.
        """
        token = self._load_access_token()
        start = _format_utc(window_start)
        end = _format_utc(window_end)

        features: dict[str, float | str] = {"wearable_present": "true"}
        features.update(self._collect_paired_device_status(token))
        features.update(self._collect_intraday_metrics(token, start, end))
        features.update(self._collect_daily_metrics(token))
        return features

    def _collect_intraday_metrics(
        self,
        token: str,
        start_time: str,
        end_time: str,
    ) -> dict[str, float]:
        """Legge metriche legate alla finestra temporale corrente.

        `rollUp` aggrega i punti Google Health dentro finestre piu' piccole
        (qui 60 secondi), che poi riassumiamo nella riga finale del progetto.
        Se una metrica non esiste nella finestra, viene semplicemente omessa.
        """
        metrics: dict[str, float] = {}

        heart_payload = self._try_rollup(token, "heart-rate", start_time, end_time)
        heart_values = _numbers_by_key(
            heart_payload,
            ("beatsPerMinuteAvg", "beatsPerMinute"),
        )
        if heart_values:
            metrics["heart_rate_mean"] = mean(heart_values)
            metrics["heart_rate_std"] = pstdev(heart_values) if len(heart_values) > 1 else 0.0

        steps_payload = self._try_rollup(token, "steps", start_time, end_time)
        step_values = _numbers_by_key(steps_payload, ("countSum", "count"))
        if step_values:
            metrics["steps"] = sum(step_values)
        elif "heart_rate_mean" in metrics:
            # Google Health spesso omette del tutto i data point `steps` quando
            # non ci sono passi nella finestra. Con battito presente sappiamo
            # pero' che il wearable era attivo, quindi l'assenza di passi e'
            # informativa: per il modello e' meglio `0` di `nan`.
            metrics["steps"] = 0.0

        hrv_payload = self._try_rollup(
            token,
            "heart-rate-variability",
            start_time,
            end_time,
        )
        hrv_values = _numbers_by_key(
            hrv_payload,
            (
                "rootMeanSquareOfSuccessiveDifferencesMilliseconds",
                "standardDeviationMilliseconds",
                "rootMeanSquareOfSuccessiveDifferencesMillisecondsAvg",
                "standardDeviationMillisecondsAvg",
            ),
        )
        if hrv_values:
            metrics["hrv_rmssd"] = mean(hrv_values)

        spo2_payload = self._try_rollup(token, "oxygen-saturation", start_time, end_time)
        spo2_values = _numbers_by_key(
            spo2_payload,
            ("percentageAvg", "percentage", "averagePercentage"),
        )
        if spo2_values:
            metrics["spo2_mean"] = mean(spo2_values)

        sedentary_payload = self._try_list_data_points(
            token,
            "sedentary-period",
            start_time=start_time,
            end_time=end_time,
            page_size=100,
        )
        sedentary_minutes = _sum_interval_minutes(sedentary_payload)
        if sedentary_minutes is not None:
            metrics["sedentary_minutes"] = sedentary_minutes
        elif metrics.get("steps") == 0.0 and "heart_rate_mean" in metrics:
            # Stima conservativa: se nella finestra ci sono battiti ma zero
            # passi, consideriamo sedentari i 4 minuti osservati. Questo rende
            # il dataset reale piu' simile al generico PAMAP2 usato nel modello.
            metrics["sedentary_minutes"] = _window_minutes(start_time, end_time)

        return metrics

    def _collect_daily_metrics(self, token: str) -> dict[str, float]:
        """Legge metriche giornaliere o notturne utili al modello.

        Resting heart rate, HRV giornaliera, SpO2 notturna e sleep summary non
        sono necessariamente legati agli ultimi 4 minuti. Li trattiamo come
        contesto wearable giornaliero, se Google Health li espone.
        """
        metrics: dict[str, float] = {}

        resting_payload = self._try_list_data_points(
            token,
            "daily-resting-heart-rate",
            page_size=10,
        )
        resting_values = _numbers_by_key(resting_payload, ("beatsPerMinute",))
        if resting_values:
            metrics["resting_heart_rate"] = resting_values[0]

        daily_hrv_payload = self._try_list_data_points(
            token,
            "daily-heart-rate-variability",
            page_size=10,
        )
        daily_hrv_values = _numbers_by_key(
            daily_hrv_payload,
            (
                "averageHeartRateVariabilityMilliseconds",
                "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds",
            ),
        )
        if daily_hrv_values and "hrv_rmssd" not in metrics:
            metrics["hrv_rmssd"] = daily_hrv_values[0]

        daily_spo2_payload = self._try_list_data_points(
            token,
            "daily-oxygen-saturation",
            page_size=10,
        )
        daily_spo2_values = _numbers_by_key(
            daily_spo2_payload,
            ("averagePercentage", "percentage"),
        )
        if daily_spo2_values and "spo2_mean" not in metrics:
            metrics["spo2_mean"] = daily_spo2_values[0]

        sleep_payload = self._try_list_data_points(token, "sleep", page_size=10)
        sleep_minutes = _numbers_by_key(sleep_payload, ("minutesAsleep",))
        awake_minutes = _numbers_by_key(sleep_payload, ("minutesAwake",))
        if sleep_minutes:
            metrics["sleep_minutes"] = sleep_minutes[0]
        if awake_minutes:
            metrics["awake_minutes"] = awake_minutes[0]

        return metrics

    def _collect_paired_device_status(self, token: str) -> dict[str, float | str]:
        """Recupera presenza e batteria dal device associato all'account.

        Google Health espone i paired devices dell'utente. Usiamo questi dati
        per distinguere un problema tecnico, per esempio watch scarico/non
        sincronizzato, da una vera anomalia comportamentale.
        """
        payload = self._try_get_json(token, "/v4/users/me/pairedDevices")
        devices = []
        if isinstance(payload, dict):
            raw_devices = payload.get("pairedDevices") or payload.get("devices") or []
            if isinstance(raw_devices, list):
                devices = [item for item in raw_devices if isinstance(item, dict)]
        if not devices:
            return {}

        tracker = _select_tracker_device(devices)
        status: dict[str, float | str] = {"wearable_present": "true"}
        battery_level = tracker.get("batteryLevel") or tracker.get("battery_level")
        if battery_level is not None:
            status["wearable_battery_pct"] = float(battery_level)
        return status

    def _try_rollup(
        self,
        token: str,
        data_type: str,
        start_time: str,
        end_time: str,
    ) -> Any:
        """Chiama `dataPoints:rollUp` e restituisce `None` se la metrica manca.

        Alcuni data type possono non essere disponibili per l'account o per gli
        scope concessi. L'adapter resta tollerante: una feature mancante non
        deve impedire di salvare le altre feature della finestra.
        """
        try:
            return self._post_json(
                token,
                f"/v4/users/me/dataTypes/{data_type}/dataPoints:rollUp",
                {
                    "range": {
                        "startTime": start_time,
                        "endTime": end_time,
                    },
                    "windowSize": "60s",
                },
            )
        except RuntimeError:
            return None

    def _try_list_data_points(
        self,
        token: str,
        data_type: str,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        page_size: int = 10,
    ) -> Any:
        """Legge data point raw/daily tramite endpoint `dataPoints`.

        Quando sono presenti `start_time` ed `end_time`, aggiunge un filtro
        temporale. Per metriche giornaliere usa invece gli ultimi punti
        disponibili, perche' Google Health le modella come riepiloghi di giornata.
        """
        query: dict[str, str | int] = {"page_size": page_size}
        if start_time and end_time:
            snake_type = data_type.replace("-", "_")
            query["filter"] = (
                f'data_type.{snake_type}.interval.start_time >= "{start_time}" '
                f'AND data_type.{snake_type}.interval.end_time <= "{end_time}"'
            )
        path = f"/v4/users/me/dataTypes/{data_type}/dataPoints?{urlencode(query)}"
        return self._try_get_json(token, path)

    def _try_get_json(self, token: str, path: str) -> Any:
        """Versione tollerante di GET: errori API diventano `None`."""
        try:
            return self._get_json(token, path)
        except RuntimeError:
            return None

    def _get_json(
        self,
        token: str,
        path: str,
        *,
        allow_refresh: bool = True,
    ) -> Any:
        """Esegue una GET autenticata verso Google Health API.

        Se l'access token e' scaduto e Google risponde 401, prova una sola volta
        il refresh automatico e ripete la chiamata.
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
                return self._get_json(
                    str(refreshed["access_token"]),
                    path,
                    allow_refresh=False,
                )
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Google Health API HTTP {exc.code}: {body_text}") from exc
        except URLError as exc:
            raise RuntimeError(f"Google Health API network error: {exc}") from exc

    def _post_json(
        self,
        token: str,
        path: str,
        body: dict[str, Any],
        *,
        allow_refresh: bool = True,
    ) -> Any:
        """Esegue una POST autenticata verso Google Health API.

        Serve soprattutto per `dataPoints:rollUp`, che richiede il range
        temporale nel body JSON. Anche qui il 401 attiva un refresh automatico.
        """
        url = f"{self.config.api_base_url}{path}"
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
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
                return self._post_json(
                    str(refreshed["access_token"]),
                    path,
                    body,
                    allow_refresh=False,
                )
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Google Health API HTTP {exc.code}: {body_text}") from exc
        except URLError as exc:
            raise RuntimeError(f"Google Health API network error: {exc}") from exc

    def _load_access_token(self) -> str:
        """Carica o rinnova l'access token usando il modulo OAuth Google."""
        return load_valid_access_token(
            self.config.token_file,
            self.config.client_file,
        )


def _numbers_by_key(payload: Any, keys: tuple[str, ...]) -> list[float]:
    """Estrae numeri da una risposta Google cercando piu' nomi campo possibili."""
    values: list[float] = []
    _collect_numbers_by_key(payload, set(keys), values)
    return values


def _collect_numbers_by_key(payload: Any, keys: set[str], values: list[float]) -> None:
    """Visita ricorsivamente JSON dict/list e accumula i valori numerici trovati."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys:
                number = _to_float(value)
                if number is not None:
                    values.append(number)
            _collect_numbers_by_key(value, keys, values)
    elif isinstance(payload, list):
        for item in payload:
            _collect_numbers_by_key(item, keys, values)


def _sum_interval_minutes(payload: Any) -> float | None:
    """Somma la durata in minuti dei data point con un intervallo temporale."""
    data_points = _data_points(payload)
    total = 0.0
    found = False
    for point in data_points:
        interval = _find_first_interval(point)
        if not interval:
            continue
        start = _parse_time(interval.get("startTime"))
        end = _parse_time(interval.get("endTime"))
        if not start or not end:
            continue
        total += max(0.0, (end - start).total_seconds() / 60.0)
        found = True
    return total if found else None


def _data_points(payload: Any) -> list[dict[str, Any]]:
    """Normalizza possibili nomi lista data point in una lista di dizionari."""
    if not isinstance(payload, dict):
        return []
    points = payload.get("dataPoints") or payload.get("reconciledDataPoints") or []
    if not isinstance(points, list):
        return []
    return [point for point in points if isinstance(point, dict)]


def _find_first_interval(payload: Any) -> dict[str, Any] | None:
    """Trova il primo oggetto `interval` dentro una risposta annidata."""
    if isinstance(payload, dict):
        interval = payload.get("interval")
        if isinstance(interval, dict):
            return interval
        for value in payload.values():
            found = _find_first_interval(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_first_interval(item)
            if found:
                return found
    return None


def _select_tracker_device(devices: list[dict[str, Any]]) -> dict[str, Any]:
    """Preferisce un device TRACKER; altrimenti usa il primo device disponibile."""
    trackers = [
        device
        for device in devices
        if str(device.get("deviceType") or device.get("device_type") or "").upper()
        == "TRACKER"
    ]
    return trackers[0] if trackers else devices[0]


def _to_float(value: Any) -> float | None:
    """Converte valori numerici Google, anche stringhe, in float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> datetime | None:
    """Converte timestamp RFC3339 Google in `datetime` UTC."""
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _window_minutes(start_time: str, end_time: str) -> float:
    """Calcola la durata in minuti tra due timestamp Google/RFC3339."""
    start = _parse_time(start_time)
    end = _parse_time(end_time)
    if not start or not end:
        return 0.0
    return max(0.0, (end - start).total_seconds() / 60.0)


def _format_utc(value: datetime) -> str:
    """Converte una data qualunque in ISO UTC con suffisso `Z` per Google API."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
