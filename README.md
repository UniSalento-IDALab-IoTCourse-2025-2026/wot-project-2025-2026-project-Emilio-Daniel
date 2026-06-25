# Progetto IoT 2026 - Edge AI ADL

Questo repository contiene il nucleo reale del progetto IoT per il monitoraggio
comportamentale e spaziale delle Attivita' della Vita Quotidiana (ADL).

L'obiettivo non e' sostituire una diagnosi medica, ma costruire un sistema di
triage predittivo basato su Raspberry Pi 4, Google Pixel Watch 2, BLE indoor
positioning, misurazione elettrica/NILM e modello di Anomaly Detection eseguito
in locale.

Il progetto e' pensato per usare dati reali. Non stiamo addestrando il modello
finale su dati simulati: la baseline verra' raccolta dal setup reale installato
sul Raspberry Pi.

## Architettura

```text
Google Pixel Watch 2 / Fitbit API
        |
        v
Fitbit/Google Health adapter

BLE samples da Android/beacon indoor
        |
        v
BLE adapter

Shelly EM / NILM samples
        |
        v
Shelly adapter

        tutti gli adapter
              |
              v
edge_ingest aggrega una finestra da 8 minuti
              |
              v
data/processed/latest_window.csv
              |
              v
edge_ai esegue Isolation Forest + debounce
              |
              v
outputs/patient-001-decision.json
```

## Struttura

```text
config/
  edge.example.yml      Configurazione esempio dell'edge node

android_app/
  app Android per scansione BLE/manual test e invio dati al Raspberry

edge_ingest/
  config.py             Lettura configurazione YAML
  time_windows.py       Calcolo finestre temporali
  ble_collector.py      Scanner BLE alternativo da Raspberry
  ble_cli.py            Comando BLE discover/scan alternativo
  fitbit_adapter.py     Polling reale Fitbit Web API via OAuth token
  ble_adapter.py        Aggregazione campioni BLE gia' raccolti
  shelly_adapter.py     Aggregazione campioni Shelly/NILM gia' raccolti
  aggregator.py         Fusione dati in una riga feature
  cli.py                Comando collect-window

edge_ai/
  schema.py             Contratto delle feature in ingresso
  features.py           Lettura e validazione CSV/JSON
  model.py              Isolation Forest paziente-specifica
  debounce.py           Anti alarm fatigue e alert tecnici
  cli.py                Comandi train/infer

edge_receiver/
  app.py                Receiver HTTP locale sul Raspberry Pi
  ble_storage.py        Scrittura campioni BLE Android nel CSV grezzo
  cli.py                Comando per avviare il receiver

docs/
  ANDROID_APP.md        Guida app Android, emulatore e APK
  API_CONSTRAINTS.md    Vincoli reali Google/Fitbit e BLE
  FEATURE_SCHEMA.md     Schema dataset reale
  REAL_DATA_PLAN.md     Piano raccolta dati reali
  RPI_DEPLOYMENT.md     Setup Raspberry Pi
```

## Cosa e' stato fatto finora

- Ho letto il PDF/proposta del progetto e ho ricostruito l'architettura reale:
  Pixel Watch 2, Raspberry Pi 4, BLE indoor positioning, Shelly/NILM, Edge AI e dashboard.
- Ho verificato i vincoli pratici delle API: i dati biometrici del Pixel Watch non vanno
  letti come stream BLE grezzo, ma tramite Google Health/Fitbit API con OAuth.
- Ho creato il nucleo `edge_ai`, pensato per girare sia su questo PC sia sul Raspberry Pi.
- Ho definito lo schema delle feature reali che gli adapter hardware devono produrre.
- Ho implementato un modello paziente-specifico con `IsolationForest` per anomaly detection ADL.
- Ho aggiunto una logica di debounce per ridurre falsi allarmi e alarm fatigue.
- Ho distinto gli alert clinici dagli alert tecnici, ad esempio wearable scarico o non indossato.
- Ho creato la CLI AI con due comandi: training della baseline reale e inferenza sull'ultima finestra.
- Ho rimosso `joblib` e ora salvo/carico i modelli con `pickle` standard in file `.pkl`.
- Ho creato il nuovo pacchetto `edge_ingest`, cioe' il ponte tra dati reali e modello AI.
- Ho aggiunto una configurazione YAML di esempio in `config/edge.example.yml`.
- Ho implementato un primo adapter Fitbit Web API, pronto a usare un token OAuth reale.
- Ho implementato adapter CSV per BLE e Shelly/NILM, cosi' appena il Raspberry raccoglie campioni
  grezzi possiamo aggregarli in feature.
