# Test completo del sistema IoT

Questo file contiene la procedura ordinata e dettagliata per provare il sistema sviluppato
finora.

La procedura copre:

```text
Daniel D1-D9
broker MQTT, backend FastAPI, PostgreSQL, subscriber MQTT, REST API, WebSocket,
autenticazione, ruoli, alert e task.

Emilio E1-E8
publisher MQTT Edge, mock di supporto, dashboard medico, overview pazienti, alert,
dati wearable, dati spaziali, spiegazione AI e stato tecnico del sistema.
```

Il flusso principale da testare e':

```text
Beacon BLE + Google Watch / Google Health
-> Edge Node su PC o Raspberry Pi 5
-> aggregazione finestra ogni 4 minuti
-> inferenza AI locale
-> pubblicazione MQTT protetta da TLS
-> backend Cloud reale
-> PostgreSQL
-> Dashboard medico via REST e WebSocket
```

Il `mock_backend_per_test` resta disponibile soltanto come strumento di supporto per
sviluppo o scenari finti controllati. La dashboard, nella configurazione attuale, deve
puntare al backend reale di Daniel.

## Come leggere questo file

Ogni blocco contiene tre informazioni:

```text
Cosa fa il comando       -> effetto tecnico sul sistema
Cosa stiamo testando     -> requisito D/E verificato
Quando e' superato       -> output o comportamento atteso
```

I comandi lunghi e spiegati servono a noi durante sviluppo e debug.
Alla fine del file c'e' una sezione separata con i comandi brevi e importanti da usare
quando tutto e' gia' configurato.

Questa non e' ancora la procedura finale per il paziente. Nella versione finale il
Raspberry dovra' partire con servizi automatici, senza richiedere comandi manuali.

## Test automatici e manuali aggiunti da E21-E33

Dashboard:

```powershell
cd Dashboard
npm test
npm run build
cd ..
```

Cosa verifica:

```text
ErrorBoundary attivo
offline cache paziente
metriche modello AI
confidenza decisione
giornata tipo
brief mattino
report settimanali
diagnostica rapida
```

Test manuale demo:

```text
1. Login medico.
2. Aprire patient-001.
3. Verificare Brief del mattino e Riepilogo 24 ore.
4. Aprire Valutazione comportamentale e controllare confidenza, affidabilita' modello,
   spiegazione naturale, trend e drift.
5. Aprire Giornata tipo e cambiare metrica.
6. Aprire Stato sistema e premere Diagnostica rapida.
7. Spegnere temporaneamente il backend e ricaricare la dashboard: deve apparire la cache
   offline e le azioni operative devono essere bloccate.
8. Riaccendere backend e aggiornare.
```

Android:

```text
Seguire la checklist in:
Applicazione IoT Companion/companion_Android_app/TEST_CHECKLIST.md
```

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
Documenti
Script
mock_backend_per_test
```

I file locali da non pubblicare su Git sono:

```text
cloud\.env
cloud\backend\.env
cloud\mqtt\passwd
cloud\mqtt\certs
edge_node\config\edge.yml
```

## 1. Preparare gli ambienti Python e Node

### 1.1 Ambiente Python principale

Questo ambiente serve per:

```text
Edge Node
publisher MQTT Edge
runtime Edge
test Edge
mock backend di supporto
```

Cosa fa:

```text
crea l'ambiente Python principale del progetto
installa le librerie Edge Node
installa le librerie del mock backend di supporto
installa pytest e dipendenze locali
isola tutto dal Python globale del PC
```

Cosa stiamo testando:

```text
che il PC sia pronto a eseguire Edge Node, publisher MQTT, runtime, test e mock
```

Comandi:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r edge_node\requirements.txt
.\.venv\Scripts\pip.exe install -r mock_backend_per_test\requirements.txt
```

Verifica:

```powershell
.\.venv\Scripts\python.exe -m pytest --version
```

Quando e' superato:

```text
compare una versione di pytest
non compaiono errori di modulo mancante
```

### 1.2 Ambiente Python backend Cloud

Il backend reale di Daniel usa un ambiente separato dentro `cloud/backend`.

Cosa fa:

```text
crea l'ambiente Python dedicato al backend Cloud
installa FastAPI
installa SQLAlchemy e Alembic
installa driver PostgreSQL
installa client MQTT backend
installa librerie per auth, WebSocket e test
```

Cosa stiamo testando:

```text
che il backend reale possa essere avviato senza dipendere dall'ambiente Edge
```

Comandi:

```powershell
cd cloud\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
cd ..\..
```

Quando e' superato:

```text
l'installazione finisce senza errori
cloud/backend/.venv esiste
```

### 1.3 Dipendenze Dashboard React

Cosa fa:

```text
scarica le dipendenze Node della dashboard
installa React, Vite e lucide-react
compila il frontend in modalita produzione
verifica JSX, import e CSS
```

Cosa stiamo testando:

```text
che la Dashboard medico possa essere costruita senza errori prima di avviarla
```

Comandi:

```powershell
cd Dashboard
npm install
npm run build
cd ..
```

Quando e' superato:

```text
Vite produce la cartella dist
il comando termina con built successfully / built in ...
```

## 2. Preparare configurazioni locali e segreti

I file reali `.env`, password e certificati non devono andare su Git.

### 2.1 Creare i file `.env` solo se mancano

Cosa fa:

```text
crea i file locali partendo dagli esempi versionati
non sovrascrive file gia' configurati
lascia i segreti fuori da Git
```

