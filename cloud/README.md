# Triage IoT - Cloud e backend

Questo componente esegue sul PC il broker MQTT, PostgreSQL, il backend FastAPI e il
worker che persiste i messaggi prodotti dal Raspberry Pi.

Il progetto completo raccoglie Google Health e beacon BLE, elabora finestre e score AI
sul Raspberry, invia i risultati via MQTT TLS e li presenta nella dashboard e nell'app
Android.

## Architettura

```text
Raspberry Edge -> MQTT TLS -> Mosquitto -> worker -> PostgreSQL
                                               ^          |
                                               |          v
Android <---------- REST / FCM ------------ FastAPI <-> Dashboard
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

## Servizi

| Servizio | Funzione | Porta host |
| --- | --- | --- |
| `mqtt` | Mosquitto con TLS, ACL e persistenza | `8883` |
| `postgres` | database applicativo | `5432` |
| `backend-migrations` | migrazioni Alembic all'avvio | nessuna |
| `backend` | API REST, WebSocket, auth e FCM | `8080` |
| `backend-mqtt-worker` | ingestione MQTT nel database | nessuna |

Il backend gestisce pazienti, utenti e ruoli, telemetria, alert, task, questionari,
notifiche, report, routine ambientale, spiegazioni AI e audit.

## Configurazione

Partire sempre dagli esempi:

```powershell
Copy-Item .env.example .env
Copy-Item backend\.env.example backend\.env
```

Sostituire tutti i placeholder. Creare localmente:

- `mqtt/passwd`, con utenti `edge_patient_001`, `backend` e `mqtt_test`;
- `mqtt/certs/ca.crt`, `server.crt` e `server.key`;
- `firebase/service-account.json` solo se si usano notifiche reali.

Questi file sono ignorati da Git. Non pubblicare password, chiavi private, token,
service account, dump PostgreSQL o dati dei pazienti.

## Avvio

Dal repository integrato e' consigliato:

```powershell
.\Script\avvio\avviaPC.ps1
```

Per avviare il solo componente Cloud:

```powershell
cd cloud
docker compose up -d --build
docker compose ps
```

Controlli:

```text
http://127.0.0.1:8080/health
http://127.0.0.1:8080/ready
http://127.0.0.1:8080/docs
```

Log utili:

```powershell
docker compose logs -f backend
docker compose logs -f backend-mqtt-worker
docker compose logs -f mqtt
```

Arresto senza eliminare dati:

```powershell
docker compose stop
```

## Test

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

## Pulizia controllata di un paziente

Dal repository integrato il comando seguente mostra soltanto un'anteprima:

```powershell
.\Script\manutenzione\pulisciDatiPaziente.ps1 -PatientId patient-001
```

La modalita `-Execute` crea prima un dump PostgreSQL, elimina i dati storici del solo
paziente e conserva identita, associazioni e dispositivi. Prima dell'esecuzione il
servizio Edge sul Raspberry deve essere fermo e la sua coda MQTT deve essere archiviata,
come descritto nel README principale.

I contratti ufficiali sono nel repository integrato in `Documenti/contracts/`.

## Note operative

- Il Raspberry si collega all'indirizzo LAN del PC sulla porta `8883`.
- La dashboard usa `http://127.0.0.1:8080/api/v1` quando gira sullo stesso PC.
- Il telefono usa `http://IP_PC:8080/api/v1` dalla rete locale.
- Le migrazioni sono eseguite prima dell'avvio del backend.
- Il prototipo non espone PostgreSQL o MQTT direttamente su Internet.
