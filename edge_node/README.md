# Edge Node Raspberry

Questa cartella contiene tutto cio' che gira sul Raspberry Pi o sul PC durante i test
locali.

## Contenuto

```text
edge_ai/        modello Isolation Forest, debounce e CLI train/infer
edge_ingest/    aggregazione dati Fitbit, BLE e Shelly in finestre da 8 minuti
edge_receiver/  receiver FastAPI per campioni BLE inviati dall'app Android
config/         configurazioni YAML dell'edge node
data/           dati grezzi, feature aggregate e stato locale
models/         modelli addestrati
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

## Addestramento modello

```bash
python -m edge_ai.cli train \
  --input data/processed/baseline.csv \
  --patient-id patient-001 \
  --output models/patient-001.pkl
```

## Inferenza

```bash
python -m edge_ai.cli infer \
  --model models/patient-001.pkl \
  --input data/processed/latest_window.csv \
  --state data/state/patient-001-debounce.json \
  --output outputs/patient-001-decision.json
```
