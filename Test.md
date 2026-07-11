# Test completo D1-D4 ed E1-E4

Questo file contiene una procedura ordinata per verificare la prima versione del sistema:

```text
Cloud Daniel D1-D4
Edge/MQTT Emilio E1
Mock backend E2
Dashboard medico E3-E4
```

L'obiettivo e' avere una prima inquadratura end-to-end: broker MQTT, backend Cloud,
database, publisher Edge, mock frontend e dashboard funzionanti.

## 0. Prerequisiti

Sul PC devono essere disponibili:

```text
Python 3.11 o superiore
Node.js 20 o superiore
Docker Desktop avviato
Git
PowerShell
```

Tutti i comandi partono dalla root del progetto:

```powershell
cd "C:\Users\emili\OneDrive\Desktop\Secondo Semestre\IoT\Progetto IoT 2026"
```

Controllare di essere nella cartella giusta:

```powershell
Get-ChildItem
```

Dovresti vedere almeno:

```text
cloud
edge_node
Dashboard
mock_backend
Script
Documenti
```

## 1. Preparare gli ambienti Python e Node

### 1.1 Ambiente Python principale

Questo ambiente serve per Edge Node, mock backend e test locali.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r edge_node\requirements.txt
.\.venv\Scripts\pip.exe install -r mock_backend\requirements.txt
```

Verifica:

```powershell
.\.venv\Scripts\python.exe -m pytest --version
```

Output atteso:

```text
pytest ...
```

### 1.2 Ambiente Python backend Cloud

Il backend reale di Daniel ha un suo `.venv` separato dentro `cloud/backend`.

```powershell
cd cloud\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
cd ..\..
```

### 1.3 Dipendenze dashboard React

```powershell
cd Dashboard
npm install
npm run build
cd ..
```

Output atteso:

```text
build completata
```

## 2. Preparare configurazioni locali e segreti

I file reali `.env`, password e certificati non devono andare su Git.

### 2.1 Creare `.env` Cloud

```powershell
Copy-Item cloud\.env.example cloud\.env -Force
Copy-Item cloud\backend\.env.example cloud\backend\.env -Force
```

Aprire `cloud\.env` e sostituire i placeholder:

```text
POSTGRES_PASSWORD=...
MQTT_EDGE_PASSWORD=...
MQTT_BACKEND_PASSWORD=...
MQTT_TEST_PASSWORD=...
IOT_BACKEND_MQTT_PASSWORD=...
IOT_BACKEND_DATABASE_URL=postgresql+psycopg://iot_backend:<POSTGRES_PASSWORD>@localhost:5432/progetto_iot
```

Importante: per i test locali puoi usare password semplici, ma devono combaciare con gli
utenti Mosquitto creati nel passaggio successivo.

### 2.2 Generare certificati TLS MQTT locali

```powershell
New-Item -ItemType Directory -Force cloud\mqtt\certs | Out-Null

docker run --rm `
  -v ${PWD}\cloud\mqtt\certs:/certs `
  alpine/openssl req -x509 -newkey rsa:2048 -days 365 -nodes `
  -keyout /certs/server.key `
  -out /certs/server.crt `
  -subj "/CN=localhost" `
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

Copy-Item cloud\mqtt\certs\server.crt cloud\mqtt\certs\ca.crt -Force

docker run --rm `
  -v ${PWD}\cloud\mqtt\certs:/certs `
  alpine chmod 644 /certs/ca.crt /certs/server.crt /certs/server.key
```

Verifica:

```powershell
Get-ChildItem cloud\mqtt\certs
```

Devono esistere:

```text
ca.crt
server.crt
server.key
```

### 2.3 Creare utenti Mosquitto

Sostituire le password con quelle scelte in `cloud\.env`.

```powershell
docker run --rm `
  -v ${PWD}\cloud\mqtt:/mosquitto/config `
  eclipse-mosquitto:2.0 `
  mosquitto_passwd -b -c /mosquitto/config/passwd edge_patient_001 PASSWORD_EDGE

docker run --rm `
  -v ${PWD}\cloud\mqtt:/mosquitto/config `
  eclipse-mosquitto:2.0 `
  mosquitto_passwd -b /mosquitto/config/passwd backend PASSWORD_BACKEND

docker run --rm `
  -v ${PWD}\cloud\mqtt:/mosquitto/config `
  eclipse-mosquitto:2.0 `
  mosquitto_passwd -b /mosquitto/config/passwd mqtt_test PASSWORD_TEST
```

Verifica:

```powershell
Test-Path cloud\mqtt\passwd
```

Output atteso:

```text
True
```

## 3. Test Daniel D1 - Broker MQTT

