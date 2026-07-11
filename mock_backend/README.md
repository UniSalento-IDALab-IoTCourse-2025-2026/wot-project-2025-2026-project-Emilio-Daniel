# Mock Backend Dashboard

Backend finto per sviluppare dashboard medico, app paziente e caregiver senza aspettare
il Cloud reale.

## Avvio

```powershell
cd mock_backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

URL utili:

```text
http://127.0.0.1:8090/health
http://127.0.0.1:8090/api/v1/patients
http://127.0.0.1:8090/api/v1/patients/patient-001/current
ws://127.0.0.1:8090/ws/v1/patients/patient-001
```

## Scenari

Impostare prima dell'avvio:

```powershell
$env:MOCK_SCENARIO = "normal"
```

Valori disponibili:

```text
normal
severe_alert
technical_issue
missing_data
```

Intervallo eventi WebSocket:

```powershell
$env:MOCK_WS_INTERVAL_SECONDS = "5"
```

## Config dashboard

Quando creeremo la dashboard React, il file `.env` potra' usare:

```text
VITE_API_BASE_URL=http://127.0.0.1:8090/api/v1
VITE_WS_BASE_URL=ws://127.0.0.1:8090/ws/v1
VITE_DATA_SOURCE=mock
```

Per passare al backend reale bastera' cambiare URL e `VITE_DATA_SOURCE`.