- Ho predisposto la parte BLE lato aggregazione: il sistema sa leggere campioni stanza/RSSI
  da `data/raw/ble_samples.csv` e trasformarli in feature per il modello.
- Ho aggiunto il receiver HTTP locale per Android: il telefono potra' inviare campioni BLE
  al Raspberry con `POST /ble/sample`.
- Ho creato l'app Android `IoT Edge Companion` in `android_app/`, con modalita manuale
  per emulatore e modalita BLE reale per telefono fisico.
- Ho aggiunto il Foreground Service BLE nell'app Android, cosi' il monitoraggio puo'
  restare attivo in background con notifica persistente.
- Ho aggiunto il comando che genera `data/processed/latest_window.csv`.
- Ho aggiornato la documentazione di deployment su Raspberry Pi.
- Ho eseguito controlli di compilazione/import e test tecnici end-to-end della pipeline.

## In parole povere

Per ora abbiamo costruito le fondamenta del sistema.

Abbiamo preparato il "cervello" del progetto, cioe' il modulo AI che ricevera' i dati
del paziente, imparera' la sua routine quotidiana e poi segnalera' eventuali anomalie.
Questo modulo non fa diagnosi mediche: produce solo un livello di attenzione, ad esempio
routine normale, sospetto lieve, allarme severo oppure problema tecnico.

Abbiamo anche preparato il "traduttore" tra i sensori reali e il modello AI. Questo pezzo
si chiama `edge_ingest`: prende dati da Fitbit/Pixel Watch, BLE e Shelly, li mette tutti
nello stesso formato e produce un file CSV che il modello sa leggere.

Quindi oggi non abbiamo ancora collegato fisicamente i sensori reali, ma abbiamo gia'
deciso e implementato come dovranno parlare con il resto del sistema. Quando arrivera'
il Raspberry Pi, dovremo collegare una sorgente alla volta:

1. Fitbit/Pixel Watch tramite API e OAuth.
2. BLE tramite telefono Android come scanner mobile dei beacon nelle stanze.
3. Shelly tramite lettura HTTP dei consumi.

Dopo il collegamento, il Raspberry raccogliera' dati veri per circa due settimane.
Questi dati formeranno la baseline personale del paziente. Solo dopo quella fase
addestreremo il modello definitivo e lo useremo per rilevare anomalie reali.

## Step attuale

Il nuovo step implementato e' l'aggregatore Edge:

```bash
python -m edge_ingest.cli --config config/edge.example.yml
```

Questo comando:

1. legge la configurazione;
2. calcola l'ultima finestra temporale da 8 minuti;
3. interroga gli adapter abilitati;
4. fonde le feature in una singola riga;
5. scrive `data/processed/latest_window.csv`.

Se vuoi costruire la baseline reale, il comando diventa:

```bash
python -m edge_ingest.cli --config config/edge.example.yml --append-baseline
```

In questo caso, oltre a scrivere `latest_window.csv`, appende la riga anche a:

```text
data/processed/baseline.csv
```

## Configurazione

Il file di partenza e':

```text
config/edge.example.yml
```

Nel file di esempio BLE e' abilitato per testare subito il flusso Android/receiver,
mentre Fitbit e Shelly restano disabilitati finche' non avremo credenziali o hardware:

```yaml
fitbit:
  enabled: false

ble:
  enabled: true

shelly:
  enabled: false
```

Quando avremo credenziali e hardware, abiliteremo anche le altre sorgenti una alla volta.

## Fitbit / Pixel Watch 2

Il file token non va committato. Deve essere creato localmente cosi':

```text
config/fitbit_token.json
```

Formato previsto:

```json
{
  "access_token": "TOKEN_OAUTH_REALE"
}
```

Poi si abilita Fitbit nel file YAML:

```yaml
fitbit:
  enabled: true
  token_file: config/fitbit_token.json
  user_id: "-"
  api_base_url: https://api.fitbit.com
```

L'adapter attuale legge:

- frequenza cardiaca intraday;
- media e deviazione standard della frequenza cardiaca nella finestra;
- resting heart rate se presente;
- HRV giornaliero se disponibile;
- SpO2 giornaliero se disponibile;
- sleep summary se disponibile;
- batteria e presenza wearable tramite device status se disponibile.

