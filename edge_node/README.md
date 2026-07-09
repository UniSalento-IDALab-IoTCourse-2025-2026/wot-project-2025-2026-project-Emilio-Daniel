# Edge Node Raspberry

Questa cartella contiene tutto cio' che gira sul Raspberry Pi o sul PC durante i test
locali.

## Contenuto

```text
edge_ai/        modelli generici/personale, fusione, debounce e CLI train/infer
edge_auth/      setup OAuth Google Health/Fitbit, token e refresh per Pixel Watch 2
edge_baseline/  gestione fase baseline: start, status, finalize, train
<<<<<<< HEAD
edge_datasets/  convertitori dataset pubblici CASAS/fitbitdata/PAMAP2/WESAD
edge_ingest/    aggregazione dati Fitbit, BLE e Shelly in finestre da 4 minuti
=======
edge_datasets/  convertitori dataset pubblici CASAS/PAMAP2/WESAD
edge_ingest/    aggregazione dati Google Health/Fitbit, BLE e Shelly in finestre da 4 minuti
>>>>>>> 4fb8463ce1af090dbe5827ace9cb727510ff9b8f
edge_receiver/  receiver FastAPI per campioni BLE inviati dall'app Android
edge_runtime/   ciclo edge: aggregazione, qualita, inferenza e decisione
edge_stack/     comando unico che avvia receiver BLE e runtime continuo
edge_quality/   controlli qualita dati per baseline/training
config/         configurazioni YAML dell'edge node
data/           dati grezzi, feature aggregate e stato locale
models/         modelli generici e modelli paziente-specifici
outputs/        decisioni JSON prodotte dall'AI
```

## Setup

Da questa cartella:

```bash
pip install -r requirements.txt
```

Se usi la virtualenv creata nella root del progetto su Windows:

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Google Health OAuth / Pixel Watch 2

Il Pixel Watch 2 sincronizza i dati biometrici con Fitbit/Google. Il Raspberry li legge
via API solo dopo autorizzazione OAuth.

Per nuove credenziali usiamo Google Health API. I file locali sono:

```text
config/google_health_client.json
config/google_health_token.json
```

Sono ignorati da Git perche' contengono credenziali e token.

Controllo stato:

```powershell
python -m edge_auth.cli google-health status
```

Refresh manuale, se serve:

```powershell
python -m edge_auth.cli google-health refresh
```

Poi in `config/edge.yml`:

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

Durante il ciclo edge il token viene rinfrescato automaticamente quando scade. Il delay e
il lookback sono specifici di Google Health: servono per compensare la sincronizzazione
cloud del watch senza spostare indietro la finestra BLE.

Fitbit resta supportato come adapter legacy, ma per il Pixel Watch 2 nuovo percorso e'
Google Health. La procedura completa e' in `../Documenti/GOOGLE_WATCH_SETUP.md`.

## Receiver Android BLE

```bash
python -m edge_receiver.cli --config config/edge.example.yml --host 0.0.0.0 --port 8000
```

L'app Android invia campioni a:

```text
POST /ble/sample
```

Il receiver salva i campioni in:

```text
data/raw/ble_samples.csv
```

## Comando Unico Edge Stack

Normalmente dalla root del progetto usiamo il launcher breve:

```powershell
.\avviaSistema
```

Su Windows, se PowerShell non lo esegue senza estensione:

```powershell
.\avviaSistema.cmd
```

Sul Raspberry Pi:

```bash
chmod +x avviaSistema
./avviaSistema
```

Internamente il launcher entra in `edge_node/` ed esegue:

```bash
python -m edge_stack.cli --config config/edge.yml
```

Questo avvia due processi coordinati:

```text
edge_receiver
  -> resta in ascolto su http://0.0.0.0:8000
  -> riceve campioni BLE dall'app Android
  -> aggiorna data/raw/ble_samples.csv

edge_runtime --loop
  -> ogni 4 minuti legge tutte le sorgenti abilitate
  -> Google Health / Pixel Watch 2
  -> BLE gia' ricevuti dal receiver
  -> Shelly/NILM se abilitato in futuro
  -> aggiorna latest_window.csv e decision JSON
```

Il comando si ferma con `CTRL+C`.

Durante la baseline:

```bash
./avviaSistema --append-baseline
```

Il file `config/edge.yml` decide quali sorgenti entrano in `latest_window.csv`.
Per avere Watch e beacon insieme servono entrambe:

```yaml
google_health:
  enabled: true
  data_delay_minutes: 0

ble:
  enabled: true
```

Con `google_health.data_delay_minutes: 0`, il runtime usa la stessa finestra
corrente da 4 minuti per Google Watch 2 e BLE. Se Google Health non ha ancora
sincronizzato un valore, quel campo resta vuoto/`nan`, ma la decisione viene
comunque prodotta senza ritardare artificialmente la finestra.

