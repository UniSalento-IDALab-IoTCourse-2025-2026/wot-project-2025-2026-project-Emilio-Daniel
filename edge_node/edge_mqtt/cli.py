from __future__ import annotations

import argparse
import json
from pathlib import Path

from edge_ingest.config import load_config
from edge_mqtt.messages import build_cycle_messages
from edge_mqtt.publisher import EdgeMqttPublisher


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-mqtt",
        description="Publish or inspect Edge MQTT payloads produced by the runtime.",
    )
    parser.add_argument("--config", default="config/edge.yml")
    parser.add_argument("--status", default="outputs/last-cycle.json")
    parser.add_argument("--decision", default=None)
    parser.add_argument("--absence", default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print MQTT messages without connecting to the broker.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    status_path = Path(args.status)
    with status_path.open("r", encoding="utf-8") as handle:
        status_payload = json.load(handle)
    decision_path = (
        Path(args.decision)
        if args.decision
        else Path("outputs") / f"{config.patient.patient_id}-decision.json"
    )
    absence_path = (
        Path(args.absence)
        if args.absence
        else Path("outputs") / f"{config.patient.patient_id}-absence.json"
    )
    messages = build_cycle_messages(
        patient_id=config.patient.patient_id,
        edge_id=config.mqtt.edge_id,
        status_payload=status_payload,
        latest_window_csv=config.paths.latest_window_csv,
        decision_json=decision_path,
        absence_json=absence_path,
        retain_status=config.mqtt.retain_status,
    )

    if args.dry_run:
        print(
            json.dumps(
                [
                    {
                        "topic": message.topic,
                        "qos": message.qos,
                        "retain": message.retain,
                        "payload": message.payload,
                    }
                    for message in messages
                ],
                indent=2,
            )
        )
        return

    summary = EdgeMqttPublisher(config.mqtt, config.patient.patient_id).publish(messages)
    print(json.dumps(summary.to_dict(), indent=2))


if __name__ == "__main__":
    main()
