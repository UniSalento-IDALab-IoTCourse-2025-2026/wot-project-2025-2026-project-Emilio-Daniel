# Dashboard e architettura app medico, caregiver e paziente

Questo documento descrive la scelta consigliata per la parte dashboard del progetto:
app paziente, app caregiver, dashboard medico, comunicazione MQTT/WebSocket, backend
Cloud e ruolo del Raspberry Pi 5.

L'obiettivo e' avere una panoramica chiara prima di iniziare a implementare frontend e
backend.

## Decisione principale

Le tre interfacce non devono essere uguali.

La scelta consigliata e':

```text
Paziente -> app mobile Android
Caregiver -> app mobile Android/iOS
Medico   -> dashboard web
```

Motivo: paziente, caregiver e medico hanno bisogni e responsabilita' diversi.

Il paziente deve avere un'app mobile semplice ma utile: non solo raccolta dati, ma anche
dashboard personale, promemoria, notifiche, esercizi e test cognitivi richiesti dal
medico. Il medico invece ha bisogno di una dashboard web piu' ricca, con grafici,
storico, alert, stato sensori, spiegazione AI e strumenti per inviare attivita o test al
paziente. Il caregiver deve ricevere informazioni sintetiche e operative, senza dati
clinici grezzi o spiegazioni tecniche del modello.

## Ruolo corretto dell'app paziente

L'app paziente non e' solo un'app tecnica per inviare i beacon.

Deve avere due ruoli:

```text
1. Raccolta dati
   -> scansione BLE
   -> invio stanza al Raspberry
   -> stato connessione e monitoraggio

2. Supporto al paziente
   -> dashboard personale semplice
   -> notifiche
   -> promemoria
   -> esercizi
   -> pulsante SOS/richiesta aiuto
   -> test cognitivi inviati dal medico
   -> invio risultati test al backend
```

Quindi la comunicazione non e' solo:

```text
App paziente -> Raspberry
```

ma anche:

```text
Medico dashboard -> Backend -> App paziente
App paziente -> Backend -> Medico dashboard
```

Esempio importante:

```text
1. Il medico vede un alert o un andamento sospetto.
2. Dalla dashboard invia un test cognitivo al paziente.
3. Il paziente riceve una notifica nell'app.
4. Il paziente completa il test.
5. Il risultato torna al backend.
6. Il medico vede punteggio, risposte e tempo di completamento.
```

Questa parte e' fondamentale per rendere il sistema non solo osservativo, ma anche
interattivo e utile nel controllo a distanza.

## Architettura consigliata

```text
App Android paziente
  -> scansiona beacon BLE
  -> stima stanza
  -> invia campioni BLE al Raspberry

Google Pixel Watch 2
  -> sincronizza dati con telefono/account Google
  -> Google Health API
  -> Raspberry legge i dati via OAuth

Raspberry Pi 5
  -> edge_receiver riceve campioni BLE
  -> edge_runtime ogni 4 minuti
  -> data/raw/*.csv
  -> latest_window.csv
  -> AI/fusion/debounce
  -> patient-001-decision.json
  -> pubblica dati/eventi

Backend
  -> riceve eventi dal Raspberry
  -> salva su database
  -> espone API REST per storico
  -> espone WebSocket per aggiornamenti realtime

Dashboard medico web
  -> legge storico via REST
  -> riceve aggiornamenti live via WebSocket
  -> puo' inviare task/test al paziente tramite backend

App Android paziente
  -> riceve notifiche/task dal backend
  -> mostra esercizi o test cognitivi
  -> invia risultati al backend
  -> il medico vede risultati nella dashboard
```

## Ruolo di BLE, MQTT e WebSocket

### BLE

BLE serve solo per la localizzazione indoor.

Nel nostro progetto:

```text
Beacon nelle stanze
-> app Android paziente
-> stanza stimata
-> POST al Raspberry
-> data/raw/ble_samples.csv
```

BLE non e' il canale giusto per mandare dati alla dashboard medico. Serve solo nella
parte locale paziente/casa.

### MQTT

MQTT e' adatto alla parte IoT, quindi al collegamento tra Raspberry e backend.

Il Raspberry puo' pubblicare:

```text
stato ciclo edge
dati ultima finestra
decisione AI
alert
stato sensori
heartbeat Raspberry
```

Esempi di topic possibili:

```text
iot/patient-001/edge/status
iot/patient-001/edge/window
iot/patient-001/edge/decision
iot/patient-001/edge/alert
iot/patient-001/sensors/watch
iot/patient-001/sensors/ble
```