Cosa stiamo testando:

```text
che Cloud, backend, MQTT e Dashboard abbiano configurazioni locali leggibili
```

Comandi:

```powershell
if (-not (Test-Path cloud\.env)) { Copy-Item cloud\.env.example cloud\.env }
if (-not (Test-Path cloud\backend\.env)) { Copy-Item cloud\backend\.env.example cloud\backend\.env }
if (-not (Test-Path Dashboard\.env)) { Copy-Item Dashboard\.env.example Dashboard\.env }
```

Aprire `cloud\.env` e controllare almeno:

```text
IOT_BACKEND_ENVIRONMENT=development
IOT_BACKEND_DEMO_AUTH_ENABLED=true
IOT_BACKEND_DEMO_AUTH_PASSWORD=<password_demo>
IOT_BACKEND_DEMO_DOCTOR_EMAIL=medico.demo@localhost.invalid

IOT_BACKEND_DATABASE_URL=postgresql+psycopg://iot_backend:<password_postgres>@localhost:5432/progetto_iot

IOT_BACKEND_MQTT_HOST=localhost
IOT_BACKEND_MQTT_PORT=8883
IOT_BACKEND_MQTT_USE_TLS=true
IOT_BACKEND_MQTT_USERNAME=backend
IOT_BACKEND_MQTT_PASSWORD=<password_backend_mqtt>
IOT_BACKEND_MQTT_CA_FILE=../mqtt/certs/ca.crt

POSTGRES_DB=progetto_iot
POSTGRES_USER=iot_backend
POSTGRES_PASSWORD=<password_postgres>
```

Aprire `Dashboard\.env` e controllare:

```text
VITE_API_BASE_URL=http://127.0.0.1:8080/api/v1
VITE_WS_BASE_URL=ws://127.0.0.1:8080/ws/v1
VITE_DATA_SOURCE=real
```

Quando e' superato:

```text
i file .env esistono
le password combaciano tra Docker, backend e Mosquitto
la dashboard punta al backend reale su porta 8080
```

### 2.2 Configurare `edge_node/config/edge.yml`

Cosa fa:

```text
prepara il file reale dell'Edge
abilita il publisher MQTT
configura broker, TLS, client_id, edge_id e coda locale
lascia la password MQTT fuori dal file usando MQTT_EDGE_PASSWORD
```

Cosa stiamo testando:

```text
che l'Edge sia pronto a pubblicare verso il broker di Daniel senza salvare segreti su Git
```

Se il file manca:

```powershell
Copy-Item edge_node\config\edge.example.yml edge_node\config\edge.yml
```

Nel blocco `mqtt` impostare:

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

Quando e' superato:

```text
edge_node/config/edge.yml esiste
mqtt.enabled e' true
la password non e' scritta nel file
```

### 2.3 Generare certificati TLS MQTT locali

Cosa fa:

```text
genera certificato e chiave locale self-signed
crea una CA locale per i test
permette a Mosquitto di accettare connessioni TLS sulla porta 8883
permette anche WebSocket sicuro sulla porta 9001
```

Cosa stiamo testando:

```text
che il broker possa lavorare in modalita simile al Cloud reale e non in chiaro
```

Comandi:

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

Quando e' superato:

```text
ca.crt esiste
server.crt esiste
server.key esiste
```

### 2.4 Creare utenti Mosquitto

Cosa fa:

```text
crea il file cloud/mqtt/passwd
aggiunge l'utente Edge
aggiunge l'utente backend
aggiunge l'utente di test
separa le credenziali tra componenti diversi
```

Cosa stiamo testando:

```text
che MQTT non usi accesso anonimo e che ogni componente abbia permessi separati
```

Sostituire le password con quelle scelte in `cloud\.env`.

Comandi:

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

Quando e' superato:

```text
True
```

Nota: su Windows il warning sul proprietario del file `passwd` e' normale nei test
locali.

## 3. Test Daniel D1 - Broker MQTT

D1 riguarda broker MQTT, TLS, WSS, utenti, ACL, Last Will e retained policy.

### 3.1 Avviare MQTT

Cosa fa:

```text
avvia il container iot-mqtt
espone MQTT locale sulla porta 1883
espone MQTT/TLS sulla porta 8883
espone MQTT over WebSocket sicuro sulla porta 9001
carica utenti, password, ACL e certificati
```

Cosa stiamo testando:

```text
D1: broker vivo, configurazione valida e container Docker avviato
```

Comandi:

```powershell
cd cloud
docker compose up -d mqtt
docker compose ps
cd ..
```

Quando e' superato:

```text
iot-mqtt risulta running
non ci sono errori nel docker compose
```

### 3.2 Test automatico MQTT locale

Cosa fa:

```text
pubblica messaggi come Edge autorizzato
prova a pubblicare su un paziente non autorizzato
verifica ricezione comandi tecnici se previsti dal test D1
simula disconnessione improvvisa dell'Edge
controlla Last Will
testa MQTT/TLS su 8883
testa WebSocket sicuro su 9001
controlla retained policy
```

Cosa stiamo testando:

```text
D1: sicurezza topic, ACL, TLS, WSS, Last Will e retained message
```

Comando:

```powershell
.\Script\test\test_mqtt_local.ps1
```

Quando e' superato:

```text
All local MQTT tests passed.
```

Se fallisce qui, non andare avanti. Prima sistemare:

```text
cloud/.env
cloud/mqtt/passwd
cloud/mqtt/certs
cloud/mqtt/mosquitto.conf
Docker Desktop
```

