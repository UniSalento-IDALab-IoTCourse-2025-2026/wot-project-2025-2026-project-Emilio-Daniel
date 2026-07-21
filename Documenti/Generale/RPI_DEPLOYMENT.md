# Raspberry Pi Deployment Notes

Questa repo e' pensata per essere copiata sul Raspberry Pi 5 senza cambiare codice del modello.
Sul Pi collegheremo gli adapter reali che produrranno il CSV/JSON conforme a `FEATURE_SCHEMA.md`.

## Setup base

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip bluetooth bluez
cd /home/pi/progetto-iot/edge_node
python3 -m venv ../.venv
source ../.venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Google Health OAuth / Pixel Watch 2

Prima della baseline, collegare l'account Fitbit/Google usato dal Google Pixel Watch 2.
Il Raspberry non legge il battito dal Bluetooth del watch: legge le API dopo consenso
OAuth.

Per nuove credenziali usiamo Google Health API. La procedura completa e' in:

```text
GOOGLE_WATCH_SETUP.md
```

Sul Raspberry devono essere presenti questi file locali:

```text
config/google_health_client.json
config/google_health_token.json
```

Controllare che siano pronti:

```bash
python -m edge_auth.cli google-health status
```

Testare il refresh token:

```bash
python -m edge_auth.cli google-health refresh
```

In `config/edge.yml` abilitare Google Health:

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

Motivazione della configurazione:

- Google Health e' il percorso attuale per Pixel Watch 2;
- Fitbit resta nel progetto come compatibilita legacy, ma e' disabilitato;
- il delay e il lookback riducono i buchi di battito dovuti alla sincronizzazione cloud;
- il delay vale solo per Google Health, quindi i dati BLE restano sulla finestra corrente.

Fitbit legacy usa ancora questi file, solo per setup gia' esistenti:

```text
config/fitbit_client.json
config/fitbit_token.json
```

e questi comandi:

```bash
python -m edge_auth.cli fitbit status
python -m edge_auth.cli fitbit refresh
```

## Modelli AI sul Raspberry

Il Raspberry puo' usare tre artefatti:

```text
models/generic_spatial.pkl    modello generico spaziale/domestico
models/generic_wearable.pkl   modello generico wearable/fisiologico
models/patient-001.pkl        modello personale addestrato dopo baseline
```

Nel file `config/edge.yml` indicare i percorsi:

```yaml
ai:
  generic_model: models/generic_spatial.pkl
  generic_spatial_model: models/generic_spatial.pkl
  generic_wearable_model: models/generic_wearable.pkl
  personal_model: models/patient-001.pkl
  baseline_gate_enabled: true
  baseline_gate_block_score: 60.0
```

Il modello generico spaziale si crea da CASAS gia' convertito nello schema feature:

```bash
python -m edge_ai.cli train-generic \
  --input data/processed/generic_spatial_dataset.csv \
  --output models/generic_spatial.pkl \
  --model-id generic-spatial \
  --model-kind generic_spatial
```

Il modello generico wearable si crea dal dataset wearable unificato
`generic_wearable_dataset.csv`, ottenuto unendo fitbitdata, WESAD, PAMAP2 e
gli eventuali dataset fisiologici convertiti nello stesso schema:

```bash
python -m edge_ai.cli train-generic \
  --input data/processed/generic_wearable_dataset.csv \
  --output models/generic_wearable.pkl \
  --model-id generic-wearable \
  --model-kind generic_wearable
```

Nel modello generico attuale `hrv_rmssd` e' incluso. Per evitare falsi allarmi,
il training applica un clipping fisiologico sulla coda alta della HRV: una HRV
molto alta non viene trattata automaticamente come rischio, mentre valori bassi
o medi restano informativi.

Nel dataset wearable aggiornato entrano anche `Health data.csv` e HuGCDN2014-OXI:
il primo fornisce pulse/SpO2, il secondo RR/SpO2 da file MATLAB. Per addestrare
la normalita generica usiamo `Status = 0`, label HuGCDN `0` e SpO2 media almeno
92. Per leggere i `.mat` e' necessaria la dipendenza `scipy`, gia' presente in
`requirements.txt`.

Se uno dei due dataset generici manca, il relativo file puo' mancare: il runtime non
si blocca e fonde solo i modelli disponibili.

## Baseline reale

Quando hardware e sorgenti reali sono pronti, avviare la sessione baseline:

Per i tempi del progetto useremo una baseline compatta da 5/6 giorni. In produzione una
baseline piu' lunga sarebbe preferibile.