Motivo: MQTT e' leggero, robusto e pensato per dispositivi come Raspberry Pi.

### WebSocket

WebSocket serve tra backend e dashboard web.

La dashboard medico deve aggiornarsi in tempo reale quando arriva una nuova decisione,
senza fare refresh continuo della pagina.

Flusso consigliato:

```text
Raspberry -> MQTT -> Backend -> WebSocket -> Dashboard medico
```

REST API e WebSocket hanno ruoli diversi:

```text
REST API   -> caricare storico, dettagli paziente, report, dati vecchi
WebSocket  -> aggiornamenti live, nuovo alert, nuovo ciclo completato
MQTT       -> comunicazione IoT dal Raspberry al backend
```

Per le notifiche verso l'app paziente conviene aggiungere anche un canale push:

```text
Backend -> Push notification -> App paziente
```

Su Android il canale tipico e' Firebase Cloud Messaging, o un servizio equivalente. Il
push serve per avvisare il paziente anche quando l'app non e' aperta.

## Passaggio dall'ambiente locale all'infrastruttura Cloud-Broker

Il funzionamento interno del Raspberry Pi 5 rimane invariato: acquisizione dei dati,
aggregazione della finestra di quattro minuti, controllo qualita', inferenza AI, fusione
dei modelli e generazione della decisione JSON. La comunicazione Cloud viene aggiunta
dopo questo flusso e non sostituisce il funzionamento locale dell'Edge Node.

Al termine di ogni ciclo, un client MQTT sul Raspberry pubblica i dati necessari verso
un broker remoto. Il Raspberry continua quindi a funzionare anche se la connessione
Internet non e' disponibile; i messaggi non inviati dovranno essere accodati localmente
e ritrasmessi al ripristino della rete.

```text
Sensori e Google Health
-> Raspberry Pi 5
-> aggregazione e inferenza locale
-> JSON/CSV locali
-> MQTT publisher
-> Broker MQTT Cloud
-> Backend e client autorizzati
```

Il broker MQTT puo' essere Mosquitto installato su una VPS oppure un servizio gestito,
come HiveMQ Cloud o AWS IoT Core. Il broker non esegue la logica clinica: autentica i
client, riceve i messaggi e li distribuisce ai subscriber autorizzati. In questo modo il
Raspberry pubblica ogni evento una sola volta e non deve collegarsi separatamente a ogni
dashboard.

Il backend, sviluppabile con FastAPI, opera anche come client MQTT. Si iscrive ai topic
dei pazienti, valida i payload ricevuti, salva telemetria e decisioni nel database,
gestisce utenti e permessi ed espone API REST e WebSocket alle applicazioni. Quando
riceve un evento critico, puo' inoltre inviare una notifica push tramite Firebase Cloud
Messaging anche se l'app mobile e' chiusa.

Il canale raccomandato per la dashboard medico e':

```text
Raspberry -> MQTT/TLS -> Broker -> Backend -> WebSocket/WSS -> Dashboard medico
```

Questa soluzione evita di distribuire nel browser credenziali MQTT con permessi ampi e
mantiene nel backend autorizzazione, tracciamento e trasformazione dei dati. MQTT over
WebSockets e' comunque tecnicamente utilizzabile per collegare direttamente una web app
al broker, ad esempio in un prototipo. In tal caso servono TLS, credenziali temporanee e
ACL che consentano a ogni utente di leggere esclusivamente i topic autorizzati.

## Topic MQTT e comunicazione bidirezionale

Una struttura coerente dei topic permette di separare telemetria, allarmi, stato dei
sensori e comandi. Una proposta iniziale e':

```text
iot/patients/patient-001/edge/status
iot/patients/patient-001/telemetry/window
iot/patients/patient-001/telemetry/decision
iot/patients/patient-001/alerts/critical
iot/patients/patient-001/sensors/watch
iot/patients/patient-001/sensors/ble
iot/patients/patient-001/commands/task
iot/patients/patient-001/commands/ack
```

I topic `telemetry` e `alerts` viaggiano principalmente dal Raspberry al Cloud. I topic
`commands` permettono la comunicazione inversa, ad esempio per registrare la presa in
carico di un allarme o notificare la disponibilita' di un nuovo task. I comandi clinici
devono comunque essere creati e autorizzati dal backend, che conserva il relativo log.

Ogni payload dovrebbe includere almeno:

```text
schema_version
message_id
patient_id
edge_id
timestamp_utc
event_type
payload
```

`message_id` consente al backend di riconoscere eventuali duplicati prodotti da una
ritrasmissione MQTT. `schema_version` permette di aggiornare in futuro il formato senza
rompere i client gia' installati.

