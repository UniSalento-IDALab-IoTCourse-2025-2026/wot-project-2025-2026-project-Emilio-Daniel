from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Alert, Decision, FeatureWindow, Task, TaskResult, WeeklyReport

PATIENT_TIMEZONE = ZoneInfo("Europe/Rome")
LEVEL_BY_SEVERITY = {"yellow": "attention", "orange": "risk", "red": "alert"}
WEEK_DAYS = 7


def week_bounds(reference: datetime) -> tuple[datetime, datetime]:
    """Restituisce l'inizio (lunedi' 00:00 locale) e la fine della settimana.

    La settimana e' calcolata nel fuso Europe/Rome e convertita in orari
    timezone-aware per interrogare il database (archiviato in UTC).
    """
    local = reference.astimezone(PATIENT_TIMEZONE)
    local_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = local_start - timedelta(days=local.weekday())
    week_start = monday.astimezone(PATIENT_TIMEZONE)
    week_end = week_start + timedelta(weeks=1)
    return week_start, week_end


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def numeric_values(windows: list[FeatureWindow], key: str) -> list[float]:
    return [
        float(window.features[key])
        for window in windows
        if isinstance(window.features.get(key), (int, float))
        and not isinstance(window.features.get(key), bool)
    ]


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


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


def _count_days_by_level(decisions: list[Decision]) -> tuple[int, int, int]:
    """Conta i giorni distinti con attenzione/rischio/allerta.

    Per ogni giorno (UTC) considera il livello piu' severo rilevato e
    incrementa il contatore della relativa fascia. Livelli sconosciuti
    vengono ignorati.
    """
    day_levels: dict[str, str] = {}
    for decision in decisions:
        level = decision.level or "green"
        if level not in LEVEL_BY_SEVERITY:
            continue
        day = decision.timestamp.date().isoformat()
        if day not in day_levels or _severity_rank(level) > _severity_rank(day_levels[day]):
            day_levels[day] = level
    counts = {"attention": 0, "risk": 0, "alert": 0}
    for level in day_levels.values():
        counts[LEVEL_BY_SEVERITY[level]] += 1
    return counts["attention"], counts["risk"], counts["alert"]


def _severity_rank(level: str) -> int:
    return {"green": 0, "yellow": 1, "orange": 2, "red": 3}.get(level, 0)