## 4. Test Daniel D2-D3 - Backend e PostgreSQL

### 4.1 Avviare PostgreSQL

Cosa fa:

```text
avvia il container iot-postgres
crea il database progetto_iot
crea l'utente iot_backend
espone PostgreSQL sulla porta 5432
```

Cosa stiamo testando:

```text
D3: servizio database disponibile per backend e worker MQTT
```

Comandi:

```powershell
cd cloud
docker compose up -d postgres
docker compose ps
cd ..
```

Quando e' superato:

```text
iot-postgres risulta healthy oppure running
```

### 4.2 Applicare migrazioni Alembic

Cosa fa:

```text
esegue le migrazioni del backend
crea le tabelle necessarie
aggiorna lo schema database alla versione attesa dal codice
```

Cosa stiamo testando:

```text
D3: schema PostgreSQL riproducibile e versionato
```

Comandi:

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
cd ..\..
```

Quando e' superato:

```text
Alembic termina senza errori
le tabelle sono create o gia' aggiornate
```

### 4.3 Controllare le tabelle

Cosa fa:

```text
entra nel container PostgreSQL
lista le tabelle del database progetto_iot
```

Cosa stiamo testando:

```text
che lo schema contenga utenti, pazienti, Edge, finestre, decisioni, alert e task
```

Comandi:

```powershell
cd cloud
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "\dt"
cd ..
```

Quando e' superato:

```text
compaiono tabelle come users, patients, edge_devices, edge_cycles,
feature_windows, decisions, alerts, tasks, task_results
```

### 4.4 Avviare backend reale

Cosa fa:

```text
avvia FastAPI sulla porta 8080
espone health, ready, OpenAPI e docs
carica configurazione e segreti dal file .env
abilita REST API, auth, WebSocket, alert e task
```

Cosa stiamo testando:

```text
D2, D5, D6, D7, D8, D9: backend reale avviabile e raggiungibile
```

Terminale dedicato:

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Lasciare questo terminale aperto.

In un secondo terminale:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-RestMethod http://127.0.0.1:8080/ready
Invoke-WebRequest http://127.0.0.1:8080/openapi.json
```

Aprire anche:

```text
http://127.0.0.1:8080/docs
```

Quando e' superato:

```text
/health restituisce ok
/ready restituisce ready
/openapi.json restituisce HTTP 200
/docs si apre nel browser
```

## 5. Test Daniel D4 - Subscriber MQTT e ingestione

D4 verifica che il backend legga i messaggi MQTT e li salvi su PostgreSQL.

### 5.1 Avviare subscriber MQTT backend

Cosa fa:

```text
avvia il worker MQTT del backend
si collega al broker come utente backend
si iscrive ai topic Edge
riceve finestre, decisioni, alert e stato sensori
salva i dati su PostgreSQL
```

Cosa stiamo testando:

```text
D4: backend pronto a ricevere eventi MQTT reali dall'Edge
```

Terminale dedicato:

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m app.mqtt.worker
```

Lasciare questo terminale aperto.

Quando e' superato:

```text
il worker resta in ascolto
non termina con errori di TLS, password o database
```

### 5.2 Test automatico MQTT -> backend -> PostgreSQL

Cosa fa:

```text
avvia mqtt e postgres se necessario
applica migrazioni Alembic
avvia temporaneamente il worker MQTT
pubblica messaggi di finestra, decisione e alert
verifica che i messaggi siano salvati sul database
```

Cosa stiamo testando:

```text
D4: pipeline reale MQTT -> worker backend -> validazione -> PostgreSQL
```

Comando:

```powershell
.\Script\test\test_backend_mqtt_ingest.ps1
```

Quando e' superato:

```text
Backend MQTT integration test passed.
```

### 5.3 Controllo manuale PostgreSQL

Cosa fa:

```text
interroga direttamente le tabelle scritte dal worker MQTT
mostra gli ultimi messaggi salvati
```

Cosa stiamo testando:

```text
che i messaggi siano arrivati fino al database e non solo al broker
```

Comandi:

```powershell
cd cloud
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, created_at from feature_windows order by created_at desc limit 5;"
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, level, created_at from decisions order by created_at desc limit 5;"
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, level, status, created_at from alerts order by created_at desc limit 5;"
cd ..
```

Quando e' superato:

```text
compaiono righe recenti nelle tabelle feature_windows, decisions e alerts
```

## 6. Test Daniel D5-D9 - API, WebSocket, auth, alert e task

### 6.1 Test automatici backend completi

Cosa fa:

```text
esegue tutta la suite test del backend reale
controlla API D5
controlla WebSocket D6
controlla auth e ruoli D7
controlla alert D8
controlla task D9
controlla schema database e MQTT ingest
```

Cosa stiamo testando:

```text
che il backend di Daniel sia coerente prima di collegarlo alla dashboard
```

Comandi:

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m pytest
cd ..\..
```

Quando e' superato:

```text
tutti i test passano
in precedenza la suite completa era 48 passed
```

### 6.2 Login REST manuale

Cosa fa:

```text
chiama l'endpoint login reale
ottiene access token
prepara header Authorization per chiamate successive
```

Cosa stiamo testando:

```text
D7: autenticazione reale e token Bearer
```

Comandi:

```powershell
$login = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8080/api/v1/auth/login" `
  -ContentType "application/json" `
  -Body '{"email":"medico.demo@localhost.invalid","password":"PASSWORD_DEMO"}'

$token = $login.access_token
$headers = @{ Authorization = "Bearer $token" }
```

