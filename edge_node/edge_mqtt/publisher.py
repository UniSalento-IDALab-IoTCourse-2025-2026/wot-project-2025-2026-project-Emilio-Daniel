from __future__ import annotations

import os
import socket
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from edge_ingest.config import EdgeIngestConfig, MqttConfig
from edge_mqtt.messages import MqttMessage, build_cycle_messages, build_last_will_message
from edge_mqtt.queue import DiskMqttQueue


@dataclass
class PublishSummary:
    """Sintesi serializzabile della pubblicazione MQTT del ciclo."""

    enabled: bool
    status: str
    attempted: int = 0
    published: int = 0
    queued: int = 0
    queue_depth: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "status": self.status,
            "attempted": self.attempted,
            "published": self.published,
            "queued": self.queued,
            "queue_depth": self.queue_depth,
            "errors": self.errors,
        }


def publish_runtime_outputs(
    *,
    config: EdgeIngestConfig,
    status_payload: dict[str, Any],
    decision_output: Path,
    absence_output: Path | None = None,
) -> PublishSummary:
    """Pubblica gli output del ciclo Edge senza far fallire il runtime locale."""
    mqtt_config = config.mqtt
    queue = DiskMqttQueue(mqtt_config.queue_dir)
    if not mqtt_config.enabled:
        return PublishSummary(
            enabled=False,
            status="disabled",
            queue_depth=queue.depth(),
        )

    try:
        messages = build_cycle_messages(
            patient_id=config.patient.patient_id,
            edge_id=mqtt_config.edge_id,
            status_payload=status_payload,
            latest_window_csv=config.paths.latest_window_csv,
            decision_json=decision_output,
            retain_status=mqtt_config.retain_status,
            absence_json=absence_output,
        )
        return EdgeMqttPublisher(mqtt_config, config.patient.patient_id).publish(messages)
    except Exception as exc:
        return PublishSummary(
            enabled=True,
            status="failed_before_publish",
            queue_depth=queue.depth(),
            errors=[f"{type(exc).__name__}: {exc}"],
        )


class EdgeMqttPublisher:
    """Publisher MQTT dell'Edge Node con TLS, Last Will e coda locale."""

    def __init__(self, config: MqttConfig, patient_id: str) -> None:
        self.config = config
        self.patient_id = patient_id
        self.queue = DiskMqttQueue(config.queue_dir)

    def publish(self, messages: list[MqttMessage]) -> PublishSummary:
        summary = PublishSummary(
            enabled=True,
            status="starting",
            attempted=len(messages),
            queue_depth=self.queue.depth(),
        )
        try:
            client = self._build_client()
            previous_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(self.config.connect_timeout_seconds)
            try:
                client.connect(
                    self.config.host,
                    self.config.port,
                    keepalive=self.config.keepalive_seconds,
                )
            finally:
                socket.setdefaulttimeout(previous_timeout)
            client.loop_start()
        except Exception as exc:
            summary.errors.append(f"connect: {type(exc).__name__}: {exc}")
            summary.queued += self._enqueue_all(messages)
            summary.queue_depth = self.queue.depth()
            summary.status = "queued_connect_failed"
            return summary

        try:
            self._flush_queue(client, summary)
            for message in messages:
                if self._publish_one(client, message, summary):
                    summary.published += 1
                else:
                    summary.queued += self._enqueue_all([message])
            summary.queue_depth = self.queue.depth()
            summary.status = "published" if not summary.errors else "partial"
            return summary
        finally:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass

    def _build_client(self):
        try:
            import paho.mqtt.client as mqtt
        except Exception as exc:  # pragma: no cover - depends on local setup.
            raise RuntimeError("paho-mqtt non installato. Eseguire pip install -r requirements.txt") from exc

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.config.client_id,
            clean_session=True,
        )
        password = self._password()
        if not password:
            raise RuntimeError(
                "Password MQTT mancante. Impostare mqtt.password nel config locale "
                f"oppure la variabile {self.config.password_env}."
            )
        client.username_pw_set(self.config.username, password)
        if self.config.use_tls:
            ca_file = Path(self.config.ca_file)
            if not ca_file.exists():
                raise FileNotFoundError(f"CA MQTT non trovata: {ca_file}")
            client.tls_set(
                ca_certs=str(ca_file),
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            client.tls_insecure_set(False)

        will_message = build_last_will_message(
            patient_id=self.patient_id,
            edge_id=self.config.edge_id,
        )
        client.will_set(
            will_message.topic,
            payload=will_message.to_json(),
            qos=will_message.qos,
            retain=will_message.retain,
        )
        return client

    def _password(self) -> str:
        if self.config.password:
            return self.config.password
        if self.config.password_env:
            return os.environ.get(self.config.password_env, "")
        return ""

    def _flush_queue(self, client: Any, summary: PublishSummary) -> None:
        queued_messages = self.queue.iter_messages(self.config.max_flush_messages)
        if self.queue.last_quarantined:
            summary.errors.append(
                "queue: quarantined "
                f"{len(self.queue.last_quarantined)} malformed message(s)"
            )
        for queued in queued_messages:
            if self._publish_one(client, queued.message, summary):
                self.queue.remove(queued)
                summary.published += 1
            else:
                return

    def _publish_one(self, client: Any, message: MqttMessage, summary: PublishSummary) -> bool:
        try:
            info = client.publish(
                message.topic,
                payload=message.to_json(),
                qos=message.qos,
                retain=message.retain,
            )
            if getattr(info, "rc", 0) != 0:
                summary.errors.append(f"publish rc={info.rc} topic={message.topic}")
                return False
            info.wait_for_publish(timeout=self.config.publish_timeout_seconds)
            if hasattr(info, "is_published") and not info.is_published():
                summary.errors.append(f"publish timeout topic={message.topic}")
                return False
            return True
        except Exception as exc:
            summary.errors.append(f"publish: {type(exc).__name__}: {exc}")
            return False

    def _enqueue_all(self, messages: list[MqttMessage]) -> int:
        count = 0
        for message in messages:
            self.queue.enqueue(message)
            count += 1
        return count
