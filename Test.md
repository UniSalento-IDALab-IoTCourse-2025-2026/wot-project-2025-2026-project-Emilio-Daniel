# Test completo D1-D4 ed E1-E5

Questo file contiene una procedura ordinata per verificare la prima versione del sistema:

```text
Cloud Daniel D1-D4
Edge/MQTT Emilio E1
Mock backend E2
Dashboard medico E3-E5
```

L'obiettivo e' avere una prima inquadratura end-to-end: broker MQTT, backend Cloud,
database, publisher Edge, mock frontend e dashboard funzionanti.

## Come leggere questo file

Ogni blocco di test ha sempre tre livelli:

```text
Cosa fa il comando       -> effetto tecnico sul sistema
Cosa stiamo testando     -> requisito D/E che vogliamo verificare
Quando e' superato       -> output o comportamento atteso
```

Questi comandi non sono la procedura finale per il paziente. Servono a noi sviluppatori
per collaudare i pezzi uno alla volta. Nella versione finale Raspberry e servizi Cloud
dovranno partire con script unici e servizi automatici.

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

Cosa fa:

```text
crea l'ambiente Python principale del progetto
installa librerie Edge Node, AI, MQTT, FastAPI mock e pytest
isola le dipendenze dal Python globale del PC
```

Cosa stiamo testando:

```text
che il PC sia pronto a eseguire Edge Node, mock backend e test automatici
```

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

Cosa fa:

```text
crea l'ambiente Python dedicato al backend Cloud reale
installa FastAPI, SQLAlchemy, Alembic, PostgreSQL driver, MQTT worker e test backend
```

Cosa stiamo testando:

```text
che la parte Cloud possa essere avviata senza dipendere dall'ambiente Edge
```

```powershell
cd cloud\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
cd ..\..
```

### 1.3 Dipendenze dashboard React

Cosa fa:

```text
scarica le dipendenze Node della dashboard
compila il frontend React con Vite
verifica che JSX, import e CSS siano validi
```

Cosa stiamo testando:

```text
che la Dashboard medico possa essere costruita senza errori
```

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

Cosa fa:

```text
crea i file locali con password, URL database e credenziali MQTT
parte dagli esempi versionati ma lascia i segreti fuori da Git
```

Cosa stiamo testando:

```text
che broker, backend e database possano leggere configurazioni reali locali
```

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

Cosa fa:

```text
genera una CA/certificato locale self-signed per Mosquitto
abilita il listener MQTT sicuro sulla porta 8883
abilita anche WSS sulla porta 9001
```

Cosa stiamo testando:

```text
che il broker possa accettare connessioni TLS come avverra' sul Cloud/VPS
```

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

Cosa fa:

```text
crea il file cloud/mqtt/passwd usato da Mosquitto
aggiunge tre identita separate: Edge, backend e client di test
```

Cosa stiamo testando:

```text
che ogni componente abbia credenziali separate e non usi accesso anonimo
```

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

Cosa fa:

```text
avvia il container Docker iot-mqtt
espone MQTT locale 1883, MQTT/TLS 8883 e WSS 9001
carica password, ACL, certificati e configurazione Mosquitto
```

Cosa stiamo testando:

```text
che il broker D1 sia vivo e raggiungibile
```

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

Cosa fa:

```text
pubblica messaggi come Edge autorizzato
prova a pubblicare su un paziente non autorizzato
verifica che il backend possa inviare comandi all'Edge
simula una caduta improvvisa dell'Edge e controlla il Last Will
testa MQTT/TLS su 8883
testa handshake MQTT over secure WebSocket su 9001
controlla che i retained message siano usati solo per stato corrente
```

Cosa stiamo testando:

```text
D1: sicurezza base del broker, ACL, TLS, WSS, Last Will e policy retained
```

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

Cosa fa:

```text
avvia l'app FastAPI reale di Daniel
espone health, ready, docs e OpenAPI sulla porta 8080
carica la configurazione da cloud/backend/.env e variabili IOT_BACKEND_*
```

Cosa stiamo testando:

```text
D2: struttura backend FastAPI, configurazione, logging, error handling e documentazione API
```

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Lasciare questo terminale aperto.

### 4.2 Verificare health, ready e OpenAPI

In un secondo terminale dalla root:

Cosa fa:

```text
interroga il backend reale
verifica che il processo sia vivo
verifica che la configurazione minima sia caricata
verifica che FastAPI produca il contratto OpenAPI
```

Cosa stiamo testando:

```text
che la base Cloud sia raggiungibile prima di collegare MQTT/database/dashboard
```

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

