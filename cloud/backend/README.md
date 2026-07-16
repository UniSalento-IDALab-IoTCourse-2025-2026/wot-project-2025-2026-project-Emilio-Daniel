# Cloud Backend

Backend FastAPI unico per dashboard medico, app paziente, caregiver e integrazione MQTT.

## Scopo

Questa cartella contiene il backend Cloud del progetto. Al momento copre i blocchi D2,
D3, D4, D5, D6, D7, D8, D9, D13, D14, D15, D16, D17, D18 e D19 della scaletta di Daniel:

```text
MQTT broker -> backend -> database -> dashboard/app
```

Stato attuale:

```text
D2 -> struttura FastAPI, health/ready, OpenAPI, errori e log
D3 -> PostgreSQL, SQLAlchemy models, Alembic migrations e test schema
D4 -> subscriber MQTT, validazione payload Edge e ingestione nel database
D5 -> API REST reali per dashboard e app
D6 -> WebSocket realtime verso dashboard
D7 -> autenticazione, autorizzazione per ruolo e audit
D8 -> logica alert, presa in carico e alert automatici da decisioni AI
D9 -> task clinici, risultati, scadenze e scoring controllato
D13 -> riepilogo aggregato ultime 24 ore
D14 -> timeline normalizzata del paziente
D15 -> template questionari, programmazioni e storico punteggi
D16 -> dettaglio alert composto e workflow operativo
D17 -> aggregazioni spaziali BLE e confronto con riferimento/baseline
D18 -> spiegazioni AI normalizzate
D19 -> validazione check-in brevi e evento questionnaire_completed
```

Estensioni completate su D5-D8:

```text
API admin -> utenti, pazienti e associazioni
Auth avanzata -> me, cambio password, revoca sessioni, last_login_at, rate limit
WebSocket -> ping/pong applicativo
Alert -> anti-spam, source, severita' clinica/tecnica, escalation
```

## Struttura

```text
cloud/backend/
  app/
    main.py
    api/
      router.py
      routes/
        auth.py
        patients.py
        telemetry.py
        alerts.py
        tasks.py
        questionnaires.py
        notifications.py
        realtime.py
        health.py
    core/
      config.py
      errors.py
      logging.py
    auth/
      security.py
      dependencies.py
    db/
      base.py
      models.py
      session.py
    mqtt/
      client.py
      events.py
      ingest.py
      schemas.py
      topics.py
      worker.py
    schemas/
    services/
  alembic/
    env.py
    versions/
      20260710_0001_initial_schema.py
      20260712_0002_auth_audit.py
  scripts/
    export_openapi.py
  tests/
    test_database_schema.py
    test_d5_api.py
    test_d6_realtime.py
    test_d7_auth.py
    test_health.py
    test_mqtt_ingest.py
  alembic.ini
  requirements.txt
```

## Avvio locale

Se serve anche il database reale locale, avviare prima PostgreSQL e applicare le
migrazioni:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud
docker compose up -d postgres

cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend
.\.venv\Scripts\python -m alembic upgrade head
```

Poi avviare il backend:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Endpoint:

```text
http://127.0.0.1:8080/health
http://127.0.0.1:8080/ready
http://127.0.0.1:8080/docs
http://127.0.0.1:8080/openapi.json
```

Endpoint dashboard/app principali:

```text
POST   http://127.0.0.1:8080/api/v1/auth/login
POST   http://127.0.0.1:8080/api/v1/auth/refresh
POST   http://127.0.0.1:8080/api/v1/auth/logout
GET    http://127.0.0.1:8080/api/v1/patients
GET    http://127.0.0.1:8080/api/v1/patients/patient-001/current
GET    http://127.0.0.1:8080/api/v1/patients/patient-001/windows
GET    http://127.0.0.1:8080/api/v1/patients/patient-001/decisions
GET    http://127.0.0.1:8080/api/v1/patients/patient-001/alerts
GET    http://127.0.0.1:8080/api/v1/alerts/alert-1/details
GET    http://127.0.0.1:8080/api/v1/patients/patient-001/tasks
GET    http://127.0.0.1:8080/api/v1/patients/patient-001/system-status
GET    http://127.0.0.1:8080/api/v1/patients/patient-001/spatial-summary
GET    http://127.0.0.1:8080/api/v1/questionnaires/templates
GET    http://127.0.0.1:8080/api/v1/questionnaires/patients/patient-001/schedules
GET    http://127.0.0.1:8080/api/v1/questionnaires/patients/patient-001/results
WS     ws://127.0.0.1:8080/ws/v1/patients/patient-001?token=<access_token>
```

Le route REST principali richiedono:

```http
Authorization: Bearer <access_token>
```

Utenti demo locali opzionali:

```text
IOT_BACKEND_DEMO_AUTH_ENABLED=true
IOT_BACKEND_DEMO_AUTH_PASSWORD=<password locale non committata>
IOT_BACKEND_DEMO_DOCTOR_EMAIL=<email medico locale>
IOT_BACKEND_DEMO_CAREGIVER_EMAIL=<email caregiver locale>
IOT_BACKEND_DEMO_PATIENT_EMAIL=<email paziente locale>
IOT_BACKEND_DEMO_ADMIN_EMAIL=<email admin locale>
```

Gli utenti demo vengono creati solo in ambiente `development`/`test`, solo se
abilitati nel `.env` locale. Non inserire password reali nei file versionati.

## Subscriber MQTT

Il worker MQTT del backend si collega al broker, si iscrive ai topic Edge, valida i
payload e salva i messaggi nelle tabelle PostgreSQL corrette.

Avvio manuale:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend
.\.venv\Scripts\python -m app.mqtt.worker
```

