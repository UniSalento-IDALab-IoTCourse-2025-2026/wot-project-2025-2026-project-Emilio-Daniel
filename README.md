Per eliminire tutti i desktop.ini: Get-ChildItem -Path . -Filter "desktop.ini" -Recurse -Force | Remove-Item -Force
Per ottenere le modifiche corrette usare "git pull origin main"

# Progetto IoT 2026

Questo repository contiene il nucleo reale del progetto IoT per il monitoraggio
comportamentale e spaziale delle Attivita' della Vita Quotidiana (ADL).

L'obiettivo non e' sostituire una diagnosi medica, ma costruire un sistema di
triage predittivo basato su Raspberry Pi 5, Google Pixel Watch 2, BLE indoor
positioning, misurazione elettrica/NILM e modello di Anomaly Detection eseguito
in locale.

Il progetto e' pensato per usare dati reali. Non stiamo addestrando il modello
finale su dati simulati: la baseline verra' raccolta dal setup reale installato
sul Raspberry Pi.

La parte AI ora segue un approccio ibrido a tre modelli: un modello generico
spaziale/domestico, un modello generico wearable/fisiologico e un modello personale
addestrato progressivamente sulla baseline reale del paziente. Il sistema confronta
tutti gli score disponibili e produce una decisione fusa.

## Indice