```bash
python -m edge_baseline.cli --config config/edge.yml start --days 6
```

Questo crea `data/state/baseline-session.json`.

Durante la baseline il ciclo periodico deve usare `--append-baseline`. Le finestre con
qualita `error` vengono rifiutate e non finiscono in `data/processed/baseline.csv`.
Se uno o entrambi i modelli generici sono presenti, il runtime produce comunque una
decisione mentre raccoglie i dati personali.
In piu', i modelli generici funzionano da safety gate: se uno score supera
`baseline_gate_block_score`, la finestra viene usata per triage ma non entra nella
baseline personale.

Controllare avanzamento:

```bash
python -m edge_baseline.cli --config config/edge.yml status
```

Dopo circa 6 giorni, se lo status indica che la baseline e' pronta:

```bash
python -m edge_baseline.cli --config config/edge.yml finalize
python -m edge_baseline.cli --config config/edge.yml train
```

Il modello viene salvato in `models/patient-001.pkl`.
Da questo momento il runtime usa i due modelli generici e quello personale, poi fonde
gli score disponibili nel JSON finale.

## Ciclo edge periodico

Il comando principale del Raspberry e':

```bash
python -m edge_runtime.cli --config config/edge.yml
```

Questo comando:

- legge i dati gia' ricevuti in `data/raw/`;
- produce `data/processed/latest_window.csv`;
- se trova `models/generic_spatial.pkl`, esegue il modello generico spaziale;
- se trova `models/generic_wearable.pkl`, esegue il modello generico wearable;
- se trova `models/patient-001.pkl`, esegue il modello personale;
- fonde `generic_spatial_score`, `generic_wearable_score` e `personal_score`;
- aggiorna `data/state/patient-001-debounce.json`;
- salva `outputs/patient-001-decision.json`;
- salva `outputs/last-quality-report.json`;
- salva `outputs/last-cycle.json` con lo stato del ciclo.

Se nessun modello esiste ancora, il ciclo non fallisce: aggrega la finestra e salta
l'inferenza con stato `skipped_all_models_missing`.

Per i test manuali continui, senza cron/systemd, usare:

```bash
python -m edge_runtime.cli --config config/edge.yml --loop
```

Il loop resta acceso e ogni 4 minuti esegue lo stesso ciclo completo:

```text
BLE raw CSV
-> Google Health API
-> latest_window.csv
-> quality report
-> modelli AI
-> debounce
-> outputs/patient-001-decision.json
```

Questa modalita e' utile su Windows e su Raspberry quando vogliamo vedere nel terminale
ogni ciclo completato senza schedulatore esterno.

La decisione AI usa questi livelli:

```text
0-35    green     normale
35-65   yellow    attenzione lieve, visibile ma non pubblicata come alert
65-80   orange    anomalia importante, pubblicata se confermata dal debounce
80-100  red       anomalia severa, pubblicata subito
```

`technical` resta separato dai colori clinici e indica problemi di sensori, token o dati.

Per capire quale sorgente sta spingendo la decisione:

```bash
cat outputs/patient-001-decision.json
```

Su Windows/PowerShell, i comandi piu' leggibili sono:

```powershell
$d = Get-Content outputs\patient-001-decision.json | ConvertFrom-Json
```

Per vedere il perche' lato Google Watch / wearable:

```powershell
$d.evidence.fusion.models.generic_wearable.feature_explanation | ConvertTo-Json -Depth 8
```

Per vedere il perche' lato Beacon / BLE:

```powershell
$d.evidence.fusion.models.generic_spatial.feature_explanation | ConvertTo-Json -Depth 8
```

`generic_wearable` spiega feature come battito, HRV, SpO2, passi e minuti sedentari.
`generic_spatial` spiega feature come cambi stanza e minuti nelle stanze. Entrambe le
spiegazioni sono tecniche: indicano quali feature sono piu' lontane dal training, non una
diagnosi clinica.

Il ciclo esegue anche controlli qualita sui dati. Se `--append-baseline` e' attivo ma il
report qualita ha stato `error`, la finestra non viene aggiunta a
`data/processed/baseline.csv`.
Se la qualita e' buona ma il safety gate generico blocca la finestra, in
`outputs/last-cycle.json` troverai `baseline_skipped_reason: generic_safety_gate`.

## Cron provvisorio

```cron
*/4 * * * * cd /home/pi/progetto-iot/edge_node && . ../.venv/bin/activate && python -m edge_runtime.cli --config config/edge.yml
```

