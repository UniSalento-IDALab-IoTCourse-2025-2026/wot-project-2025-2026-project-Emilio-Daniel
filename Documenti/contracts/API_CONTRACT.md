# Contratto API e WebSocket

Questo documento definisce il contratto condiviso tra backend Cloud, dashboard medico,
app paziente e app caregiver.

Stato: aggiornato a D5-D9.

## Regole comuni

- Base REST: `/api/v1`.
- Base WebSocket: `/ws/v1`.
- Tutte le date sono ISO 8601 UTC.
- I valori mancanti sono `null`.
- Le liste usano risposta paginata con `items`, `page`, `page_size`, `total`.
- Le chiamate REST protette usano `Authorization: Bearer <access_token>`.
- La WebSocket usa lo stesso access token come query string.
- Nessun endpoint restituisce password, hash password, token Google Health, token FCM o
  segreti.

Nota errori: FastAPI puo' restituire errori nel formato standard `detail`. La dashboard
li trasforma in messaggi leggibili. Il formato applicativo desiderato resta:

```json
{
  "code": "resource_not_found",
  "message": "Risorsa non trovata.",
  "details": {
    "resource": "patient",
    "patient_id": "patient-001"
  }
}
```

## Ruoli applicativi

```text
admin
doctor
caregiver
patient
```

Regole principali:

- `admin`: gestisce utenti, pazienti e associazioni.
- `doctor`: vede pazienti assegnati, crea task, prende in carico e risolve alert.
- `caregiver`: vede pazienti assegnati e puo' prendere in carico alert autorizzati.
- `patient`: vede i propri task e invia risultati.

L'Edge/Raspberry non usa le API cliniche REST: pubblica tramite MQTT con credenziali
dedicate.

## Endpoint REST principali

```text
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout
GET    /api/v1/auth/me
POST   /api/v1/auth/change-password
POST   /api/v1/auth/sessions/revoke

GET    /api/v1/patients
GET    /api/v1/patients/{patient_id}/current
GET    /api/v1/patients/{patient_id}/windows
GET    /api/v1/patients/{patient_id}/decisions
GET    /api/v1/patients/{patient_id}/alerts
GET    /api/v1/patients/{patient_id}/tasks
POST   /api/v1/patients/{patient_id}/tasks
GET    /api/v1/patients/{patient_id}/system-status

PATCH  /api/v1/alerts/{alert_id}/acknowledge
PATCH  /api/v1/alerts/{alert_id}/resolve

POST   /api/v1/tasks/{task_id}/results
PATCH  /api/v1/tasks/{task_id}/cancel

GET    /api/v1/questionnaires/templates
POST   /api/v1/questionnaires/templates
GET    /api/v1/questionnaires/patients/{patient_id}/schedules
POST   /api/v1/questionnaires/patients/{patient_id}/schedules
PATCH  /api/v1/questionnaires/schedules/{schedule_id}/suspend
POST   /api/v1/questionnaires/schedules/{schedule_id}/generate-due-task
GET    /api/v1/questionnaires/patients/{patient_id}/results

POST   /api/v1/admin/patients
POST   /api/v1/admin/users
POST   /api/v1/admin/users/{user_id}/patients/{patient_id}
```

Gli endpoint notifiche push e stato app paziente saranno completati nel blocco FCM/app.