Sostituire `PASSWORD_DEMO` con il valore di `IOT_BACKEND_DEMO_AUTH_PASSWORD` in
`cloud\.env`.

Quando e' superato:

```text
$token contiene una stringa
$login.user.role e' doctor
```

### 6.3 Endpoint principali

Cosa fa:

```text
legge pazienti, stato corrente, finestre, decisioni, alert, task e stato sistema
```

Cosa stiamo testando:

```text
D5, D8, D9: API usate dalla dashboard medico
```

Comandi:

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/api/v1/patients" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8080/api/v1/patients/patient-001/current" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8080/api/v1/patients/patient-001/windows?limit=20" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8080/api/v1/patients/patient-001/decisions?limit=20" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8080/api/v1/patients/patient-001/alerts" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8080/api/v1/patients/patient-001/tasks" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8080/api/v1/patients/patient-001/system-status" -Headers $headers
```

Quando e' superato:

```text
tutte le chiamate restituiscono HTTP 200
i payload hanno items oppure campi paziente coerenti
```

## 7. Test Emilio E1 - Publisher MQTT Edge

E1 verifica che il Raspberry/Edge pubblichi gli output locali su MQTT senza rompere il
ciclo locale.

### 7.1 Test unitari Edge MQTT

Cosa fa:

```text
testa la costruzione dei payload MQTT Edge
verifica topic e QoS
verifica conversione nan -> null
verifica che alerts/critical venga creato solo quando should_publish=true
verifica la coda locale su disco
```

Cosa stiamo testando:

```text
E1: messaggi Edge coerenti con il contratto MQTT
```

Comandi:

```powershell
cd edge_node
..\.venv\Scripts\python.exe -m pytest tests\test_edge_mqtt.py
cd ..
```

Quando e' superato:

```text
3 passed
```

### 7.2 Generare payload MQTT senza pubblicare

Cosa fa:

```text
legge last-cycle.json
legge latest_window.csv
legge patient-001-decision.json
costruisce i messaggi MQTT
li stampa senza connettersi al broker
```

Cosa stiamo testando:

```text
che topic, message_id, schema_version, patient_id, edge_id e timestamp siano corretti
```

Comandi:

```powershell
cd edge_node
..\.venv\Scripts\python.exe -m edge_mqtt.cli --config config\edge.yml --dry-run
cd ..
```

Quando e' superato:

```text
compaiono topic edge/status, telemetry/window e telemetry/decision
alerts/critical compare solo se la decisione lo richiede
```

### 7.3 Pubblicazione reale Edge -> MQTT

Cosa fa:

```text
si connette al broker MQTT/TLS
pubblica i file locali dell'Edge
usa l'utente edge_patient_001
se il broker non risponde, accoda su disco
```

Cosa stiamo testando:

```text
E1 integrato con D1 e D4: Edge -> MQTT -> backend -> PostgreSQL
```

Comandi:

```powershell
$env:MQTT_EDGE_PASSWORD="PASSWORD_EDGE"
cd edge_node
..\.venv\Scripts\python.exe -m edge_mqtt.cli --config config\edge.yml
cd ..
```

Quando e' superato:

```text
il comando termina senza interrompere il ciclo locale
i messaggi risultano published oppure queued
il worker backend li salva su PostgreSQL se e' acceso
```

## 8. Test Edge runtime completo con comando unico

Questo test controlla il comando che poi useremo sul Raspberry Pi 5.

### 8.1 Avvio su Windows

Cosa fa:

```text
avvia edge_stack.cli
avvia receiver HTTP per app Android
avvia runtime ogni 4 minuti
aggrega BLE e Google Health
genera latest_window.csv
genera last-cycle.json
genera patient-001-decision.json
gestisce baseline automatica
pubblica MQTT se abilitato
```

Cosa stiamo testando:

```text
che il sistema possa partire con un comando unico e non con tanti comandi separati
```

Comandi:

```powershell
$env:MQTT_EDGE_PASSWORD="PASSWORD_EDGE"
.\Script\avvio\avviaSistema.ps1
```

Quando e' superato:

```text
compare Avvio sistema IoT
il receiver parte su http://0.0.0.0:8000
il runtime resta in loop
ogni 4 minuti viene prodotta una nuova finestra
```

### 8.2 Avvio su Raspberry Pi 5 / Linux

Cosa fa:

```text
avvia lo stesso stack Edge usando lo script bash
usa Python del virtualenv Linux se presente
```

Cosa stiamo testando:

```text
che lo stesso meccanismo funzioni anche sul Raspberry
```

Comandi:

```bash
export MQTT_EDGE_PASSWORD="PASSWORD_EDGE"
chmod +x Script/avvio/avviaSistema
./Script/avvio/avviaSistema
```

Quando e' superato:

```text
il processo Edge parte come su Windows
il receiver ascolta su porta 8000
il runtime genera finestre da 4 minuti
```

### 8.3 Controllare output locali Edge

Cosa fa:

```text
legge la finestra aggregata
legge l'ultimo ciclo runtime
legge la decisione AI
legge il report qualita dati
```

Cosa stiamo testando:

```text
che l'Edge continui a funzionare localmente anche senza dashboard o Cloud
```

Comandi:

```powershell
Get-Content edge_node\data\processed\latest_window.csv
Get-Content edge_node\outputs\last-cycle.json
Get-Content edge_node\outputs\patient-001-decision.json
Get-Content edge_node\outputs\last-quality-report.json
```

Quando e' superato:

```text
latest_window.csv contiene una finestra da 4 minuti
last-cycle.json contiene cycle_completed
patient-001-decision.json contiene level e anomaly_score
last-quality-report.json contiene stato qualita
```

## 9. Test Emilio E3-E8 - Dashboard medico con backend reale

La dashboard deve usare il backend reale, quindi `Dashboard\.env` deve contenere:

```text
VITE_API_BASE_URL=http://127.0.0.1:8080/api/v1
VITE_WS_BASE_URL=ws://127.0.0.1:8080/ws/v1
VITE_DATA_SOURCE=real
```

### 9.1 Avviare Dashboard

Cosa fa:

```text
avvia Vite sulla porta 5173
serve la dashboard React
usa REST e WebSocket configurati nel file .env
```

Cosa stiamo testando:

```text
E3-E8: frontend medico collegato al backend reale
```

Comandi:

```powershell
cd Dashboard
npm run dev
```

Aprire:

```text
http://127.0.0.1:5173
```

Credenziali:

```text
email medico demo = IOT_BACKEND_DEMO_DOCTOR_EMAIL in cloud/.env
password = IOT_BACKEND_DEMO_AUTH_PASSWORD in cloud/.env
```

Quando e' superato:

```text
la pagina login appare
il login riesce
la dashboard mostra la lista pazienti
```

### 9.2 Test E3 - Struttura navigabile

Cosa fa:

```text
verifica il flusso base della dashboard medico
```

Cosa stiamo testando:

```text
login, sessione, navigazione, error handling e WebSocket client
```

Verificare nella UI:

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

Quando e' superato:

```text
si puo' navigare tra le sezioni senza errori
la dashboard non mostra pagina bianca
```

### 9.3 Test E4 - Overview e lista pazienti

Cosa fa:

```text
verifica la vista iniziale operativa del medico
```

Cosa stiamo testando:

```text
ordinamento pazienti, filtri, semafori, stanza, watch, Edge e dati obsoleti
```

Verificare nella UI:

```text
lista pazienti ordinabile per severita
lista pazienti ordinabile per ultimo aggiornamento
semafori green, yellow, orange, red e technical
stanza corrente visibile
watch presente/assente visibile
Raspberry online/offline visibile
dati vecchi evidenziati
anomalia comportamentale separata da problema tecnico
click sul paziente senza perdere filtri e ordinamento
```

Quando e' superato:

```text
il medico capisce subito quale paziente richiede attenzione
problemi tecnici e comportamentali non sono confusi
```

### 9.4 Test E5 - Alert e presa in carico

Cosa fa:

```text
verifica la gestione operativa degli alert
```

Cosa stiamo testando:

```text
visualizzazione alert, filtri, presa in carico, risoluzione con nota e task collegato
```

Verificare nel tab `Alert`:

```text
timestamp alert
livello
score
motivi
stato
filtro per livello
filtro per stato
filtro per intervallo temporale
Prendi in carico con conferma
Risolvi con nota obbligatoria
utente che ha preso in carico
timestamp presa in carico
creazione task dal dettaglio alert
aggiornamento dopo evento WebSocket
```

Quando e' superato:

```text
un alert puo' passare da new ad acknowledged
un alert puo' passare da acknowledged a resolved solo con nota
il task di follow-up viene creato
la UI non cancella il testo della nota durante aggiornamenti realtime
```

### 9.5 Test E6 - Dati wearable e spaziali

Cosa fa:

```text
mostra in modo visuale i dati wearable e spaziali delle finestre Edge
```

Cosa stiamo testando:

```text
grafici biometrici, timeline stanze, minuti per stanza e gestione valori mancanti
```

Verificare nel tab `Paziente`:

```text
grafico frequenza cardiaca media
grafico deviazione standard frequenza cardiaca
grafico SpO2
grafico passi quando disponibili
grafico sonno quando disponibile
grafico sedentarieta quando disponibile
pannello HRV RMSSD
provenienza HRV Google Health/Fitbit
badge acquisito
badge imputato
badge non acquisito
timeline stanze
grafico minuti per stanza
cambi stanza
cambi notturni
permanenza massima
selettore Giorno
selettore Settimana
valori mancanti mostrati come n/d e non come 0
```

Quando e' superato:

```text
la dashboard mostra andamento wearable e spaziale senza interpretare null come zero
```

### 9.6 Test E7 - Valutazione comportamentale

Cosa fa:

```text
mostra in linguaggio clinico comprensibile come la valutazione e' stata composta dalle fonti disponibili
```

Cosa stiamo testando:

```text
indice complessivo, fonti, composizione, fattori principali e avanzamento del profilo personale
```

Verificare nel tab `Paziente`, sezione `Valutazione comportamentale`:

```text
indice di scostamento su 100
livello e sintesi della valutazione in italiano
Routine negli ambienti
Parametri dal wearable
Profilo personale quando disponibile
incidenza effettiva delle fonti
regola prevista 15/15/70 dopo baseline
fattori principali con nomi leggibili e unita' di misura
stato Misurato o Stima tecnica
assenza di nomi interni con underscore nella vista principale
pannello espandibile Dettagli tecnici del calcolo
valore rilevato e valore usato nel calcolo
scostamento standardizzato
messaggio Profilo in preparazione quando manca
giorni baseline trascorsi
finestre valide su 1000
finestre baseline scartate
linguaggio da triage senza messaggi assoluti
```

Quando e' superato:

```text
il medico comprende subito quali fonti e indicatori hanno inciso sul risultato
il modello personale risulta chiaramente disponibile o non disponibile
la baseline mostra avanzamento reale quando il backend riceve edge/status
i dettagli tecnici restano disponibili senza dominare la vista principale
```

### 9.7 Test E8 - Stato tecnico del sistema

Cosa fa:

```text
mostra lo stato operativo di Raspberry, ultimo ciclo Edge, sensori, Google Health,
MQTT, coda locale, WebSocket e qualita dati
```

Cosa stiamo testando:

```text
E8: distinzione tra problema tecnico e segnale comportamentale, senza mostrare segreti
```

Prima di testare questa sezione devono essere avviati:

```text
backend reale
worker MQTT backend
Edge completo con publisher MQTT
dashboard
```

Verificare nel tab `Sistema`:

```text
stato generale Operativo / Attenzione tecnica / Guasto da verificare
ultimo contatto Raspberry
Raspberry online/offline
ultimo ciclo Edge
durata della finestra, ad esempio 4 min
stato qualita dati
conteggio errori e warning qualita
stato wearable
presenza wearable
batteria wearable quando disponibile
stato BLE
stanza corrente BLE
campioni BLE dell'ultimo ciclo quando disponibili
stato Google Health
feature Google Health disponibili
eventuale errore OAuth senza token o segreti
stato MQTT
messaggi pubblicati
messaggi rimasti nella coda locale
warning temporanei separati dai guasti persistenti
eventi realtime leggibili in italiano
```

Controllo REST diretto:

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/api/v1/patients/patient-001/system-status" -Headers $headers
```