def _daily_feature_totals(
    windows: list[FeatureWindow], key: str
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for window in windows:
        value = window.features.get(key)
        if not _is_number(value):
            continue
        day = window.window_end.astimezone(PATIENT_TIMEZONE).date().isoformat()
        totals[day] = totals.get(day, 0.0) + float(value)
    return totals


def _prevalent_room(windows: list[FeatureWindow]) -> str | None:
    room_keys = {
        "bedroom": "bedroom_minutes",
        "kitchen": "kitchen_minutes",
        "bathroom": "bathroom_minutes",
        "living_room": "living_room_minutes",
    }
    totals: dict[str, float] = {}
    for window in windows:
        for room, key in room_keys.items():
            value = window.features.get(key)
            if _is_number(value):
                totals[room] = totals.get(room, 0.0) + float(value)
    if not totals:
        return None
    room, minutes = max(totals.items(), key=lambda item: item[1])
    return room if minutes > 0 else None


def _weekly_metrics(
    db: Session, patient_id: str, start: datetime, end: datetime
) -> dict[str, Any]:
    """Calcola tutti gli aggregati settimanali per un intervallo dato."""
    decisions = decisions_between(db, patient_id, start, end)
    windows = windows_between(db, patient_id, start, end)

    scores = [float(decision.anomaly_score) for decision in decisions if _is_number(decision.anomaly_score)]
    attention_days, risk_days, alert_days = _count_days_by_level(decisions)

    sleep_totals = _daily_feature_totals(windows, "sleep_minutes")
    steps_totals = _daily_feature_totals(windows, "steps")
    night_totals = _daily_feature_totals(windows, "night_room_changes")

    return {
        "mean_score": _mean(scores),
        "max_score": round(max(scores), 3) if scores else None,
        "attention_days": attention_days,
        "risk_days": risk_days,
        "alert_days": alert_days,
        "decision_count": len(decisions),
        "window_count": len(windows),
        "alerts_created": _count_rows(db, Alert, Alert.opened_at, start, end),
        "alerts_resolved": _count_rows(db, Alert, Alert.closed_at, start, end),
        "tasks_sent": _count_rows(db, Task, Task.created_at, start, end),
        "tasks_completed": _count_rows(db, TaskResult, TaskResult.completed_at, start, end),
        "sleep_mean_minutes": _mean(list(sleep_totals.values())) if sleep_totals else None,
        "steps_mean": round(sum(steps_totals.values()) / len(steps_totals), 3) if steps_totals else None,
        "prevalent_room": _prevalent_room(windows),
        "night_room_changes": _mean(list(night_totals.values())) if night_totals else None,
        "_day_counts": {
            "sleep": len(sleep_totals),
            "steps": len(steps_totals),
            "night": len(night_totals),
        },
    }


def _count_rows(db: Session, model: type, column: Any, start: datetime, end: datetime) -> int:
    return len(
        db.execute(
            select(model.id).where(column > start, column <= end)
        ).scalars().all()
    )


def generate_weekly_report(
    db: Session,
    patient_id: str,
    *,
    reference: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Calcola e salva il report settimanale del paziente.

    Aggrega score AI, livelli giornalieri, alert, task, sonno, passi, stanza
    prevalente e cambi notturni, e confronta con la settimana precedente.
    Se il report per quella settimana esiste gia' e non viene forzato,
    restituisce quello persistito.
    """
    reference = reference or datetime.now(PATIENT_TIMEZONE)
    week_start, week_end = week_bounds(reference)

    existing = _fetch_report(db, patient_id, week_start)
    if existing is not None and not force:
        return _report_to_payload(existing)

    previous_start = week_start - timedelta(weeks=1)
    previous_end = week_end - timedelta(weeks=1)
    current = _weekly_metrics(db, patient_id, week_start, week_end)
    previous = _fetch_report(db, patient_id, previous_start)
    if previous is None:
        previous_metrics = _weekly_metrics(db, patient_id, previous_start, previous_end)
        previous_payload = _as_metrics_payload(previous_metrics)
    else:
        previous_payload = {
            "mean_score": previous.mean_score,
            "attention_days": previous.attention_days,
            "alerts_created": previous.alerts_created,
            "alerts_resolved": previous.alerts_resolved,
            "tasks_sent": previous.tasks_sent,
            "tasks_completed": previous.tasks_completed,
            "sleep_mean_minutes": previous.sleep_mean_minutes,
            "steps_mean": previous.steps_mean,
            "night_room_changes": previous.night_room_changes,
        }

    generated_at = datetime.now(PATIENT_TIMEZONE)
    summary = _build_summary(current, previous_payload)

    if existing is None:
        existing = WeeklyReport(patient_id=patient_id, week_start=week_start, week_end=week_end)
        db.add(existing)
    existing.generated_at = generated_at
    existing.mean_score = current["mean_score"]
    existing.max_score = current["max_score"]
    existing.attention_days = current["attention_days"]
    existing.risk_days = current["risk_days"]
    existing.alert_days = current["alert_days"]
    existing.alerts_created = current["alerts_created"]
    existing.alerts_resolved = current["alerts_resolved"]
    existing.tasks_sent = current["tasks_sent"]
    existing.tasks_completed = current["tasks_completed"]
    existing.sleep_mean_minutes = current["sleep_mean_minutes"]
    existing.steps_mean = current["steps_mean"]
    existing.prevalent_room = current["prevalent_room"]
    existing.night_room_changes = current["night_room_changes"]
    existing.vs_previous_mean_score = previous_payload.get("mean_score")
    existing.vs_previous_attention_days = previous_payload.get("attention_days")
    existing.summary = summary
    existing.payload = _full_payload(patient_id, week_start, week_end, generated_at, current, previous_payload, summary)
    db.flush()
    return _report_to_payload(existing)


def _fetch_report(db: Session, patient_id: str, week_start: datetime) -> WeeklyReport | None:
    return (
        db.execute(
            select(WeeklyReport).where(
                WeeklyReport.patient_id == patient_id,
                WeeklyReport.week_start == week_start,
            )
        )
        .scalars()
        .first()
    )


def _as_metrics_payload(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "mean_score": metrics["mean_score"],
        "attention_days": metrics["attention_days"],
        "alerts_created": metrics["alerts_created"],
        "alerts_resolved": metrics["alerts_resolved"],
        "tasks_sent": metrics["tasks_sent"],
        "tasks_completed": metrics["tasks_completed"],
        "sleep_mean_minutes": metrics["sleep_mean_minutes"],
        "steps_mean": metrics["steps_mean"],
        "night_room_changes": metrics["night_room_changes"],
    }


def _delta_label(current: float | None, previous: float | None) -> str | None:
    if current is None or previous is None:
        return None
    if previous == 0:
        return "invariato"
    delta = (current - previous) / abs(previous)
    if delta > 0.1:
        return "in aumento"
    if delta < -0.1:
        return "in diminuzione"
    return "stabile"


def _build_summary(current: dict[str, Any], previous: dict[str, Any]) -> str:
    """Sintesi prudente, non diagnostica, nella lingua della dashboard."""
    parts: list[str] = []
    score_trend = _delta_label(current["mean_score"], previous.get("mean_score"))
    if current["mean_score"] is None:
        parts.append("Score AI non sufficiente per una valutazione settimanale")
    else:
        base = f"Score AI medio {current['mean_score']:.0f}"
        if score_trend:
            base = f"{base} ({score_trend} rispetto alla settimana precedente)"
        parts.append(base)
    attention_label = {
        "attention_days": "giorni con attenzione",
        "risk_days": "giorni a rischio",
        "alert_days": "giorni in allerta",
    }
    level_days = [f"{current[key]} {label}" for key, label in attention_label.items() if current[key] > 0]
    if level_days:
        parts.append(", ".join(level_days))
    elif current["decision_count"]:
        parts.append("nessun giorno oltre il livello di attenzione")
    if current["alerts_created"] or current["alerts_resolved"]:
        parts.append(f"alert: {current['alerts_created']} creati, {current['alerts_resolved']} risolti")
    if current["sleep_mean_minutes"] is not None:
        parts.append(f"sonno medio {current['sleep_mean_minutes']:.0f} min/night")
    if current["prevalent_room"]:
        parts.append(f"stanza prevalente: {current['prevalent_room']}")
    if not parts:
        parts.append("Dati insufficienti per un riepilogo settimanale")
    return ". ".join(parts) + "."


def _full_payload(
    patient_id: str,
    week_start: datetime,
    week_end: datetime,
    generated_at: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
    summary: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "report_type": "weekly_clinical_operational_summary",
        "patient_id": patient_id,
        "range": {
            "start": week_start.isoformat(),
            "end": week_end.isoformat(),
            "days": WEEK_DAYS,
        },
        "generated_at": generated_at.isoformat(),
        "summary": summary,
        "mean_score": current["mean_score"],
        "max_score": current["max_score"],
        "attention_days": current["attention_days"],
        "risk_days": current["risk_days"],
        "alert_days": current["alert_days"],
        "alerts": {
            "created": current["alerts_created"],
            "resolved": current["alerts_resolved"],
        },
        "tasks": {
            "sent": current["tasks_sent"],
            "completed": current["tasks_completed"],
        },
        "sleep": {"mean_minutes": current["sleep_mean_minutes"]},
        "steps": {"mean": current["steps_mean"]},
        "prevalent_room": current["prevalent_room"],
        "night_room_changes": current["night_room_changes"],
        "previous_week": {
            "available": previous.get("mean_score") is not None,
            "mean_score": previous.get("mean_score"),
            "attention_days": previous.get("attention_days"),
        },
        "disclaimer": "Riepilogo di supporto: non sostituisce la valutazione clinica del medico.",
    }


def _report_to_payload(report: WeeklyReport) -> dict[str, Any]:
    title = f"Settimana dal {report.week_start.astimezone(PATIENT_TIMEZONE):%d/%m/%Y} al {report.week_end.astimezone(PATIENT_TIMEZONE):%d/%m/%Y}"
    return {
        "report_id": f"WeeklyReport:{report.id}",
        "patient_id": report.patient_id,
        "title": title,
        "week_start": report.week_start.isoformat(),
        "week_end": report.week_end.isoformat(),
        "generated_at": report.generated_at.isoformat(),
        "summary": report.summary,
        "mean_score": report.mean_score,
        "max_score": report.max_score,
        "attention_days": report.attention_days,
        "risk_days": report.risk_days,
        "alert_days": report.alert_days,
        "alerts": {
            "created": report.alerts_created,
            "resolved": report.alerts_resolved,
        },
        "tasks": {
            "sent": report.tasks_sent,
            "completed": report.tasks_completed,
        },
        "sleep": {"mean_minutes": report.sleep_mean_minutes},
        "steps": {"mean": report.steps_mean},
        "prevalent_room": report.prevalent_room,
        "night_room_changes": report.night_room_changes,
        "vs_previous_mean_score": report.vs_previous_mean_score,
        "vs_previous_attention_days": report.vs_previous_attention_days,
        "range": {
            "start": report.week_start.isoformat(),
            "end": report.week_end.isoformat(),
            "days": WEEK_DAYS,
        },
        "disclaimer": "Riepilogo di supporto: non sostituisce la valutazione clinica del medico.",
    }


def weekly_reports_payload(db: Session, patient_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Restituisce i report settimanali persistiti, dal piu' recente."""
    rows = (
        db.execute(
            select(WeeklyReport)
            .where(WeeklyReport.patient_id == patient_id)
            .order_by(WeeklyReport.week_start.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_report_to_payload(row) for row in rows]