## Modello AI ibrido

Il sistema ora supporta tre modelli:

```text
models/generic_spatial.pkl    modello generico spaziale/domestico, da CASAS
models/generic_wearable.pkl   modello generico fisiologico/wearable, da fitbitdata/WESAD/PAMAP2
models/patient-001.pkl        modello personale creato dalla baseline reale
```

I due modelli generici servono nei primi giorni, quando non abbiamo ancora abbastanza
dati del paziente. Il modello personale viene creato dopo la baseline da 5/6 giorni.
Quando piu' modelli sono presenti, `edge_runtime` li esegue e produce una decisione
fusa:

```text
latest_window.csv
-> modello generico spaziale   -> generic_spatial_score
-> modello generico wearable   -> generic_wearable_score
-> modello personale           -> personal_score
-> fusion.py                   -> anomaly_score finale
-> debounce.py                 -> livello green/yellow/orange/red/technical
```

Nel JSON finale la sezione `evidence.fusion` conserva i punteggi separati, cosi'
possiamo capire se l'allarme nasce dalla routine spaziale, dai dati wearable, dalla
baseline personale o da una concordanza tra piu' modelli.

Scala operativa:

```text
0-35    green     normale
35-65   yellow    attenzione lieve, non pubblicata come alert
65-80   orange    anomalia importante, pubblicata se confermata dal debounce
80-100  red       anomalia severa, pubblicata subito
```

`technical` resta separato dai colori clinici e segnala problemi di device o dati.

Per capire quale parte ha causato lo score, leggere la decisione:

```powershell
Get-Content outputs\patient-001-decision.json
```

Poi isolare la spiegazione del Watch:

```powershell
$d = Get-Content outputs\patient-001-decision.json | ConvertFrom-Json
$d.evidence.fusion.models.generic_wearable.feature_explanation | ConvertTo-Json -Depth 8
```

oppure quella dei Beacon/BLE:

```powershell
$d = Get-Content outputs\patient-001-decision.json | ConvertFrom-Json
$d.evidence.fusion.models.generic_spatial.feature_explanation | ConvertTo-Json -Depth 8
```

`generic_wearable` guarda feature come battito e SpO2. Per scelta progettuale
non usa `hrv_rmssd`, perche' nei dataset pubblici e in Google Health questo
valore puo' avere scale diverse e generare falsi score alti.
`generic_spatial` guarda room changes e minuti nelle stanze.

Durante la baseline i modelli generici vengono usati anche come filtro di sicurezza:
se uno dei loro score supera `ai.baseline_gate_block_score`, la finestra puo' generare
triage ma non viene aggiunta a `baseline.csv`. Cosi' evitiamo che un comportamento
gia' sospetto venga imparato come normalita personale.

## Ciclo edge unico

Questo e' il comando principale da usare sul Raspberry:

```powershell
python -m edge_runtime.cli --config config/edge.example.yml
```

Attenzione: questo comando va lanciato da dentro `edge_node/`. Se sei nella root del
progetto:

```powershell
cd edge_node
python -m edge_runtime.cli --config config\edge.example.yml
```

Se la virtualenv non e' attiva, sempre da dentro `edge_node/` puoi usare:

```powershell
..\.venv\Scripts\python.exe -m edge_runtime.cli --config config\edge.example.yml
```

Fa questo flusso:

```text
legge i dati ricevuti in data/raw/
-> crea data/processed/latest_window.csv
-> se esiste models/generic_spatial.pkl, esegue il modello generico spaziale
-> se esiste models/generic_wearable.pkl, esegue il modello generico wearable
-> se esiste models/patient-001.pkl, esegue il modello personale
-> fonde tutti i risultati disponibili
-> aggiorna data/state/patient-001-debounce.json
-> salva outputs/patient-001-decision.json
-> salva outputs/last-quality-report.json
-> salva outputs/last-cycle.json
```

Se nessun modello esiste ancora, il ciclo non fallisce: produce comunque
`latest_window.csv` e segna `skipped_all_models_missing` in `outputs/last-cycle.json`.

Ogni ciclo controlla anche la qualita dei dati. Se il report ha stato `error`, la finestra
non viene considerata adatta alla baseline.

Durante la baseline, se almeno un modello generico e' disponibile, il runtime continua a
produrre triage mentre raccoglie i dati personali:

```bash
python -m edge_runtime.cli --config config/edge.example.yml --append-baseline
```

Se i dati non superano i controlli qualita, il runtime non appende la riga a
`data/processed/baseline.csv` e scrive `baseline_skipped_reason: quality_error`.
Se invece la qualita e' buona ma un modello generico segnala rischio alto, scrive
`baseline_skipped_reason: generic_safety_gate`.