Nota: OAuth completo con refresh token sara' uno dei prossimi step. Per ora il modulo
si aspetta un `access_token` valido.

## BLE indoor positioning

Per il nostro progetto scegliamo questa impostazione come riferimento:

- beacon BLE fissi nelle stanze;
- telefono Android indossato/tenuto dal paziente come scanner mobile;
- il telefono scansiona i beacon, sceglie quello con RSSI piu' forte e stima la stanza;
- il telefono invia al Raspberry Pi una riga con `timestamp`, `room`, `rssi` e `beacon_id`;
- questa soluzione e' piu' vicina all'idea "seguo il paziente in casa" con un solo Raspberry Pi fisso.

Questa parte e' gia' predisposta lato software: abbiamo creato sia il receiver locale
sul Raspberry/PC sia l'app Android che puo' inviare campioni manuali e avviare un
Foreground Service BLE per il monitoraggio in background.

### Hardware previsto

Per la prima versione reale servono:

- beacon BLE configurabili, uno per stanza;
- un telefono Android che resta vicino/addosso al paziente;
- un Raspberry Pi locale fisso, usato come gateway e receiver dati;
- rete locale condivisa tra telefono Android e Raspberry Pi.

Ogni beacon avra' una stanza associata, ad esempio:

```yaml
beacons:
  AA:BB:CC:DD:EE:01: kitchen
  AA:BB:CC:DD:EE:02: bedroom
  AA:BB:CC:DD:EE:03: bathroom
  AA:BB:CC:DD:EE:04: living_room
```

L'app Android usera' questa mappa per trasformare il beacon piu' vicino nella stanza
corrente. Il Raspberry non dovra' stimare la stanza: dovra' ricevere e salvare il dato.

### Cosa abbiamo fatto con Android

Abbiamo preparato:

1. app Android minimale per invio manuale e scansione beacon BLE;
2. mappa `beacon_id -> stanza`;
3. scelta della stanza tramite RSSI piu' forte;
4. invio HTTP al Raspberry Pi;
5. receiver locale sul Raspberry, gia' predisposto in `edge_receiver`;
6. salvataggio in `data/raw/ble_samples.csv`;
7. aggregazione con il codice gia' presente;
8. Foreground Service BLE, cioe' monitoraggio in background con notifica persistente.

L'app Android e' gia' stata creata in:

```text
android_app/
```

Ha due modalita:

- manuale/emulatore: inseriamo stanza, RSSI e beacon id a mano e testiamo l'invio HTTP;
- BLE reale: su telefono Android fisico scansionera' i beacon e inviera' automaticamente
  la stanza stimata.

La modalita BLE reale viene gestita da un Foreground Service Android: dopo aver premuto
`Avvia monitoraggio BLE`, l'app continua a lavorare in background e mostra una notifica
persistente. Questo e' importante per il progetto reale, perche' il telefono deve restare
attivo anche quando lo schermo e' spento o l'app non e' in primo piano.

### Receiver Raspberry per Android

Avvio del receiver locale:

```bash
python -m edge_receiver.cli --config config/edge.yml --host 0.0.0.0 --port 8000
```

Endpoint disponibile:

```text
POST /ble/sample
```

Payload che l'app Android dovra' inviare:

```json
{
  "timestamp": "2026-06-25T10:00:00Z",
  "room": "kitchen",
  "rssi": -61,
  "beacon_id": "AA:BB:CC:DD:EE:01",
  "beacon_name": "KitchenBeacon",
  "phone_id": "android-phone"
}
```

Test manuale da terminale:

```bash
curl -X POST http://RASPBERRY_IP:8000/ble/sample \
  -H "Content-Type: application/json" \
  -d '{"room":"kitchen","rssi":-61,"beacon_id":"AA:BB:CC:DD:EE:01","beacon_name":"KitchenBeacon","phone_id":"android-phone"}'
```

Il receiver appende il campione a:

```text
data/raw/ble_samples.csv
```

### Test app Android senza beacon

Senza telefono Android fisico e senza beacon non possiamo testare il BLE reale, ma possiamo
testare tutta la parte applicativa e di rete:

```text
App Android in emulatore
        |
        v
POST /ble/sample
        |
        v
Receiver Raspberry/PC
        |
        v
data/raw/ble_samples.csv
        |
        v
edge_ingest
```

Per provarla:

1. avviare il receiver sul PC:

```bash
python -m edge_receiver.cli --config config/edge.example.yml --host 0.0.0.0 --port 8000
```

