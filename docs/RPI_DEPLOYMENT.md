# Raspberry Pi Deployment Notes

Questa repo e' pensata per essere copiata sul Raspberry Pi 4 senza cambiare codice del modello.
Sul Pi collegheremo gli adapter reali che produrranno il CSV/JSON conforme a `docs/FEATURE_SCHEMA.md`.

## Setup base

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip bluetooth bluez
python3 -m venv .venv
source .venv/bin/activate
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
python -m edge_ingest.cli --config config/edge.yml
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
*/15 * * * * cd /home/pi/progetto-iot && . .venv/bin/activate && python -m edge_ingest.cli --config config/edge.yml && python -m edge_ai.cli infer --model models/patient-001.pkl --input data/processed/latest_window.csv --state data/state/patient-001-debounce.json --output outputs/patient-001-decision.json
```

Durante le prime due settimane di baseline, usare invece:

```cron
*/15 * * * * cd /home/pi/progetto-iot && . .venv/bin/activate && python -m edge_ingest.cli --config config/edge.yml --append-baseline
```

In produzione i collector reali scriveranno i campioni grezzi in `data/raw/`, poi
`edge_ingest` produrra' la finestra aggregata per il modello.