Durante i primi 5/6 giorni di baseline, usare invece:

```cron
*/4 * * * * cd /home/pi/progetto-iot/edge_node && . ../.venv/bin/activate && python -m edge_runtime.cli --config config/edge.yml --append-baseline
```

In produzione i collector reali scriveranno i campioni grezzi in `data/raw/`, poi
`edge_runtime` usera' `edge_ingest` e `edge_ai` per produrre l'output finale.

## Avvio Cloud su Raspberry Pi 5

Se il Raspberry deve eseguire anche lo stack Cloud locale della demo, usare Docker
Compose e systemd invece degli script PowerShell.

Avvio manuale:

```bash
cd /home/pi/progetto-iot/cloud
docker compose up -d mqtt postgres backend backend-mqtt-worker
```

Installazione systemd:

```bash
cd /home/pi/progetto-iot
sudo cp cloud/deploy/iot-cloud-stack.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iot-cloud-stack.service
sudo systemctl status iot-cloud-stack.service
```

Smoke test su Raspberry:

```bash
cd /home/pi/progetto-iot
chmod +x Script/avvio/backupPostgres Script/avvio/ruotaLogCloud Script/test/test_cloud_smoke
START_COMPOSE=true ./Script/test/test_cloud_smoke
```

Backup PostgreSQL manuale:

```bash
cd /home/pi/progetto-iot
chmod +x Script/avvio/backupPostgres
./Script/avvio/backupPostgres
```

Backup automatico giornaliero:

```bash
sudo cp cloud/deploy/iot-cloud-backup.service /etc/systemd/system/
sudo cp cloud/deploy/iot-cloud-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iot-cloud-backup.timer
```

Rotazione log MQTT:

```bash
cd /home/pi/progetto-iot
chmod +x Script/avvio/ruotaLogCloud
./Script/avvio/ruotaLogCloud
```

Nota: i file systemd assumono il percorso `/home/pi/progetto-iot`. Se il progetto viene
copiato altrove, aggiornare `WorkingDirectory` ed `ExecStart`.

File raw principali da controllare:

```text
data/raw/ble_samples.csv
data/raw/google_health_samples.csv
data/raw/shelly_samples.csv
```

Per vedere le ultime righe dell'orologio:

```powershell
Import-Csv data\raw\google_health_samples.csv | Select-Object -Last 10 | ConvertTo-Json -Depth 4
```

Il file Google Health viene scritto a ogni ciclo runtime quando `google_health.enabled`
e' `true`. E' utile per debug e storico: il modello continua a usare
`data/processed/latest_window.csv`.

## Controllo qualita manuale

```bash
python -m edge_quality.cli --config config/edge.yml
```

Il report viene salvato in:

```text
outputs/last-quality-report.json
```

Controlla problemi tecnici come:

- campioni BLE mancanti o insufficienti;
- timestamp strani;
- wearable cloud abilitato ma senza dati;
- wearable non presente;
- Shelly/NILM abilitato ma senza campioni.

La stanza BLE sempre uguale per ore viene registrata come osservazione `info`, non come
errore qualita, perche' e' un comportamento potenzialmente interessante.

## Receiver Android BLE

Avviare il receiver locale sul Raspberry:

```bash
python -m edge_receiver.cli --config config/edge.yml --host 0.0.0.0 --port 8000
```

Questo processo resta sempre acceso e riceve i campioni dall'app Android. Il ciclo
`edge_runtime` invece puo' essere eseguito ogni 4 minuti da cron/systemd.

L'app Android inviera' campioni BLE a:

```text
POST http://RASPBERRY_IP:8000/ble/sample
```

Payload minimo:

```json
{
  "room": "kitchen",
  "rssi": -61,
  "beacon_id": "AA:BB:CC:DD:EE:01"
}
```

Test da terminale:

```bash
curl -X POST http://127.0.0.1:8000/ble/sample \
  -H "Content-Type: application/json" \
  -d '{"room":"kitchen","rssi":-61,"beacon_id":"AA:BB:CC:DD:EE:01"}'
```

## Test BLE Raspberry Scanner Alternativo

Prima di raccogliere la baseline, scoprire il tag BLE:

```bash
python -m edge_ingest.ble_cli --config config/edge.yml --discover
```

Inserire poi `target_addresses` o `target_names` in `config/edge.yml` e provare una
scansione reale:

```bash
python -m edge_ingest.ble_cli --config config/edge.yml
```