Quando e' superato:

```text
la pagina Sistema permette di capire se il dato manca per un guasto tecnico,
per un ritardo temporaneo o per assenza reale del sensore
nessun token OAuth, password, client_secret o header Authorization viene mostrato
```

### 9.8 Build finale Dashboard

Cosa fa:

```text
compila la dashboard in modalita produzione
```

Cosa stiamo testando:

```text
assenza di errori JSX, import, CSS e dipendenze frontend
```

Comandi:

```powershell
cd Dashboard
npm run build
cd ..
```

Quando e' superato:

```text
build completata senza errori
```

### 9.9 Verifica grafica, responsive e interazioni

Cosa fa:

```text
controlla il design system moderno della dashboard nelle quattro aree operative
verifica dialoghi, animazioni, stati vuoti, filtri e layout responsive
```

Cosa stiamo testando:

```text
la navigazione laterale resta utilizzabile e si trasforma in menu su tablet e telefono
la pagina non genera scorrimento orizzontale
testi, pulsanti, grafici e tabelle non si sovrappongono
le animazioni non spostano il contenuto e rispettano la preferenza movimento ridotto
```

Passaggi:

1. Aprire `http://127.0.0.1:5173` e accedere come medico.
2. Cercare un paziente dalla barra laterale e cambiare ordinamento e filtro.
3. Aprire Quadro clinico, Segnalazioni, Attivita e Stato sistema.
4. In Segnalazioni aprire i dialoghi Prendi in carico e Risolvi, quindi chiuderli con Annulla e con il tasto `Esc`.
5. In Attivita aprire Nuova attivita e controllare campi, priorita e scadenza.
6. Ridimensionare il browser a circa `390 x 844` pixel e aprire il menu mobile.
7. Passare il puntatore sui grafici e verificare tooltip, assi e ingrandimento.

