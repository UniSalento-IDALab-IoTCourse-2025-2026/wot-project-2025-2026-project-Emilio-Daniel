# Contratti condivisi

Questa cartella contiene i contratti tra Edge, backend, dashboard medico, app paziente e
app caregiver.

I contratti servono per permettere a Emilio e Daniel di lavorare in parallelo senza
rompere l'integrazione.

## File principali

```text
API_CONTRACT.md       Endpoint REST, WebSocket, errori e regole payload
MQTT_CONTRACT.md      Topic MQTT, QoS, sicurezza e payload Edge
examples/            Esempi JSON condivisi
schemas/             Spazio per JSON Schema/OpenAPI, se necessari
```

## Regola operativa

- Emilio prepara esempi reali anonimizzati prodotti dall'Edge.
- Daniel stabilizza contratti API/MQTT e aggiunge esempi backend/task/alert.
- Quando un payload reale cambia, il contratto va aggiornato prima di modificare frontend
  o backend.

## Stato iniziale

Gli esempi lato Daniel sono gia' presenti. Gli esempi Edge reali sono placeholder finche'
Emilio non fornisce i file anonimizzati.
