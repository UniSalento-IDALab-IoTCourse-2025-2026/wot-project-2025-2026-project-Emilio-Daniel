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


def test_absence_alert_message_is_published(tmp_path) -> None:
    latest = tmp_path / "latest_window.csv"
    latest.write_text(
        "patient_id,window_start,window_end,bedroom_minutes\n"
        "patient-001,2026-07-11T10:00:00+00:00,2026-07-11T10:04:00+00:00,4\n",
        encoding="utf-8",
    )
    decision = tmp_path / "patient-001-decision.json"
    decision.write_text(
        json.dumps(
            {
                "patient_id": "patient-001",
                "level": "green",
                "should_publish": False,
                "anomaly_score": 0.0,
            }
        ),
        encoding="utf-8",
    )
    absence = tmp_path / "patient-001-absence.json"
    absence.write_text(
        json.dumps(
            {
                "patient_id": "patient-001",
                "kind": "no_movement",
                "level": "orange",
                "category": "no_movement",
                "title": "Assenza di movimento da verificare",
                "description": "Nessun cambio stanza da oltre 4 ore.",
                "reason": "Nessun movimento per oltre 4 ore.",
                "duration_minutes": 300.0,
                "no_movement_minutes": 300.0,
                "last_room": "living_room",
                "last_transition_at": "2026-07-11T05:00:00Z",
                "ble_quality": "ok",
                "message_id": "absence-abc123",
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
        absence_json=absence,
        retain_status=True,
    )

    absence_messages = [
        message for message in messages if message.topic.endswith("/alerts/critical")
    ]
    assert len(absence_messages) == 1
    message = absence_messages[0]
    assert message.payload["event_type"] == "alert_created"
    assert message.payload["message_id"] == "absence-abc123"
    assert message.payload["payload"]["level"] == "orange"
    assert message.payload["payload"]["category"] == "no_movement"
    assert message.payload["payload"]["last_room"] == "living_room"
    assert message.payload["payload"]["duration_minutes"] == 300.0
    assert message.payload["payload"]["ble_quality"] == "ok"


def test_absence_alert_skipped_when_file_absent(tmp_path) -> None:
    latest = tmp_path / "latest_window.csv"
    latest.write_text(
        "patient_id,window_start,window_end,bedroom_minutes\n"
        "patient-001,2026-07-11T10:00:00+00:00,2026-07-11T10:04:00+00:00,4\n",
        encoding="utf-8",
    )
    decision = tmp_path / "patient-001-decision.json"
    decision.write_text(
        json.dumps({"patient_id": "patient-001", "level": "green", "should_publish": False}),
        encoding="utf-8",
    )
    missing = tmp_path / "missing-absence.json"

    messages = build_cycle_messages(
        patient_id="patient-001",
        edge_id="edge-rpi5-001",
        status_payload={"status": "cycle_completed"},
        latest_window_csv=latest,
        decision_json=decision,
        absence_json=missing,
        retain_status=True,
    )

    alerts = [message for message in messages if message.topic.endswith("/alerts/critical")]
    assert alerts == []


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

def test_offline_queue_survives_process_restart(tmp_path) -> None:
    from edge_mqtt.messages import MqttMessage

    message = MqttMessage(
        topic="iot/patients/patient-001/telemetry/window",
        qos=1,
        payload={
            "schema_version": 1,
            "message_id": "offline-window-001",
            "event_type": "patient_window_updated",
            "patient_id": "patient-001",
            "edge_id": "edge-rpi5-001",
            "timestamp": "2026-07-11T10:00:00Z",
        },
    )
    queue_dir = tmp_path / "queue"
    DiskMqttQueue(queue_dir).enqueue(message)

    restarted = DiskMqttQueue(queue_dir)
    assert restarted.depth() == 1
    queued = restarted.iter_messages(limit=5)
    assert len(queued) == 1
    assert queued[0].message.topic == "iot/patients/patient-001/telemetry/window"
    assert queued[0].message.payload["message_id"] == "offline-window-001"


def test_failed_publish_keeps_message_for_retry(tmp_path) -> None:
    from edge_mqtt.messages import MqttMessage

    message = MqttMessage(
        topic="iot/patients/patient-001/telemetry/decision",
        payload={"message_id": "retry-decision-001", "level": "orange"},
    )
    queue = DiskMqttQueue(tmp_path / "queue")
    queue.enqueue(message)

    attempts = queue.iter_messages(limit=5)
    assert len(attempts) == 1
    queue.remove(attempts[0])
    assert queue.depth() == 0


def test_fifo_order_is_preserved(tmp_path) -> None:
    from edge_mqtt.messages import MqttMessage

    queue = DiskMqttQueue(tmp_path / "queue")
    for index in range(3):
        queue.enqueue(
            MqttMessage(
                topic="iot/patients/patient-001/telemetry/window",
                payload={"message_id": f"fifo-{index:03d}"},
            )
        )
    queued = queue.iter_messages(limit=10)
    ids = [item.message.payload["message_id"] for item in queued]
    assert ids == ["fifo-000", "fifo-001", "fifo-002"]


def test_corrupt_queue_file_is_quarantined_without_blocking_valid_messages(tmp_path) -> None:
    from edge_mqtt.messages import MqttMessage

    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    (queue_dir / "000-corrupt.json").write_text("", encoding="utf-8")
    queue = DiskMqttQueue(queue_dir)
    queue.enqueue(
        MqttMessage(
            topic="iot/patients/patient-001/edge/status",
            payload={"message_id": "valid-after-corrupt"},
        )
    )

    queued = queue.iter_messages(limit=10)

    assert [item.message.message_id for item in queued] == ["valid-after-corrupt"]
    assert len(queue.last_quarantined) == 1
    assert queue.last_quarantined[0].parent == queue_dir / "quarantine"
    assert not (queue_dir / "000-corrupt.json").exists()
    assert queue.depth() == 1


def test_runtime_publisher_forwards_technical_absence_signal(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from edge_mqtt.publisher import EdgeMqttPublisher, PublishSummary, publish_runtime_outputs

    latest = tmp_path / "latest.csv"
    latest.write_text(
        "patient_id,window_start,window_end\n"
        "patient-001,2026-10-05T10:00:00Z,2026-10-05T10:04:00Z\n",
        encoding="utf-8",
    )
    decision = tmp_path / "decision.json"
    decision.write_text(
        json.dumps({"patient_id": "patient-001", "level": "green", "should_publish": False}),
        encoding="utf-8",
    )
    absence = tmp_path / "absence.json"
    absence.write_text(
        json.dumps(
            {
                "patient_id": "patient-001",
                "kind": "ble_unreliable",
                "level": "technical",
                "category": "technical",
                "title": "Sensore di movimento non affidabile",
                "message_id": "absence-technical-001",
            }
        ),
        encoding="utf-8",
    )
    mqtt = SimpleNamespace(
        enabled=True,
        queue_dir=tmp_path / "queue",
        edge_id="edge-rpi5-001",
        retain_status=True,
    )
    config = SimpleNamespace(
        patient=SimpleNamespace(patient_id="patient-001"),
        paths=SimpleNamespace(latest_window_csv=latest),
        mqtt=mqtt,
    )
    captured = []

    def capture_publish(self, messages):
        captured.extend(messages)
        return PublishSummary(enabled=True, status="published", published=len(messages))

    monkeypatch.setattr(EdgeMqttPublisher, "publish", capture_publish)

    publish_runtime_outputs(
        config=config,
        status_payload={"status": "cycle_completed"},
        decision_output=decision,
        absence_output=absence,
    )

    alerts = [message for message in captured if message.topic.endswith("/alerts/critical")]
    assert len(alerts) == 1
    assert alerts[0].message_id == "absence-technical-001"
    assert alerts[0].payload["payload"]["category"] == "technical"
