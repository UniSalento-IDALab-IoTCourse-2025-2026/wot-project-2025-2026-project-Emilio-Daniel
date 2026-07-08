# Raspberry Pi Deployment Notes

Questa repo e' pensata per essere copiata sul Raspberry Pi 5 senza cambiare codice del modello.
Sul Pi collegheremo gli adapter reali che produrranno il CSV/JSON conforme a `docs/FEATURE_SCHEMA.md`.

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

## Fitbit OAuth / Pixel Watch 2

Prima della baseline, collegare l'account Fitbit/Google usato dal Google Pixel Watch 2.
Il Raspberry non legge il battito dal Bluetooth del watch: legge le API dopo consenso
OAuth.

Nel portale sviluppatori Fitbit registrare l'app e impostare questo redirect URI:

```text
http://127.0.0.1:8765/callback
```

Poi, da dentro `edge_node/`:

```bash
python -m edge_auth.cli fitbit setup --client-id CLIENT_ID --client-secret CLIENT_SECRET
```

Il comando salva:

```text
config/fitbit_client.json
config/fitbit_token.json
```

Controllare che sia tutto pronto:

```bash
python -m edge_auth.cli fitbit status
```

In `config/edge.yml` abilitare Fitbit:

```yaml
fitbit:
  enabled: true
  token_file: config/fitbit_token.json
  client_file: config/fitbit_client.json
  user_id: "-"
  api_base_url: https://api.fitbit.com
```

L'access token viene rinfrescato automaticamente dal ciclo edge. Se si vuole forzare un
test manuale:

```bash
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
- Fitbit abilitato ma senza dati;
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