## Dashboard caregiver

L'app caregiver ha un ruolo diverso sia dall'app paziente sia dalla dashboard medico.
Deve mostrare informazioni sintetiche, comprensibili e orientate all'azione:

```text
stato generale a semaforo
ultimo aggiornamento del sistema
eventuali richieste di assistenza
problemi tecnici: watch scarico, telefono offline, monitoraggio interrotto
promemoria terapeutici o operativi
allarmi severi gia' validati dal sistema
stato di presa in carico dell'allarme
```

Non deve mostrare dati fisiologici grezzi, dettagli diagnostici o feature AI difficili da
interpretare. Quando l'app e' aperta puo' ricevere aggiornamenti tramite WebSocket o un
client MQTT con permessi limitati. Quando e' chiusa o in background riceve notifiche push
generate dal backend.

Anche l'app paziente segue lo stesso principio di connettivita': aggiornamenti live in
foreground e push notification in background. La scansione BLE locale resta invece
gestita dal Foreground Service Android e continua indipendentemente dal collegamento al
Cloud.

## Flusso di un evento critico

Il flusso completo di un allarme severo e della sua presa in carico e':

```text
1. L'Edge AI calcola una decisione red con should_publish=true.
2. Il Raspberry salva il JSON localmente e pubblica l'evento via MQTT/TLS.
3. Il broker consegna il messaggio al backend e agli eventuali client autorizzati.
4. Il backend valida e salva l'evento nel database.
5. La dashboard medico riceve l'aggiornamento tramite WebSocket/WSS.
6. Il backend invia una notifica push urgente al caregiver.
7. Il medico o il caregiver prende in carico l'evento.
8. Il backend registra l'acknowledgement e aggiorna tutti i client connessi.
```

La presa in carico deve contenere almeno utente, ruolo, data e ora. Non elimina
l'allarme: ne cambia lo stato da `new` a `acknowledged` e successivamente, quando
previsto, a `resolved`. Questo mantiene una traccia verificabile delle azioni eseguite.

## Microservizi: si o no?

Per ora no, non conviene partire con microservizi veri.

Meglio una struttura modulare ma semplice:

```text
Raspberry Pi
  edge_receiver
  edge_runtime
  edge_ai
  mqtt_publisher

Backend unico modulare
  API REST
  WebSocket
  MQTT subscriber
  database

Frontend medico web

App Android paziente
```

Questa architettura e' gia abbastanza seria, ma non introduce troppa complessita.

I microservizi possono arrivare dopo, se il progetto cresce:

```text
auth service
patient service
telemetry service
alert service
notification service
```

Per il progetto attuale rischierebbero di complicare deployment, debugging e testing.

## App paziente

L'app paziente non deve essere solo un raccoglitore BLE. Deve restare semplice nel
linguaggio e nell'interfaccia, ma puo' avere funzioni attive di supporto quotidiano.

Funzioni principali lato raccolta dati:

```text
scansione BLE beacon
stanza rilevata
invio campioni al Raspberry
stato connessione al Raspberry
stato monitoraggio attivo/non attivo
eventuali warning semplici: telefono offline, receiver non raggiungibile, batteria bassa
```

Funzioni principali lato paziente:

```text
dashboard personale semplice
stato giornata: tutto ok / attenzione / controlla dispositivo
promemoria per muoversi o alzarsi
esercizi consigliati
notifiche dal medico/sistema
pulsante SOS o richiesta aiuto
test cognitivi inviati dal medico
storico semplice delle attivita completate
```

La dashboard paziente deve essere molto diversa da quella medico. Non deve mostrare
score tecnici o feature complesse, ma messaggi comprensibili:

```text
Monitoraggio attivo
Orologio collegato
Telefono collegato al Raspberry
Ultimo aggiornamento pochi minuti fa
Oggi hai completato 2 esercizi su 3
Il medico ti ha inviato un test
```

### Test cognitivi richiesti dal medico

Questa e' una funzione importante.

Flusso consigliato:

```text
Medico vede alert o dati sospetti nella dashboard
-> medico invia richiesta test cognitivo
-> backend crea un task per il paziente
-> app paziente riceve notifica
-> paziente apre il test
-> app salva risposte, tempo, completamento
-> backend riceve risultati
-> dashboard medico mostra esito del test
```

Esempi di test/attivita possibili:

```text
mini questionario di orientamento
test memoria breve
test attenzione semplice
test umore/percezione stato
conferma benessere: "come ti senti?"
esercizio guidato: alzarsi e camminare per pochi minuti
```