Nota: le route REST principali sono disponibili con D5, il WebSocket realtime reale e'
disponibile con D6 e l'autorizzazione completa e' stata aggiunta con D7.

## 5. Test Daniel D3 - PostgreSQL e migrazioni

### 5.1 Avviare PostgreSQL

Cosa fa:

```text
avvia il container iot-postgres
crea il database progetto_iot con utente iot_backend
espone PostgreSQL sulla porta 5432
```

Cosa stiamo testando:

```text
D3: servizio database disponibile per il backend
```

```powershell
cd cloud
docker compose up -d postgres
docker compose ps
cd ..
```

Attendere che `iot-postgres` sia `healthy`.

### 5.2 Applicare migrazioni Alembic

Cosa fa:

```text
esegue le migrazioni versionate del backend
crea o aggiorna le tabelle PostgreSQL
porta lo schema DB alla versione attesa dal codice
```

Cosa stiamo testando:

```text
D3: schema database riproducibile e versionato
```

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

Cosa fa:

```text
entra nel container PostgreSQL
lista le tabelle presenti nel database progetto_iot
```

Cosa stiamo testando:

```text
che Alembic abbia creato le tabelle necessarie a pazienti, Edge, finestre, decisioni, alert e task
```

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

Cosa fa:

```text
avvia mqtt e postgres se non sono gia attivi
applica le migrazioni Alembic
avvia temporaneamente il worker MQTT del backend
pubblica tre messaggi MQTT: finestra, decisione e alert
verifica sul database che i tre messaggi siano stati salvati
ferma il worker temporaneo
```

Cosa stiamo testando:

```text
D4: pipeline reale MQTT -> subscriber backend -> validazione -> PostgreSQL
```

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

Cosa fa:

```text
interroga direttamente le tabelle scritte dal subscriber MQTT
mostra gli ultimi messaggi salvati
```

Cosa stiamo testando:

```text
che i dati non siano solo ricevuti dal broker ma persistiti nel database
```

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

Cosa fa:

```text
abilita il publisher MQTT dell'Edge
imposta host, porta TLS, utente Edge, CA file e coda locale
lascia la password fuori dal file usando MQTT_EDGE_PASSWORD
```

Cosa stiamo testando:

```text
E1: configurazione Edge pronta per pubblicare verso il broker di Daniel
```

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

Cosa fa:

```text
testa la costruzione dei payload MQTT Edge
verifica che nan diventi null
verifica topic e QoS dei messaggi
verifica che alerts/critical venga creato solo con should_publish=true
verifica la coda locale su disco
```

Cosa stiamo testando:

```text
E1: messaggi Edge coerenti con contratto MQTT e tolleranza a broker non disponibile
```

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

Cosa fa:

```text
legge last-cycle.json, latest_window.csv e patient-001-decision.json
costruisce i messaggi MQTT
li stampa a schermo senza connettersi al broker
```

Cosa stiamo testando:

```text
che il contenuto pubblicabile sia corretto prima di inviarlo davvero
```

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

Cosa fa:

```text
connette l'Edge al broker MQTT/TLS
pubblica edge/status, telemetry/window e telemetry/decision
pubblica alerts/critical solo se la decisione lo richiede
se il broker non risponde, salva i messaggi nella coda locale
```

Cosa stiamo testando:

```text
E1: pubblicazione reale dell'Edge senza interrompere il ciclo locale
```

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

Cosa fa:

```text
prepara il lato Cloud completo: broker, database e schema aggiornato
```

Cosa stiamo testando:

```text
che il backend abbia tutto il necessario per ricevere cio' che pubblica l'Edge
```

```powershell
cd cloud
docker compose up -d mqtt postgres
cd ..\cloud\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

### 8.2 Avviare subscriber backend

Cosa fa:

```text
avvia il worker MQTT del backend reale
si iscrive ai topic Edge
resta in ascolto di finestre, decisioni, alert e stati sensori
```

Cosa stiamo testando:

```text
che Daniel D4 sia pronto a ricevere messaggi pubblicati da Emilio E1
```

Terminale dedicato:

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m app.mqtt.worker
```

Lasciare aperto.

### 8.3 Pubblicare dal modulo Edge

Cosa fa:

```text
usa i file locali dell'Edge come sorgente
pubblica gli eventi sul broker con l'utente edge_patient_001
```

Cosa stiamo testando:

```text
integrazione E1 -> D1 -> D4
```

In un altro terminale:

```powershell
cd edge_node
$env:MQTT_EDGE_PASSWORD="PASSWORD_EDGE"
..\.venv\Scripts\python.exe -m edge_mqtt.cli --config config\edge.yml
cd ..
```

