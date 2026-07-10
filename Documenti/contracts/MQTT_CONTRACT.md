# Contratto MQTT

Questo documento definisce i topic e le regole MQTT tra Raspberry Pi 5 e backend Cloud.

## Regole comuni

Ogni messaggio MQTT deve contenere:

```json
{
  "schema_version": 1,
  "message_id": "uuid-or-ulid",
  "event_type": "edge_cycle_completed",
  "patient_id": "patient-001",
  "edge_id": "edge-rpi5-001",
  "timestamp": "2026-07-10T10:00:00Z",
  "payload": {}
}
```

Regole:

- `patient_id` identifica il paziente.
- `edge_id` identifica il Raspberry installato.
- `timestamp` e' sempre ISO 8601 in UTC.
- `schema_version` parte da `1`.
- `message_id` e' univoco e serve per deduplicare ritrasmissioni QoS 1/offline queue.
- I valori mancanti devono essere `null`, non stringhe `"nan"`.
- Non inviare token OAuth, password, refresh token, token FCM o certificati.
- `event_type` descrive il tipo evento.
- `level` descrive il livello clinico/tecnico quando presente.
- `should_publish` indica se l'evento va trattato come alert pubblicabile.

## Topic

```text
iot/patients/{patient_id}/edge/status
iot/patients/{patient_id}/telemetry/window
iot/patients/{patient_id}/telemetry/decision
iot/patients/{patient_id}/alerts/critical
iot/patients/{patient_id}/sensors/watch
iot/patients/{patient_id}/sensors/ble
iot/patients/{patient_id}/commands/task
iot/patients/{patient_id}/commands/ack
```

## QoS consigliato

| Topic | QoS | Retained | Note |
| --- | --- | --- | --- |
| `edge/status` | 1 | solo stato online/offline | stato tecnico Edge |
| `telemetry/window` | 1 | no | finestra aggregata |
| `telemetry/decision` | 1 | no | decisione AI |
| `alerts/critical` | 1 | no | alert pubblicabili |
| `sensors/watch` | 0 o 1 | no | stato watch |
| `sensors/ble` | 0 o 1 | no | stato BLE |
| `commands/task` | 1 | no | comandi backend, se necessari |
| `commands/ack` | 1 | no | ack dei comandi |

## Last Will

Il Raspberry deve configurare un Last Will su:

```text
iot/patients/{patient_id}/edge/status
```

Payload minimo:

```json
{
  "schema_version": 1,
  "message_id": "generated-by-edge",
  "event_type": "edge_offline_unexpected",
  "patient_id": "patient-001",
  "edge_id": "edge-rpi5-001",
  "timestamp": "2026-07-10T10:00:00Z",
  "payload": {
    "online": false,
    "reason": "mqtt_last_will"
  }
}
```

## Sicurezza

- MQTT deve usare TLS.
- Ogni Raspberry ha credenziali dedicate.
- Il Raspberry puo' pubblicare solo sui topic del proprio `patient_id`.
- Il backend puo' sottoscrivere topic dei pazienti autorizzati e pubblicare solo comandi
  consentiti.
- I topic di pazienti diversi devono essere separati tramite ACL.

## Event type minimi

```text
edge_cycle_completed
patient_window_updated
decision_updated
alert_created
sensor_watch_updated
sensor_ble_updated
edge_offline_unexpected
command_acknowledged
```

## Esempi

Gli esempi sono in:

```text
Documenti/contracts/examples/
```

Esempi Edge reali da Emilio:

```text
edge_last_cycle.example.json
edge_patient_decision.example.json
edge_latest_window.example.json
edge_decision_green.example.json
edge_decision_yellow.example.json
edge_decision_orange.example.json
edge_decision_red.example.json
edge_decision_technical.example.json
```