Per ogni test conviene salvare:

```text
task_id
patient_id
created_by doctor_id
tipo test
domande/istruzioni
orario invio
orario apertura
orario completamento
risposte
score test, se previsto
durata
stato: inviato / visto / completato / scaduto
```

### Notifiche

L'app paziente dovrebbe ricevere notifiche per:

```text
test cognitivo richiesto dal medico
esercizio o promemoria
telefono non connesso al Raspberry
monitoraggio BLE spento
watch non sincronizzato o batteria bassa
richiesta di conferma benessere
```

Le notifiche non devono spaventare il paziente. Devono essere brevi e pratiche:

```text
Il medico ti ha inviato un breve test.
Controlla che il telefono sia vicino a te.
Il monitoraggio e' in pausa: riaprire l'app.
E' ora di fare un breve esercizio.
```

Funzioni da evitare o nascondere al paziente:

```text
score AI dettagliati
feature tecniche
grafici clinici complessi
spiegazione modello
storico clinico
messaggi tipo "anomalia severa" senza mediazione del medico
```

Motivo: il paziente non deve interpretare dati clinici o tecnici. L'app deve aiutare la
raccolta dati, favorire comportamenti utili e permettere al medico di interagire a
distanza in modo controllato.

## Dashboard medico

La dashboard medico e' il centro di monitoraggio.

Sezioni consigliate:

### 1. Overview paziente

Mostra lo stato corrente:

```text
livello attuale: green/yellow/orange/red/technical
ultimo aggiornamento
stanza corrente
Raspberry online/offline
watch presente
batteria watch
qualita ultima finestra
```

### 2. Alert

Lista alert recenti:

```text
timestamp
livello
should_publish
motivo
score finale
modello che ha causato alert
stato: nuovo/visto/gestito
```

Esempi di origine alert:

```text
generic_wearable_anomaly_only
generic_spatial_anomaly_only
multi_model_agreement_orange
multi_model_agreement_red
technical
```

Da un alert il medico dovrebbe poter avviare azioni:

```text
invia test cognitivo
invia richiesta "come ti senti?"
invia esercizio o promemoria
segnare alert come visto/gestito
aggiungere nota clinica
```

### 3. Dati wearable

Visualizzare:

```text
heart_rate_mean
heart_rate_std
resting_heart_rate
hrv_rmssd
spo2_mean
sleep_minutes
awake_minutes
steps
sedentary_minutes
wearable_battery_pct
```

Questi dati arrivano da:

```text
data/raw/google_health_samples.csv
data/processed/latest_window.csv
outputs/patient-001-decision.json
```

### 4. Dati beacon / posizione

Visualizzare:

```text
stanza corrente
room_changes
night_room_changes
bedroom_minutes
kitchen_minutes
bathroom_minutes
living_room_minutes
longest_single_room_minutes
```

Questi dati arrivano da:

```text
data/raw/ble_samples.csv
data/processed/latest_window.csv
outputs/patient-001-decision.json
```

### 5. AI explanation

La dashboard medico dovrebbe mostrare il perche' dello score.

Nel JSON finale abbiamo:

```text
evidence.fusion.models.generic_wearable.feature_explanation
evidence.fusion.models.generic_spatial.feature_explanation
```

Quindi si puo' mostrare:

```text
score finale
score wearable
score spatial/beacon
feature wearable piu' anomale
feature spaziali piu' anomale
```

Esempio wearable:

```text
heart_rate_mean
heart_rate_std
spo2_mean
steps
sedentary_minutes
```

Esempio spatial:

```text
room_changes
bedroom_minutes
kitchen_minutes
bathroom_minutes
living_room_minutes
```

Nota importante: queste spiegazioni sono tecniche. Indicano quali feature sono lontane
dal training del modello, non sono una diagnosi clinica.

### 6. Storico

Serve per vedere andamento nel tempo:

```text
score finale nel tempo
heart rate nel tempo
SpO2 nel tempo
passi nel tempo
stanza nel tempo
minuti per stanza
alert nel tempo
qualita dati nel tempo
```

Per storico e grafici conviene salvare su database quello che oggi e' nei JSON/CSV.

### 7. Stato sistema

Mostrare:

```text
Raspberry online/offline
ultimo ciclo completato
MQTT connesso/non connesso
BLE receiver attivo
Google Health attivo
ultimo refresh token ok/non ok
ultimo file raw scritto
qualita dati
```

Questa parte e' fondamentale per distinguere:

```text
problema clinico/comportamentale
problema tecnico di raccolta dati
```

### 8. Task e test cognitivi