2. aprire `android_app/` in Android Studio;
3. avviare l'app su emulatore;
4. usare come URL:

```text
http://10.0.2.2:8000/ble/sample
```

5. premere `Invia campione manuale`;
6. controllare che il campione arrivi in:

```text
data/raw/ble_samples.csv
```

### Rendere l'app installabile su Android

Per generare un APK:

1. aprire Android Studio;
2. `File -> Open`;
3. selezionare la cartella `android_app`;
4. attendere il sync Gradle;
5. scegliere `Build -> Build Bundle(s) / APK(s) -> Build APK(s)`;
6. al termine cliccare `locate` per trovare l'APK.

Per installarla su un telefono Android:

1. abilitare le opzioni sviluppatore;
2. abilitare debug USB;
3. collegare il telefono via USB;
4. premere `Run` da Android Studio oppure installare l'APK generato.

Per una versione finale firmata:

1. `Build -> Generate Signed Bundle / APK`;
2. scegliere `APK`;
3. creare o selezionare un keystore;
4. scegliere build type `release`;
5. generare l'APK firmato.

Il collector scrive un CSV reale:

```text
data/raw/ble_samples.csv
```

Formato minimo:

```csv
timestamp,room,scanner_id,address,name,rssi,tx_power,distance_m,service_uuids,manufacturer_data
2026-06-24T10:00:00Z,kitchen,android-phone,AA:BB:CC:DD:EE:01,KitchenBeacon,-61,-59,1.259,[],{}
2026-06-24T10:02:00Z,living_room,android-phone,AA:BB:CC:DD:EE:04,LivingBeacon,-70,-59,3.548,[],{}
```

Feature prodotte:

- `room_changes`;
- `night_room_changes`;
- `bedroom_minutes`;
- `kitchen_minutes`;
- `bathroom_minutes`;
- `living_room_minutes`;
- `longest_single_room_minutes`.

L'aggregatore legge questo file e produce feature di permanenza stanza compatibili con
il modello AI.

## Shelly / NILM

L'adapter Shelly attuale aggrega un CSV reale gia' raccolto dal Raspberry:

```text
data/raw/shelly_samples.csv
```

Formato minimo:

```csv
timestamp,power_w
2026-06-24T10:00:00Z,42.5
2026-06-24T10:01:00Z,44.1
```

Formato esteso, utile quando aggiungiamo una prima disaggregazione NILM:

```csv
timestamp,power_w,appliance,tv_active
2026-06-24T10:00:00Z,800,coffee,0
2026-06-24T10:04:00Z,120,tv,1
```

Feature prodotte:

- `nilm_total_wh`;
- `nilm_kitchen_events`;
- `nilm_tv_minutes`;
- `nilm_coffee_events`;
- `nilm_stove_events`.

## Comandi principali

Raccogliere ultima finestra reale:

```bash
python -m edge_ingest.cli --config config/edge.example.yml
```

Raccogliere ultima finestra e aggiungerla alla baseline:

```bash
python -m edge_ingest.cli --config config/edge.example.yml --append-baseline
```

Training su baseline reale:

```bash
python -m edge_ai.cli train \
  --input data/processed/baseline.csv \
  --patient-id patient-001 \
  --output models/patient-001.pkl
```

Inferenza su ultima finestra reale:

```bash
python -m edge_ai.cli infer \
  --model models/patient-001.pkl \
  --input data/processed/latest_window.csv \
  --state data/state/patient-001-debounce.json \
  --output outputs/patient-001-decision.json
```

## Flusso sul Raspberry Pi

Durante la raccolta baseline:

```bash
python -m edge_ingest.cli --config config/edge.yml --append-baseline
```

Dopo circa due settimane:

```bash
python -m edge_ai.cli train \
  --input data/processed/baseline.csv \
  --patient-id patient-001 \
  --output models/patient-001.pkl
```

Durante il funzionamento normale:

```bash
python -m edge_ingest.cli --config config/edge.yml
python -m edge_ai.cli infer \
  --model models/patient-001.pkl \
  --input data/processed/latest_window.csv \
  --state data/state/patient-001-debounce.json \
  --output outputs/patient-001-decision.json
```

## Prossimi step

1. Testare il Foreground Service BLE su telefono Android fisico con beacon reali.
2. Implementare OAuth Fitbit completo con refresh token.
3. Implementare collector Shelly reale via HTTP e salvataggio campioni, se useremo Shelly.
4. Preparare `config/edge.yml` reale per il vostro paziente/test.
5. Avviare raccolta baseline reale.
6. Addestrare il modello.
7. Collegare output JSON al backend/dashboard.