Quando e' superato:

```text
tutte le viste sono leggibili su desktop, tablet e telefono
i dialoghi non usano finestre native del browser
nessun dato tecnico grezzo sostituisce le etichette comprensibili al medico
```

## 10. Test mock opzionale

Il mock non e' piu' il backend principale. Serve solo se il backend reale e' spento o se
vogliamo scenari finti controllati.

### 10.1 Avviare mock backend

Cosa fa:

```text
avvia un backend finto sulla porta 8090
simula API REST e WebSocket compatibili con la dashboard
```

Cosa stiamo testando:

```text
E2: possibilita' di sviluppare UI anche senza backend reale acceso
```

Comandi:

```powershell
cd mock_backend_per_test
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

Per usare il mock, modificare temporaneamente `Dashboard\.env`:

```text
VITE_API_BASE_URL=http://127.0.0.1:8090/api/v1
VITE_WS_BASE_URL=ws://127.0.0.1:8090/ws/v1
VITE_DATA_SOURCE=mock
```

Poi riavviare:

```powershell
cd Dashboard
npm run dev
```

Quando e' superato:

```text
la dashboard funziona anche con il mock
```

### 10.2 Test automatici mock

Cosa fa:

```text
verifica gli endpoint mock principali
verifica scenari paziente, alert, task e WebSocket simulati
```

Comando:

```powershell
.\.venv\Scripts\python.exe -m pytest mock_backend_per_test\tests
```

Quando e' superato:

```text
tutti i test mock passano
```

Per tornare al backend reale, ripristinare `Dashboard\.env`:

```text
VITE_API_BASE_URL=http://127.0.0.1:8080/api/v1
VITE_WS_BASE_URL=ws://127.0.0.1:8080/ws/v1
VITE_DATA_SOURCE=real
```

## 11. Test app Android paziente 0.3

### 11.1 Compilare e installare la nuova APK

Cosa fa:

```text
compila la home paziente, i grafici nativi e la nuova schermata attivita'
verifica risorse XML e codice Java prima dell'installazione
produce la APK debug aggiornata
```

Comandi:

```powershell
cd "Applicazione IoT Companion\companion_Android_app"
$env:JAVA_HOME="C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat clean assembleDebug lintDebug
```

APK da installare:

```text
Applicazione IoT Companion/companion_Android_app/app/build/outputs/apk/debug/app-debug.apk
```

### 11.2 Configurare telefono, receiver e backend

Cosa verifica:

```text
il telefono raggiunge sia il receiver BLE sia il backend clinico
il backend e' esposto alla rete locale e non soltanto a 127.0.0.1
```

Avviare il backend con:

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Nelle impostazioni amministrative dell'app usare:

```text
Receiver: http://IP_PC_O_RPI:8000/ble/sample
Backend:  http://IP_PC_BACKEND:8080/api/v1
```

Da browser del telefono devono aprirsi:

```text
http://IP_PC_O_RPI:8000/docs
http://IP_PC_BACKEND:8080/docs
```

### 11.3 Verificare home, dati e grafici

Cosa verifica:

```text
il login associa il telefono esclusivamente al patient_id autorizzato
la home mostra stanza, monitoraggio e ultimo aggiornamento
frequenza cardiaca, SpO2, passi e sonno compaiono soltanto se acquisiti
i valori mancanti restano indicati come non disponibili e non diventano zero
i grafici usano le ultime finestre Edge e mostrano ora/valore al tocco
```

Procedura:

1. accedere con l'account paziente associato a `patient-001`;
2. premere `Aggiorna` dopo almeno un ciclo Edge completo;
3. confrontare le schede con `edge_node/data/processed/latest_window.csv`;
4. toccare piu' punti sui grafici di frequenza cardiaca e SpO2;
5. verificare che ora e valore cambino senza spostare il layout;
6. disattivare temporaneamente la rete e verificare che la cache resti visibile;
7. riattivare la rete e controllare il nuovo aggiornamento.

Il backend alimenta lo storico tramite:

```text
GET /api/v1/telemetry/patients/patient-001/windows?limit=90
```

### 11.4 Verificare attivita', messaggi e lavoro offline

Cosa verifica:

```text
le attivita' mostrano tipo, priorita' e scadenza
la compilazione mostra numero di passaggi e campi leggibili
seen, started e completed vengono registrati nel backend
un risultato creato senza rete resta in coda e viene ritrasmesso
```

Procedura:

1. creare dalla dashboard un check-in o un test per `patient-001`;
2. aggiornare l'app e aprire la scheda `Attivita' per te`;
3. controllare tipo, scadenza e pulsante `Inizia attivita'`;
4. completare tutti i passaggi e inviare;
5. verificare in dashboard il passaggio a `completed`;
6. ripetere con rete disattivata e controllare il messaggio di salvataggio locale;
7. riattivare la rete e attendere la sincronizzazione automatica;
8. inviare anche un messaggio dal medico e verificare `Nuovo`/`Letto`.