### 8.4 Verificare salvataggio su PostgreSQL

Cosa fa:

```text
controlla le tabelle scritte dal worker dopo la pubblicazione Edge
```

Cosa stiamo testando:

```text
che il messaggio pubblicato dall'Edge arrivi fino al database Cloud
```

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

Cosa fa:

```text
avvia in un solo comando il receiver HTTP per l'app Android
avvia il runtime Edge in loop ogni 240 secondi
aggrega BLE, Google Health e altri dati configurati
produce latest_window.csv, decision JSON e last-cycle.json
gestisce baseline automatica e training personale quando pronto
pubblica su MQTT se mqtt.enabled=true
```

Cosa stiamo testando:

```text
che il Raspberry possa essere usato con un comando unico, senza lanciare pezzi separati
```

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

Cosa fa:

```text
legge i principali output locali dell'Edge
controlla finestra aggregata, stato ciclo, decisione AI e qualita dati
```

Cosa stiamo testando:

```text
che l'Edge continui a funzionare anche localmente e offline, indipendentemente dal Cloud
```

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

E2 resta utile per sviluppare la Dashboard con scenari controllati, anche se REST D5 e
WebSocket D6 reali sono disponibili.

### 10.1 Avviare mock backend

Terminale dedicato:

Cosa fa:

```text
avvia un backend finto sulla porta 8090
simula API REST e WebSocket; il backend reale ora espone REST D5 e WebSocket D6
```

Cosa stiamo testando:

```text
E2: sviluppo della dashboard anche se il backend reale non ha ancora tutte le API
```

```powershell
cd mock_backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

Lasciare aperto.

### 10.2 Verificare health e pazienti

In un altro terminale:

Cosa fa:

```text
verifica che il mock sia vivo
legge la lista pazienti demo
```

Cosa stiamo testando:

```text
che la dashboard abbia dati realistici per E3/E4/E5
```

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

Cosa fa:

```text
cambia il comportamento del mock backend
permette di provare routine, alert severo, problema tecnico e dati mancanti
```

Cosa stiamo testando:

```text
che la dashboard gestisca scenari diversi senza cambiare codice frontend
```

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

## 11. Test Emilio E3-E5 - Dashboard medico

### 11.1 Avviare dashboard

Terminale dedicato:

Cosa fa:

```text
avvia il server Vite della dashboard medico
serve React sulla porta 5173
usa le variabili VITE_* o i default per parlare col mock backend
```

Cosa stiamo testando:

```text
E3/E4/E5: frontend accessibile dal browser e collegato alle API mock
```

```powershell
cd Dashboard
npm run dev
```

Aprire:

```text
http://127.0.0.1:5173
```

Credenziali locali:

```text
Usare email e password configurate nel .env locale del backend.
```

### 11.2 Test E3 - Struttura navigabile

Cosa fa:

```text
verifica il flusso utente base della dashboard medico
```

Cosa stiamo testando:

```text
login, sessione, navigazione, tab principali, error handling e WebSocket client
```

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

Cosa fa:

```text
verifica la vista operativa iniziale del medico
```

Cosa stiamo testando:

```text
ordinamento pazienti, filtri, semafori, stato stanza/watch/edge, dato obsoleto e distinzione tecnico-comportamentale
```

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

### 11.4 Test E5 - Pagina alert e presa in carico

Prima di questo test devono essere gia' avviati:

```text
mock_backend su http://127.0.0.1:8090
Dashboard su http://127.0.0.1:5173
```

Per vedere piu' rapidamente gli aggiornamenti realtime puoi avviare il mock con:

```powershell
$env:MOCK_WS_INTERVAL_SECONDS="2"
cd mock_backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

Cosa fa:

```text
avvia il mock backend con eventi WebSocket piu' frequenti
permette alla dashboard di ricevere eventi alert_acknowledged e alert_resolved piu' velocemente
```

Cosa stiamo testando:

```text
E5: gestione operativa degli alert, presa in carico, risoluzione con nota e task collegato
```

Aprire la dashboard:

```text
http://127.0.0.1:5173
```

Credenziali locali:

```text
Usare email e password configurate nel .env locale del backend.
```

Passaggi UI:

```text
selezionare Paziente Priorita
aprire il tab Alert
verificare timestamp, livello, score, motivi e stato
filtrare per livello red
filtrare per stato Nuovi
filtrare per ultime 24 ore
premere Prendi in carico
confermare la finestra di conferma
verificare che compaiano utente e timestamp di presa in carico
provare a premere Risolvi senza nota
verificare che la dashboard blocchi l'azione
inserire una nota di risoluzione
premere Risolvi e confermare
filtrare per stato Risolti
premere Crea task sull'alert
aprire il tab Task
verificare che esista un task di follow-up collegato all'alert
```

