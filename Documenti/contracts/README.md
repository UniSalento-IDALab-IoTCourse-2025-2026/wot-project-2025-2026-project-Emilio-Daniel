# Contratti condivisi

Questa cartella contiene i contratti tra Edge, backend, dashboard medico, app paziente e
app caregiver.

I contratti servono per permettere a Emilio e Daniel di lavorare in parallelo senza
rompere l'integrazione.

## File principali

```text
API_CONTRACT.md       Endpoint REST, WebSocket, auth, alert e task
MQTT_CONTRACT.md      Topic MQTT, QoS, sicurezza e payload Edge
openapi.json          OpenAPI generato dal backend FastAPI reale
examples/            Esempi JSON condivisi e anonimizzati
schemas/             Spazio per JSON Schema aggiuntivi, se necessari
```

## Regola operativa

- Emilio mantiene aggiornati gli esempi reali anonimizzati prodotti dall'Edge.
- Daniel mantiene aggiornati OpenAPI, REST, WebSocket e regole backend.
- Quando un payload reale cambia, il contratto va aggiornato nella stessa modifica di
  frontend/backend/Edge.

## Stato attuale

Gli esempi Edge iniziali sono stati sostituiti con payload reali anonimizzati basati su:

```text
edge_node/outputs/last-cycle.json
edge_node/outputs/patient-001-decision.json
edge_node/data/processed/latest_window.csv
```

Il backend reale D5-D9 e la dashboard devono usare questi contratti come riferimento.

## Rigenerare OpenAPI

```powershell
cd cloud/backend
.\.venv\Scripts\python.exe -m scripts.export_openapi
```