### 11.5 Verificare che il BLE non abbia regressioni

Cosa verifica:

```text
la nuova interfaccia non modifica il Foreground Service BLE
la scansione continua con app chiusa e schermo bloccato
```

Procedura:

1. controllare la notifica persistente `IoT Edge Companion attivo`;
2. sostare vicino a ciascun beacon e verificare il cambio stanza;
3. bloccare lo schermo per almeno dieci minuti;
4. controllare che `edge_node/data/raw/ble_samples.csv` continui a ricevere righe;
5. riaprire l'app e verificare che la stanza sia aggiornata.

Quando e' superato:

```text
home, grafici, attivita', cache offline e monitoraggio BLE funzionano insieme
```

## 12. Pulizia dopo i test

### 12.1 Fermare processi manuali

Cosa fa:

```text
ferma backend, worker MQTT, Edge runtime e dashboard avviati a mano
```

Comando:

```text
CTRL+C
```

### 12.2 Fermare Docker

Cosa fa:

```text
ferma broker MQTT e PostgreSQL
```

Comandi:

```powershell
cd cloud
docker compose down
cd ..
```

### 12.3 Pulire build frontend

Cosa fa:

```text
rimuove la build generata da Vite
non tocca il codice sorgente
```

Comando:

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

## 13. Verifica funzioni Emilio E13-E20

Questa parte serve a verificare le ultime viste aggiunte alla Dashboard e l'estensione
dei check-in nell'app paziente. Prima devono essere accesi Docker, backend, worker MQTT,
Edge e Dashboard come nelle sezioni precedenti.

### E13 - Riepilogo ultime 24 ore

Aprire `patient-001` nella Dashboard e restare in `Quadro clinico`.

Controllare:

- la sezione `Riepilogo ultime 24 ore`;
- indice medio e picco massimo;
- stanza prevalente e permanenze per stanza;
- badge di affidabilita';
- dati mancanti mostrati come non disponibili.

Endpoint backend coinvolto:

```text
GET /api/v1/patients/patient-001/summary/24h
```

### E14 - Timeline

Aprire la scheda `Timeline`.

Controllare:

- ordinamento cronologico degli eventi;
- filtri per tipo evento;
- filtro per data e orario;
- presenza di decisioni, alert, task, messaggi e stati tecnici.

Endpoint backend coinvolto:

```text
GET /api/v1/patients/patient-001/timeline
```

### E15 - Valutazioni

Aprire la scheda `Valutazioni`.

Provare:

