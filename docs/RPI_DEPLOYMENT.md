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

## Training con baseline reale

Raccogliere circa due settimane di finestre reali in `data/processed/baseline.csv`.
Poi:

```bash
python -m edge_ai.cli train \
  --input data/processed/baseline.csv \
  --patient-id patient-001 \
  --output models/patient-001.pkl
```

## Inferenza periodica

Ogni job edge deve prima produrre un file aggiornato, ad esempio
`data/processed/latest_window.csv`.

```bash
python -m edge_ingest.cli --config config/edge.yml --collect-ble
```

Poi:

```bash
python -m edge_ai.cli infer \
  --model models/patient-001.pkl \
  --input data/processed/latest_window.csv \
  --state data/state/patient-001-debounce.json \
  --output outputs/patient-001-decision.json
```

## Cron provvisorio

```cron
*/8 * * * * cd /home/pi/progetto-iot/edge_node && . ../.venv/bin/activate && python -m edge_ingest.cli --config config/edge.yml --collect-ble && python -m edge_ai.cli infer --model models/patient-001.pkl --input data/processed/latest_window.csv --state data/state/patient-001-debounce.json --output outputs/patient-001-decision.json
```

Durante le prime due settimane di baseline, usare invece:

```cron
*/8 * * * * cd /home/pi/progetto-iot/edge_node && . ../.venv/bin/activate && python -m edge_ingest.cli --config config/edge.yml --collect-ble --append-baseline
```

In produzione i collector reali scriveranno i campioni grezzi in `data/raw/`, poi
`edge_ingest` produrra' la finestra aggregata per il modello.

## Receiver Android BLE

Avviare il receiver locale sul Raspberry:

```bash
python -m edge_receiver.cli --config config/edge.yml --host 0.0.0.0 --port 8000
```

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
