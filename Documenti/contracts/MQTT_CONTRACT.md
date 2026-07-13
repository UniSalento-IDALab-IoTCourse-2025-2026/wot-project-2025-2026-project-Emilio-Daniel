# Contratto MQTT

Questo documento definisce i topic e le regole MQTT tra Raspberry Pi 5 e backend Cloud.

Stato: aggiornato a E1 e D4/D8.

## Direzione del flusso

MQTT viene usato principalmente per:

```text
Raspberry/Edge -> broker MQTT -> backend Cloud
```

La dashboard e le app non leggono MQTT direttamente: usano API REST, WebSocket
applicativo e notifiche push.

I task paziente non vengono inviati via MQTT. Sono creati dal backend tramite REST e
verranno notificati all'app paziente tramite il modulo notifiche/push.

## Envelope comune

Ogni messaggio MQTT pubblicato dall'Edge deve avere:

```json
{
  "schema_version": 1,
  "message_id": "decision-updated-uuid",
  "event_type": "decision_updated",
  "patient_id": "patient-001",
  "edge_id": "edge-rpi5-001",
  "timestamp": "2026-07-13T10:00:00Z",
  "payload": {}
}
```

Regole:

- `schema_version` resta `1` fino a modifica concordata.
- `message_id` e' univoco e serve per deduplica QoS 1/offline queue.
- `timestamp` e' sempre ISO 8601 UTC.
- I valori mancanti devono essere `null`, non stringhe `"nan"`.
- Non pubblicare token OAuth, password, refresh token, token FCM o certificati.
- `payload` contiene il corpo specifico dell'evento.

## Topic pubblicati dall'Edge

```text
iot/patients/{patient_id}/edge/status
iot/patients/{patient_id}/telemetry/window
iot/patients/{patient_id}/telemetry/decision
iot/patients/{patient_id}/alerts/critical
iot/patients/{patient_id}/sensors/watch
iot/patients/{patient_id}/sensors/ble
```

## QoS e retained

| Topic | QoS | Retained | Note |
| --- | --- | --- | --- |
| `edge/status` | 1 | solo stato tecnico corrente | ciclo Edge e Last Will |
| `telemetry/window` | 1 | no | finestra aggregata di 4 minuti |
| `telemetry/decision` | 1 | no | decisione AI Edge |
| `alerts/critical` | 1 | no | alert creato da decisione pubblicabile |
| `sensors/watch` | 0 o 1 | no | stato sintetico watch |
| `sensors/ble` | 0 o 1 | no | stato sintetico BLE |

Regola retained:

- `edge/status` puo' essere retained solo per stato corrente online/offline.
- finestre, decisioni, alert e dati sensore non devono essere retained.

## Last Will

Il Raspberry deve configurare un Last Will su:

```text
iot/patients/{patient_id}/edge/status
```

Payload:

```json
{
  "schema_version": 1,
  "message_id": "edge-offline-unexpected-demo",
  "event_type": "edge_offline_unexpected",
  "patient_id": "patient-001",
  "edge_id": "edge-rpi5-001",
  "timestamp": "2026-07-13T10:00:00Z",
  "payload": {
    "online": false,
    "reason": "mqtt_last_will"
  }
}
```

## Event type pubblicati dall'Edge

```text
edge_cycle_completed
edge_offline_unexpected
patient_window_updated
decision_updated
alert_created
sensor_watch_updated
sensor_ble_updated
```

## Payload per topic

### `edge/status`

`payload` contiene lo stato dell'ultimo ciclo Edge:

```json
{
  "status": "cycle_completed",
  "window_start": "2026-07-12T09:04:00+00:00",
  "window_end": "2026-07-12T09:08:00+00:00",
  "quality_status": "ok",
  "inference": "completed_generic_spatial_plus_generic_wearable",
  "decision_level": "green",
  "should_publish": false,
  "online": true
}
```

### `telemetry/window`

`payload` contiene la finestra aggregata:

```json
{
  "window_start": "2026-07-12T09:04:00+00:00",
  "window_end": "2026-07-12T09:08:00+00:00",
  "features": {
    "wearable_present": true,
    "wearable_battery_pct": 14,
    "heart_rate_mean": null,
    "resting_heart_rate": 51,
    "hrv_rmssd": 84.65,
    "spo2_mean": 96,
    "room_changes": null
  }
}
```

### `telemetry/decision`

`payload` contiene la decisione AI Edge:

```json
{
  "patient_id": "patient-001",
  "window_start": "2026-07-12T09:04:00+00:00",
  "window_end": "2026-07-12T09:08:00+00:00",
  "level": "green",
  "should_publish": false,
  "anomaly_score": 0.0,
  "reasons": ["Routine inside learned baseline"],
  "model_label": "agreement_normal",
  "evidence": {}
}
```

### `alerts/critical`

Questo messaggio esiste solo quando la decisione ha `should_publish=true`.

```json
{
  "level": "red",
  "status": "new",
  "category": "behavioral",
  "title": "Allarme Edge red",
  "description": "Allarme severo confermato da piu modelli.",
  "opened_at": "2026-07-13T10:00:00Z",
  "anomaly_score": 91.0,
  "model_label": "contract_example",
  "decision": {}
}
```

## Sicurezza

- MQTT deve usare TLS.
- Ogni Raspberry ha username/password dedicati.
- Il Raspberry puo' pubblicare solo sui topic del proprio `patient_id`.
- Il backend sottoscrive topic autorizzati.
- I topic di pazienti diversi devono essere separati tramite ACL.
- I messaggi sensibili vengono persistiti nel backend, non letti direttamente dal
  frontend.

## Esempi versionati

Gli esempi JSON sono in:

```text
Documenti/contracts/examples/
```

Esempi Edge:

```text
edge_last_cycle.example.json
edge_latest_window.example.json
edge_patient_decision.example.json
edge_alert_critical.example.json
edge_decision_green.example.json
edge_decision_yellow.example.json
edge_decision_orange.example.json
edge_decision_red.example.json
edge_decision_technical.example.json
edge_decision_levels.example.json
```