1. vedere i template questionari disponibili;
2. creare una programmazione giornaliera o settimanale;
3. generare subito il task dalla programmazione;
4. completare il task dall'app paziente;
5. verificare che il risultato compaia nello storico.

Endpoint backend coinvolti:

```text
GET  /api/v1/questionnaires/templates
GET  /api/v1/questionnaires/patients/patient-001/schedules
POST /api/v1/questionnaires/patients/patient-001/schedules
POST /api/v1/questionnaires/schedules/{schedule_id}/generate-due-task
GET  /api/v1/questionnaires/patients/patient-001/results
```

### E16 - Segnalazioni composte

Aprire `Segnalazioni`.

Provare:

- aprire il workflow clinico di un alert;
- prendere in carico;
- creare un task di follow-up;
- risolvere con nota;
- eliminare definitivamente solo quando l'alert e' risolto.

Endpoint backend coinvolto:

```text
GET /api/v1/alerts/{alert_id}/details
```

### E17 - Routine ambientale

Aprire `Routine ambientale`.

Controllare:

- minuti per stanza;
- stanza prevalente;
- cambi stanza;
- cambi notturni;
- permanenza massima;
- qualita' BLE e confronto baseline se disponibile.

Endpoint backend coinvolto:

```text
GET /api/v1/patients/patient-001/spatial-summary
```

### E18 - Spiegazione AI avanzata

Aprire `Quadro clinico` e guardare `Valutazione comportamentale`.

Controllare:

- confronto con score precedente;
- affidabilita' del dato;
- fattori che aumentano e riducono l'indice;
- dati mancanti o stimati;
- contributi dei modelli spaziale, wearable e personale.

### E19 - Check-in app paziente

Dalla Dashboard creare o generare un check-in breve. Nell'app Android paziente:

1. accedere con il profilo paziente;
2. aprire il task ricevuto;
3. verificare domande si/no, scala 0-10, scelta singola e testo;
4. inviare le risposte;
5. spegnere la rete e riprovare per verificare coda locale;
6. riaccendere la rete e controllare che l'invio venga ritentato.

### E20 - Report esportabile

Aprire la scheda `Report`.

Controllare:

- dati principali del paziente;
- indice AI corrente;
- decisioni recenti;
- alert e task recenti;
- assenza di token o dati tecnici sensibili.

Poi cliccare `Esporta PDF` e salvare tramite stampa del browser.

Endpoint backend coinvolto:

```text
GET /api/v1/patients/patient-001/report-data
```

## 14. Comandi importanti in breve

Questa sezione e' volutamente breve. Usarla quando tutto e' gia' stato configurato.

### Terminale 1 - Docker Cloud

```powershell
cd "C:\Users\emili\OneDrive\Desktop\Secondo Semestre\IoT\Progetto IoT 2026"
cd cloud
docker compose up -d mqtt postgres
docker compose ps
cd ..
```

### Terminale 2 - Backend reale

```powershell
cd "C:\Users\emili\OneDrive\Desktop\Secondo Semestre\IoT\Progetto IoT 2026\cloud\backend"
Stop-Process -Id 20208
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

### Terminale 3 - Worker MQTT backend

```powershell
cd "C:\Users\emili\OneDrive\Desktop\Secondo Semestre\IoT\Progetto IoT 2026\cloud\backend"
.\.venv\Scripts\python.exe -m app.mqtt.worker
```

### Terminale 4 - Edge completo

```powershell
cd "C:\Users\emili\OneDrive\Desktop\Secondo Semestre\IoT\Progetto IoT 2026"
$env:MQTT_EDGE_PASSWORD="PASSWORD_EDGE"
.\Script\avvio\avviaSistema.ps1
```

### Terminale 5 - Dashboard

```powershell
cd "C:\Users\emili\OneDrive\Desktop\Secondo Semestre\IoT\Progetto IoT 2026\Dashboard"
npm run dev
```

Aprire:

```text
Dashboard: http://127.0.0.1:5173
Backend docs: http://127.0.0.1:8080/docs

Le credenziali di accesso del medico demo sono:
 - medico.demo@localhost.invalid
 - provaprova

Le credenziali di accesso del paziente demo sono:
 - paziente.demo@localhost.invalid
 - provaprova

Le credenziali di accesso del caregiver demo sono:
 - caregiver.demo@localhost.invalid
 - provaprova

Receiver
http://IP_PC:8000/ble/sample

Backend clinico
http://IP_PC:8080/api/v1
```

### Test automatici rapidi

Da root:

```powershell
.\Script\test\test_mqtt_local.ps1
.\Script\test\test_backend_mqtt_ingest.ps1
.\.venv\Scripts\python.exe -m pytest edge_node\tests
.\.venv\Scripts\python.exe -m pytest mock_backend_per_test\tests
```

Backend:

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m pytest
cd ..\..
```

Dashboard:

```powershell
cd Dashboard
npm run build
cd ..
```

### Controlli finali Edge

```powershell
Get-Content edge_node\data\processed\latest_window.csv
Get-Content edge_node\outputs\last-cycle.json
Get-Content edge_node\outputs\patient-001-decision.json
Get-Content edge_node\outputs\last-quality-report.json
```

### Controlli finali PostgreSQL

```powershell
cd cloud
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, created_at from feature_windows order by created_at desc limit 5;"
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, level, created_at from decisions order by created_at desc limit 5;"
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "select message_id, patient_id, level, status, created_at from alerts order by created_at desc limit 5;"
cd ..
```
