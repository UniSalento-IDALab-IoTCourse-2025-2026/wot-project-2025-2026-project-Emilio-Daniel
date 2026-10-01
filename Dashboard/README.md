# Triage IoT - Dashboard medico

Dashboard React/Vite usata dal medico per consultare dati, score AI, timeline, alert,
attivita, questionari, report e stato tecnico del sistema.

I dati arrivano dal backend FastAPI tramite REST e WebSocket. La dashboard non interroga
direttamente Raspberry, broker o database.

## Progetto completo

```text
Sensori e app -> Raspberry Edge -> MQTT -> Backend/PostgreSQL -> Dashboard
                                                        \-> App Android / FCM
```

Repository del progetto:

- [integrazione](https://github.com/emipasca12/ProgettoIoT)
- [Edge](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-edge-Pascadopoli-Spedicato)
- [Cloud](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-cloud-Pascadopoli-Spedicato)
- [Dashboard](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-dashboard-Pascadopoli-Spedicato)
- [Android](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-android-Pascadopoli-Spedicato)
- [Presentazione](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-presentation-Pascadopoli-Spedicato)

I link dell'organizzazione diventano disponibili dopo la creazione dei repository per
la consegna.

## Funzioni

- login e sessione medico;
- selezione paziente e anagrafica separata;
- riepilogo 24 ore e confronto con baseline;
- dati fisiologici e routine ambientale;
- grafici interattivi e storico dello score AI;
- spiegazione, confidenza, metriche modello, trend e drift;
- timeline unificata;
- alert con workflow clinico;
- attivita e questionari per il paziente;
- messaggi personalizzati a paziente e caregiver;
- report esportabile e stato tecnico;
- cache locale leggera in caso di indisponibilita temporanea del backend.

## Requisiti e configurazione

- Node.js 20 o successivo;
- backend disponibile sulla porta `8080`.

Creare `.env` senza versionarlo:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8080/api/v1
VITE_WS_BASE_URL=ws://127.0.0.1:8080/ws/v1
VITE_DATA_SOURCE=real
```

## Avvio

Nel repository integrato, il comando ufficiale e':

```powershell
.\Script\avvio\avviaPC.ps1
```

Per sviluppo del solo frontend:

```powershell
cd Dashboard
npm ci
npm run dev
```

Aprire <http://127.0.0.1:5173>.

## Test e build

```powershell
npm test
npm run build
```

La build viene prodotta in `dist/`, cartella esclusa da Git.

## Sicurezza e uso clinico

La dashboard mostra solo i pazienti autorizzati dal backend. Token e password non
devono essere inseriti nel codice o nei log. Gli score sono indicatori di supporto e
non sostituiscono il giudizio medico.
