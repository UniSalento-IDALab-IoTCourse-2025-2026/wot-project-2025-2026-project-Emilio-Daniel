# Contratto API e WebSocket

Questo documento definisce le API minime tra backend, dashboard medico, app paziente e
app caregiver.

## Regole comuni

- Base path: `/api/v1`.
- Tutte le date sono ISO 8601 UTC.
- I valori mancanti sono `null`.
- Gli errori hanno sempre `code`, `message`, `details`.
- Le liste usano paginazione.
- Ogni endpoint deve rispettare ruoli e autorizzazioni.
- Nessun endpoint restituisce password, refresh token Google Health, token FCM o segreti.

## Formato errore

```json
{
  "code": "resource_not_found",
  "message": "The requested resource was not found.",
  "details": {
    "resource": "patient",
    "patient_id": "patient-001"
  }
}
```

## Ruoli

```text
admin
doctor
caregiver
patient
edge
```

Regole sintetiche:

- `doctor`: vede pazienti assegnati, alert, storico, task, risultati.
- `caregiver`: vede stato sintetico e alert autorizzati, puo' prendere in carico se previsto.
- `patient`: vede i propri task, invia risultati e stato app.
- `edge`: pubblica dati tramite MQTT, non usa API cliniche.
- `admin`: gestisce utenti, pazienti e associazioni.

## Endpoint minimi

```text
POST   /api/v1/auth/login
GET    /api/v1/patients
GET    /api/v1/patients/{patient_id}/current
GET    /api/v1/patients/{patient_id}/windows
GET    /api/v1/patients/{patient_id}/decisions
GET    /api/v1/patients/{patient_id}/alerts
PATCH  /api/v1/alerts/{alert_id}/acknowledge
PATCH  /api/v1/alerts/{alert_id}/resolve
POST   /api/v1/patients/{patient_id}/tasks
GET    /api/v1/patients/{patient_id}/tasks
POST   /api/v1/tasks/{task_id}/results
POST   /api/v1/devices/push-token
POST   /api/v1/patients/{patient_id}/app-status
GET    /api/v1/patients/{patient_id}/system-status
WS     /ws/v1/patients/{patient_id}
```

## Endpoint principali

### Login

```text
POST /api/v1/auth/login
```

Request:

```json
{
  "email": "<email configurata nel .env locale>",
  "password": "<password non committata>"
}
```

Response:

```json
{
  "access_token": "jwt-access-token",
  "refresh_token": "opaque-refresh-token",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "user_id": "user-1",
    "role": "doctor",
    "display_name": "Nome visualizzato"
  }
}
```

Il refresh token e' opaco: il backend salva solo il suo hash e puo' revocarlo con
`POST /api/v1/auth/logout`.

### Current paziente

```text
GET /api/v1/patients/{patient_id}/current
```

Response minima:

```json
{
  "patient_id": "patient-001",
  "edge_id": "edge-rpi5-001",
  "last_update": "2026-07-10T10:00:00Z",
  "level": "green",
  "should_publish": false,
  "anomaly_score": 0.0,
  "current_room": "kitchen",
  "watch": {
    "present": true,
    "battery_pct": 72,
    "available_features": ["heart_rate_mean", "steps"]
  },
  "edge": {
    "online": true,
    "quality_status": "ok"
  }
}
```

### Creazione task paziente

```text
POST /api/v1/patients/{patient_id}/tasks
```

Request:

```json
{
  "type": "check_in",
  "priority": "normal",
  "expires_at": "2026-07-10T18:00:00Z",
  "title": "Controllo benessere",
  "instructions": "Rispondi a queste brevi domande.",
  "payload": {
    "questions": [
      {
        "id": "q1",
        "type": "single_choice",
        "text": "Come ti senti adesso?",
        "options": ["bene", "cosi_cosi", "male"]
      }
    ]
  }
}
```

Response:

```json
{
  "task_id": "task-001",
  "patient_id": "patient-001",
  "status": "created",
  "created_at": "2026-07-10T10:00:00Z"
}
```

### Risultato task

```text
POST /api/v1/tasks/{task_id}/results
```

Request:

```json
{
  "patient_id": "patient-001",
  "started_at": "2026-07-10T10:05:00Z",
  "completed_at": "2026-07-10T10:07:10Z",
  "answers": [
    {
      "question_id": "q1",
      "value": "bene"
    }
  ],
  "score": null,
  "duration_seconds": 130,
  "device_info": {
    "platform": "android",
    "app_version": "1.0.0"
  }
}
```

## WebSocket

Endpoint:

```text
WS /ws/v1/patients/{patient_id}?token=<access_token>
```

La connessione viene accettata solo se il token e' valido e l'utente puo' leggere
quel `patient_id`.

Ogni evento WebSocket ha questo formato:

```json
{
  "event_type": "decision_updated",
  "event_id": "event-001",
  "patient_id": "patient-001",
  "timestamp": "2026-07-10T10:00:00Z",
  "payload": {}
}
```

Eventi minimi:

```text
edge_cycle_completed
patient_window_updated
decision_updated
alert_created
alert_acknowledged
alert_resolved
task_created
task_seen
task_completed
system_status_updated
```

## OpenAPI

Il file OpenAPI definitivo verra' generato dal backend FastAPI quando D2 sara' avviato.
Percorso previsto:

```text
Documenti/contracts/openapi.json
```
