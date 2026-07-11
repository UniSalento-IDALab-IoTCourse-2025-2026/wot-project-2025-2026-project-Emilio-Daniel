from __future__ import annotations

import ssl
import time
from pathlib import Path

import paho.mqtt.client as mqtt

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.mqtt.ingest import ingest_mqtt_message
from app.mqtt.topics import subscription_topics

logger = get_logger(__name__)


class BackendMqttSubscriber:
    """Subscriber MQTT che salva in PostgreSQL i messaggi ricevuti dall'Edge."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            clean_session=True,
        )
        self._configure_client()

    def _configure_client(self) -> None:
        self.client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)
        self.client.reconnect_delay_set(
            min_delay=self.settings.mqtt_reconnect_min_delay_seconds,
            max_delay=self.settings.mqtt_reconnect_max_delay_seconds,
        )
        if self.settings.mqtt_use_tls:
            ca_file = Path(self.settings.mqtt_ca_file)
            self.client.tls_set(
                ca_certs=str(ca_file),
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            self.client.tls_insecure_set(False)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def run_forever(self) -> None:
        """Si collega al broker MQTT e resta attivo, riconnettendosi se serve."""
        while True:
            try:
                logger.info(
                    "mqtt_connecting",
                    extra={
                        "host": self.settings.mqtt_host,
                        "port": self.settings.mqtt_port,
                        "tls": self.settings.mqtt_use_tls,
                    },
                )
                self.client.connect(
                    self.settings.mqtt_host,
                    self.settings.mqtt_port,
                    keepalive=self.settings.mqtt_keepalive_seconds,
                )
                self.client.loop_forever(retry_first_connection=True)
            except KeyboardInterrupt:
                logger.info("mqtt_subscriber_stopped_by_user")
                self.client.disconnect()
                raise
            except Exception as exc:
                logger.exception(
                    "mqtt_subscriber_error",
                    extra={"error_type": exc.__class__.__name__},
                )
                time.sleep(self.settings.mqtt_reconnect_max_delay_seconds)

    def _on_connect(self, client: mqtt.Client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            logger.error("mqtt_connect_failed", extra={"reason_code": str(reason_code)})
            return
        logger.info("mqtt_connected", extra={"reason_code": str(reason_code)})
        for topic, qos in subscription_topics():
            client.subscribe(topic, qos=qos)
            logger.info("mqtt_subscribed", extra={"topic": topic, "qos": qos})

    def _on_disconnect(self, _client: mqtt.Client, _userdata, _flags, reason_code, _properties) -> None:
        logger.warning("mqtt_disconnected", extra={"reason_code": str(reason_code)})

    def _on_message(self, _client: mqtt.Client, _userdata, message: mqtt.MQTTMessage) -> None:
        topic = str(message.topic)
        with SessionLocal() as db:
            result = ingest_mqtt_message(db, topic, bytes(message.payload))
        log_extra = {
            "topic": result.topic,
            "status": result.status,
            "patient_id": result.patient_id,
            "message_id": result.message_id,
            "reason": result.reason,
        }
        if result.status == "rejected":
            logger.warning("mqtt_message_rejected", extra=log_extra)
        elif result.status == "duplicate":
            logger.info("mqtt_message_duplicate", extra=log_extra)
        else:
            logger.info("mqtt_message_ingested", extra=log_extra)
