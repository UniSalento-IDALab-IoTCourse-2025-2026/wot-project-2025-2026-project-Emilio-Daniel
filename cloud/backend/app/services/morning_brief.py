from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Decision, FeatureWindow

PATIENT_TIMEZONE = ZoneInfo("Europe/Rome")
MORNING_END_HOUR = 8
NIGHT_DURATION_HOURS = 10
BASELINE_NIGHTS = 7
CONFIDENCE_HIGH_WINDOWS = 6
CONFIDENCE_MEDIUM_WINDOWS = 2

NON_BEDROOM_ROOMS = ("kitchen_minutes", "bathroom_minutes", "living_room_minutes")


def morning_night_bounds(reference: datetime) -> tuple[datetime, datetime]:
    """Ultima notte completamente conclusa: 22:00-08:00 in Europe/Rome.

    Se ora locale < 08:00 considera la notte precedente (quella appena finita
    ieri mattina), altrimenti la notte del giorno corrente. Restituisce
    datetime timezone-aware in UTC.
    """
    local = reference.astimezone(PATIENT_TIMEZONE)
    end_date: date = local.date() if local.hour >= MORNING_END_HOUR else local.date() - timedelta(days=1)
    end = datetime.combine(end_date, time(hour=MORNING_END_HOUR), tzinfo=PATIENT_TIMEZONE)
    start = end - timedelta(hours=NIGHT_DURATION_HOURS)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _sum(values: list[float]) -> float | None:
    return round(sum(values), 2) if values else None


def decisions_between(db: Session, patient_id: str, start: datetime, end: datetime) -> list[Decision]:
    return list(
        db.execute(
            select(Decision)
            .where(
                Decision.patient_id == patient_id,
                Decision.timestamp > start,
                Decision.timestamp <= end,
            )
            .order_by(Decision.timestamp, Decision.id)
        ).scalars()
    )


def windows_between(db: Session, patient_id: str, start: datetime, end: datetime) -> list[FeatureWindow]:
    return list(
        db.execute(
            select(FeatureWindow)
            .where(
                FeatureWindow.patient_id == patient_id,
                FeatureWindow.window_end > start,
                FeatureWindow.window_end <= end,
            )
            .order_by(FeatureWindow.window_end, FeatureWindow.id)
        ).scalars()
    )


def _feature_values(windows: list[FeatureWindow], key: str) -> list[float]:
    return [float(window.features[key]) for window in windows if _is_number(window.features.get(key))]