La dashboard medico dovrebbe avere una sezione dedicata a task inviati al paziente:

```text
test inviati
test completati
test scaduti
risultati
tempo di completamento
storico risposte
note del medico
```

Il medico deve poter creare un nuovo task scegliendo:

```text
paziente
tipo test
priorita
scadenza
testo istruzione
notifica immediata o programmata
```

Questo rende la dashboard medico non solo osservativa, ma anche operativa.

## Livelli alert

Scala attuale:

```text
0-35    green     normale
35-65   yellow    attenzione lieve, dashboard si', alert forte no
65-80   orange    anomalia importante, alert se confermata dal debounce
80-100  red       anomalia severa, alert immediato
technical          problema tecnico, separato dagli alert clinici
```

Uso consigliato in dashboard:

```text
green     -> stato normale
yellow    -> evidenziare ma non trattare come emergenza
orange    -> alert importante, da verificare
red       -> alert severo
technical -> problema device/sensori/token
```

## Dati da pubblicare dal Raspberry

Il Raspberry dovrebbe pubblicare almeno:

### Stato ciclo

Da `outputs/last-cycle.json`:

```text
status
patient_id
window_start/window_end
window_start_local/window_end_local
quality_status
google_health_enabled
google_health_samples_logged
received_google_health_csv
google_health_available_features
received_ble_csv
inference
decision_level
should_publish
fusion_mode
```

### Decisione AI

Da `outputs/patient-001-decision.json`:

```text
level
should_publish
anomaly_score
reasons
evidence.fusion
window_start/window_end
```

### Ultima finestra dati

Da `data/processed/latest_window.csv`:

```text
wearable features
spatial/BLE features
NILM features, se presenti
```

## Dati app paziente e task medico

Oltre ai dati prodotti dal Raspberry, il backend dovra' gestire anche dati generati
dall'app paziente.

### Task inviati dal medico

```text
task_id
patient_id
doctor_id
type: cognitive_test / exercise / check_in / reminder
status: created / sent / seen / completed / expired
priority
created_at
expires_at
payload
```

### Risultati inviati dal paziente

```text
task_id
patient_id
started_at
completed_at
answers
score
duration_seconds
device_info
```

### Stato app paziente

```text
app_online
last_seen
ble_monitoring_active
last_room
phone_battery
raspberry_reachable
notifications_enabled
```

Questi dati non arrivano dal Raspberry, ma direttamente dall'app paziente al backend.
Servono per capire se il paziente sta usando correttamente il sistema.

## Database consigliato

Per una prima versione:

```text
PostgreSQL o SQLite
```

PostgreSQL e' migliore se ci sara' backend vero o piu' pazienti.
SQLite puo' bastare per un prototipo locale.

Tabelle minime:

```text
patients
doctors
edge_cycles
decisions
latest_windows / feature_windows
alerts
sensor_status
patient_app_status
tasks
task_results
notifications
```

## Prima versione consigliata

Per non complicare troppo:

```text
1. Raspberry produce JSON/CSV come adesso
2. aggiungere publisher MQTT sul Raspberry
3. backend unico riceve MQTT e salva su database
4. dashboard medico web legge REST + WebSocket
5. app Android paziente continua a fare BLE e invio al Raspberry
6. backend invia task/notifiche all'app paziente
7. app paziente invia risultati test/task al backend
```

In questa fase non servono microservizi separati.

## Perche' web per medico e app mobile per paziente

Dashboard medico web:

```text
schermo grande
grafici piu' leggibili
storico e tabelle
facile accesso da PC/tablet
aggiornamenti rapidi senza installare app
```

App paziente mobile:

```text
necessaria per BLE
sempre vicina al paziente
puo' lavorare in background
puo' inviare stanza al Raspberry
puo' ricevere notifiche
puo' mostrare dashboard personale semplice
puo' eseguire test cognitivi e inviare risultati
```

Fare tutto web sarebbe debole per il paziente, perche' il browser non e' ideale per il
monitoraggio BLE continuo in background.

Fare tutto mobile sarebbe scomodo per il medico, perche' grafici, storico e confronto
sono molto piu' leggibili in web dashboard.

## Riassunto finale

Scelta consigliata:

```text
App paziente: Android mobile
App caregiver: Android/iOS mobile
Dashboard medico: web app
BLE: localizzazione indoor
MQTT: Raspberry -> backend
WebSocket: backend -> dashboard realtime
Push notification: backend -> app paziente e caregiver
REST API: dashboard/app -> backend
Microservizi: non subito, backend modulare unico
```

Questa scelta mantiene il progetto realistico, scalabile e comprensibile.
