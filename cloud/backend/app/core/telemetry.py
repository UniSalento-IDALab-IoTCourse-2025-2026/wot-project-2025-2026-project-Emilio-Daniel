from __future__ import annotations

"""Contatori realtime per il monitoring operativo (D33).

I contatori sono in-memory: servono ad avere una fotografia immediata dello
stato del backend nel processo corrente. Su piu' repliche ogni avvio riparte
da zero; per conteggi storici il sistema si affida comunque alle righe del
database, espresse nelle metriche `*_received`.
"""

_mqtt_messages_received: int = 0
_firebase_errors: int = 0


def increment_mqtt_messages_received() -> None:
    global _mqtt_messages_received
    _mqtt_messages_received += 1


def increment_firebase_errors() -> None:
    global _firebase_errors
    _firebase_errors += 1


def mqtt_messages_received() -> int:
    return _mqtt_messages_received


def firebase_errors() -> int:
    return _firebase_errors


def telemetry_snapshot() -> dict[str, int]:
    """Restituisce la fotografia dei contatori correnti, JSON-safe."""
    return {
        "mqtt_messages_received_total": _mqtt_messages_received,
        "firebase_errors_total": _firebase_errors,
    }