D1 verifica Mosquitto, TLS, WSS, utenti, ACL, retained policy e Last Will.

### 3.1 Avviare MQTT

```powershell
cd cloud
docker compose up -d mqtt
docker compose ps
cd ..
```

Output atteso:

```text
iot-mqtt ... running
```

### 3.2 Test automatico MQTT locale

Lo script legge le password da `cloud\.env`.

```powershell
.\Script\test\test_mqtt_local.ps1
```

Output atteso:

```text
Test 1 - edge publish allowed on patient-001
Test 2 - edge publish denied/not delivered on patient-999
Test 3 - backend command is received by edge
Test 4 - Last Will is published on unexpected edge disconnect
Test 5 - MQTT over TLS works on 8883
Test 6 - MQTT over secure WebSockets handshake works on 9001
Test 7 - retained policy keeps only current status retained
All local MQTT tests passed.
```

Se fallisce qui, non andare avanti: prima sistemare certificati, `passwd`, `.env` o Docker.

## 4. Test Daniel D2 - Backend FastAPI base

### 4.1 Avviare backend reale

Terminale dedicato:

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Lasciare questo terminale aperto.

### 4.2 Verificare health, ready e OpenAPI

In un secondo terminale dalla root:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-RestMethod http://127.0.0.1:8080/ready
Invoke-WebRequest http://127.0.0.1:8080/openapi.json
```

Output atteso:

```text
health.status = ok
ready.status = ready
openapi.json HTTP 200
```

Aprire anche:

```text
http://127.0.0.1:8080/docs
```

Nota: per ora molte route REST reali sono placeholder. Questo e' normale finche' Daniel
non completa D5 e D6.

## 5. Test Daniel D3 - PostgreSQL e migrazioni

### 5.1 Avviare PostgreSQL

```powershell
cd cloud
docker compose up -d postgres
docker compose ps
cd ..
```

Attendere che `iot-postgres` sia `healthy`.

### 5.2 Applicare migrazioni Alembic

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
cd ..\..
```

Output atteso:

```text
Running upgrade ... initial_schema
```

### 5.3 Controllare tabelle

```powershell
cd cloud
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "\dt"
cd ..
```

Devono comparire tabelle come:

```text
users
patients
edge_devices
edge_cycles
feature_windows
decisions
alerts
tasks
task_results
notifications
```

## 6. Test Daniel D4 - Subscriber MQTT e ingestione

D4 verifica che il backend legga messaggi MQTT e li salvi nel database.

### 6.1 Test automatico completo MQTT -> backend -> PostgreSQL

```powershell
.\Script\test\test_backend_mqtt_ingest.ps1
```

Output atteso:

```text
Backend MQTT integration test passed.
```

Lo script fa tutto:

```text
avvia mqtt e postgres
applica Alembic
avvia app.mqtt.worker
pubblica window, decision e alert
controlla che siano salvati in PostgreSQL
```

### 6.2 Controllo manuale opzionale DB

```powershell
cd cloud
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, created_at from feature_windows order by created_at desc limit 5;"
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, level, created_at from decisions order by created_at desc limit 5;"
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, level, status, created_at from alerts order by created_at desc limit 5;"
cd ..
```

## 7. Test Emilio E1 - Publisher MQTT Edge

E1 verifica che il Raspberry/Edge pubblichi gli output locali su MQTT senza rompere il
ciclo locale.

### 7.1 Preparare `edge_node/config/edge.yml`

Se non esiste:

```powershell
Copy-Item edge_node\config\edge.example.yml edge_node\config\edge.yml -Force
```

Aprire `edge_node\config\edge.yml` e nella sezione `mqtt` impostare:

```yaml
mqtt:
  enabled: true
  host: localhost
  port: 8883
  use_tls: true
  username: edge_patient_001
  password: ""
  password_env: MQTT_EDGE_PASSWORD
  client_id: edge-rpi5-001
  edge_id: edge-rpi5-001
  ca_file: ../cloud/mqtt/certs/ca.crt
  queue_dir: data/state/mqtt_queue
```

Nel terminale impostare la password Edge scelta in `cloud\.env`:

```powershell
$env:MQTT_EDGE_PASSWORD="PASSWORD_EDGE"
```

### 7.2 Test unitari Edge MQTT

```powershell
cd edge_node
..\.venv\Scripts\python.exe -m pytest tests\test_edge_mqtt.py
cd ..
```

Output atteso:

```text
3 passed
```

### 7.3 Generare payload MQTT senza pubblicare

Serve per verificare topic, QoS, `message_id`, `schema_version` e conversione `nan -> null`.

