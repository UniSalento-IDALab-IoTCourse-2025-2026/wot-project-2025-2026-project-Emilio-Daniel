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

Login locale:

```text
Usare email e password configurate nel file .env locale del backend.
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
- Grafici wearable/spaziali con intervallo giornaliero o settimanale.
- Valutazione comportamentale con sintesi clinica, contributo delle fonti, fattori principali e avanzamento del profilo personale.
- Alert con presa in carico e risoluzione.
- Task con creazione check-in dimostrativo.
- Stato tecnico del sistema con ultimo ciclo Edge, durata finestra, sensori, Google Health/OAuth, MQTT, coda locale e distinzione warning/guasti.

## Esperienza dell'interfaccia

La dashboard usa un design system clinico responsive condiviso da tutte le viste:

- navigazione laterale con ricerca paziente, filtri e indicatori di attivita;
- header realtime con aggiornamento manuale e accesso rapido alle segnalazioni;
- gerarchia visiva uniforme per routine, attenzione, anomalie e guasti tecnici;
- grafici interattivi, tabelle leggibili e pannelli AI con terminologia comprensibile;
- dialoghi interni per presa in carico, risoluzione alert e creazione attivita;
- feedback di caricamento, errore, esito operazione e assenza dati;
- animazioni brevi disattivate automaticamente quando il sistema richiede movimento ridotto;
- layout desktop, tablet e mobile senza scorrimento orizzontale della pagina.

Gli stili di base restano in `src/styles.css`; il livello visuale moderno e le regole
responsive sono isolati in `src/modern.css`.

## Nota clinica

La UI usa sempre linguaggio da triage: segnala livelli, score e dati tecnici, ma non
presenta diagnosi automatiche.