Sul Raspberry, quando useremo `config/edge.yml` reale:

```bash
python -m edge_runtime.cli --config config/edge.yml
```

Per lasciarlo acceso e far partire automaticamente un ciclo ogni 4 minuti:

```bash
python -m edge_runtime.cli --config config/edge.yml --loop
```

In modalita loop il terminale mostra log `INFO` compatti e ogni ciclo aggiorna
`latest_window.csv`, report qualita e decisione AI.

## Controllo qualita manuale

```bash
python -m edge_quality.cli --config config/edge.example.yml
```

Output:

```text
outputs/last-quality-report.json
```

Il report segnala problemi tecnici come:

- pochi o zero campioni BLE nella finestra;
- timestamp BLE invalidi o nel futuro;
- wearable cloud abilitato ma senza dati biometrici;
- wearable non presente;
- Shelly/NILM abilitato ma senza campioni.

La stessa stanza per molte ore viene salvata come osservazione `info`, non come errore:
ci interessa proprio come possibile comportamento da analizzare.

## Fase baseline

La baseline e' la raccolta della routine reale del paziente. Non va fatta con dati
simulati: parte solo quando Raspberry, app Android/beacon e sorgenti reali sono pronti.

Per i tempi del progetto useremo una baseline compatta da 5/6 giorni. Una baseline piu'
lunga sarebbe migliore, ma questa scelta ci permette di addestrare comunque su dati reali.

Avvio baseline:

```bash
python -m edge_baseline.cli --config config/edge.yml start --days 6
```

Questo crea:

```text
data/state/baseline-session.json
```

Durante la baseline il cron deve lanciare:

```bash
python -m edge_runtime.cli --config config/edge.yml --append-baseline
```

Ogni ciclo:

```text
controlla qualita
-> se qualita ok/warning, appende a data/processed/baseline.csv
-> se qualita error, rifiuta la finestra
-> aggiorna data/state/baseline-session.json
```

Controllare avanzamento:

```bash
python -m edge_baseline.cli --config config/edge.yml status
```

Dopo circa 6 giorni, quando lo status indica che la baseline e' pronta:

```bash
python -m edge_baseline.cli --config config/edge.yml finalize
python -m edge_baseline.cli --config config/edge.yml train
```

Il modello viene salvato in:

```text
models/patient-001.pkl
```

Da questo momento il runtime usera' i due generici e `models/patient-001.pkl`, se
gli artefatti sono presenti.

## Aggregazione dati

```bash
python -m edge_ingest.cli --config config/edge.example.yml
```

Output:

```text
data/processed/latest_window.csv
```

Per costruire la baseline:

```bash
python -m edge_ingest.cli --config config/edge.example.yml --append-baseline
```

Output baseline:

```text
data/processed/baseline.csv
```

## Conversione Dataset Pubblici

I dataset pubblici non vengono dati direttamente al modello: prima devono essere
convertiti nello stesso schema di `latest_window.csv` e `baseline.csv`.

Il converter CASAS e' gia' disponibile:

```bash
python -m edge_datasets.cli casas \
  --input-dir data/external/casas \
  --output data/processed/generic_spatial_dataset.csv \
  --window-minutes 4
```

Per un test veloce su pochi file:

```bash
python -m edge_datasets.cli casas \
  --input-dir data/external/casas \
  --include aruba.csv,milan.csv \
  --limit-rows-per-file 50000 \
  --output data/processed/generic_spatial_dataset.sample.csv
```

Il risultato e' un CSV compatibile con:

```bash
python -m edge_ai.cli train-generic \
  --input data/processed/generic_spatial_dataset.csv \
  --output models/generic_spatial.pkl \
  --model-id generic-spatial \
  --model-kind generic_spatial
```

Nota: CASAS contiene dati ambientali/spaziali, quindi le colonne wearable e NILM restano
vuote. Questo e' previsto per il modello `generic_spatial.pkl`.

Il converter PAMAP2 e' disponibile per costruire il dataset wearable generico:

```bash
python -m edge_datasets.cli pamap2 \
  --input-dir data/external/pamap2/Protocol \
  --output data/processed/generic_wearable_dataset_pamap2.csv \
  --window-minutes 4
```

Per un test veloce prima della conversione completa:

```bash
python -m edge_datasets.cli pamap2 \
  --input-dir data/external/pamap2/Protocol \
  --limit-rows-per-file 200000 \
  --output data/processed/generic_wearable_dataset_pamap2.sample.csv \
  --window-minutes 4
```

PAMAP2 contiene heart rate e activity id ad alta frequenza. Il converter produce:

- media e deviazione standard della frequenza cardiaca;
- passi stimati dagli activity id;
- minuti sedentari stimati dagli activity id;
- `wearable_present = 1`;
- colonne spaziali, sonno, SpO2 e NILM vuote.

Questo e' previsto per `generic_wearable.pkl`: fitbitdata, WESAD e PAMAP2
completano la parte fisiologica/wearable, mentre CASAS resta dedicato alla parte
spaziale/domestica.

Il converter WESAD crea invece finestre wearable da BVP/HRV del polso:

```bash
python -m edge_datasets.cli wesad \
  --input-dir data/external/wesad \
  --output data/processed/generic_wearable_dataset_wesad.csv \
  --window-minutes 4
```

Di default vengono usate solo label WESAD normali:

```text
1 = baseline
3 = amusement
4 = meditation
```

La label `2 = stress` e i transitori vengono scartati perche' il modello
`IsolationForest` deve imparare la normalita, non considerare lo stress come routine.

Il converter `fitbitdata` usa invece i dataset locali messi in
`data/external/fitbitdata`:

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

Questo converter legge:

- `archive2/train.csv` e `archive2/test.csv`, se presenti, per heart rate e HRV
  con filtro diretto sulla colonna `condition`;
- in alternativa, `archive2/time_domain_features_train.csv` piu'
  `archive2/heart_rate_non_linear_features_train.csv` per tenere, di default,
  solo la condizione `no stress`;
- `Activity.csv` per passi e minuti sedentari;
- `Sleep_health_and_lifestyle_dataset.csv` per heart rate, resting heart rate, sleep minutes e daily steps;
- `Health data.csv` per pulse e SpO2, usando di default solo `Status = 0`;
- `HuGCDN2014-OXI` per RR e SpO2 dai file MATLAB, usando di default solo label `0`
  e finestre con SpO2 media almeno 92.

Dopo fitbitdata, PAMAP2 e WESAD, i CSV wearable si uniscono cosi':

```bash
python -m edge_datasets.cli merge \
  --inputs data/processed/generic_wearable_dataset_fitbitdata.csv,data/processed/generic_wearable_dataset_pamap2.csv,data/processed/generic_wearable_dataset_wesad.csv \
  --output data/processed/generic_wearable_dataset.csv
```

## Addestramento modello

Modello generico spaziale, da CASAS gia' convertito nello schema feature del progetto:

```bash
python -m edge_ai.cli train-generic \
  --input data/processed/generic_spatial_dataset.csv \
  --output models/generic_spatial.pkl \
  --model-id generic-spatial \
  --model-kind generic_spatial
```

Modello generico wearable, da fitbitdata/WESAD/PAMAP2 o dataset wearable equivalente:

Prima si converte fitbitdata:

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

Poi si converte PAMAP2:

```bash
python -m edge_datasets.cli pamap2 \
  --input-dir data/external/pamap2/Protocol \
  --output data/processed/generic_wearable_dataset_pamap2.csv \
  --window-minutes 4
```

Poi uniamo fitbitdata, PAMAP2 e WESAD in `data/processed/generic_wearable_dataset.csv`
e addestriamo:

```bash
python -m edge_ai.cli train-generic \
  --input data/processed/generic_wearable_dataset.csv \
  --output models/generic_wearable.pkl \
  --model-id generic-wearable \
  --model-kind generic_wearable
```

Nota: `hrv_rmssd` viene escluso automaticamente dal modello generico wearable.
Il valore resta nel CSV e potra' essere usato in futuro dal modello personale,
ma il generico installabile su Raspberry usa solo feature piu' confrontabili tra
dataset pubblici e dati Google Health reali.

Con i dati attuali il modello generico wearable seleziona le feature realmente
coperte in modo solido: `heart_rate_mean`, `heart_rate_std`, `hrv_rmssd` e
`spo2_mean`.
Le feature piu' rare, come sleep/steps/resting heart rate, restano nei CSV ma non
vengono forzate nel generico se non hanno abbastanza copertura.

Modello personale, dalla baseline reale del paziente:

```bash
python -m edge_ai.cli train \
  --input data/processed/baseline.csv \
  --patient-id patient-001 \
  --output models/patient-001.pkl
```

## Inferenza

Il comando consigliato resta il runtime unico, perche' gestisce automaticamente i due
generici, il modello personale, la fusione e il debounce:

```bash
python -m edge_runtime.cli --config config/edge.example.yml
```

La CLI `edge_ai infer` resta utile per testare un singolo modello isolato:

```bash
python -m edge_ai.cli infer \
  --model models/patient-001.pkl \
  --input data/processed/latest_window.csv \
  --state data/state/patient-001-debounce.json \
  --output outputs/patient-001-decision.json
```
