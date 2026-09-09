from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from edge_ai.absence import (
    AbsenceConfig,
    AbsenceDebouncer,
    absence_message_id,
    build_absence_indicators,
    evaluate_absence,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def _ble_csv(tmp_path, samples):
    path = tmp_path / "ble_samples.csv"
    path.write_text(
        "timestamp,room\n"
        + "".join(f"{ts.isoformat()},{room}\n" for ts, room in samples),
        encoding="utf-8",
    )
    return path


def _baseline_frame(longest_values):
    return pd.DataFrame(
        {
            "window_start": [
                (NOW - timedelta(minutes=5 * (index + 1))).isoformat()
                for index in _range(len(longest_values))
            ],
            "longest_single_room_minutes": list(longest_values),
        }
    )


def _range(length):
    return list(range(length))


def _samples_boom(samples, now=NOW):
    ts, room = samples[-1]
    return ts, room


def test_no_movement_triggers_alert_when_no_room_change_for_more_than_4h(tmp_path):
    start = NOW - timedelta(hours=6)
    samples = [(start + timedelta(minutes=m), "living_room") for m in range(0, 360, 30)]
    samples.append((NOW - timedelta(minutes=2), "living_room"))
    path = _ble_csv(tmp_path, samples)
    indicators = build_absence_indicators(path, NOW)
    signal = evaluate_absence(indicators)
    assert signal is not None
    assert signal.kind == "no_movement"
    assert signal.level == "orange"
    assert signal.duration_minutes >= 4 * 60
    assert signal.last_room == "living_room"


def test_no_movement_not_triggered_when_room_changed_recently(tmp_path):
    start = NOW - timedelta(hours=2)
    path = _ble_csv(
        tmp_path,
        [
            (start, "bedroom"),
            (NOW - timedelta(minutes=30), "living_room"),
            (NOW - timedelta(minutes=15), "kitchen"),
        ],
    )
    indicators = build_absence_indicators(path, NOW)
    assert evaluate_absence(indicators) is None


def test_no_kitchen_access_for_more_than_12h_triggers_alert(tmp_path):
    bathroom_now = NOW - timedelta(minutes=10)
    path = _ble_csv(
        tmp_path,
        [
            (NOW - timedelta(hours=13), "kitchen"),
            (bathroom_now, "bathroom"),
        ],
    )
    indicators = build_absence_indicators(path, NOW)
    signal = evaluate_absence(indicators)
    assert signal is not None
    assert signal.kind == "no_amenity_access"
    assert "cucina" in signal.reason
    assert signal.duration_minutes >= 12 * 60


def test_no_bathroom_access_has_priority_over_kitchen(tmp_path):
    kitchen_now = NOW - timedelta(minutes=5)
    path = _ble_csv(
        tmp_path,
        [
            (NOW - timedelta(hours=13), "bathroom"),
            (kitchen_now, "kitchen"),
            (NOW - timedelta(minutes=2), "living_room"),
        ],
    )
    indicators = build_absence_indicators(path, NOW)
    signal = evaluate_absence(indicators)
    assert signal is not None
    assert signal.kind == "no_amenity_access"
    assert "bagno" in signal.reason


def test_long_room_stay_triggers_when_over_multiplied_baseline(tmp_path):
    baseline = _baseline_frame([20.0, 25.0, 30.0])
    start = NOW - timedelta(hours=3)
    samples = [(start + timedelta(minutes=m), "bedroom") for m in range(0, 180, 30)]
    samples.append((NOW - timedelta(minutes=2), "bedroom"))
    path = _ble_csv(tmp_path, samples)
    indicators = build_absence_indicators(path, NOW, baseline_frame=baseline)
    signal = evaluate_absence(indicators)
    assert signal is not None
    assert signal.kind == "long_room_stay"
    assert signal.level == "yellow"
    assert indicators.baseline_longest_stay_minutes == 25.0


def test_long_room_stay_not_triggered_within_baseline(tmp_path):
    baseline = _baseline_frame([60.0, 90.0, 120.0])
    start = NOW - timedelta(hours=1)
    samples = [(start + timedelta(minutes=m), "living_room") for m in range(0, 60, 5)]
    samples.append((NOW - timedelta(minutes=2), "living_room"))
    path = _ble_csv(tmp_path, samples)
    indicators = build_absence_indicators(path, NOW, baseline_frame=baseline)
    assert evaluate_absence(indicators) is None


def test_ble_absent_generates_technical_fault(tmp_path):
    missing = tmp_path / "missing.csv"
    indicators = build_absence_indicators(missing, NOW)
    assert indicators.ble_available is False
    signal = evaluate_absence(indicators)
    assert signal is not None
    assert signal.kind == "ble_unreliable"
    assert signal.category == "technical"
    assert signal.level == "technical"


def test_ble_stale_generates_technical_fault_not_absence(tmp_path):
    start = NOW - timedelta(hours=5)
    path = _ble_csv(tmp_path, [(start, "bedroom")])
    indicators = build_absence_indicators(path, NOW, ble_stale_minutes=30.0)
    assert indicators.ble_stale is True
    signal = evaluate_absence(indicators)
    assert signal is not None
    assert signal.kind == "ble_unreliable"


def test_indicator_uses_last_room_and_transition(tmp_path):
    start = NOW - timedelta(minutes=90)
    path = _ble_csv(
        tmp_path,
        [
            (start, "bedroom"),
            (NOW - timedelta(minutes=30), "kitchen"),
            (NOW - timedelta(minutes=10), "living_room"),
        ],
    )
    indicators = build_absence_indicators(path, NOW)
    assert indicators.current_room == "living_room"
    assert indicators.minutes_since_last_room_change == 10.0


def test_dedup_same_episode_in_cooldown():
    config = AbsenceConfig()
    debouncer = AbsenceDebouncer(config)
    signal = _no_movement_signal("living_room")
    assert debouncer.update(signal, NOW) is not None
    assert debouncer.update(signal, NOW + timedelta(minutes=5)) is None
    assert debouncer.episode == 1


def test_new_episode_after_cooldown_and_reset():
    config = AbsenceConfig(resend_cooldown_hours={"no_movement": 1.0})
    debouncer = AbsenceDebouncer(config)
    signal = _no_movement_signal("living_room")
    assert debouncer.update(signal, NOW) is not None
    assert debouncer.update(signal, NOW + timedelta(hours=2)) is not None
    assert debouncer.episode == 2
    assert debouncer.update(None, NOW + timedelta(hours=3)) is None
    assert debouncer.last_signature is None
    assert debouncer.update(signal, NOW + timedelta(hours=4)) is not None


def test_debouncer_save_and_load_roundtrip(tmp_path):
    config = AbsenceConfig()
    debouncer = AbsenceDebouncer(config)
    signal = _no_movement_signal("bedroom")
    debouncer.update(signal, NOW)
    state = tmp_path / "absence-debounce.json"
    debouncer.save(state)
    loaded = AbsenceDebouncer.load(state, config)
    assert loaded.episode == 1
    assert loaded.last_signature == signal.signature()


def test_message_id_stable_for_episode():
    signal = _no_movement_signal("living_room")
    first = absence_message_id("patient-001", signal, 1)
    again = absence_message_id("patient-001", signal, 1)
    escalated = absence_message_id("patient-001", signal, 2)
    assert first == again
    assert first != escalated
    assert first.startswith("absence-")


def _no_movement_signal(room_value="living_room"):
    from edge_ai.absence import AbsenceSignal

    return AbsenceSignal(
        kind="no_movement",
        level="orange",
        category="no_movement",
        title="Assenza di movimento da verificare",
        description="Nessun cambio stanza da oltre 4 ore.",
        reason="Nessun movimento per oltre 4 ore.",
        duration_minutes=300.0,
        last_room=room_value,
        last_transition_at=NOW - timedelta(hours=5),
        ble_quality="ok",
    )