Topic ascoltati:

```text
iot/patients/+/edge/status
iot/patients/+/telemetry/window
iot/patients/+/telemetry/decision
iot/patients/+/alerts/critical
iot/patients/+/sensors/watch
iot/patients/+/sensors/ble
```

Il worker rifiuta payload senza `schema_version`, `message_id`, `patient_id` o timestamp
valido; inoltre rifiuta valori mancanti scritti come stringa `"nan"`. I duplicati sono
gestiti tramite i vincoli univoci su `message_id`.

## Test

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend
.\.venv\Scripts\python -m pytest
```

I test unitari non richiedono broker MQTT o database reale. Lo schema DB, l'ingestione
MQTT e le API D5 vengono verificati con SQLite in memoria; PostgreSQL reale viene testato
applicando Alembic sul servizio Docker.

Test completo locale con broker MQTT, PostgreSQL e worker reale:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT
.\Script\test\test_backend_mqtt_ingest.ps1
```

## Esportare OpenAPI

FastAPI espone sempre OpenAPI a runtime:

```text
http://127.0.0.1:8080/openapi.json
```

Per salvare il contratto condiviso usato da dashboard e app:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend
.\.venv\Scripts\python -m scripts.export_openapi
```

Output:

```text
Documenti/contracts/openapi.json
```

## Configurazione

Le variabili usano prefisso:

```text
IOT_BACKEND_
```

Per sviluppo locale bisogna creare file `.env` locali partendo dagli esempi:

```powershell
Copy-Item C:\Users\Daniel\Desktop\ProgettoIoT\cloud\.env.example C:\Users\Daniel\Desktop\ProgettoIoT\cloud\.env
Copy-Item C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend\.env.example C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend\.env
```

I file `.env` reali sono ignorati da Git. Qui vanno inserite le password locali o reali,
mentre nel codice restano solo nomi di variabili e valori non sensibili.

Nota sicurezza: se `IOT_BACKEND_ENVIRONMENT=production`, il backend rifiuta l'avvio
quando mancano i segreti o quando trova placeholder tipo `CAMBIA_...`.

Esempi:

```powershell
$env:IOT_BACKEND_ENVIRONMENT = "development"
$env:IOT_BACKEND_LOG_LEVEL = "INFO"
$env:IOT_BACKEND_MQTT_HOST = "localhost"
$env:IOT_BACKEND_MQTT_PORT = "8883"
$env:IOT_BACKEND_MQTT_USE_TLS = "true"
$env:IOT_BACKEND_MQTT_PASSWORD = "<password-mqtt>"
$env:IOT_BACKEND_DATABASE_URL = "postgresql+psycopg://iot_backend:<password-postgres>@localhost:5432/progetto_iot"
```

## Database PostgreSQL

Avviare PostgreSQL locale:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud
docker compose up -d postgres
```

Applicare le migrazioni:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend
.\.venv\Scripts\python -m alembic upgrade head
```

Controllare le tabelle:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "\dt"
```

Backup locale:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud
New-Item -ItemType Directory -Force backups | Out-Null
docker compose exec -T postgres pg_dump -U iot_backend -d progetto_iot > backups\progetto_iot_backup.sql
```

Restore locale:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud
Get-Content backups\progetto_iot_backup.sql | docker compose exec -T postgres psql -U iot_backend -d progetto_iot
```

