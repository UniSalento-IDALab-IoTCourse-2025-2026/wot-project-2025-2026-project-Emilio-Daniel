# Raspberry Pi Deployment Notes

Questa repo e' pensata per essere copiata sul Raspberry Pi 4 senza cambiare codice del modello.
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

## Ciclo edge periodico

Il comando principale del Raspberry e':

```bash
python -m edge_runtime.cli --config config/edge.yml
```

Questo comando:

- legge i dati gia' ricevuti in `data/raw/`;
- produce `data/processed/latest_window.csv`;
- se trova `models/patient-001.pkl`, esegue inferenza;
- aggiorna `data/state/patient-001-debounce.json`;
- salva `outputs/patient-001-decision.json`;
- salva `outputs/last-quality-report.json`;
- salva `outputs/last-cycle.json` con lo stato del ciclo.

Se il modello non esiste ancora, il ciclo non fallisce: aggrega la finestra e salta
l'inferenza.

Il ciclo esegue anche controlli qualita sui dati. Se `--append-baseline` e' attivo ma il
report qualita ha stato `error`, la finestra non viene aggiunta a
`data/processed/baseline.csv`.

## Cron provvisorio

```cron
*/8 * * * * cd /home/pi/progetto-iot/edge_node && . ../.venv/bin/activate && python -m edge_runtime.cli --config config/edge.yml
```

Durante i primi 5/6 giorni di baseline, usare invece:

```cron
*/8 * * * * cd /home/pi/progetto-iot/edge_node && . ../.venv/bin/activate && python -m edge_runtime.cli --config config/edge.yml --append-baseline
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
`edge_runtime` invece puo' essere eseguito ogni 8 minuti da cron/systemd.

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