Quando e' superato:

```text
l'alert mostra stato acknowledged dopo la presa in carico
l'alert mostra stato resolved dopo la risoluzione
la nota e' obbligatoria
il task compare nella sezione Task
la dashboard si aggiorna quando arrivano eventi WebSocket compatibili
```

Test REST opzionale senza usare la UI:

```powershell
$alerts = Invoke-RestMethod http://127.0.0.1:8090/api/v1/patients/patient-004/alerts
$alertId = $alerts.items[0].alert_id

Invoke-RestMethod `
  -Method Patch `
  -Uri "http://127.0.0.1:8090/api/v1/alerts/$alertId/acknowledge" `
  -ContentType "application/json" `
  -Body '{"user_id":"doctor-test"}'

Invoke-RestMethod http://127.0.0.1:8090/api/v1/patients/patient-004/alerts

Invoke-RestMethod `
  -Method Patch `
  -Uri "http://127.0.0.1:8090/api/v1/alerts/$alertId/resolve" `
  -ContentType "application/json" `
  -Body '{"user_id":"doctor-test","note":"Controllo completato dal medico."}'

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8090/api/v1/patients/patient-004/tasks" `
  -ContentType "application/json" `
  -Body '{"type":"alert_follow_up","priority":"high","title":"Follow-up alert","instructions":"Verificare alert preso in carico.","payload":{"source_alert_id":"test"}}'

Invoke-RestMethod http://127.0.0.1:8090/api/v1/patients/patient-004/tasks
```

Cosa fa:

```text
legge l'alert mock di patient-004
lo prende in carico tramite API
verifica che lo stato sia persistito nel mock
lo risolve con nota obbligatoria
crea un task manuale collegabile all'alert
verifica che il task sia visibile nella lista task
```

Cosa stiamo testando:

```text
che i pulsanti della dashboard poggino su API reali del mock e non solo su stato locale React
```

Output atteso:

```text
status acknowledged dopo acknowledge
acknowledged_by valorizzato
status resolved dopo resolve
resolved_by e resolution_note valorizzati
task status created nella lista task
```

### 11.5 Build finale Dashboard

Cosa fa:

```text
compila la dashboard in modalita produzione
```

Cosa stiamo testando:

```text
che la dashboard non abbia errori di import/JSX/CSS prima di versionarla o consegnarla
```

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

Cosa fa:

```text
esegue i test Python automatici di Edge e mock backend
```

Cosa stiamo testando:

```text
regressioni veloci sui payload MQTT Edge e sugli endpoint principali del mock backend
incluso il ciclo alert acknowledge/resolve usato da E5
```

```powershell
.\.venv\Scripts\python.exe -m pytest edge_node\tests
.\.venv\Scripts\python.exe -m pytest mock_backend\tests
```

Da backend Cloud:

Cosa fa:

```text
esegue i test automatici scritti da Daniel sul backend reale
```

Cosa stiamo testando:

```text
health backend, schema database e ingestione MQTT a livello unitario
```

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

Cosa fa:

```text
tiene accesi broker MQTT e database PostgreSQL
```

```powershell
cd cloud
docker compose up -d mqtt postgres
cd ..
```

### Terminale 2 - Backend Cloud reale

Cosa fa:

```text
applica migrazioni e avvia API/documentazione backend su 8080
```

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

### Terminale 3 - Subscriber MQTT reale

Cosa fa:

```text
ascolta i messaggi MQTT Edge e li salva nel database
```

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m app.mqtt.worker
```

### Terminale 4 - Edge completo

Cosa fa:

```text
avvia receiver Android/BLE e runtime Edge automatico
```

```powershell
$env:MQTT_EDGE_PASSWORD="PASSWORD_EDGE"
.\Script\avvio\avviaSistema.ps1
```

### Terminale 5 - Mock backend per dashboard

Cosa fa:

```text
fornisce API REST/WebSocket simulate alla dashboard
```

La dashboard puo' ancora usare il mock quando vogliamo scenari controllati:

```powershell
cd mock_backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

### Terminale 6 - Dashboard

Cosa fa:

```text
avvia l'interfaccia medico in React
```

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
La Dashboard puo' puntare al backend reale per REST D5 e WebSocket D6. Il mock resta
utile per simulare scenari controllati.
```

## 14. Usare backend reale D5/D6/D7

Le REST reali D5, il WebSocket reale D6 e l'auth D7 sono disponibili. Modificare la Dashboard per
puntare interamente al backend reale.

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
