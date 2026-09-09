from __future__ import annotations

from datetime import datetime, timedelta, timezone

from edge_ai.debounce import AlertDebouncer, DebounceConfig, decision_to_json
from edge_ai.schema import InferenceResult

BASE = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)


def inference(
    score: float,
    index: int,
    *,
    battery: float | None = None,
    worn: bool = True,
) -> InferenceResult:
    start = BASE + timedelta(minutes=4 * index)
    context = {
        "wearable_present": "true" if worn else "false",
        "wearable_battery_pct": battery if battery is not None else "",
    }
    return InferenceResult(
        patient_id="patient-001",
        window_start=start,
        window_end=start + timedelta(minutes=4),
        anomaly_score=score,
        model_decision_value=score,
        model_label="fusion",
        feature_values={},
        context=context,
    )


def test_red_score_publishes_immediately() -> None:
    debouncer = AlertDebouncer()
    decision = debouncer.update(inference(90.0, 0))
    assert decision.level == "red"
    assert decision.should_publish is True


def test_single_orange_score_is_not_published() -> None:
    debouncer = AlertDebouncer()
    decision = debouncer.update(inference(70.0, 0))
    assert decision.level == "orange"
    assert decision.should_publish is False


def test_repeated_orange_scores_are_published() -> None:
    debouncer = AlertDebouncer()
    for index in range(4):
        decision = debouncer.update(inference(70.0, index))
    assert decision.level == "orange"
    assert decision.should_publish is True
    assert "Average important anomalous score" in decision.reasons[1]


def test_yellow_score_is_visible_but_not_published() -> None:
    debouncer = AlertDebouncer()
    decision = debouncer.update(inference(45.0, 0))
    assert decision.level == "yellow"
    assert decision.should_publish is False


def test_low_score_is_green() -> None:
    debouncer = AlertDebouncer()
    decision = debouncer.update(inference(12.0, 0))
    assert decision.level == "green"
    assert decision.should_publish is False


def test_wearable_not_detected_is_technical() -> None:
    debouncer = AlertDebouncer()
    decision = debouncer.update(inference(90.0, 0, worn=False))
    assert decision.level == "technical"
    assert decision.should_publish is True
    assert "Wearable not detected" in decision.reasons[0]


def test_low_battery_is_technical() -> None:
    debouncer = AlertDebouncer()
    decision = debouncer.update(inference(95.0, 0, battery=5.0))
    assert decision.level == "technical"
    assert "below technical threshold" in decision.reasons[0]


def test_prune_removes_old_windows() -> None:
    debouncer = AlertDebouncer(config=DebounceConfig(orange_min_records=4))
    for index in range(4):
        debouncer.update(inference(70.0, index))
    assert len(debouncer.history) == 4
    debouncer._prune(BASE + timedelta(days=3))
    assert debouncer.history == []


def test_save_and_load_roundtrip(tmp_path) -> None:
    path = tmp_path / "debounce.json"
    debouncer = AlertDebouncer()
    debouncer.update(inference(70.0, 0))
    debouncer.save(path)
    loaded = AlertDebouncer.load(path)
    assert len(loaded.history) == 1
    assert float(loaded.history[0]["anomaly_score"]) == 70.0


def test_decision_to_json_serializes_dates() -> None:
    debouncer = AlertDebouncer()
    decision = debouncer.update(inference(90.0, 0))
    payload = decision_to_json(decision)
    assert payload["level"] == "red"
    assert isinstance(payload["window_start"], str)
    assert "T" in payload["window_start"]