```powershell
cd edge_node
..\.venv\Scripts\python.exe -m edge_mqtt.cli --config config\edge.yml --dry-run
cd ..
```

Output atteso:

```text
topic iot/patients/patient-001/edge/status
topic iot/patients/patient-001/telemetry/window
topic iot/patients/patient-001/telemetry/decision
eventuale topic iot/patients/patient-001/alerts/critical solo se should_publish=true
```

### 7.4 Pubblicare davvero su MQTT

Assicurarsi che il broker sia attivo:

```powershell
cd cloud
docker compose up -d mqtt
cd ..
```

Pubblicare:

```powershell
cd edge_node
..\.venv\Scripts\python.exe -m edge_mqtt.cli --config config\edge.yml
cd ..
```

Output atteso:

```text
published >= 1
status published oppure queued_flushed
errors vuoto
```

Se il broker e' spento, il publisher non deve bloccare il sistema: deve accodare su disco
in `edge_node/data/state/mqtt_queue`.

## 8. Test Emilio E1 con Cloud reale Daniel

Questo passaggio collega Edge Publisher e backend subscriber.

### 8.1 Avviare servizi Cloud

```powershell
cd cloud
docker compose up -d mqtt postgres
cd ..\cloud\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

### 8.2 Avviare subscriber backend

Terminale dedicato:

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m app.mqtt.worker
```

Lasciare aperto.

### 8.3 Pubblicare dal modulo Edge

In un altro terminale:

```powershell
cd edge_node
$env:MQTT_EDGE_PASSWORD="PASSWORD_EDGE"
..\.venv\Scripts\python.exe -m edge_mqtt.cli --config config\edge.yml
cd ..
```

### 8.4 Verificare salvataggio su PostgreSQL

```powershell
cd cloud
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, created_at from edge_cycles order by created_at desc limit 3;"
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, created_at from feature_windows order by created_at desc limit 3;"
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, level, created_at from decisions order by created_at desc limit 3;"
cd ..
```

Output atteso:

```text
almeno una riga recente sulle tabelle corrispondenti
```

## 9. Test Edge runtime locale con comando unico

Questo test controlla il comando che poi useremo sul Raspberry Pi 5:

```text
receiver Android/BLE + runtime ogni 4 minuti + baseline automatica + MQTT se abilitato
```

### 9.1 Avvio singolo stack Edge

Terminale dedicato:

```powershell
.\Script\avvio\avviaSistema.ps1
```

Output atteso:

```text
EDGE-STACK: Avvio stack IoT edge
EDGE-STACK: Receiver: http://0.0.0.0:8000
EDGE-STACK: Runtime loop: ogni 240 secondi
EDGE-STACK: Baseline automatica: attiva
INFO: Uvicorn running on http://0.0.0.0:8000
INFO: Edge runtime loop started
```

### 9.2 Verificare file locali prodotti

Dopo almeno un ciclo:

```powershell
Get-Content edge_node\data\processed\latest_window.csv
Get-Content edge_node\outputs\last-cycle.json
Get-Content edge_node\outputs\patient-001-decision.json
Get-Content edge_node\outputs\last-quality-report.json
```

Output atteso:

```text
latest_window.csv contiene una finestra da 4 minuti
last-cycle.json status cycle_completed
patient-001-decision.json level green/yellow/orange/red/technical
last-quality-report.json status ok/warning/error
```

### 9.3 Stop

Nel terminale dello stack:

```text
CTRL+C
```

## 10. Test Emilio E2 - Mock backend

E2 serve per sviluppare la Dashboard anche quando il backend reale di Daniel non ha
ancora D5/D6 completi.

### 10.1 Avviare mock backend

Terminale dedicato:

```powershell
cd mock_backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

Lasciare aperto.

### 10.2 Verificare health e pazienti

In un altro terminale:

```powershell
Invoke-RestMethod http://127.0.0.1:8090/health
Invoke-RestMethod http://127.0.0.1:8090/api/v1/patients
```

Output atteso:

```text
health.status = ok
lista con 5 pazienti: green, yellow, orange, red, technical
```

### 10.3 Test scenari mock

Chiudere e riavviare il mock cambiando scenario:

```powershell
$env:MOCK_SCENARIO="normal"
cd mock_backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8090
```

Scenari disponibili:

```powershell
$env:MOCK_SCENARIO="normal"
$env:MOCK_SCENARIO="severe_alert"
$env:MOCK_SCENARIO="technical_issue"
$env:MOCK_SCENARIO="missing_data"
```

Per tornare allo scenario normale:

```powershell
Remove-Item Env:\MOCK_SCENARIO -ErrorAction SilentlyContinue
```

## 11. Test Emilio E3-E4 - Dashboard medico

### 11.1 Avviare dashboard

Terminale dedicato:

```powershell
cd Dashboard
npm run dev
```

Aprire:

```text
http://127.0.0.1:5173
```

Credenziali demo:

```text
doctor@example.test
password-demo
```

### 11.2 Test E3 - Struttura navigabile

Verificare:

```text
login funzionante
sidebar pazienti visibile
tab Paziente
tab Alert
tab Task
tab Sistema
stato WebSocket visibile
refresh manuale con pulsante
logout funzionante
```

### 11.3 Test E4 - Overview e lista pazienti

Verificare:

```text
overview superiore con monitorati, alta priorita, tecnici, obsoleti
lista pazienti con semaforo green/yellow/orange/red/technical
ordinamento Severita
ordinamento Update
filtro Tutti
filtro Comportamentali
filtro Tecnici
filtro Obsoleti
click su paziente senza perdere filtro e ordinamento
stanza corrente visibile
watch ok/assente visibile
edge online/offline visibile
segnale comportamentale separato da guasto tecnico
dati obsoleti evidenziati
```

Pazienti mock utili:

```text
Paziente Demo        -> green / routine
Paziente Osservazione -> yellow / segnale comportamentale
Paziente Rientro     -> orange / segnale comportamentale
Paziente Priorita    -> red / segnale comportamentale
Paziente Tecnico     -> technical / guasto tecnico
```

### 11.4 Build finale Dashboard

```powershell
cd Dashboard
npm run build
cd ..
```

Output atteso:

```text
build completata
```

## 12. Test automatici disponibili

Da root progetto:

```powershell
.\.venv\Scripts\python.exe -m pytest edge_node\tests
.\.venv\Scripts\python.exe -m pytest mock_backend\tests
```

Da backend Cloud:

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m pytest
cd ..\..
```

Output atteso:

```text
passed
```

Se un test dice `No module named pytest`, reinstallare:

```powershell
.\.venv\Scripts\pip.exe install pytest
cd cloud\backend
.\.venv\Scripts\pip.exe install pytest
cd ..\..
```

## 13. Sequenza rapida consigliata per demo locale

Questa e' la sequenza piu' comoda per vedere tutto senza rifare ogni volta la preparazione.

### Terminale 1 - Docker Cloud

```powershell
cd cloud
docker compose up -d mqtt postgres
cd ..
```

### Terminale 2 - Backend Cloud reale

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

### Terminale 3 - Subscriber MQTT reale

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m app.mqtt.worker
```

### Terminale 4 - Edge completo

```powershell
$env:MQTT_EDGE_PASSWORD="PASSWORD_EDGE"
.\Script\avvio\avviaSistema.ps1
```

### Terminale 5 - Mock backend per dashboard

Finche' D5/D6 non sono completi, la dashboard usa il mock:

```powershell
cd mock_backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

### Terminale 6 - Dashboard

```powershell
cd Dashboard
npm run dev
```

Aprire:

```text
Dashboard mock: http://127.0.0.1:5173
Backend reale Daniel: http://127.0.0.1:8080/docs
Mock backend: http://127.0.0.1:8090/docs
```

Nota importante:

```text
La Dashboard usa ancora mock_backend finche' Daniel non completa D5 REST e D6 WebSocket.
Il Cloud reale D1-D4 si testa invece tramite MQTT, subscriber e database.
```

## 14. Quando D5 e D6 saranno pronti

Quando Daniel completa REST e WebSocket reali, modificare la Dashboard per puntare al
backend reale.

Creare o modificare `Dashboard\.env`:

```text
VITE_API_BASE_URL=http://127.0.0.1:8080/api/v1
VITE_WS_BASE_URL=ws://127.0.0.1:8080/ws/v1
VITE_DATA_SOURCE=real
```

Riavviare Vite:

```powershell
cd Dashboard
npm run dev
```

Da quel momento il mock backend puo' restare come strumento di sviluppo, ma non sara'
piu' il backend principale della dashboard.

## 15. Pulizia dopo i test

Fermare Docker:

```powershell
cd cloud
docker compose down
cd ..
```

Fermare eventuali processi manuali con `CTRL+C`.

Pulire build frontend se serve:

```powershell
Remove-Item Dashboard\dist -Recurse -Force -ErrorAction SilentlyContinue
```

Non cancellare:

```text
cloud\.env
cloud\backend\.env
cloud\mqtt\passwd
cloud\mqtt\certs
edge_node\config\edge.yml
edge_node\models
```

Sono file locali necessari ai test reali e non devono essere versionati su Git.
