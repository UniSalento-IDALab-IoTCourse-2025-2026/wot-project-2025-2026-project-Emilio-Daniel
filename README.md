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

BLE samples da tag/beacon indoor
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
edge_ingest aggrega una finestra da 15 minuti
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

edge_ingest/
  config.py             Lettura configurazione YAML
  time_windows.py       Calcolo finestre temporali
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

docs/
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
2. BLE tramite scanner sul Raspberry Pi.
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
2. calcola l'ultima finestra temporale da 15 minuti;
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

Per ora gli adapter sono disabilitati:

```yaml
fitbit:
  enabled: false

ble:
  enabled: false

shelly:
  enabled: false
```

Quando avremo credenziali e hardware, abiliteremo una sorgente alla volta.

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

- beacon/tag BLE mobile sul paziente;
- scanner BLE fissi oppure Raspberry Pi posizionato in modo strategico;
- il sistema rileva il segnale del tag indossato e stima la stanza;
- questa soluzione e' piu' vicina all'idea "seguo il paziente in casa".

Questa parte verra' implementata piu' avanti, quando avremo scelto e acquistato
l'hardware BLE reale.

L'adapter BLE attuale aggrega un CSV reale gia' raccolto dal Raspberry:

```text
data/raw/ble_samples.csv
```

Formato minimo:

```csv
timestamp,room,rssi
2026-06-24T10:00:00Z,kitchen,-61
2026-06-24T10:02:00Z,living_room,-70
```

Feature prodotte:

- `room_changes`;
- `night_room_changes`;
- `bedroom_minutes`;
- `kitchen_minutes`;
- `bathroom_minutes`;
- `living_room_minutes`;
- `longest_single_room_minutes`.

Quando avremo il Raspberry, aggiungeremo lo scanner BLE reale con `bleak` o libreria
equivalente. L'aggregatore e' gia' pronto a leggere il file prodotto dallo scanner.

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

1. Implementare OAuth Fitbit completo con refresh token.
2. Implementare collector BLE reale su Raspberry Pi.
3. Implementare collector Shelly reale via HTTP e salvataggio campioni.
4. Preparare `config/edge.yml` reale per il vostro paziente/test.
5. Avviare raccolta baseline reale.
6. Addestrare il modello.
7. Collegare output JSON al backend/dashboard.