def night_metrics(
    db: Session,
    patient_id: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Aggrega i segnali della fascia notturna 22:00-08:00."""
    windows = windows_between(db, patient_id, start, end)
    decisions = decisions_between(db, patient_id, start, end)

    scores = [float(decision.anomaly_score) for decision in decisions if _is_number(decision.anomaly_score)]
    away_minutes = [
        float(minutes)
        for window in windows
        for room in NON_BEDROOM_ROOMS
        if _is_number(minutes := window.features.get(room))
    ]
    awake_values = _feature_values(windows, "awake_minutes")

    return {
        "window_count": len(windows),
        "decision_count": len(decisions),
        "sleep_minutes": _sum(_feature_values(windows, "sleep_minutes")),
        "awake_minutes": _sum(awake_values),
        "wakeups": sum(1 for value in awake_values if value > 0),
        "night_heart_rate_mean": _mean(_feature_values(windows, "heart_rate_mean")),
        "spo2_mean": _mean(_feature_values(windows, "spo2_mean")),
        "night_room_changes": _sum(_feature_values(windows, "night_room_changes")),
        "away_from_bedroom_minutes": _sum(away_minutes),
        "bedroom_minutes": _sum(_feature_values(windows, "bedroom_minutes")),
        "ai_score": _mean(scores),
        "max_score": round(max(scores), 2) if scores else None,
    }


def _baseline_nights(db: Session, patient_id: str, current_end: datetime) -> dict[str, Any]:
    """Media delle N notti precedenti (baseline personale)."""
    totals: dict[str, list[float]] = {
        "sleep_minutes": [],
        "awake_minutes": [],
        "wakeups": [],
        "night_heart_rate_mean": [],
        "spo2_mean": [],
        "night_room_changes": [],
        "away_from_bedroom_minutes": [],
        "ai_score": [],
        "max_score": [],
    }
    nights = 0
    for offset in range(1, BASELINE_NIGHTS + 1):
        anchor_end = current_end - timedelta(days=offset)
        metrics = night_metrics(db, patient_id, anchor_end - timedelta(hours=NIGHT_DURATION_HOURS), anchor_end)
        if metrics["window_count"] == 0 and metrics["decision_count"] == 0:
            continue
        nights += 1
        for key in totals:
            value = metrics[key]
            if value is not None:
                totals[key].append(float(value))
    if nights == 0:
        return {"available": False, "nights": 0}
    return {
        "available": True,
        "nights": nights,
        "sleep_minutes": _mean(totals["sleep_minutes"]),
        "awake_minutes": _mean(totals["awake_minutes"]),
        "wakeups": round(sum(totals["wakeups"]) / len(totals["wakeups"])) if totals["wakeups"] else None,
        "night_heart_rate_mean": _mean(totals["night_heart_rate_mean"]),
        "spo2_mean": _mean(totals["spo2_mean"]),
        "night_room_changes": _mean(totals["night_room_changes"]),
        "away_from_bedroom_minutes": _mean(totals["away_from_bedroom_minutes"]),
        "ai_score": _mean(totals["ai_score"]),
        "max_score": _mean(totals["max_score"]),
    }


def _confidence_code(metrics: dict[str, Any]) -> str:
    if metrics["window_count"] >= CONFIDENCE_HIGH_WINDOWS and (
        metrics["sleep_minutes"] is not None or metrics["night_heart_rate_mean"] is not None
    ):
        return "alta"
    if metrics["window_count"] >= CONFIDENCE_MEDIUM_WINDOWS:
        return "media"
    return "bassa"


def _build_summary(metrics: dict[str, Any], baseline: dict[str, Any]) -> str:
    """Frase prudente e non diagnostica del tipo richiesto da E27."""
    max_score = metrics["max_score"]
    if max_score is not None and max_score >= 70:
        opening = "Notte con segnali da verificare"
    elif max_score is not None and max_score >= 40:
        opening = "Notte con qualche variazione"
    else:
        opening = "Notte complessivamente stabile"

    room_changes = metrics["night_room_changes"]
    room_phrase = "senza movimenti notturni rilevati"
    if room_changes is not None and room_changes > 0:
        room_phrase = f"con {room_changes:.0f} movimenti notturni"

    sleep_qualifier = "sonno in linea con la media"
    if metrics["sleep_minutes"] is not None and baseline.get("sleep_minutes") is not None:
        delta = metrics["sleep_minutes"] - baseline["sleep_minutes"]
        if delta <= -30:
            sleep_qualifier = "sonno leggermente ridotto"
        elif delta >= 30:
            sleep_qualifier = "sonno leggermente aumentato"
    elif metrics["sleep_minutes"] is None:
        sleep_qualifier = "dati sonno non disponibili"

    return f"{opening}, {room_phrase} e {sleep_qualifier}."


def morning_brief_payload(
    db: Session,
    patient_id: str,
    *,
    reference: datetime | None = None,
) -> dict[str, Any]:
    """Compone il brief del mattino confrontato con la baseline personale (D29)."""
    reference = reference or datetime.now(timezone.utc)
    night_start, night_end = morning_night_bounds(reference)
    metrics = night_metrics(db, patient_id, night_start, night_end)
    baseline = _baseline_nights(db, patient_id, night_end)

    deltas = {
        "sleep_delta_minutes": (
            round(metrics["sleep_minutes"] - baseline["sleep_minutes"], 2)
            if metrics["sleep_minutes"] is not None and baseline.get("sleep_minutes") is not None
            else None
        ),
        "awake_delta_minutes": (
            round((metrics["awake_minutes"] or 0) - (baseline.get("awake_minutes") or 0), 2)
            if metrics["awake_minutes"] is not None or baseline.get("awake_minutes") is not None
            else None
        ),
        "heart_rate_delta": (
            round(metrics["night_heart_rate_mean"] - baseline["night_heart_rate_mean"], 2)
            if metrics["night_heart_rate_mean"] is not None and baseline.get("night_heart_rate_mean") is not None
            else None
        ),
        "room_changes_delta": (
            round((metrics["night_room_changes"] or 0) - (baseline.get("night_room_changes") or 0), 2)
            if metrics["night_room_changes"] is not None or baseline.get("night_room_changes") is not None
            else None
        ),
        "ai_score_delta": (
            round(metrics["ai_score"] - baseline["ai_score"], 2)
            if metrics["ai_score"] is not None and baseline.get("ai_score") is not None
            else None
        ),
    }

    summary = _build_summary(metrics, baseline)
    return {
        "patient_id": patient_id,
        "date": night_end.astimezone(PATIENT_TIMEZONE).strftime("%Y-%m-%d"),
        "night": {
            "start": night_start.isoformat(),
            "end": night_end.isoformat(),
        },
        "summary": summary,
        "sleep_minutes": metrics["sleep_minutes"],
        "awake_minutes": metrics["awake_minutes"],
        "wakeups": metrics["wakeups"],
        "night_heart_rate_mean": metrics["night_heart_rate_mean"],
        "spo2_mean": metrics["spo2_mean"],
        "night_room_changes": metrics["night_room_changes"],
        "away_from_bedroom_minutes": metrics["away_from_bedroom_minutes"],
        "ai_score": metrics["ai_score"],
        "max_score": metrics["max_score"],
        "confidence": _confidence_code(metrics),
        "counts": {
            "windows": metrics["window_count"],
            "decisions": metrics["decision_count"],
        },
        "baseline": {
            "available": baseline["available"],
            "nights": baseline["nights"],
            "sleep_minutes": baseline.get("sleep_minutes"),
            "awake_minutes": baseline.get("awake_minutes"),
            "night_heart_rate_mean": baseline.get("night_heart_rate_mean"),
            "night_room_changes": baseline.get("night_room_changes"),
            "ai_score": baseline.get("ai_score"),
            "max_score": baseline.get("max_score"),
        },
        "vs_baseline": deltas,
        "disclaimer": "Lettura notturna prudente: utile per orientare il controllo del mattino, non sostituisce valutazioni cliniche.",
    }