## Auth

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
    "email": "medico.demo@example.invalid",
    "role": "doctor",
    "display_name": "Medico Demo",
    "last_login_at": "2026-07-13T10:00:00Z"
  }
}
```

### Refresh

```text
POST /api/v1/auth/refresh
```

Request:

```json
{
  "refresh_token": "opaque-refresh-token"
}
```

Response:

```json
{
  "access_token": "new-jwt-access-token",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "user_id": "user-1",
    "email": "medico.demo@example.invalid",
    "role": "doctor",
    "display_name": "Medico Demo"
  }
}
```

Il refresh token e' opaco. Il backend salva solo il suo hash.

### Logout e revoca sessione

```text
POST /api/v1/auth/logout
POST /api/v1/auth/sessions/revoke
```

Entrambi ricevono:

```json
{
  "refresh_token": "opaque-refresh-token"
}
```

## Pazienti

### Lista pazienti

```text
GET /api/v1/patients?page=1&page_size=20
```

Response:

```json
{
  "items": [
    {
      "patient_id": "patient-001",
      "display_name": "Paziente Demo",
      "last_update": "2026-07-13T10:00:00Z",
      "level": "green",
      "signal_type": "routine",
      "current_room": "kitchen",
      "edge_online": true,
      "watch_present": true,
      "has_open_alerts": false
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

### Stato corrente

```text
GET /api/v1/patients/{patient_id}/current
```

Response minima:

```json
{
  "patient_id": "patient-001",
  "edge_id": "edge-rpi5-001",
  "last_update": "2026-07-13T10:00:00Z",
  "level": "green",
  "signal_type": "routine",
  "should_publish": false,
  "anomaly_score": 0.0,
  "ai_explanation": {
    "previous_score": 40.0,
    "score_delta": 32.5,
    "score_direction": "aumento",
    "updated_at": "2026-07-13T10:00:00Z",
    "model_label": "generic_wearable_anomaly_only",
    "data_reliability": {
      "level": "media",
      "ratio": 0.58,
      "available_features": 7,
      "expected_features": 11,
      "imputed_features": 2,
      "quality_status": "warning"
    },
    "positive_factors": [
      {
        "feature": "heart_rate_mean",
        "label": "Frequenza cardiaca media",
        "unit": "bpm",
        "value": 82.0,
        "model_value": 82.0,
        "impact": 2.1,
        "direction": "above_training",
        "direction_label": "Piu' alto del riferimento",
        "imputed": false,
        "model": "generic_wearable"
      }
    ],
    "negative_factors": [],
    "missing_or_imputed_features": [
      {
        "feature": "steps",
        "label": "Passi",
        "unit": "",
        "status": "imputed"
      }
    ],
    "message": "Supporto al triage: la decisione finale resta al medico."
  },
  "current_room": "kitchen",
  "watch": {
    "present": true,
    "battery_pct": 72,
    "available_features": ["heart_rate_mean", "hrv_rmssd", "spo2_mean"]
  },
  "edge": {
    "online": true,
    "quality_status": "ok",
    "mqtt_queue_depth": 0
  }
}
```

### Finestre e decisioni

```text
GET /api/v1/patients/{patient_id}/windows?limit=12
GET /api/v1/patients/{patient_id}/decisions?limit=8
```

Supportano anche filtri temporali `date_from` e `date_to`.

### Stato tecnico e baseline

```text
GET /api/v1/patients/{patient_id}/system-status
```

Response minima:

```json
{
  "patient_id": "patient-001",
  "updated_at": "2026-07-13T10:00:00Z",
  "mode": "routine",
  "edge": {
    "online": true,
    "quality_status": "ok",
    "quality_issue_count": 0,
    "quality_error_count": 0,
    "quality_warning_count": 0,
    "mqtt_queue_depth": 0,
    "last_seen_at": "2026-07-13T10:00:00Z",
    "last_cycle_at": "2026-07-13T10:00:00Z",
    "cycle_status": "cycle_completed",
    "window_start": "2026-07-13T09:56:00Z",
    "window_end": "2026-07-13T10:00:00Z",
    "window_minutes": 4,
    "mqtt": {
      "enabled": true,
      "status": "published",
      "attempted": 3,
      "published": 3,
      "queued": 0,
      "queue_depth": 0,
      "errors": []
    }
  },
  "ai": {
    "fusion_mode": "generic_spatial_plus_generic_wearable",
    "inference": "completed_generic_spatial_plus_generic_wearable",
    "personal_model_available": false,
    "baseline": {
      "available": true,
      "status": "collecting",
      "started_at": "2026-07-12T09:11:33Z",
      "planned_days": 7,
      "target_end_at": "2026-07-19T09:11:33Z",
      "accepted_windows": 320,
      "rejected_windows": 12,
      "min_training_windows": 1000,
      "ready_by_time": false,
      "trained": false,
      "reason": "baseline_not_ready"
    }
  },
  "sensors": {
    "watch": {
      "status": "active",
      "present": true,
      "battery_pct": 72,
      "last_seen_at": "2026-07-13T10:00:00Z"
    },
    "ble": {
      "status": "active",
      "current_room": "kitchen",
      "last_seen_at": "2026-07-13T10:00:00Z",
      "samples_collected": 12
    },
    "google_health": {
      "status": "active",
      "enabled": true,
      "samples_logged": true,
      "available_feature_count": 3,
      "available_features": ["heart_rate_mean", "hrv_rmssd", "spo2_mean"],
      "last_window_at": "2026-07-13T10:00:00Z",
      "oauth_error": null
    }
  }
}
```

Il blocco `ai.baseline` deriva dall'ultimo messaggio MQTT `edge/status`. Se il backend
non ha ancora ricevuto uno stato Edge con baseline, `available` puo' essere `false` e i
campi di avanzamento possono essere `null`.

I campi `edge.mqtt.errors` e `sensors.google_health.oauth_error` devono contenere solo
messaggi ripuliti. Non devono mai includere token OAuth, refresh token, password,
`client_secret` o header `Authorization`.

## Alert

### Lista alert paziente

```text
GET /api/v1/patients/{patient_id}/alerts?level=red&status=new&page=1&page_size=20
```

Response item:

```json
{
  "alert_id": "alert-1",
  "patient_id": "patient-001",
  "level": "red",
  "status": "new",
  "category": "behavioral",
  "source": "ai",
  "clinical_severity": "red",
  "technical_severity": null,
  "escalated": false,
  "escalated_at": null,
  "title": "Allarme Edge red",
  "description": "Allarme severo confermato da piu modelli.",
  "opened_at": "2026-07-13T10:00:00Z",
  "closed_at": null,
  "anomaly_score": null,
  "acknowledged_at": null,
  "acknowledged_by": null,
  "acknowledged_role": null,
  "resolved_at": null,
  "resolved_by": null,
  "resolved_role": null,
  "resolution_note": null,
  "message_id": "alert-from-decision-demo"
}
```

### Presa in carico

```text
PATCH /api/v1/alerts/{alert_id}/acknowledge
```

Request:

```json
{
  "note": "Alert preso in carico per verifica."
}
```

Response: payload alert aggiornato.

### Risoluzione

```text
PATCH /api/v1/alerts/{alert_id}/resolve
```

Request:

```json
{
  "note": "Controllo completato, nessuna azione ulteriore richiesta."
}
```

La nota e' obbligatoria. Response: payload alert aggiornato.

## Task

Tipi ammessi:

```text
check_in
cognitive_test
mobility_test
medication_reminder
custom
```

Stati possibili:

```text
created
completed
expired
cancelled
```

Gli stati `sent` e `seen` saranno aggiunti soltanto quando verra' completato il flusso
app/notifiche push. Nel backend D5-D9 il ciclo task operativo e' `created`,
`completed`, `expired` o `cancelled`.

Destinatari ammessi:

```text
patient
caregiver
```

### Creazione task

```text
POST /api/v1/patients/{patient_id}/tasks
```

Request:

```json
{
  "type": "check_in",
  "schema_version": 1,
  "priority": "normal",
  "assigned_to": "patient",
  "expires_at": "2026-07-13T18:00:00Z",
  "title": "Controllo benessere",
  "instructions": "Rispondi a queste brevi domande.",
  "medical_note": "Task dimostrativo di triage.",
  "payload": {
    "questions": [
      {
        "id": "q1",
        "type": "single_choice",
        "text": "Come ti senti adesso?",
        "options": ["bene", "cosi_cosi", "male"]
      }
    ]
  },
  "scoring": null
}
```

Response:

```json
{
  "task_id": "task-1",
  "patient_id": "patient-001",
  "status": "created",
  "type": "check_in",
  "schema_version": 1,
  "priority": "normal",
  "assigned_to": "patient",
  "title": "Controllo benessere",
  "instructions": "Rispondi a queste brevi domande.",
  "medical_note": "Task dimostrativo di triage.",
  "due_at": "2026-07-13T18:00:00Z",
  "expires_at": "2026-07-13T18:00:00Z",
  "payload": {},
  "scoring": null,
  "created_at": "2026-07-13T10:00:00Z"
}
```

Per un follow-up da alert la dashboard usa:

```json
{
  "type": "custom",
  "priority": "high",
  "title": "Follow-up Priorita alta",
  "payload": {
    "workflow": "alert_follow_up",
    "source_alert_id": "alert-1"
  }
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
  "started_at": "2026-07-13T10:05:00Z",
  "completed_at": "2026-07-13T10:07:10Z",
  "answers": [
    {
      "question_id": "q1",
      "value": "bene"
    }
  ],
  "duration_seconds": 130,
  "device_info": {
    "platform": "android",
    "app_version": "1.0.0"
  },
  "note": "Compilato dal paziente."
}
```

Response:

```json
{
  "result_id": "result-1",
  "task_id": "task-1",
  "patient_id": "patient-001",
  "status": "received",
  "completed_at": "2026-07-13T10:07:10Z",
  "duration_seconds": 130,
  "score": null,
  "score_details": null,
  "answers": [],
  "result_type": "check_in",
  "content": {},
  "note": "Compilato dal paziente.",
  "device_info": {},
  "received_at": "2026-07-13T10:07:11Z"
}
```

### Annullamento task

```text
PATCH /api/v1/tasks/{task_id}/cancel
```

Request:

```json
{
  "note": "Task non piu necessario."
}
```

## WebSocket

Endpoint:

```text
WS /ws/v1/patients/{patient_id}?token=<access_token>
```

La connessione viene accettata solo se:

- il token e' valido;
- l'utente puo' leggere quel paziente.

Il client puo' inviare testo semplice:

```text
ping
```

Il backend risponde con evento `pong`.

Formato evento:

```json
{
  "event_type": "decision_updated",
  "event_id": "event-001",
  "patient_id": "patient-001",
  "timestamp": "2026-07-13T10:00:00Z",
  "payload": {}
}
```

Eventi supportati:

```text
system_status_updated
decision_updated
alert_created
alert_acknowledged
alert_resolved
task_created
task_completed
task_cancelled
questionnaire_completed
pong
```

## Questionari programmabili

I questionari sono definiti tramite template versionati e possono essere programmati per
un paziente. Ogni invio genera comunque un task concreto, quindi app paziente e dashboard
continuano a usare il flusso task gia' esistente.

### Creazione template

```text
POST /api/v1/questionnaires/templates
```

Request:

```json
{
  "template_key": "daily_checkin",
  "title": "Check-in quotidiano",
  "description": "Breve controllo sullo stato percepito.",
  "task_type": "check_in",
  "questions": [
    {
      "id": "mood",
      "type": "scale",
      "text": "Come ti senti oggi?",
      "min": 0,
      "max": 10
    },
    {
      "id": "dizziness",
      "type": "yes_no",
      "text": "Hai avuto capogiri?"
    },
    {
      "id": "sleep",
      "type": "single_choice",
      "text": "Hai dormito bene?",
      "options": ["bene", "cosi_cosi", "male"]
    }
  ],
  "scoring": {
    "type": "scale_average",
    "question_ids": ["mood"]
  }
}
```

Tipi domanda supportati:

```text
yes_no
scale
single_choice
text
```

### Programmazione

```text
POST /api/v1/questionnaires/patients/{patient_id}/schedules
```

Request:

```json
{
  "template_id": "template-1",
  "frequency": "daily",
  "interval": 1,
  "next_run_at": "2026-07-16T08:00:00Z",
  "payload_overrides": {
    "task_due_hours": 12
  }
}
```

### Generazione task dovuto

```text
POST /api/v1/questionnaires/schedules/{schedule_id}/generate-due-task
```

Response:

```json
{
  "status": "generated",
  "schedule": {
    "schedule_id": "schedule-1",
    "patient_id": "patient-001",
    "status": "active",
    "frequency": "daily",
    "next_run_at": "2026-07-17T08:00:00Z",
    "last_task_id": "task-12"
  },
  "task": {
    "task_id": "task-12",
    "patient_id": "patient-001",
    "status": "created",
    "type": "check_in",
    "title": "Check-in quotidiano"
  }
}
```

Se il task e' gia' stato generato nello stesso periodo, il backend restituisce
`already_generated` e il riferimento al task esistente.

### Storico risultati

```text
GET /api/v1/questionnaires/patients/{patient_id}/results
```

Response item:

```json
{
  "result_id": "result-1",
  "task_id": "task-12",
  "patient_id": "patient-001",
  "template_key": "daily_checkin",
  "template_version": 1,
  "schedule_id": "schedule-1",
  "title": "Check-in quotidiano",
  "completed_at": "2026-07-16T08:03:00Z",
  "duration_seconds": 120,
  "score": 7.0,
  "score_details": {
    "type": "scale_average",
    "score": 7.0,
    "count": 1
  },
  "answers": [
    {
      "question_id": "mood",
      "value": 7
    }
  ]
}
```

## OpenAPI

Il file OpenAPI generato dal backend e' versionato qui:

```text
Documenti/contracts/openapi.json
```

Rigenerazione:

```powershell
cd cloud/backend
.\.venv\Scripts\python.exe -m scripts.export_openapi
```

## Estensione companion Android E10

L'identita' paziente non viene accettata sulla fiducia dal client. Ogni endpoint usa il
bearer token e verifica l'associazione `patient_users` prima di leggere o modificare i
dati.

```text
PATCH /api/v1/tasks/{task_id}/state
GET   /api/v1/notifications?patient_id={patient_id}
PATCH /api/v1/notifications/{notification_id}/seen
POST  /api/v1/notifications/devices/register
POST  /api/v1/notifications/devices/status
```

Payload stato task:

```json
{
  "state": "started",
  "occurred_at": "2026-07-14T10:01:00Z",
  "device_id": "android-uuid"
}
```

Payload registrazione device:

```json
{
  "patient_id": "patient-001",
  "device_id": "android-uuid",
  "platform": "android",
  "app_version": "0.2.0",
  "fcm_token": "valore-riservato",
  "notifications_enabled": true
}
```

La risposta espone soltanto `fcm_registered: true/false` e non restituisce il token.
