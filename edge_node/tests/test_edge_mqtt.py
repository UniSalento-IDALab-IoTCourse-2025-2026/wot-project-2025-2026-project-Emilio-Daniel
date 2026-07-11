from __future__ import annotations

import json

from edge_mqtt.messages import build_cycle_messages
from edge_mqtt.queue import DiskMqttQueue


def test_build_cycle_messages_converts_latest_window_nan_to_null(tmp_path) -> None:
    latest = tmp_path / "latest_window.csv"
    latest.write_text(
        "patient_id,window_start,window_end,heart_rate_mean,spo2_mean,wearable_present\n"
        "patient-001,2026-07-11T10:00:00+00:00,2026-07-11T10:04:00+00:00,nan,96.5,true\n",
        encoding="utf-8",
    )
    decision = tmp_path / "patient-001-decision.json"
    decision.write_text(
        json.dumps(
            {
                "patient_id": "patient-001",
                "window_start": "2026-07-11T10:00:00+00:00",
                "window_end": "2026-07-11T10:04:00+00:00",
                "level": "green",
                "should_publish": False,
                "anomaly_score": 0.0,
                "model_label": "agreement_normal",
            }
        ),
        encoding="utf-8",
    )

    messages = build_cycle_messages(
        patient_id="patient-001",
        edge_id="edge-rpi5-001",
        status_payload={"status": "cycle_completed"},
        latest_window_csv=latest,
        decision_json=decision,
        retain_status=True,
    )

    window_message = next(
        message for message in messages if message.topic.endswith("/telemetry/window")
    )
    assert window_message.qos == 1
    assert window_message.retain is False
    assert window_message.payload["payload"]["features"]["heart_rate_mean"] is None
    assert window_message.payload["payload"]["features"]["spo2_mean"] == 96.5
    assert window_message.payload["payload"]["features"]["wearable_present"] is True


def test_alert_message_is_created_only_when_decision_should_publish(tmp_path) -> None:
    latest = tmp_path / "latest_window.csv"
    latest.write_text(
        "patient_id,window_start,window_end,kitchen_minutes\n"
        "patient-001,2026-07-11T10:00:00+00:00,2026-07-11T10:04:00+00:00,4\n",
        encoding="utf-8",
    )
    decision = tmp_path / "patient-001-decision.json"
    decision.write_text(
        json.dumps(
            {
                "patient_id": "patient-001",
                "window_start": "2026-07-11T10:00:00+00:00",
                "window_end": "2026-07-11T10:04:00+00:00",
                "level": "red",
                "should_publish": True,
                "anomaly_score": 88.0,
                "model_label": "multi_model_red",
                "reasons": ["Score severo confermato"],
            }
        ),
        encoding="utf-8",
    )

    messages = build_cycle_messages(
        patient_id="patient-001",
        edge_id="edge-rpi5-001",
        status_payload={"status": "cycle_completed"},
        latest_window_csv=latest,
        decision_json=decision,
        retain_status=True,
    )

    alert_message = next(
        message for message in messages if message.topic.endswith("/alerts/critical")
    )
    assert alert_message.qos == 1
    assert alert_message.retain is False
    assert alert_message.payload["event_type"] == "alert_created"
    assert alert_message.payload["payload"]["level"] == "red"
    assert alert_message.payload["payload"]["decision"]["anomaly_score"] == 88.0


def test_disk_queue_roundtrip(tmp_path) -> None:
    latest = tmp_path / "latest_window.csv"
    latest.write_text(
        "patient_id,window_start,window_end,kitchen_minutes\n"
        "patient-001,2026-07-11T10:00:00+00:00,2026-07-11T10:04:00+00:00,4\n",
        encoding="utf-8",
    )
    decision = tmp_path / "patient-001-decision.json"
    decision.write_text(
        json.dumps({"patient_id": "patient-001", "level": "green", "should_publish": False}),
        encoding="utf-8",
    )
    message = build_cycle_messages(
        patient_id="patient-001",
        edge_id="edge-rpi5-001",
        status_payload={"status": "cycle_completed"},
        latest_window_csv=latest,
        decision_json=decision,
        retain_status=True,
    )[0]

    queue = DiskMqttQueue(tmp_path / "queue")
    queue.enqueue(message)

    queued = queue.iter_messages(limit=10)
    assert queue.depth() == 1
    assert queued[0].message.topic == message.topic
    assert queued[0].message.payload["message_id"] == message.payload["message_id"]
    queue.remove(queued[0])
    assert queue.depth() == 0
