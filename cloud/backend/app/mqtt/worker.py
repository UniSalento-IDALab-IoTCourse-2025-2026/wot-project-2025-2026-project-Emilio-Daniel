from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.mqtt.client import BackendMqttSubscriber


def main() -> None:
    """Avvia il worker subscriber MQTT del backend."""
    settings = get_settings()
    configure_logging(settings.log_level)
    BackendMqttSubscriber(settings).run_forever()


if __name__ == "__main__":
    main()
