# Dashboard Medico IoT

Dashboard web React per il triage clinico del progetto IoT.

## Avvio con mock backend

Terminale 1:

```powershell
cd mock_backend
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

Terminale 2:

```powershell
cd Dashboard
npm install
npm run dev
```

Aprire:

```text
http://127.0.0.1:5173
```

Login demo:

```text
doctor@example.test
password-demo
```

## Configurazione

Sviluppo mock:

```text
VITE_API_BASE_URL=http://127.0.0.1:8090/api/v1
VITE_WS_BASE_URL=ws://127.0.0.1:8090/ws/v1
VITE_DATA_SOURCE=mock
```

Produzione o backend reale:

```text
VITE_API_BASE_URL=https://host-backend/api/v1
VITE_WS_BASE_URL=wss://host-backend/ws/v1
VITE_DATA_SOURCE=real
```

La dashboard usa solo queste variabili per passare da mock a backend reale.

## Schermate

- Login e sessione locale.
- Lista pazienti ordinata per severita'.
- Dettaglio paziente con stato corrente e ultime finestre.
- Alert con presa in carico e risoluzione.
- Task con creazione check-in dimostrativo.
- Stato sistema con Edge, Watch, BLE, Google Health e WebSocket.

## Nota clinica

La UI usa sempre linguaggio da triage: segnala livelli, score e dati tecnici, ma non
presenta diagnosi automatiche.
