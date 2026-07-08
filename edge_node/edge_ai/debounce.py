from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from numbers import Number
from pathlib import Path
from typing import Any, Union

from edge_ai.schema import InferenceResult, TriageDecision


@dataclass
class DebounceConfig:
    yellow_score: float = 35.0
    orange_score: float = 65.0
    red_score: float = 80.0
    debounce_window_hours: float = 48.0
    orange_min_records: int = 4
    wearable_battery_min_pct: float = 12.0


class AlertDebouncer:
    def __init__(self, config: Union[DebounceConfig, None] = None):
        """Inizializza lo stato del debounce degli allarmi.

        Il debounce serve a ridurre il rischio di `alarm fatigue`: il sistema
        mantiene memoria delle finestre recenti e decide se una sequenza di
        anomalie e' davvero rilevante. La configurazione consente di modificare
        soglie e durata della finestra temporale senza cambiare la logica.
        """
        self.config = config or DebounceConfig()
        self.history: list[dict[str, Any]] = []

    @classmethod
    def load(
        cls,
        path: Union[str, Path],
        config: Union[DebounceConfig, None] = None,
    ) -> "AlertDebouncer":
        """Carica da disco la storia recente usata per il debounce.

        Se il file non esiste viene creato un oggetto vuoto, scelta utile sul
        primo avvio del Raspberry. Se invece il file e' presente, la lista
        `history` permette di continuare il ragionamento tra un ciclo edge e il
        successivo.
        """
        debouncer = cls(config=config)
        source = Path(path)
        if source.exists():
            with source.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            history = payload.get("history", [])
            if isinstance(history, list):
                debouncer.history = history
        return debouncer

    def save(self, path: Union[str, Path]) -> None:
        """Salva su disco la storia del debounce.

        La persistenza e' necessaria perche' il ciclo edge puo' essere eseguito
        ogni 4 minuti da cron/systemd: senza salvataggio ogni esecuzione
        perderebbe memoria delle anomalie precedenti.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump({"history": self.history}, handle, indent=2)

    def update(self, result: InferenceResult) -> TriageDecision:
        """Trasforma il risultato del modello in una decisione di triage.

        La funzione distingue problemi tecnici, attenzione lieve, anomalia
        importante confermata e anomalia severa immediata. In questo modo il
        modello non produce una diagnosi, ma un livello operativo utile al
        personale sanitario.
        """
        self._append(result)
        self._prune(result.window_end)

        technical_reasons = self._technical_reasons(result)
        if technical_reasons:
            return TriageDecision(
                patient_id=result.patient_id,
                window_start=result.window_start,
                window_end=result.window_end,
                level="technical",
                should_publish=True,
                anomaly_score=result.anomaly_score,
                reasons=technical_reasons,
                model_label=result.model_label,
                evidence=self._decision_evidence(result),
            )

        if result.anomaly_score >= self.config.red_score:
            return TriageDecision(
                patient_id=result.patient_id,
                window_start=result.window_start,
                window_end=result.window_end,
                level="red",
                should_publish=True,
                anomaly_score=result.anomaly_score,
                reasons=["Current anomaly score exceeds severe threshold"],
                model_label=result.model_label,
                evidence=self._decision_evidence(result),
            )

        if result.anomaly_score >= self.config.orange_score:
            orange_records = [
                item for item in self.history
                if item.get("patient_id") == result.patient_id
                and float(item.get("anomaly_score", 0.0)) >= self.config.orange_score
            ]
            if len(orange_records) >= self.config.orange_min_records:
                avg_score = sum(
                    float(item.get("anomaly_score", 0.0))
                    for item in orange_records
                ) / len(orange_records)
                return TriageDecision(
                    patient_id=result.patient_id,
                    window_start=result.window_start,
                    window_end=result.window_end,
                    level="orange",
                    should_publish=True,
                    anomaly_score=result.anomaly_score,
                    reasons=[
                        f"{len(orange_records)} important anomalous records in debounce window",
                        f"Average important anomalous score {avg_score:.1f}",
                    ],
                    model_label=result.model_label,
                    evidence=self._decision_evidence(result),
                )
            return TriageDecision(
                patient_id=result.patient_id,
                window_start=result.window_start,
                window_end=result.window_end,
                level="orange",
                should_publish=False,
                anomaly_score=result.anomaly_score,
                reasons=[
                    "Current anomaly score exceeds important threshold",
                    "Waiting for repeated windows or model confirmation before publishing",
                ],
                model_label=result.model_label,
                evidence=self._decision_evidence(result),
            )

        if result.anomaly_score >= self.config.yellow_score:
            return TriageDecision(
                patient_id=result.patient_id,
                window_start=result.window_start,
                window_end=result.window_end,
                level="yellow",
                should_publish=False,
                anomaly_score=result.anomaly_score,
                reasons=[
                    "Current anomaly score exceeds attention threshold",
                    "Attention level is visible in dashboard but not published as an alert",
                ],
                model_label=result.model_label,
                evidence=self._decision_evidence(result),
            )

        return TriageDecision(
            patient_id=result.patient_id,
            window_start=result.window_start,
            window_end=result.window_end,
            level="green",
            should_publish=False,
            anomaly_score=result.anomaly_score,
            reasons=["Routine inside learned baseline"],
            model_label=result.model_label,
            evidence=self._decision_evidence(result),
        )

    def _append(self, result: InferenceResult) -> None:
        """Aggiunge alla memoria interna la finestra appena valutata.

        Vengono salvati solo i dati necessari al debounce: paziente, fine
        finestra, score e label del modello. Si evita cosi' di duplicare dati
        sanitari completi nello stato tecnico.
        """
        self.history.append(
            {
                "patient_id": result.patient_id,
                "window_end": result.window_end.isoformat(),
                "anomaly_score": result.anomaly_score,
                "model_label": result.model_label,
                "fusion_mode": result.context.get("fusion", {}).get("mode"),
            }
        )

    def _decision_evidence(self, result: InferenceResult) -> dict[str, Any]:
        """Estrae dal risultato AI le prove sintetiche da salvare nel JSON.

        Quando il runtime usa modello generico e modello personale, la decisione
        finale non deve essere una scatola nera. Questa funzione copia nel
        triage solo il riepilogo della fusione, lasciando fuori le feature
        complete per non appesantire lo stato clinico-operativo.
        """
        fusion = result.context.get("fusion")
        if isinstance(fusion, dict):
            return {"fusion": fusion}
        return {}

    def _prune(self, now: datetime) -> None:
        """Elimina dalla memoria le finestre ormai fuori dalla finestra debounce.

        Il sistema deve ricordare solo un intervallo recente, ad esempio 48 ore.
        Questo limita la crescita del file di stato e rende la decisione
        dipendente dal comportamento attuale del paziente.
        """
        cutoff = now.astimezone(timezone.utc) - timedelta(hours=self.config.debounce_window_hours)
        kept = []
        for item in self.history:
            window_end = datetime.fromisoformat(str(item["window_end"]))
            if window_end.tzinfo is None:
                window_end = window_end.replace(tzinfo=timezone.utc)
            if window_end >= cutoff:
                kept.append(item)
        self.history = kept

    def _technical_reasons(self, result: InferenceResult) -> list[str]:
        """Rileva problemi tecnici da separare dagli allarmi clinici.

        Un wearable non indossato o con batteria scarica non deve essere
        interpretato come peggioramento del paziente. Per questo motivo tali
        condizioni generano motivazioni tecniche dedicate.
        """
        reasons = []
        present = result.context.get("wearable_present")
        if str(present).strip().lower() in {"false", "0", "no"}:
            reasons.append("Wearable not detected or not worn")

        battery_raw = result.context.get("wearable_battery_pct")
        battery_pct = _parse_optional_float(battery_raw)
        if battery_pct is not None:
            if battery_pct < self.config.wearable_battery_min_pct:
                reasons.append("Wearable battery below technical threshold")
        elif battery_raw is not None:
            if not isinstance(battery_raw, str) or battery_raw.strip():
                reasons.append("Wearable battery value is invalid")
        return reasons


def decision_to_json(decision: TriageDecision) -> dict[str, Any]:
    """Converte una decisione di triage in dizionario serializzabile JSON.

    Le date vengono trasformate in stringhe ISO per poter salvare il risultato
    su file o inviarlo in futuro a backend/dashboard senza perdere il riferimento
    temporale della finestra analizzata.
    """
    payload = asdict(decision)
    payload["window_start"] = decision.window_start.isoformat()
    payload["window_end"] = decision.window_end.isoformat()
    return payload


def _parse_optional_float(value: object) -> Union[float, None]:
    """Converte un valore opzionale in float quando possibile.

    Questa funzione evita errori quando i dati arrivano vuoti, mancanti o in
    formato stringa. E' usata soprattutto per la batteria del wearable, dato che
    il dato puo' non essere disponibile in tutte le risposte API.
    """
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    if isinstance(value, Number):
        return float(value)
    return None