## Firebase Cloud Messaging

Le notifiche push reali usano Firebase Admin SDK. I segreti restano nei file `.env`
locali e nel service account JSON locale, non nel repository.

Variabili principali in `cloud/backend/.env`:

```env
IOT_BACKEND_FIREBASE_ENABLED=true
IOT_BACKEND_FIREBASE_FAKE_ENABLED=false
IOT_BACKEND_FIREBASE_CREDENTIALS_FILE=../firebase/service-account.json
IOT_BACKEND_FIREBASE_PROJECT_ID=nome-progetto-firebase
```

Il file `cloud/firebase/service-account.json` deve essere scaricato dalla console
Firebase ed e' ignorato da Git. Se Firebase non e' abilitato, il backend crea comunque
la notifica in-app ma non invia la push.

Nel progetto Firebase vanno registrate le app client:

- Android: `it.unisalento.iotedgecompanion`, con file locale
  `Applicazione IoT Companion/companion_Android_app/app/google-services.json`;
- iOS: `it.unisalento.IoTEdgeCompanionIOS`, con file locale
  `Applicazione IoT Companion/companion_iOS_app/GoogleService-Info.plist`.

Per test locali senza credenziali Firebase:

```env
IOT_BACKEND_FIREBASE_ENABLED=false
IOT_BACKEND_FIREBASE_FAKE_ENABLED=true
```

La modalita' fake registra `delivery.provider = "fake"` e non invia notifiche reali.
In `production` viene rifiutata dalla configurazione.

## Questionari programmabili

Il backend supporta template questionario e programmazioni ricorrenti. Ogni occorrenza
genera un task concreto, quindi app paziente e dashboard continuano a usare il flusso
task gia' esistente.

Endpoint principali:

```text
GET   /api/v1/questionnaires/templates
POST  /api/v1/questionnaires/templates
GET   /api/v1/questionnaires/patients/{patient_id}/schedules
POST  /api/v1/questionnaires/patients/{patient_id}/schedules
PATCH /api/v1/questionnaires/schedules/{schedule_id}/suspend
POST  /api/v1/questionnaires/schedules/{schedule_id}/generate-due-task
GET   /api/v1/questionnaires/patients/{patient_id}/results
```

Tipi domanda validati:

```text
yes_no
scale
single_choice
text
```

Quando un task questionario viene completato, il backend pubblica sia `task_completed`
sia `questionnaire_completed`, cosi' dashboard e futuro centro valutazioni possono
aggiornarsi in tempo reale.

## Stato Sistema

L'endpoint `/api/v1/patients/{patient_id}/system-status` espone stato tecnico aggregato
di Raspberry, BLE, Google Health, watch e app paziente. Le soglie stale sono configurabili:

```env
IOT_BACKEND_EDGE_STALE_MINUTES=10
IOT_BACKEND_WATCH_STALE_MINUTES=12
IOT_BACKEND_BLE_STALE_MINUTES=12
IOT_BACKEND_GOOGLE_HEALTH_STALE_MINUTES=12
IOT_BACKEND_PATIENT_APP_STALE_MINUTES=15
```

Il payload non espone token Google Health, token FCM, password o client secret.

## Routine ambientale BLE

L'endpoint:

```text
GET /api/v1/patients/{patient_id}/spatial-summary
```

aggregra i dati spaziali dei beacon/BLE per la dashboard:

- minuti per stanza;
- stanza prevalente;
- cambi stanza e transizioni stanza-stanza, se presenti nel payload Edge;
- movimenti notturni da verificare;
- permanenza continuativa massima;
- qualita' del dato BLE e finestre mancanti stimate;
- confronto con baseline spaziale se disponibile, altrimenti con il periodo precedente.

Parametri utili:

```text
days=7
date_from=2026-07-16T00:00:00Z
date_to=2026-07-17T00:00:00Z
```

## Workflow alert

L'endpoint:

```text
GET /api/v1/alerts/{alert_id}/details
```

espone una segnalazione come caso operativo completo:

- decisione AI collegata;
- finestra dati collegata;
- task creati come follow-up;
- messaggi/notifiche collegati;
- storico `alert_events`;
- azioni disponibili per ruolo e stato.

La cancellazione definitiva:

```text
DELETE /api/v1/alerts/{alert_id}
```

e' permessa solo dopo `resolve`, cosi' un alert aperto non puo' sparire senza nota di
chiusura.

## Prossimi passi

- D12: completare deployment e osservabilita' Cloud.