## Stato attuale del progetto

Questa sezione riassume in parole povere cosa e' stato fatto finora. Va aggiornata
ogni volta che aggiungiamo un nuovo pezzo al sistema.

### 1. Modulo AI

Abbiamo creato il modulo `edge_ai`.

Questo e' il cervello del sistema. Legge dati aggregati ogni 8 minuti, usa un modello
`IsolationForest` e produce un livello di rischio:

- verde: routine normale;
- giallo: sospetto lieve;
- rosso: anomalia severa;
- tecnico: problema non clinico, per esempio wearable scarico o non indossato.

Il modello non fa diagnosi medica. Serve solo a segnalare anomalie nella routine del
paziente.

### 2. Aggregatore dati

Abbiamo creato il modulo `edge_ingest`.

Questo modulo prende dati da Fitbit, BLE e Shelly, li mette tutti nello stesso formato
e produce il file:

```text
data/processed/latest_window.csv
```

Durante la fase di baseline puo' anche costruire:

```text
data/processed/baseline.csv
```

Questi file sono quelli che il modello AI sa leggere.

### 3. Fitbit / Pixel Watch

Abbiamo preparato un primo adapter per Fitbit Web API.

La struttura e' pronta per leggere dati biometrici dal Pixel Watch tramite API, ma manca
ancora la parte completa di OAuth con refresh token. Questa verra' fatta quando avremo
account, permessi e dispositivo configurati.

### 4. BLE indoor positioning

Abbiamo chiarito l'architettura corretta per il nostro caso:

```text
Beacon BLE fissi nelle stanze
        +
Telefono Android come scanner mobile
        +
Raspberry Pi come receiver/gateway
```

Il telefono Android stara' vicino/addosso al paziente, scansionera' i beacon nelle stanze
e inviera' al Raspberry la stanza stimata.

Il sistema sa gia' leggere campioni BLE da CSV e trasformarli in feature come:

- minuti in camera;
- minuti in cucina;
- minuti in bagno;
- minuti in soggiorno;
- cambi stanza;
- cambi stanza notturni;
- permanenza piu' lunga in una singola stanza.

### 5. Receiver Raspberry per Android

Abbiamo creato il modulo `edge_receiver`.

Questo sara' il server locale sul Raspberry Pi. Espone l'endpoint:

```text
POST /ble/sample
```

L'app Android inviera' dati di questo tipo:

```json
{
  "room": "kitchen",
  "rssi": -61,
  "beacon_id": "AA:BB:CC:DD:EE:01"
}
```

Il Raspberry salva questi campioni in:

```text
data/raw/ble_samples.csv
```

Poi `edge_ingest` li aggrega e li passa al modello AI.

### 6. App Android

Abbiamo creato l'app `IoT Edge Companion` dentro `android_app/`.

L'app serve per due cose:

- test manuale da emulatore, senza beacon fisici;
- scansione BLE reale quando avremo telefono Android e beacon.

In modalita manuale possiamo gia' inviare campioni finti al receiver Raspberry e vedere
come vengono salvati nel CSV.

In modalita reale l'app scansionera' i beacon nelle stanze, scegliera' quello con RSSI
piu' forte e inviera' la stanza stimata al Raspberry.

Abbiamo aggiunto anche un Foreground Service BLE: quando viene premuto `Avvia monitoraggio
BLE`, Android mantiene l'app attiva in background con una notifica persistente. Il servizio
fa cicli periodici di scansione, sceglie il beacon/stanza piu' forte e invia il campione
al receiver locale.

### 7. Shelly / NILM

Abbiamo predisposto un adapter per dati Shelly/NILM.

Per ora non abbiamo ancora deciso se useremo davvero Shelly o un altro dispositivo di
misurazione consumi. Il codice e' pronto a leggere dati da:

```text
data/raw/shelly_samples.csv
```

### 8. Documentazione

Abbiamo documentato architettura, comandi, deployment Raspberry, schema feature e vincoli
reali delle API.

Il README deve rimanere il punto principale da leggere per capire lo stato del progetto.

### 9. Cosa manca ancora

Mancano ancora i collegamenti reali con hardware:

- test app Android su telefono fisico;
- beacon BLE fisici nelle stanze;
- Raspberry Pi reale;
- Fitbit OAuth completo;
- eventuale Shelly o alternativa per consumi;
- backend/dashboard finale.