- [Architettura](#architettura)
- [Struttura](#struttura)
- [Cosa e' stato fatto finora](#cosa-e-stato-fatto-finora)
- [In parole povere](#in-parole-povere)
- [Modello AI ibrido](#modello-ai-ibrido)
- [Step attuale](#step-attuale)
- [Configurazione](#configurazione)
- [Google Health / Pixel Watch 2](#google-health--pixel-watch-2)
- [BLE indoor positioning](#ble-indoor-positioning)
  - [Hardware previsto](#hardware-previsto)
  - [Cosa abbiamo fatto con Android](#cosa-abbiamo-fatto-con-android)
  - [Cosa abbiamo fatto con iOS](#cosa-abbiamo-fatto-con-ios)
  - [Receiver Raspberry per app mobile](#receiver-raspberry-per-app-mobile)
  - [Test app Android con beacon reali](#test-app-android-con-beacon-reali)
  - [Rendere l'app installabile su Android](#rendere-lapp-installabile-su-android)
- [Shelly / NILM](#shelly--nilm)
- [Comandi principali](#comandi-principali)
  - [Comando unico consigliato](#comando-unico-consigliato)
  - [Fase baseline](#fase-baseline)
  - [Procedura completa per addestrare il modello sul Raspberry Pi](#procedura-completa-per-addestrare-il-modello-sul-raspberry-pi)
  - [Comandi separati](#comandi-separati)
- [Flusso sul Raspberry Pi](#flusso-sul-raspberry-pi)
- [Prossimi step](#prossimi-step)
- [Stato attuale del progetto](#stato-attuale-del-progetto)

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
edge_ingest aggrega una finestra da 4 minuti
              |
              v
edge_node/data/processed/latest_window.csv
              |
              v
edge_ai esegue generico spaziale + generico wearable + personale + fusione + debounce
              |
              v
edge_node/outputs/patient-001-decision.json
```

## Struttura

```text
avviaSistema       Launcher breve per Raspberry/Linux
avviaSistema.cmd   Launcher breve per Windows
avviaSistema.ps1   Launcher PowerShell alternativo

edge_node/
  requirements.txt      Dipendenze Python del Raspberry/edge node

  config/
    edge.example.yml    Configurazione esempio dell'edge node

  edge_ingest/
    config.py           Lettura configurazione YAML
    time_windows.py     Calcolo finestre temporali
    ble_collector.py    Scanner BLE alternativo da Raspberry
    ble_cli.py          Comando BLE discover/scan alternativo
    fitbit_adapter.py   Polling reale Fitbit Web API via OAuth token
    ble_adapter.py      Aggregazione campioni BLE gia' raccolti
    shelly_adapter.py   Aggregazione campioni Shelly/NILM gia' raccolti
    aggregator.py       Fusione dati in una riga feature
    cli.py              Comando collect-window

  edge_auth/
    fitbit_oauth.py     Setup OAuth Fitbit, salvataggio token e refresh
    cli.py              Comandi fitbit setup/status/refresh

  edge_ai/
    schema.py           Contratto delle feature in ingresso
    features.py         Lettura e validazione CSV/JSON
    model.py            Isolation Forest generica e paziente-specifica
    fusion.py           Fusione tra score spaziale, wearable e personale
    debounce.py         Anti alarm fatigue e alert tecnici
    cli.py              Comandi train/infer

  edge_baseline/
    cli.py              Start/status/finalize/train baseline reale
    session.py          Stato della raccolta baseline

  edge_datasets/
    cli.py              Conversione dataset pubblici nello schema edge
    casas_converter.py  Conversione CASAS in generic_spatial_dataset.csv
    fitbitdata_converter.py Conversione dataset Fitbit-style in generic_wearable_dataset_fitbitdata.csv
    pamap2_converter.py Conversione PAMAP2 in generic_wearable_dataset_pamap2.csv
    wesad_converter.py  Conversione WESAD in generic_wearable_dataset_wesad.csv
    merge.py            Unione CSV convertiti nello schema feature ufficiale

  edge_receiver/
    app.py              Receiver HTTP locale sul Raspberry Pi
    ble_storage.py      Scrittura campioni BLE Android nel CSV grezzo
    cli.py              Comando per avviare il receiver

  edge_runtime/
    cli.py              Ciclo edge: aggregazione, qualita, inferenza e decisione

  edge_stack/
    cli.py              Comando unico per receiver BLE + runtime continuo

  edge_quality/
    checks.py           Controlli qualita dati prima di baseline/training
    cli.py              Comando manuale per generare report qualita

  data/
    raw/                Campioni grezzi reali da app/sensori
    processed/          Finestre aggregate per AI
    state/              Stato debounce/allarmi

  models/               Modelli generici e modelli paziente-specifici
  outputs/              Decisioni JSON prodotte dall'AI

Applicazione IoT Companion/
  companion_Android_app/
    app Android per scansione BLE/manual test e invio dati al Raspberry
  companion_iOS_app/
    sorgenti Swift/SwiftUI preparati, ma per ora sospesi perche' useremo Android

Documenti/
  ANDROID_APP.md        Guida app Android, emulatore e APK
  BEACON_SETUP.md       Setup reale dei 3 BlueBeacon 01
  API_CONSTRAINTS.md    Vincoli reali Google/Fitbit e BLE
  GOOGLE_WATCH_SETUP.md Procedura Pixel Watch 2 / Google Health API
  FEATURE_SCHEMA.md     Schema dataset reale
  REAL_DATA_PLAN.md     Piano raccolta dati reali
  RPI_DEPLOYMENT.md     Setup Raspberry Pi
```

Regola pratica: i comandi Python del Raspberry/AI vanno eseguiti entrando prima in
`edge_node/`. L'app Android si apre da Android Studio selezionando
`Applicazione IoT Companion/companion_Android_app/`.
L'app iOS si crea su Mac con Xcode usando i file in
`Applicazione IoT Companion/companion_iOS_app/`.

## Cosa e' stato fatto finora

- Ho letto il PDF/proposta del progetto e ho ricostruito l'architettura reale:
  Pixel Watch 2, Raspberry Pi 5, BLE indoor positioning, Shelly/NILM, Edge AI e dashboard.
- Ho verificato i vincoli pratici delle API: i dati biometrici del Pixel Watch non vanno
  letti come stream BLE grezzo, ma tramite Google Health/Fitbit API con OAuth.
- Ho creato il nucleo `edge_ai`, pensato per girare sia su questo PC sia sul Raspberry Pi.
- Ho definito lo schema delle feature reali che gli adapter hardware devono produrre.
- Ho implementato un modello paziente-specifico con `IsolationForest` per anomaly detection ADL.
- Ho esteso l'AI a tre modelli: `models/generic_spatial.pkl`,
  `models/generic_wearable.pkl` e `models/patient-001.pkl`.
- Ho aggiunto `edge_ai/fusion.py`, che confronta score spaziale, wearable e personale.
- Ho aggiunto una logica di debounce per ridurre falsi allarmi e alarm fatigue.
- Ho distinto gli alert clinici dagli alert tecnici, ad esempio wearable scarico o non indossato.
- Ho creato la CLI AI con due comandi: training della baseline reale e inferenza sull'ultima finestra.
- Ho rimosso `joblib` e ora salvo/carico i modelli con `pickle` standard in file `.pkl`.
- Ho creato il nuovo pacchetto `edge_ingest`, cioe' il ponte tra dati reali e modello AI.
- Ho aggiunto una configurazione YAML di esempio in `edge_node/config/edge.example.yml`.
- Ho implementato l'adapter Google Health per Pixel Watch 2 e mantenuto Fitbit come
  compatibilita legacy.
- Ho aggiunto `edge_auth`, che gestisce token Google Health/Fitbit, salvataggio locale e
  refresh automatico.
- Ho implementato adapter CSV per BLE e Shelly/NILM, cosi' appena il Raspberry raccoglie campioni
  grezzi possiamo aggregarli in feature.
- Ho predisposto la parte BLE lato aggregazione: il sistema sa leggere campioni stanza/RSSI
  da `edge_node/data/raw/ble_samples.csv` e trasformarli in feature per il modello.
- Ho aggiunto il receiver HTTP locale per Android: il telefono potra' inviare campioni BLE
  al Raspberry con `POST /ble/sample`.
- Ho creato l'app Android `IoT Edge Companion` in
  `Applicazione IoT Companion/companion_Android_app/`, ora orientata
  al test BLE reale con telefono fisico e BlueBeacon.
- Ho aggiunto il Foreground Service BLE nell'app Android, cosi' il monitoraggio puo'
  restare attivo in background con notifica persistente.
- Ho riordinato il repository separando `edge_node/`,
  `Applicazione IoT Companion/` e `Documenti/`.
- Ho aggiunto `edge_runtime`, il comando unico che aggrega la finestra e fa inferenza
  automaticamente se trova un modello addestrato.
- Ho aggiunto `edge_quality`, che controlla se i dati sono utilizzabili prima di salvarli
  nella baseline o addestrare il modello.
- Ho aggiunto `edge_baseline`, che gestisce start, raccolta 6 giorni, status e training
  del modello paziente-specifico.
- Ho aggiunto il comando che genera `edge_node/data/processed/latest_window.csv`.
- Ho aggiunto `edge_datasets`, partendo dal converter CASAS per creare
  `generic_spatial_dataset.csv`.
- Ho aggiunto il converter PAMAP2 per creare finestre wearable da heart rate,
  activity id, passi stimati e minuti sedentari.
- Ho aggiunto il converter WESAD per creare finestre wearable da BVP/HRV,
  usando solo label normali e scartando stress/transitori.
- Ho aggiunto il converter `fitbitdata` per usare i dataset locali in
  `data/external/fitbitdata`: HR/HRV, activity, sleep health, `Health data.csv`
  e HuGCDN2014-OXI in formato MATLAB per SpO2/RR.
- Ho unito fitbitdata, PAMAP2 e WESAD in `generic_wearable_dataset.csv`.
- Ho riaddestrato `models/generic_wearable.pkl`: ora il generico wearable usa
  `heart_rate_mean`, `heart_rate_std`, `hrv_rmssd`, `spo2_mean`, `steps` e
  `sedentary_minutes`. HRV ha peso moderato: valori alti/sani non generano
  allarme, valori molto bassi possono produrre attenzione pre-baseline.
- Nel modello generico wearable, `spo2_mean` viene trattata con una regola
  clinica semplice: valori sani/alti vengono normalizzati, mentre valori bassi
  restano informativi. Cosi' una SpO2 pari a 99-100 non genera falsi allarmi.
- Ho creato nella radice `Dataset_Modelli_Generali/` due dataset sintetici
  controllati da 300000 righe ciascuno:
  `generic_spatial_synthetic_300k.csv` e `generic_wearable_synthetic_300k.csv`.
  Servono a calibrare i modelli generici con valori normali/standard e pesi
  ragionati: battito molto alto a riposo pesa piu' di una SpO2 lievemente bassa,
  HRV bassa pesa in modo intermedio e HRV alta/sana non genera falsi allarmi.
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

Dopo il collegamento, il Raspberry raccogliera' dati veri per circa 5/6 giorni.
Durante questi giorni, se avremo gia' `models/generic_spatial.pkl` e/o
`models/generic_wearable.pkl`, il sistema potra' usare i modelli generici come
riferimento iniziale. I dati raccolti formeranno poi la baseline personale del
paziente; dopo il training, ogni finestra verra' valutata dai generici disponibili e
dal modello personale.

## Modello AI ibrido

La nuova architettura AI usa tre livelli:

```text
models/generic_spatial.pkl
  modello generico spaziale/domestico addestrato da CASAS

models/generic_wearable.pkl
  modello generico wearable/fisiologico addestrato da WESAD/PAMAP2 o simili

models/patient-001.pkl
  modello personale addestrato dalla baseline reale raccolta in casa
```

Durante i primi 5/6 giorni:

```text
dati reali ogni 4 minuti
-> controllo qualita
-> modelli generici, se disponibili
-> raccolta baseline personale
```

I modelli generici non si modificano automaticamente con i dati dei primi giorni. Invece
fanno da filtro di sicurezza: se uno score generico supera la soglia configurata, la
finestra puo' essere usata per triage ma non viene aggiunta alla baseline personale.

Dopo la baseline:

```text
dati reali ogni 4 minuti
-> controllo qualita
-> modello generico spaziale   -> generic_spatial_score
-> modello generico wearable   -> generic_wearable_score
-> modello personale           -> personal_score
-> fusione                     -> anomaly_score finale
-> debounce                    -> green / yellow / orange / red / technical
```

Il JSON finale conserva anche `evidence.fusion`, cioe' il riepilogo dei tre modelli.
In questo modo possiamo capire se una segnalazione nasce dalla parte spaziale, dalla
parte wearable, dalla routine personale oppure da una concordanza tra piu' modelli.

Scala operativa dello score:

```text
0-35    green     routine compatibile, nessun alert
35-65   yellow    attenzione lieve, visibile in dashboard ma non pubblicata
65-80   orange    anomalia importante, pubblicata solo se confermata dal debounce
80-100  red       anomalia severa, alert pubblicato subito
```

`technical` resta separato: indica problemi di sensore, batteria, token o wearable non
indossato, non un peggioramento clinico.

Per capire da quale sorgente nasce lo score:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\edge_node
$d = Get-Content outputs\patient-001-decision.json | ConvertFrom-Json
```

Spiegazione orologio / wearable:

```powershell
$d.evidence.fusion.models.generic_wearable.feature_explanation | ConvertTo-Json -Depth 8
```

Spiegazione beacon / BLE:

```powershell
$d.evidence.fusion.models.generic_spatial.feature_explanation | ConvertTo-Json -Depth 8
```

## Step attuale

Il nuovo step implementato e' l'aggregatore Edge:

```bash
cd edge_node
python -m edge_ingest.cli --config config/edge.example.yml
```

Questo comando:

1. legge la configurazione;
2. calcola l'ultima finestra temporale da 4 minuti;
3. interroga gli adapter abilitati;
4. fonde le feature in una singola riga;
5. scrive `data/processed/latest_window.csv`.

Se vuoi costruire la baseline reale, il comando diventa:

```bash
cd edge_node
python -m edge_ingest.cli --config config/edge.example.yml --append-baseline
```

In questo caso, oltre a scrivere `latest_window.csv`, appende la riga anche a:

```text
data/processed/baseline.csv
```

## Configurazione

Il file di partenza e':

```text
edge_node/config/edge.example.yml
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

## Google Health / Pixel Watch 2

Il Google Pixel Watch 2 verra' sincronizzato con l'account Fitbit/Google. Il Raspberry
non legge i dati biometrici grezzi via Bluetooth: li recupera via API dopo autorizzazione
OAuth.

Per nuove credenziali usiamo Google Health API. Fitbit resta nel progetto come adapter
legacy, ma il percorso attuale per Pixel Watch 2 e':

```text
Pixel Watch 2
-> telefono/account Google
-> Google Health API
-> token OAuth locali
-> edge_ingest/google_health_adapter.py
-> latest_window.csv
-> modelli AI
```

I file sensibili non vanno committati:

```text
config/google_health_token.json
config/google_health_client.json
```

La procedura completa di creazione API, OAuth Playground e refresh token e' in:

```text
Documenti/GOOGLE_WATCH_SETUP.md
```

Da dentro `edge_node/`, i comandi principali sono:

```powershell
python -m edge_auth.cli google-health status
python -m edge_auth.cli google-health refresh
python -m edge_runtime.cli --config config\edge.yml --loop
```

Configurazione reale:

```yaml
fitbit:
  enabled: false

google_health:
  enabled: true
  token_file: config/google_health_token.json
  client_file: config/google_health_client.json
  api_base_url: https://health.googleapis.com
  data_delay_minutes: 12
  heart_rate_lookback_minutes: 30
```

L'adapter Google Health legge o stima:

- frequenza cardiaca intraday;
- media e deviazione standard della frequenza cardiaca nella finestra;
- resting heart rate se presente;
- HRV giornaliero se disponibile;
- SpO2 giornaliero se disponibile;
- sleep summary se disponibile;
- passi; se il battito e' valido ma i passi non arrivano, usa `steps = 0.0`;
- minuti sedentari stimati quando possibile;
- batteria e presenza wearable tramite device status se disponibile.

Il refresh token e' gestito automaticamente: non serve rifare login a ogni avvio. Il
refresh manuale serve solo per test/debug.

Nota tecnica: Google Health puo' avere alcuni minuti di ritardo rispetto al watch. Per
questo `data_delay_minutes` e `heart_rate_lookback_minutes` sono configurati dentro
`google_health`: il BLE resta sulla finestra corrente, mentre solo la chiamata cloud usa
una finestra interna piu' consolidata.

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

Nota: abbiamo preparato anche una base iOS, ma per ora la parte beacon reale prosegue su
Android.

### Hardware previsto

Per la prima versione reale servono:

- beacon BLE configurabili, uno per stanza;
- un telefono Android che resta vicino/addosso al paziente;
- un Raspberry Pi locale fisso, usato come gateway e receiver dati;
- rete locale condivisa tra telefono e Raspberry Pi.

Per i 3 BlueBeacon 01 BlueUp abbiamo scelto questa mappa:

```text
Beacon 1 -> Cucina          -> kitchen
Beacon 2 -> Stanza da letto -> bedroom
Beacon 3 -> Bagno           -> bathroom
```

L'app Android usera' una mappa `identificativo_beacon=stanza` per trasformare il beacon
piu' vicino nella stanza corrente. Il formato consigliato per BlueBeacon e' `uuid-major-minor`.
La guida operativa e' in `Documenti/BEACON_SETUP.md`.

### Cosa abbiamo fatto con Android

Abbiamo preparato:

1. app Android per scansione beacon BLE reale;
2. mappa `beacon_id -> stanza`;
3. scelta della stanza tramite RSSI piu' forte;
4. invio HTTP al Raspberry Pi;
5. receiver locale sul Raspberry, gia' predisposto in `edge_receiver`;
6. salvataggio in `data/raw/ble_samples.csv`;
7. aggregazione con il codice gia' presente;
8. Foreground Service BLE, cioe' monitoraggio in background con notifica persistente.

L'app Android e' gia' stata creata in:

```text
Applicazione IoT Companion/companion_Android_app/
```

La modalita principale e' BLE reale: su telefono Android fisico scansionera' i beacon e
inviera' automaticamente la stanza stimata.

La modalita BLE reale viene gestita da un Foreground Service Android: dopo aver premuto
`Avvia monitoraggio BLE`, l'app continua a lavorare in background e mostra una notifica
persistente. Questo e' importante per il progetto reale, perche' il telefono deve restare
attivo anche quando lo schermo e' spento o l'app non e' in primo piano.

### Cosa abbiamo fatto con iOS

Abbiamo creato la cartella:

```text
Applicazione IoT Companion/companion_iOS_app/
```

Dentro ci sono sorgenti Swift/SwiftUI da copiare in un progetto Xcode sul Mac.

L'app iOS contiene:

1. schermata di configurazione del receiver Raspberry;
2. `phone_id` per identificare l'iPhone;
3. mappa `beacon/nome/UUID -> stanza`;
4. invio manuale di campioni BLE per test senza beacon;
5. scansione BLE reale tramite CoreBluetooth;
6. scelta del beacon con RSSI piu' forte;
7. invio HTTP al receiver Raspberry;
8. guida per firma, installazione su iPhone e test.

Nota: il simulatore iOS non e' adatto a testare il BLE reale. Per la scansione serve un
iPhone fisico. Inoltre iOS gestisce il background BLE in modo piu' restrittivo rispetto
ad Android; per beacon iBeacon reali potremo eventualmente evolvere l'app usando
CoreLocation con UUID/major/minor.

### Receiver Raspberry per app mobile

Avvio del receiver locale:

```bash
python -m edge_receiver.cli --config config/edge.yml --host 0.0.0.0 --port 8000
```

Endpoint disponibile:

```text
POST /ble/sample
```

Payload che l'app Android/iOS dovra' inviare:

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

### Test app Android con beacon reali

Per testare la localizzazione reale servono telefono Android fisico e i 3 BlueBeacon accesi:

```text
App Android su telefono fisico
        |
        v
BlueBeacon cucina/camera/bagno
        |
        v
POST /ble/sample con stanza stimata
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

2. aprire `Applicazione IoT Companion/companion_Android_app/` in Android Studio;
3. installare l'app su telefono Android fisico;
4. usare come URL del receiver:

```text
http://IP_DEL_PC_O_RASPBERRY:8000/ble/sample
```

5. verificare la mappa beacon protetta con `admin` / `admin`;
6. premere `Avvia monitoraggio BLE`;
7. spostarsi vicino a cucina, camera e bagno;
8. controllare che i campioni arrivino in:

```text
data/raw/ble_samples.csv
```

### Rendere l'app installabile su Android

Per generare un APK:

1. aprire Android Studio;
2. `File -> Open`;
3. selezionare la cartella `Applicazione IoT Companion/companion_Android_app`;
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

Tutti questi comandi vanno eseguiti da `edge_node/`:

```bash
cd edge_node
```

Se nel terminale vedi gia' `(.venv)`, dopo `cd edge_node` puoi usare direttamente
`python`. Non usare `..\.venv\Scripts\python.exe` dalla root del progetto: quel percorso
vale solo quando sei gia' dentro `edge_node/`.

### Comando unico consigliato

Questo e' il comando breve da usare normalmente dalla root del progetto:

```powershell
.\avviaSistema
```

Su Windows, se PowerShell non esegue lo script senza estensione, usa:

```powershell
.\avviaSistema.cmd
```

Sul Raspberry Pi, dopo il clone, la prima volta rendi eseguibile lo script:

```bash
chmod +x avviaSistema
```

Poi avvii tutto con:

```bash
./avviaSistema
```

Il launcher entra automaticamente in `edge_node/`, sceglie il Python giusto e
avvia lo stack reale: receiver BLE per l'app Android e runtime continuo per Google
Health / Pixel Watch 2. In pratica avvia insieme:

```text
edge_receiver
-> resta in ascolto su http://0.0.0.0:8000
-> riceve i campioni BLE inviati dall'app Android
-> salva/aggiorna data/raw/ble_samples.csv

edge_runtime --loop
-> ogni 4 minuti legge Google Health / Pixel Watch 2
-> legge i campioni BLE gia' ricevuti dal receiver
-> aggrega la finestra da 4 minuti
-> scrive data/processed/latest_window.csv
-> esegue i modelli AI disponibili
-> salva outputs/patient-001-decision.json
-> salva outputs/last-quality-report.json
-> salva outputs/last-cycle.json
```

Il file `config/edge.yml` deve avere abilitate le sorgenti reali:

```yaml
google_health:
  enabled: true
  data_delay_minutes: 0

ble:
  enabled: true
```

Con `google_health.data_delay_minutes: 0`, Watch e BLE vengono letti sulla stessa
finestra corrente da 4 minuti. Quindi, a ogni ciclo, `latest_window.csv` prova a
contenere insieme dati biometrici del Google Watch 2 e permanenza nelle stanze.
Se Google Health non ha ancora sincronizzato un valore, quel campo puo' restare
vuoto/`nan`, ma il sistema non sposta piu' artificialmente la finestra nel passato.

Come per il BLE, anche Google Watch ora ha uno storico raw append-only:

```text
data/raw/google_health_samples.csv
```

Per vedere le ultime righe raccolte dall'orologio:

```powershell
Import-Csv data\raw\google_health_samples.csv | Select-Object -Last 10 | ConvertTo-Json -Depth 4
```

Il comando resta attivo finche' non viene premuto `CTRL+C`. Durante la baseline:

```bash
./avviaSistema --append-baseline
```

Su Windows, la stessa baseline si avvia con:

```powershell
.\avviaSistema --append-baseline
```

Se invece vogliamo fare un solo ciclo manuale, senza tenere acceso anche il receiver,
si puo' ancora usare:

```bash
python -m edge_runtime.cli --config config/edge.yml
```

Il singolo ciclo fa:

```text
legge i dati gia' ricevuti in data/raw/
-> aggrega la finestra da 4 minuti
-> scrive data/processed/latest_window.csv
-> se trova models/generic_spatial.pkl, fa inferenza generica spaziale
-> se trova models/generic_wearable.pkl, fa inferenza generica wearable
-> se trova models/patient-001.pkl, fa inferenza personale
-> fonde tutti i risultati disponibili
-> salva outputs/patient-001-decision.json
-> salva outputs/last-quality-report.json
-> salva outputs/last-cycle.json con lo stato del ciclo
```

Se nessun modello esiste ancora, non fallisce: aggiorna la finestra e scrive nello stato
`skipped_all_models_missing`.

Con `--append-baseline`, il runtime appende anche la finestra a
`data/processed/baseline.csv`, ma solo se i controlli qualita non trovano errori.
Se i dati sono rotti o incompleti, il ciclo scrive
`baseline_skipped_reason: quality_error` e non sporca la baseline.
Se almeno un modello generico e' gia' presente, durante questi giorni il sistema puo'
produrre comunque una decisione basata sui modelli disponibili.
Se un modello generico segnala una finestra sospetta, il ciclo scrive
`baseline_skipped_reason: generic_safety_gate` e non usa quella finestra per addestrare
la normalita personale.

Controllo qualita manuale sull'ultima finestra:

```bash
python -m edge_quality.cli --config config/edge.example.yml
```

Il report viene salvato in:

```text
outputs/last-quality-report.json
```

### Fase baseline

Quando avremo hardware reale e dati veri, la baseline si avvia cosi':

Nota: per vincoli di tempo useremo una baseline compatta da 5/6 giorni. Una baseline
piu' lunga, ad esempio 14 giorni, sarebbe piu' rappresentativa; nel progetto va dichiarato
che il training e' basato su una finestra ridotta ma reale.

```bash
python -m edge_baseline.cli --config config/edge.yml start --days 6
```

Durante i 6 giorni il cron/systemd deve eseguire:

```bash
python -m edge_runtime.cli --config config/edge.yml --append-baseline
```

Il runtime aggiunge una finestra a `data/processed/baseline.csv` solo se i controlli
qualita non hanno errori. Lo stato della raccolta viene salvato in:

```text
data/state/baseline-session.json
```

Per vedere avanzamento, finestre accettate/rifiutate e prontezza al training:

```bash
python -m edge_baseline.cli --config config/edge.yml status
```

Dopo circa 6 giorni:

```bash
python -m edge_baseline.cli --config config/edge.yml finalize
python -m edge_baseline.cli --config config/edge.yml train
```

Il modello viene salvato in `models/patient-001.pkl`.

### Procedura completa per addestrare il modello sul Raspberry Pi

Questa e' la procedura che seguiremo quando il sistema sara' reale:

```text
Raspberry Pi
  -> esegue edge_receiver, edge_runtime, edge_quality, edge_baseline, edge_ai

Beacon BLE nelle stanze
  -> identificano la stanza tramite segnale BLE

Braccialetto / wearable al polso
  -> produce dati reali del paziente
  -> nel caso Google Pixel Watch 2: dati biometrici via Google Health API
  -> nel caso tag BLE: dati di prossimita/localizzazione da trasformare in campioni BLE
```

Nota importante: il modello non viene addestrato direttamente sui beacon o sul braccialetto
grezzo. Il modello viene addestrato su `data/processed/baseline.csv`, cioe' sulle feature
aggregate ogni 4 minuti dal Raspberry.

I modelli generici, invece, si addestrano prima su dataset esterni gia' trasformati nello
stesso schema feature. Gli artefatti saranno `models/generic_spatial.pkl` e
`models/generic_wearable.pkl`, installabili sul Raspberry prima della baseline del paziente.

#### 1. Preparare Raspberry Pi

Sul Raspberry metteremo questa repository e useremo la cartella:

```bash
cd edge_node
```

Poi installeremo le dipendenze Python:

```bash
python -m pip install -r requirements.txt
```

Sul Raspberry reale creeremo anche:

```text
config/edge.yml
```

partendo da:

```text
config/edge.example.yml
```

Nel file reale imposteremo anche i percorsi AI:

```yaml
ai:
  generic_model: models/generic_spatial.pkl
  generic_spatial_model: models/generic_spatial.pkl
  generic_wearable_model: models/generic_wearable.pkl
  personal_model: models/patient-001.pkl
  baseline_gate_enabled: true
  baseline_gate_block_score: 60.0
```

#### 2. Configurare beacon e braccialetto

Per le stanze:

```text
1 beacon BLE in cucina
1 beacon BLE in camera
1 beacon BLE in bagno
1 beacon BLE in soggiorno
```

Per ogni beacon dobbiamo annotare:

```text
MAC address o UUID
nome beacon
stanza associata
posizione fisica nella stanza
```

Esempio mappa:

```text
AA:BB:CC:DD:EE:01=kitchen
AA:BB:CC:DD:EE:02=bedroom
AA:BB:CC:DD:EE:03=bathroom
AA:BB:CC:DD:EE:04=living_room
```

Il braccialetto sul polso serve a rappresentare il paziente. Nel nostro progetto puo'
avere due ruoli:

```text
Google Pixel Watch 2 / Google Health
  -> dati biometrici: frequenza cardiaca, HRV, SpO2, sonno, batteria

Tag BLE / dispositivo indossabile BLE
  -> dati di posizione indoor rispetto ai beacon
```

Se useremo l'app Android `Applicazione IoT Companion/companion_Android_app`, sara' il telefono Android a scansionare i beacon
e inviare al Raspberry la stanza stimata. Se invece useremo un vero braccialetto BLE/tag,
dovremo assicurarci che il Raspberry riceva comunque righe nel formato:

```csv
timestamp,room,scanner_id,address,name,rssi,tx_power,distance_m,service_uuids,manufacturer_data
2026-06-26T10:00:00Z,kitchen,bracelet-001,AA:BB:CC:DD:EE:01,KitchenBeacon,-61,-59,1.2,[],{}
```

Queste righe devono finire in:

```text
data/raw/ble_samples.csv
```

#### 3. Avviare il receiver sul Raspberry

Il receiver deve rimanere acceso per ricevere campioni dall'app Android o dal sistema BLE:

```bash
python -m edge_receiver.cli --config config/edge.yml --host 0.0.0.0 --port 8000
```

L'endpoint sara':

```text
http://IP_DEL_RASPBERRY:8000/ble/sample
```

#### 4. Verificare che arrivino dati reali

Prima della baseline controlliamo che i campioni BLE arrivino davvero:

```powershell
type data\raw\ble_samples.csv
```

Su Raspberry/Linux:

```bash
cat data/raw/ble_samples.csv
```

Poi generiamo una finestra di prova:

```bash
python -m edge_runtime.cli --config config/edge.yml
```

File da controllare:

```text
data/processed/latest_window.csv
outputs/last-quality-report.json
outputs/last-cycle.json
```

Il report qualita deve idealmente essere:

```text
quality_status: ok
```

oppure al massimo:

```text
quality_status: warning
```

Non dobbiamo iniziare la baseline se i dati sono in `error`, per esempio se mancano
campioni BLE o se Fitbit e' abilitato ma non sta inviando dati.

#### 5. Preparare i modelli generici, se abbiamo dataset validi

Da CASAS creeremo il modello spaziale:

```bash
python -m edge_ai.cli train-generic \
  --input data/processed/generic_spatial_dataset.csv \
  --output models/generic_spatial.pkl \
  --model-id generic-spatial \
  --model-kind generic_spatial
```

Da WESAD/PAMAP2 o dataset wearable equivalente creiamo il modello wearable:

```bash
python -m edge_ai.cli train-generic \
  --input data/processed/generic_wearable_dataset.csv \
  --output models/generic_wearable.pkl \
  --model-id generic-wearable \
  --model-kind generic_wearable
```

Questi modelli non rappresentano il singolo paziente: servono come base iniziale mentre
il Raspberry raccoglie la baseline personale.

#### 6. Avviare baseline reale di 6 giorni

Quando beacon, braccialetto/wearable e Raspberry sono stabili:

Per il progetto useremo 6 giorni perche' non abbiamo 14 giorni disponibili. Questo e'
accettabile come baseline dimostrativa reale, pur essendo meno robusta di una baseline
clinica piu' lunga.

```bash
python -m edge_baseline.cli --config config/edge.yml start --days 6
```

Questo crea lo stato:

```text
data/state/baseline-session.json
```

Durante i 6 giorni il Raspberry deve eseguire ogni 4 minuti:

```bash
python -m edge_runtime.cli --config config/edge.yml --append-baseline
```

Esempio cron sul Raspberry:

```cron
*/4 * * * * cd /home/pi/progetto-iot/edge_node && . ../.venv/bin/activate && python -m edge_runtime.cli --config config/edge.yml --append-baseline
```

Questo comando:

```text
legge i dati grezzi
-> crea latest_window.csv
-> controlla la qualita
-> se models/generic_spatial.pkl esiste, produce triage spaziale
-> se models/generic_wearable.pkl esiste, produce triage wearable
-> se uno score generico e' troppo alto, blocca inserimento in baseline
-> se la qualita e' valida, appende a baseline.csv
-> se la qualita e' error, rifiuta la finestra
```

La baseline viene raccolta qui:

```text
data/processed/baseline.csv
```

#### 7. Controllare ogni giorno la baseline

Durante i 6 giorni controlleremo:

```bash
python -m edge_baseline.cli --config config/edge.yml status
```

e:

```bash
python -m edge_quality.cli --config config/edge.yml
```

Dobbiamo guardare:

```text
accepted_windows
rejected_windows
quality_error_cycles
baseline_row_count
ready_for_training
```

Se `rejected_windows` o `quality_error_cycles` crescono troppo, non addestriamo ancora:
prima correggiamo il problema dei dati.

#### 8. Chiudere baseline e addestrare

Dopo circa 6 giorni, quando lo status indica che la baseline e' pronta:

```bash
python -m edge_baseline.cli --config config/edge.yml finalize
python -m edge_baseline.cli --config config/edge.yml train
```

Il training usa:

```text
data/processed/baseline.csv
```

e salva il modello in:

```text
models/patient-001.pkl
```

Questo modello e' personale: rappresenta la routine del paziente osservato durante la
baseline. Non sostituisce i modelli generici: dopo questa fase i tre modelli lavorano
insieme, quando disponibili.

#### 9. Usare i modelli addestrati

Dopo il training, il ciclo normale diventa:

```bash
python -m edge_runtime.cli --config config/edge.yml
```

Per lasciarlo acceso e farlo lavorare automaticamente ogni 4 minuti:

```bash
python -m edge_runtime.cli --config config/edge.yml --loop
```

A questo punto il runtime:

```text
crea latest_window.csv
-> carica models/generic_spatial.pkl, se presente
-> carica models/generic_wearable.pkl, se presente
-> carica models/patient-001.pkl, se presente
-> calcola generic_spatial_score, generic_wearable_score e personal_score
-> fonde i risultati in anomaly_score finale
-> applica debounce
-> salva outputs/patient-001-decision.json
```

Output finale:

```text
outputs/patient-001-decision.json
```

Questo file sara' poi collegabile al backend/dashboard.
Nel JSON decisione manteniamo sia gli orari UTC (`window_start`, `window_end`) sia gli
orari locali (`window_start_local`, `window_end_local`). UTC serve per backend, AI e
allineamento sensori; local time serve al frontend e alla lettura umana.

### Comandi separati

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

Training modello generico spaziale:

Prima si converte CASAS:

```bash
python -m edge_datasets.cli casas \
  --input-dir data/external/casas \
  --output data/processed/generic_spatial_dataset.csv \
  --window-minutes 4
```

Poi si addestra:

```bash
python -m edge_ai.cli train-generic \
  --input data/processed/generic_spatial_dataset.csv \
  --output models/generic_spatial.pkl \
  --model-id generic-spatial \
  --model-kind generic_spatial
```

Training modello generico wearable:

Prima si convertono i dataset Fitbit-style messi in `data/external/fitbitdata`:

```bash
python -m edge_datasets.cli fitbitdata \
  --input-dir data/external/fitbitdata \
  --output data/processed/generic_wearable_dataset_fitbitdata.csv \
  --window-minutes 4 \
  --hrv-condition "no stress" \
  --health-status 0 \
  --oxi-label 0 \
  --oxi-min-spo2 92
```

Questo CSV usa:

- `archive2/train.csv` e `archive2/test.csv`, se presenti, per `heart_rate_mean`,
  `heart_rate_std` e `hrv_rmssd` con filtro sulla colonna `condition`;
- in alternativa, `archive2/time_domain_features_train.csv` piu'
  `archive2/heart_rate_non_linear_features_train.csv`;
- `Activity.csv` per passi e minuti sedentari, scalati su finestre da 4 minuti;
- `Sleep_health_and_lifestyle_dataset.csv` per heart rate, resting heart rate, sleep minutes e daily steps;
- `Health data.csv` per pulse e SpO2, usando di default solo `Status = 0`;
- `HuGCDN2014-OXI` per RR e SpO2 dai file MATLAB, usando di default solo label `0`
  e finestre con SpO2 media almeno 92.

Prima si converte PAMAP2 nello schema del progetto:

```bash
python -m edge_datasets.cli pamap2 \
  --input-dir data/external/pamap2/Protocol \
  --output data/processed/generic_wearable_dataset_pamap2.csv \
  --window-minutes 4
```

Questo CSV contiene soprattutto feature fisiologiche/motorie:

- `heart_rate_mean`;
- `heart_rate_std`;
- `steps`, stimati dagli activity id PAMAP2;
- `sedentary_minutes`, stimati dagli activity id PAMAP2;
- `wearable_present`.

Poi si converte WESAD:

```bash
python -m edge_datasets.cli wesad \
  --input-dir data/external/wesad \
  --output data/processed/generic_wearable_dataset_wesad.csv \
  --window-minutes 4
```

WESAD viene usato per estrarre feature da BVP/HRV. Di default il converter usa
solo label normali:

```text
1 = baseline
3 = amusement
4 = meditation
```

La label `2 = stress` e i transitori vengono scartati perche' il modello
`IsolationForest` deve imparare la normalita.

Poi uniamo fitbitdata, PAMAP2 e WESAD in:

```text
data/processed/generic_wearable_dataset.csv
```

con:

```bash
python -m edge_datasets.cli merge \
  --inputs data/processed/generic_wearable_dataset_fitbitdata.csv,data/processed/generic_wearable_dataset_pamap2.csv,data/processed/generic_wearable_dataset_wesad.csv \
  --output data/processed/generic_wearable_dataset.csv
```

Poi addestriamo il modello wearable. Il generico attuale include `hrv_rmssd`
usando il dataset sintetico controllato: HRV alta/sana viene normalizzata e non
genera allarme, mentre HRV molto bassa puo' contribuire allo score prima della
baseline personale.

```bash
python -m edge_ai.cli train-generic \
  --input data/processed/generic_wearable_dataset.csv \
  --output models/generic_wearable.pkl \
  --model-id generic-wearable \
  --model-kind generic_wearable
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
python -m edge_baseline.cli --config config/edge.yml start --days 6
python -m edge_runtime.cli --config config/edge.yml --append-baseline
```

Dopo circa 5/6 giorni:

```bash
python -m edge_baseline.cli --config config/edge.yml status
python -m edge_baseline.cli --config config/edge.yml finalize
python -m edge_baseline.cli --config config/edge.yml train
```

Durante il funzionamento normale:

```bash
python -m edge_runtime.cli --config config/edge.yml
```

## Prossimi step

1. Testare il Foreground Service BLE su telefono Android fisico con beacon reali.
2. Configurare la mappa reale dei 3 BlueBeacon nell'app Android.
3. Creare le credenziali Google Health OAuth reali e salvare il consenso account.
4. Preparare `edge_node/config/edge.yml` reale per Raspberry Pi 5.
5. Spostare repository, modelli generici e configurazione sul Raspberry.
6. Avviare raccolta baseline reale.
7. Addestrare `models/patient-001.pkl`.
8. Usare runtime con generici + personale + fusione.
9. Implementare collector Shelly reale via HTTP e salvataggio campioni, se useremo Shelly.
10. Collegare output JSON al backend/dashboard.

## Stato attuale del progetto

Questa sezione riassume in parole povere cosa e' stato fatto finora. Va aggiornata
ogni volta che aggiungiamo un nuovo pezzo al sistema.

### 1. Modulo AI

Abbiamo creato il modulo `edge_ai`.

Questo e' il cervello del sistema. Legge dati aggregati ogni 4 minuti, usa
`IsolationForest` in due modalita' e produce un livello di rischio:

- modello generico spaziale: `models/generic_spatial.pkl`;
- modello generico wearable: `models/generic_wearable.pkl`;
- modello personale: `models/patient-001.pkl`;
- fusione: confronto tra score spaziale, wearable e personale.

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

### 3. Google Health / Pixel Watch

Abbiamo implementato il percorso attuale per Pixel Watch 2 tramite Google Health API.

Il setup OAuth salva `config/google_health_client.json` e
`config/google_health_token.json`, gestisce access token, refresh token e scadenza.
L'adapter Google Health usa questi file e prova a fare refresh automatico quando il token
scade.

Il runtime ora puo' leggere battito, HRV, SpO2, sonno, passi, batteria e presenza
wearable quando Google li espone. Per ridurre buchi dovuti alla sincronizzazione cloud
abbiamo aggiunto `data_delay_minutes` e `heart_rate_lookback_minutes` sotto
`google_health`.

Fitbit Web API resta nel codice come compatibilita legacy, ma per nuove credenziali il
percorso documentato e' Google Health.

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

### 5. Receiver Raspberry per app mobile

Abbiamo creato il modulo `edge_receiver`.

Questo sara' il server locale sul Raspberry Pi. Espone l'endpoint:

```text
POST /ble/sample
```

L'app Android o iOS inviera' dati di questo tipo:

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

### 6. Runtime Edge

Abbiamo creato il modulo `edge_runtime`.

Questo modulo esegue il ciclo logico dell'edge node. Invece di lanciare manualmente
prima `edge_ingest` e poi `edge_ai`, ora possiamo usare:

```bash
python -m edge_runtime.cli --config config/edge.yml
```

Per test manuali continui, su Windows o Raspberry:

```bash
python -m edge_runtime.cli --config config/edge.yml --loop
```

Il comando produce `latest_window.csv`, controlla se esistono i modelli addestrati e,
se almeno un modello c'e', salva anche la decisione JSON. Se i modelli non ci sono
ancora, non fallisce: aggiorna la finestra dati e registra che l'inferenza e' stata
saltata.

In modalita loop il runtime ripete il ciclo ogni 4 minuti e stampa log `INFO` compatti,
simili al receiver BLE. Questo ci permette di provare anche Google Health come raccolta
periodica, non solo come chiamata singola.

Per il funzionamento reale continuo, pero', usiamo `edge_stack`, che avvia insieme
il receiver BLE e `edge_runtime --loop`:

```bash
python -m edge_stack.cli --config config/edge.yml
```

### 7. Qualita Dati

Abbiamo creato il modulo `edge_quality`.

Questo modulo controlla se i dati raccolti sono utilizzabili prima di inserirli nella
baseline. Per esempio segnala errori o warning tecnici come:

- BLE abilitato ma senza campioni;
- timestamp BLE invalidi o nel futuro;
- wearable cloud abilitato ma senza dati biometrici;
- wearable dichiarato non presente;
- Shelly abilitato ma senza campioni.

La permanenza nella stessa stanza per molte ore viene invece registrata come osservazione
`info`: non e' un errore del dato, ma un possibile segnale comportamentale che il modello
o la dashboard potranno usare.

Il report viene scritto in `outputs/last-quality-report.json`. Se il report ha stato
`error`, il runtime non appende quella finestra alla baseline, cosi' evitiamo di
addestrare il modello con dati sporchi.

### 8. Fase Baseline

Abbiamo creato il modulo `edge_baseline`.

Questo modulo serve a gestire la raccolta reale della routine del paziente:

```text
start baseline
-> raccolta per 6 giorni
-> controllo qualita a ogni finestra
-> conteggio finestre accettate/rifiutate
-> finalize
-> training modello
```

Lo stato viene salvato in `data/state/baseline-session.json`. Il modello finale viene
salvato in `models/patient-001.pkl`, ma solo quando avremo dati reali sufficienti.

### 9. App Android

Abbiamo creato l'app `IoT Edge Companion` dentro `Applicazione IoT Companion/companion_Android_app/`.

L'app serve per due cose:

- configurazione protetta della mappa beacon;
- scansione BLE reale con telefono Android e BlueBeacon.

In modalita reale l'app scansionera' i beacon nelle stanze, scegliera' quello con RSSI
piu' forte e inviera' la stanza stimata al Raspberry.

Abbiamo aggiunto anche un Foreground Service BLE: quando viene premuto `Avvia monitoraggio
BLE`, Android mantiene l'app attiva in background con una notifica persistente. Il servizio
fa cicli periodici di scansione, sceglie il beacon/stanza piu' forte e invia il campione
al receiver locale.

### 10. App iOS

Abbiamo creato la base dell'app iPhone dentro:

```text
Applicazione IoT Companion/companion_iOS_app/
```

Questa cartella contiene i sorgenti Swift/SwiftUI e una guida per creare il progetto su
Mac con Xcode, firmarlo e installarlo su iPhone.

L'app iOS permette:

- test manuale senza beacon fisici;
- scansione BLE reale tramite CoreBluetooth;
- visualizzazione dei beacon rilevati;
- mappatura nome/UUID beacon verso stanza;
- invio campioni al receiver Raspberry.

Nota: su iOS non possiamo fare affidamento sul MAC address BLE. Useremo nome beacon o
identificativo CoreBluetooth, e quando avremo i beacon veri valuteremo se passare a
CoreLocation per iBeacon.

### 11. Shelly / NILM

Abbiamo predisposto un adapter per dati Shelly/NILM.

Per ora non abbiamo ancora deciso se useremo davvero Shelly o un altro dispositivo di
misurazione consumi. Il codice e' pronto a leggere dati da:

```text
data/raw/shelly_samples.csv
```

### 12. Documentazione

Abbiamo documentato architettura, comandi, deployment Raspberry, schema feature e vincoli
reali delle API.

Il README deve rimanere il punto principale da leggere per capire lo stato del progetto.

### 13. Cosa manca ancora

Mancano ancora i collegamenti reali con hardware:

- beacon BLE fisici nelle stanze;
- Raspberry Pi reale;
- credenziali Google Health OAuth reali e consenso account;
- eventuale Shelly o alternativa per consumi;
- backend/dashboard finale.
