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
    yellow_score: float = 60.0
    red_score: float = 85.0
    yellow_window_hours: float = 48.0
    yellow_min_records: int = 4
    wearable_battery_min_pct: float = 12.0


class AlertDebouncer:
    def __init__(self, config: Union[DebounceConfig, None] = None):
        self.config = config or DebounceConfig()
        self.history: list[dict[str, Any]] = []

    @classmethod
    def load(
        cls,
        path: Union[str, Path],
        config: Union[DebounceConfig, None] = None,
    ) -> "AlertDebouncer":
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
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump({"history": self.history}, handle, indent=2)

    def update(self, result: InferenceResult) -> TriageDecision:
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
            )

        yellow_records = [
            item for item in self.history
            if item.get("patient_id") == result.patient_id
            and float(item.get("anomaly_score", 0.0)) >= self.config.yellow_score
        ]
        if len(yellow_records) >= self.config.yellow_min_records:
            avg_score = sum(
                float(item.get("anomaly_score", 0.0))
                for item in yellow_records
            ) / len(yellow_records)
            return TriageDecision(
                patient_id=result.patient_id,
                window_start=result.window_start,
                window_end=result.window_end,
                level="yellow",
                should_publish=True,
                anomaly_score=result.anomaly_score,
                reasons=[
                    f"{len(yellow_records)} anomalous records in debounce window",
                    f"Average anomalous score {avg_score:.1f}",
                ],
                model_label=result.model_label,
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
        )

    def _append(self, result: InferenceResult) -> None:
        self.history.append(
            {
                "patient_id": result.patient_id,
                "window_end": result.window_end.isoformat(),
                "anomaly_score": result.anomaly_score,
                "model_label": result.model_label,
            }
        )

    def _prune(self, now: datetime) -> None:
        cutoff = now.astimezone(timezone.utc) - timedelta(hours=self.config.yellow_window_hours)
        kept = []
        for item in self.history:
            window_end = datetime.fromisoformat(str(item["window_end"]))
            if window_end.tzinfo is None:
                window_end = window_end.replace(tzinfo=timezone.utc)
            if window_end >= cutoff:
                kept.append(item)
        self.history = kept

    def _technical_reasons(self, result: InferenceResult) -> list[str]:
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
    payload = asdict(decision)
    payload["window_start"] = decision.window_start.isoformat()
    payload["window_end"] = decision.window_end.isoformat()
    return payload


def _parse_optional_float(value: object) -> Union[float, None]:
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
