# AUDIT TECNICO COMPLETO — ANALISI DEL PROGETTO IoT

> Analisi del repository come senior software engineer, IoT engineer e ML engineer.
> Fase di sola lettura: nessuna modifica al codice.
> Scopo: comprendere il sistema reale, non quello descritto nella proposta.

---

## Indice

1. Riassunto del progetto
2. Architettura attuale
3. Flusso completo dei dati
4. Hardware realmente presente
5. Elaborazione dei segnali
6. Machine Learning
7. Interfaccia
8. Funzionalità già implementate
9. Problemi
10. Miglioramenti
11. Nuove funzionalità
12. Feature più interessanti
13. Architettura finale consigliata
14. Roadmap
15. Risposte finali

---

## 1. RIASSUNTO DEL PROGETTO

### Cosa abbiamo costruito

Il progetto è un **sistema IoT per il monitoraggio comportamentale e spaziale delle
Attività della Vita Quotidiana (ADL)** di pazienti anziani, con applicazione clinica
nello studio di disturbi neurodegenerativi e depressione.

Il sistema combina:
- **Google Pixel Watch 2**: dati fisiologici (HR, HRV, SpO2, sonno, passi)
- **BlueBeacon BLE ×3**: posizionamento indoor (camera, cucina, bagno, soggiorno)
- **Shelly 3EM**: monitoraggio energetico (NILM)
- **Raspberry Pi 5**: edge node con AI locale
- **Cloud**: FastAPI + PostgreSQL + MQTT
- **Dashboard**: React SPA clinica
- **App mobile**: Android (completa) + iOS (parziale)

---

## 2. ARCHITETTURA ATTUALE

### 2.1 Diagramma Architetturale (ricostruito dal codice)

```
┌─────────────────────────────────────────────────────────────────────┐
│                     SORGENTI DATI (Paziente)                        │
│                                                                     │
│  Pixel Watch 2        BlueBeacon ×3        Shelly 3EM              │
│  (Google Health API)  (Android BLE)        (Energy events)          │
│         │                 │                      │                  │
│         ↓                 ↓                      ↓                  │
│  OAuth2 REST          HTTP POST /ble          CSV grezzo            │
│  (token refresh)      (Foreground Svc)       (energy events)       │
└────────┬────────────────┬──────────────────────┬───────────────────┘
         │                │                      │
         ↓                ↓                      ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    EDGE NODE (Raspberry Pi 5)                       │
│                                                                     │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │
│  │ edge_auth  │→ │ edge_ingest  │→ │ edge_quality │→ │ edge_ai  │ │
│  │ OAuth2     │  │ 4-min window │  │ Validation   │  │ 3 models │ │
│  └────────────┘  └──────────────┘  └──────────────┘  │ + fusion │ │
│                                                       │ + debounce│ │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  └─────┬────┘ │
│  │ edge_      │  │ edge_        │  │ edge_        │        │      │
│  │ receiver   │  │ baseline     │  │ mqtt         │←───────┘      │
│  │ HTTP POST  │  │ 7-day auto   │  │ TLS + queue  │               │
│  └──────▲─────┘  └──────────────┘  └──────┬───────┘               │
│         │                                  │                        │
└─────────┼──────────────────────────────────┼────────────────────────┘
          │ HTTP                             │ MQTT/TLS
          │                                  ↓
┌─────────┴──────────────────────────────────────────────────────────┐
│                         CLOUD (Docker)                              │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌─────────────────────────┐│
│  │ Mosquitto    │──→│ FastAPI      │──→│ PostgreSQL 16           ││
│  │ MQTT/TLS     │   │ Backend      │   │ 16 tabelle              ││
│  │ ACL per pt.  │   │ :8080        │   │ + Alembic migrations    ││
│  └──────────────┘   └──────▲───────┘   └─────────────────────────┘│
│                            │                                        │
│                       WebSocket                                     │
│                            │                                        │
│  ┌─────────────────────────┴─────────────────────────────────────┐ │
│  │                     Dashboard React 19                         │ │
│  │  Login │ Paziente │ Timeline │ Alert │ Task │ Sistema │ Report │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────┐  ┌─────────────────────────────────────┐│
│  │ App Android           │  │ App iOS (parziale)                  ││
│  │ BLE + Firebase Push   │  │ Swift/SwiftUI                       ││
│  └───────────────────────┘  └─────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Componenti e Responsabilità

| Componente | Directory | Responsabilità | Dipendenze |
|-----------|-----------|----------------|------------|
| edge_auth | `edge_auth/` | OAuth Google Health, token refresh | requests, json |
| edge_ingest | `edge_ingest/` | Aggregazione dati in finestre 4 min | pandas, yaml |
| edge_quality | `edge_quality/` | Quality checks sui dati | pandas |
| edge_ai | `edge_ai/` | 3 modelli IsolationForest, fusion, debounce | scikit-learn, numpy |
| edge_baseline | `edge_baseline/` | Gestione baseline 7 giorni | pandas |
| edge_mqtt | `edge_mqtt/` | Publisher MQTT TLS + coda offline | paho-mqtt |
| edge_receiver | `edge_receiver/` | Receiver BLE da Android | FastAPI, uvicorn |
| edge_runtime | `edge_runtime/` | Ciclo edge unico (4 min) | tutti i moduli edge |
| edge_stack | `edge_stack/` | Avvio receiver + runtime | subprocess |
| edge_datasets | `edge_datasets/` | Converter dataset pubblici | pandas |
| cloud/backend | `cloud/backend/` | API REST, MQTT subscriber, WebSocket | FastAPI, SQLAlchemy |
| cloud/mqtt | `cloud/mqtt/` | Configurazione Mosquitto | Docker |
| Dashboard | `Dashboard/` | Interfaccia clinica React | React 19, Vite |
| Android App | `Applicazione IoT Companion/` | BLE scanning, Firebase push | Java, Android SDK |
| iOS App | `Applicazione IoT Companion/` | BLE monitoring | Swift, SwiftUI |

### 2.3 Grafo delle Dipendenze

```
edge_runtime
    ├── edge_ingest (aggregator, config, time_windows, ble_adapter, shelly_adapter, google_health_adapter)
    ├── edge_quality (checks)
    ├── edge_ai (model, fusion, debounce, features, schema)
    ├── edge_baseline (session)
    ├── edge_mqtt (publisher, messages, queue)
    └── edge_auth (google_health_oauth)

edge_receiver (standalone FastAPI)
    └── edge_ingest (ble_storage, config)

cloud/backend
    ├── app/api/routes (13 moduli)
    ├── app/auth (JWT, password)
    ├── app/core (config, errors, logging)
    ├── app/db/models (16 tabelle)
    ├── app/mqtt (subscriber, ingest, schemas, topics)
    └── app/services (push notifications)

Dashboard
    └── api/client.js → cloud/backend REST + WebSocket
```

---

## 3. FLUSSO COMPLETO DEI DATI

### 3.1 Ciclo Edge (ogni 4 minuti)

```
FASE 1 — RACCOLTA DATI
├── Google Health API (OAuth2)
│   ├── GET /v1/users/me/dataset:heartrate
│   ├── GET /v1/users/me/dataset:oxygen-saturation
│   ├── GET /v1/users/me/dataset:sleep-segment
│   ├── GET /v1/users/me/dataset:session-segment
│   └── Output: heart_rate_mean, heart_rate_std, resting_heart_rate,
│       hrv_rmssd, spo2_mean, sleep_minutes, awake_minutes,
│       steps, sedentary_minutes, wearable_present, battery_pct
│
├── BLE CSV (da edge_receiver via HTTP POST)
│   ├── Campioni grezzi: room, rssi, beacon_id, timestamp
│   ├── Aggregazione per finestra temporale
│   └── Output: bedroom_minutes, kitchen_minutes, bathroom_minutes,
│       living_room_minutes, room_changes, night_room_changes,
│       longest_single_room_minutes
│
└── Shelly CSV (energy events)
    ├── Campioni grezzi: timestamp, events
    └── Output: nilm_total_wh, nilm_kitchen_events, nilm_tv_minutes,
        nilm_coffee_events, nilm_stove_events

FASE 2 — AGGREGAZIONE
├── build_feature_window(): 22 colonne in una riga
├── write_latest_window(): CSV latest_window.csv
└── append_google_health_raw_row(): storico raw

FASE 3 — QUALITÀ
├── evaluate_quality(): controlli su bounds, BLE, wearable, Shelly
└── QualityReport: ok / warning / error

FASE 4 — BASELINE (se auto-baseline attivo)
├── _run_baseline_safety_gate(): modello generico blocca finestre sospette
└── append_baseline_row(): baseline.csv

FASE 5 — INFERENZA (se almeno 1 modello esiste)
├── generic_spatial → score spaziale (0-100)
├── generic_wearable → score wearable (0-100)
├── personal → score personale (0-100)
├── fuse_model_results(): fusione a pesi ponderati
└── AlertDebouncer.update(): debounce 48h → livello triage

FASE 6 — PUBBLICAZIONE
├── build_cycle_messages(): status + window + decision + alert
├── EdgeMqttPublisher.publish(): TLS + Last Will
└── DiskMqttQueue: coda offline su disco
```

### 3.2 Flusso Cloud

```
MQTT SUBSCRIBER → BackendMqttSubscriber._on_message()
    ↓
ingest_mqtt_message(): validazione + deduplicazione (message_id)
    ↓
store_payload(): salva nella tabella corretta (16 tabelle)
    ↓
publish_internal_event(): inoltra a WebSocket
    ↓
Dashboard → REST API / WebSocket → aggiornamento UI
```

### 3.3 Punti Critici nel Flusso

| Punto | Rischio | Impatto |
|-------|---------|---------|
| Google Health API delay (5-30 min) | Finestra parziale | Feature wearable incomplete |
| BLE CSV non sincronizzato | Campioni fuori finestra | Feature spaziali errate |
| Coda offline MQTT senza limite | Riempimento disco | Perdita dati |
| Deduplicazione message_id | Due payload diversi stessa finestra | Duplicati nel DB |
| NaN nelle feature | Modello su dati incompleti | Predizioni inaffidabili |

---

## 4. HARDWARE REALMENTE PRESENTE

### 4.1 Inventario

| Dispositivo | Protocollo | Dati Misurati | Stato |
|------------|------------|---------------|-------|
| Google Pixel Watch 2 | Google Health API (OAuth2 REST) | HR, HRV, SpO2, sleep, steps | ✅ Integrato |
| BlueBeacon 01 ×3 | BLE (via app Android) | Indoor positioning | ✅ Integrato |
| Shelly 3EM | HTTP/CSV | Consumo energetico | ✅ Integrato |
| Raspberry Pi 5 | — | Edge computing | ✅ Piattaforma |

## 5. ELABORAZIONE DEI SEGNALE

### 5.1 Dati Google Health (sostituisce MAX30102 + MPU6050)

**Fonte**: Google Health API via OAuth2

**Feature estratte per finestra 4 minuti:**

| Feature | Tipo | Fonte Google Health | Elaborazione |
|---------|------|--------------------| -------------|
| heart_rate_mean | Continua | heartrate dataset | Media nella finestra |
| heart_rate_std | Continua | heartrate dataset | Deviazione standard |
| resting_heart_rate | Continua | resting_hr dataset | Ultimo valore disponibile |
| hrv_rmssd | Continua | heart-rateVariability | RMSSD calcolato |
| spo2_mean | Continua | oxygen-saturation | Media nella finestra |
| steps | Discreta | steps dataset | Conteggio finestra |
| sedentary_minutes | Continua | session segment | Calcolo da dataset |
| sleep_minutes | Discreta | sleep segment | Durata sonno (notte) |
| awake_minutes | Discreta | sleep segment | Tempo sveglio durante sonno |
| wearable_present | Booleano | Presenza dati | Se ci sono dati nella finestra |
| battery_pct | Intero | Battery level | Ultimo livello batteria |

### 5.2 Dati BLE (sostituisce MPU6050 per posizionamento)

**Fonte**: Campioni BLE dalla app Android via HTTP POST

**Elaborazione:**
1. Campioni grezzi: `(room, rssi, beacon_id, timestamp)`
2. Selezione beacon con RSSI più forte per ogni timestamp
3. Mappatura beacon → stanza: `BlueBeacon 01` = cucina, `BlueBeacon 02` = camera, `BlueBeacon 03` = bagno
4. Aggregazione in feature temporali:
   - `room_changes`: numero di cambi stanza nella finestra
   - `night_room_changes`: cambi stanza tra le 0:00 e le 6:00
   - `*_minutes`: minuti trascorsi in ogni stanza
   - `longest_single_room_minutes`: permanenza continua massima in una stanza

### 5.3 Dati Shelly (sostituisce GSR per attività)

**Fonte**: Eventi energetici dal monitoraggio Shelly 3EM

**Feature estratte:**
- `nilm_total_wh`: energia totale consumata nella finestra
- `nilm_kitchen_events`: eventi rilevati in cucina (NILM)
- `nilm_tv_minutes`: minuti di utilizzo TV
- `nilm_coffee_events`: eventi macchina caffè
- `nilm_stove_events`: eventi fornelli

**Nota**: NILM (Non-Intrusive Load Monitoring) identifica quali appliance
vengono utilizzate analizzando il profilo di consumo energetico.

### 5.4 Qualità del Segnale

| Sorgente | Qualità | Problemi |
|----------|---------|----------|
| Google Health | Alta | Delay 5-30 min, dati non istantanei |
| BLE Beacons | Media | RSSI rumoroso, dipende dalla posizione |
| Shelly 3EM | Buona | Solo eventi, non flusso continuo |

### 5.5 Sincronizzazione tra Sensori

**Problema**: Le tre sorgenti hanno frequenze e delay diversi:
- Google Health: delay variabile 5-30 minuti
- BLE: real-time (ogni campione Android)
- Shelly: event-based (non continuo)

La finestra 4 minuti potrebbe avere dati parziali da una o più sorgenti.
Il sistema gestisce questo con `nan` per feature mancanti.

---

## 6. MACHINE LEARNING

### 6.1 Pipeline Completa

```
DATASET (baseline.csv o dataset pubblici)
    ↓
DATA CLEANING (validate_feature_frame)
    ↓
FEATURE ENGINEERING (22 colonne)
    ↓
PREPROCESSING (SimpleImputer + StandardScaler)
    ↓
MODEL (IsolationForest, contamination=0.05)
    ↓
TRAINING (fit su dati)
    ↓
SERIALIZATION (pickle → .pkl)
    ↓
INFERENCE (predict_record → score 0-100)
    ↓
FUSION (fuse_model_results → score ponderato)
    ↓
DEBOUNCE (AlertDebouncer → livello triage)
    ↓
OUTPUT (decision JSON)
```

### 6.2 Modelli

| Modello | File | Scope | Features | Training Data |
|---------|------|-------|----------|---------------|
| Generic Spatial | `generic_spatial.pkl` | Domestico | room_changes, bedroom_minutes, nilm_* | CASAS + sintetico 300K |
| Generic Wearable | `generic_wearable.pkl` | Fisiologico | heart_rate, hrv_rmssd, spo2, sleep | WESAD + PAMAP2 + fitbitdata + sintetico 300K |
| Personal | `patient-001.pkl` | Personale | Tutte le 22 feature | Baseline 7 giorni (dati reali) |

### 6.3 Pipeline scikit-learn

```python
Pipeline([
    ("physiology_clip", PhysiologicalFeatureClipper),  # solo generico wearable
    ("imputer", SimpleImputer(strategy="median")),
    ("scaler", StandardScaler()),
    ("feature_weights", FeatureWeightScaler),  # solo generici
    ("model", IsolationForest(
        n_estimators=200,
        contamination=0.05,
        random_state=42,
        n_jobs=-1
    ))
])
```

### 6.4 Conversione Score

```
Decision Value (IsolationForest) → Score 0-100

Score = (normal_anchor - decision_value) / (normal_anchor - severe_anchor) * 100

Fascia:
  0-35   green      routine normale
  35-65  yellow     attenzione lieve
  65-80  orange     anomalia importante
  80-100 red        anomalia severa
  technical         problema non clinico
```

### 6.5 Fusion

```
Pesi (con modello personale):
  generico spaziale: 15%
  generico wearable: 15%
  personale: 70%

Pesi (solo generici):
  generico spaziale: 50%
  generico wearable: 50%

Regole:
  - 2+ modelli concordano su soglia alta → bonus +5
  - 1 solo modello → penalty -10, max score 79.9
  - Tutti normali → max score 34.9
```

### 6.6 Debounce

```
Finestra: 48 ore
Orange: serve 4+ record arancioni per confermare
Red: pubblicato subito
Yellow: visibile in dashboard, non pubblicato come alert
Technical: separato dai livelli clinici
```

### 6.7 Dataset Pubblici Utilizzati

| Dataset | Tipo | Utilizzo |
|---------|------|----------|
| CASAS | Activity recognition | Training generico spaziale |
| WESAD | Wearable stress | Training generico wearable |
| PAMAP2 | Physical activity | Training generico wearable |
| fitbitdata | Dati Fitbit | Training generico wearable |
| Sintetico 300K | Generato | Training tutti i generici |

### 6.8 Dataset Diagnosi (non ML)

| Dataset | Tipo | Utilizzo |
|---------|------|----------|
| ADReSS | Demenza vs controllo | Test diagnosi demenza |
|建委 ADL | Activity of Daily Living | Test attività quotidiane |
| GW | Geriatric Ward | Test ambiente clinico |

### 6.9 Problemi Critici ML

| Problema | Impatto | Severità |
|----------|---------|----------|
| Nessun validation set | Overfitting non rilevabile | **CRITICO** |
| Nessuna metrica (precision, recall) | Impossibile valutare performance | **CRITICO** |
| Nessuna feature importance | Modello "black box" | **ALTO** |
| Nessun confidence score | Predizioni senza affidabilità | **ALTO** |
| Contamination fisso 0.05 | Non adattivo al profilo paziente | **MEDIO** |
| Nessun retraining automatico | Modello degrada nel tempo | **ALTO** |
| `fall_events` sempre 0 | Feature inutile nel modello | **BASSO** |
| Nessun test su inferenza | Impossibile verificare correttezza | **ALTO** |

---

## 7. INTERFAZZA

### 7.1 Stack

- React 19 + Vite 7
- lucide-react per icone
- CSS custom (styles.css: 2588 righe + modern.css: 5447 righe)
- Nessun router, nessun state management, nessuna libreria UI

### 7.2 Schermate (8 tab)

| Tab | Contenuto | Dati mostrati |
|-----|-----------|---------------|
| Quadro clinico | AI score gauge, spiegazioni, grafici, tabella finestre | Score, feature_values, feature_explanation |
| Timeline | Eventi cronologici | Alert, decisioni, eventi sistema |
| Valutazioni | Questionari programmati | PHQ-2, MMSE, MoCA, punteggi |
| Routine ambientale | Minuti per stanza, baseline | BLE spatial, confronto temporale |
| Segnalazioni | Alert con workflow | create → acknowledge → resolve → delete |
| Attività | Task clinici, messaggi | task CRUD, messaggi caregiver/paziente |
| Sistema | Stato RPi, MQTT, sensori | last_cycle, sensor_status, oauth, mqtt_queue |
| Report | Export dati | report-data endpoint |

### 7.3 Login

- Schermata a 2 pannelli (brand + form)
- Email + password
- Sessione salvata in localStorage

### 7.4 Grafici

- SVG sparkline con hover, selezione, pan/zoom
- Day/week toggle
- Chart dialog per espansione
- Feature principali: HR, SpO2, steps, room changes

### 7.5 Valutazione UX

**Punti di forza:**
- Design clinico responsive
- Gerarchia visiva per livelli di rischio
- Workflow alert completo
- Template test clinici
- Accessibilità parziale (ARIA labels)

**Problemi:**
- **5467 righe in un file** (App.jsx) — architetturalmente inaccettabile
- Nessun error boundary
- Nessun test
- Nessun router
- CSS duplicato (8000+ righe totali)
- Nessuna notificazione browser
- Nessun offline mode

---

## 8. FUNZIONALITÀ GIÀ IMPLEMENTATE

### ✅ Completamente Implementate

| # | Funzionalità | Componente |
|---|-------------|------------|
| 1 | Acquisizione dati Google Health (HR, HRV, SpO2, sleep, steps) | edge_ingest |
| 2 | Acquisizione dati BLE (indoor positioning) | edge_receiver + edge_ingest |
| 3 | Acquisizione dati Shelly/NILM | edge_ingest |
| 4 | Aggregazione in finestre 4 minuti | edge_ingest |
| 5 | Quality checks sui dati | edge_quality |
| 6 | 3 modelli IsolationForest | edge_ai |
| 7 | Fusione modelli a pesi | edge_ai/fusion |
| 8 | Debounce anti-alarm-fatigue | edge_ai/debounce |
| 9 | Baseline personale automatica 7 giorni | edge_baseline |
| 10 | Safety gate per baseline (modelli generici) | edge_runtime |
| 11 | Publisher MQTT con TLS | edge_mqtt |
| 12 | Coda offline su disco | edge_mqtt/queue |
| 13 | Last Will MQTT | edge_mqtt/messages |
| 14 | ACL MQTT per paziente | cloud/mqtt |
| 15 | Backend FastAPI completo | cloud/backend |
| 16 | Database PostgreSQL con 16 tabelle | cloud/backend/db |
| 17 | 5 migrazioni Alembic | cloud/backend/alembic |
| 18 | Subscriber MQTT backend | cloud/backend/mqtt |
| 19 | Deduplicazione su message_id | cloud/backend/mqtt |
| 20 | WebSocket real-time | cloud/backend/api |
| 21 | Autenticazione JWT con refresh token | cloud/backend/auth |
| 22 | Ruoli doctor/caregiver/patient/admin | cloud/backend/auth |
| 23 | Audit logging | cloud/backend |
| 24 | Push notification Firebase | cloud/backend/services |
| 25 | Workflow alert completo | cloud/backend/api |
| 26 | Questionari programmabili | cloud/backend/api |
| 27 | Dashboard React 8 viste | Dashboard |
| 28 | Login con sessione | Dashboard |
| 29 | Grafici SVG interattivi | Dashboard |
| 30 | App Android con BLE foreground service | Android App |
| 31 | Firebase Cloud Messaging | Android App |
| 32 | Dataset converters (CASAS, PAMAP2, WESAD, fitbitdata) | edge_datasets |
| 33 | Dataset sintetici controllati (300K righe) | edge_datasets |
| 34 | OAuth Google Health con refresh | edge_auth |
| 35 | Systemd service files | cloud/deploy |
| 36 | Docker Compose stack | cloud/docker-compose |

---

## 9. PROBLEMI

### 9.1 Bug

| # | Bug | Dove | Severità |
|---|-----|------|----------|
| 1 | `fall_events` sempre 0 nel modello | `schema.py` | Basso |
| 2 | `InconsistentVersionWarning` filtrato silenziosamente | `cli.py` | Basso |
| 3 | `app.include_router(api_router)` duplicato | `main.py` | Medio |
| 4 | `LOADING_ATTEMPTS` dict in-memory (si perde con restart) | `auth.py` | Basso |
| 5 | Rate limit login in-memory (non persistente) | `auth.py` | Basso |

### 9.2 Technical Debt

| # | Debt | Impatto |
|---|------|---------|
| 1 | Nessun layer Service nel backend | Manutenibilità |
| 2 | Nessun Pydantic schema per request/response | Type safety |
| 3 | Event bus in-memory (si perde con restart) | Perdita eventi |
| 4 | Nessuna retention database | Crescita indefinita |
| 5 | Nessun CI/CD | Deployment manuale |
| 6 | Nessun monitoring / health check | Osservabilità zero |
| 7 | CSS duplicato (8000+ righe) | Manutenibilità |
| 8 | Nessun router React | SPA monolitica |

### 9.3 Problemi Architetturali

| # | Problema | Impatto |
|---|----------|---------|
| 1 | Dashboard monolitica (5467 righe) | Impossibile manutenere/testare |
| 2 | Nessuna metrica ML | Impossibile valutare il modello |
| 3 | Nessun validation set | Overfitting non rilevabile |
| 4 | Coda offline MQTT senza limite | Riempimento disco |
| 5 | Secrets hardcoded in alcune configurazioni | Sicurezza |
| 6 | Nessun backup automatizzato | Perdita dati |

---

## 10. MIGLIORAMENTI

### 10.1 Per l'Esame (Priorità Massima)

| # | Miglioramento | Perché | Complessità |
|---|--------------|--------|-------------|
| 1 | Validation set + metriche ML | Dimostrare che il modello funziona | Bassa |
| 2 | Feature importance | Rendere il modello spiegabile | Media |
| 3 | Confidence score | Le predizioni hanno affidabilità | Bassa |
| 4 | Dashboard refactoring | Dimostrare buona pratica | Alta |
| 5 | Test automatizzati | Il sistema è testato | Media |

### 10.2 Per la Production (Priorità Alta)

| # | Miglioramento | Perché | Complessità |
|---|--------------|--------|-------------|
| 6 | Retraining automatico drift | Il sistema si auto-migliora | Media |
| 7 | Alert assenza prolungata | Rileva emergenze silenziose | Bassa |
| 8 | Alert degradazione progressiva | Monitora trend score | Bassa |
| 9 | Database retention | Crescita controllata | Bassa |
| 10 | Monitoring infrastrutturale | Osservabilità | Media |
| 11 | Backup automatizzato | Dati protetti | Bassa |

---

## 11. NUOVE FUNZIONALITÀ

Tutte le seguenti funzionalità utilizzano **esclusivamente dati e hardware già presenti**.

### 11.1 Data Features

| # | Feature | Dati utilizzati | Utilità | Complessità | Priorità |
|---|---------|----------------|---------|-------------|----------|
| 1 | Composite Wellness Index | HR, HRV, SpO2, steps, sleep, movimento | Riassume 7+ feature in 1 numero | Media | **Alta** |
| 2 | Profilo Circadiano | HR per finestra × ore × giorni | Mostra ritmo sonno-veglia | Media | **Alta** |
| 3 | Indice ADL | BLE + NILM + wearable | Misura autonomia funzionale | Alta | **Alta** |
| 4 | Analisi Sonno-Veglia | sleep, HR notturno, bedroom, night_activity | Qualità sonno oggettiva | Media | **Alta** |
| 5 | Indoor Mobility Index | room_changes, pernessa per stanza | Rileva isolamento o agitazione | Bassa | **Media** |
| 6 | Metriche Attività | steps, sedentary, BLE | Trend attività nel tempo | Bassa | **Media** |

### 11.2 AI/ML Features

| # | Feature | Dati utilizzati | Utilità | Complessità | Priorità |
|---|---------|----------------|---------|-------------|----------|
| 7 | Feature Importance (permutazione) | Modelli già addestrati | Rende il modello trasparente | Media | **Alta** |
| 8 | Confidence Score | Feature windows + modelli | Misura affidabilità predizione | Bassa | **Alta** |
| 9 | Anomaly Explanation (linguaggio naturale) | Decision JSON + baseline | Da JSON a frase clinica | Media | **Alta** |
| 10 | Retraining Automatico con Drift | Storico score + baseline | Sistema si auto-migliora | Media | **Alta** |
| 11 | Trend Prediction (forecasting) | Storico feature windows | Previsione 4-12 ore | Alta | **Alta** |
| 12 | Prediction vs Actual | Storico decisioni + windows | Valuta qualità modello | Media | **Media** |
| 13 | Clustering Giornaliero | Storico feature windows | Classifica tipi di giornata | Alta | **Media** |

### 11.3 Analytics Features

| # | Feature | Dati utilizzati | Utilità | Complessità | Priorità |
|---|---------|----------------|---------|-------------|----------|
| 14 | Matrice di Correlazione | 22 feature × storico | Trova relazioni nascoste | Bassa | **Media** |
| 15 | Confronto Settimanale | Storico feature windows | Evoluzione nel tempo | Bassa | **Media** |
| 16 | Distribuzione Oraria | BLE + timestamp | Quando il paziente fa cosa | Bassa | **Media** |
| 17 | Giorni Anomali Storici | Storico score AI | Pattern di anomalie | Bassa | **Media** |

### 11.4 Alert Features

| # | Feature | Dati utilizzati | Utilità | Complessità | Priorità |
|---|---------|----------------|---------|-------------|----------|
| 18 | Alert Adattivi (soglie dinamiche) | Baseline personale | Riduce falsi positivi | Media | **Alta** |
| 19 | Alert Degradazione Progressiva | Storico score | Avviso prima della soglia | Bassa | **Alta** |
| 20 | Alert Assenza Insolita | BLE spatial data | Rileva emergenze silenziose | Bassa | **Alta** |
| 21 | Alert Compositi | Tutti i dati | Multipli segnali = alert forte | Media | **Media** |

### 11.5 Reporting Features

| # | Feature | Dati utilizzati | Utilità | Complessità | Priorità |
|---|---------|----------------|---------|-------------|----------|
| 22 | Report Settimanale Automatico | Tutto lo storico | Riassunto per il medico | Media | **Alta** |
| 23 | Morning Brief | Dati notturni | Inizio giornata informato | Bassa | **Media** |
| 24 | Report Conversazione Clinica | Tutto lo storico | Briefing pre-visita | Alta | **Media** |

### 11.6 Dashboard Features

| # | Feature | Dati utilizzati | Utilità | Complessità | Priorità |
|---|---------|----------------|---------|-------------|----------|
| 25 | Giornata Tipo vs Oggi | Storico × 30 giorni | Confronto fondamentale | Media | **Alta** |
| 26 | Trend Overlay Multi-Feature | Storico feature windows | Relazioni temporali | Bassa | **Media** |
| 27 | Multi-Patient Summary | Backend multi-patient | Vista riepilogativa medico | Media | **Media** |

---

## 12. FEATURE PIÙ INTERESSANTI

### 🏆 WOW #1: Anomaly Explanation in Linguaggio Naturale

**Cosa fa**: Trasforma il JSON tecnico della decisione AI in una frase clinica leggibile.

**Dati utilizzati**: Decision JSON (score, feature_values, feature_explanation) + baseline

**Come funziona**:
```
JSON: {"score": 72, "feature_values": {"heart_rate_mean": 95, "bedroom_minutes": 35}}
        ↓
Confronto con baseline: HR +25% vs media, camera 2x vs solito
        ↓
OUTPUT: "Anomalia rilevata: battito cardiaco 25% sopra la media, permanenza
         in camera doppia rispetto al solito, nessun movimento in cucina per 2 ore"
```

**Cosa vede l'utente**: Il medico legge una frase, non deve interpretare grafici o JSON.

**Perché è importante**: È il passaggio da "sistema che genera dati" a "sistema che genera informazione".

---

### 🏆 WOW #2: Giornata Tipo vs Oggi (Day Profile Overlay)

**Cosa fa**: Confronta il profilo "tipico" del paziente (ultimi 30 giorni) con la giornata attuale.

**Dati utilizzati**: Storico feature windows × 30 giorni × ore

**Come funziona**:
```
Media feature per fascia oraria su 30 giorni → profilo tipico
Profilo odierno → linea sovrapposta
        ↓
Grafico con 2 linee: "tipico" vs "oggi"
```

**Cosa vede l'utente**: In un colpo d'occhio vede se il paziente sta fuori dalla routine.

**Perché è importante**: Il primo sguardo che un geriatra fa è "come è oggi rispetto al solito".

---

### 🏆 WOW #3: Alert di Assenza Insolita

**Cosa fa**: Rileva quando il paziente non si muove per un periodo anomalo.

**Dati utilizzati**: room_changes, kitchen_minutes, bathroom_minutes, bedroom_minutes

**Come funziona**:
```
Pattern spaziali ultime 4 ore
        ↓
Confronto con profilo circadiano medio
        ↓
Se per > 4 ore nessun movimento → alert
```

**Cosa vede l'utente**: "Nessuna attività rilevata da 4 ore. Verificare stato del paziente."

**Perché è importante**: Un paziente caduto a terra non genera un "score alto" - genera ZERO movimento. Questo alert rileva un'emergenza che il modello AI non cattura.

---

### 🏆 WOW #4: Retraining Automatico con Drift Detection

**Cosa fa**: Il sistema rileva quando il modello personale non è più accurato e si retraina automaticamente.

**Dati utilizzati**: Score AI storici + baseline personale

**Come funziona**:
```
Score ultimi 7 giorni
        ↓
Trend lineare dello score
        ↓
Se media score cresce per > 7 giorni → drift
        ↓
Retraining su baseline aggiornata
        ↓
Log: "Modello retrained il [data] con [N] finestre. Drift: [descrizione]"
```

**Cosa vede l'utente**: Il sistema si mantiene accurato senza intervento manuale.

**Perché è importante**: Dopo mesi, il modello diventa inutile senza retraining.

---

### 🏆 WOW #5: Report Settimanale Automatico

**Cosa fa**: Genera ogni lunedì un riassunto della settimana precedente.

**Dati utilizzati**: 1008 finestre + decisioni + alert + test

**Come funziona**:
```
1008 finestre della settimana
        ↓
Statistiche per feature, confronto con settimana precedente
        ↓
Giorni anomali, alert, test completati
        ↓
Report testuale strutturato
        ↓
"Settimana 12-18 marzo: 2 giorni anomali, media HR 78bpm (+3% vs scorsa),
 sonno medio 6.2h (-0.3h), 1 test completato, 1 alert risolto"
```

**Cosa vede l'utente**: Il medico ha un briefing pronto ogni lunedì senza fare nulla.

**Perché è importante**: Automatizzare il report è il formato in cui i medici lavorano già.

---

## 13. ARCHITETTURA FINALE CONSIGLIATA

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SORGENTI DATI                                │
│                                                                     │
│  Pixel Watch 2        BlueBeacon ×3        Shelly 3EM              │
│  (Google Health API)  (Android BLE)        (Energy events)          │
└────────┬───────────────┬──────────────────────┬────────────────────┘
         │               │                      │
         ↓               ↓                      ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    EDGE NODE (Raspberry Pi 5)                       │
│                                                                     │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │
│  │ edge_auth  │→ │ edge_ingest  │→ │ edge_quality │→ │ edge_ai  │ │
│  │ OAuth2     │  │ 4-min window │  │ Validation   │  │ 3 models │ │
│  └────────────┘  └──────────────┘  └──────────────┘  │ + fusion │ │
│                                                       │ + debounce│ │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  └─────┬────┘ │
│  │ edge_      │  │ edge_        │  │ edge_        │        │      │
│  │ receiver   │  │ baseline     │  │ mqtt         │←───────┘      │
│  │ HTTP POST  │  │ 7-day auto   │  │ TLS + queue  │               │
│  └──────▲─────┘  └──────────────┘  └──────┬───────┘               │
│         │                                  │ MQTT/TLS               │
└─────────┼──────────────────────────────────┼───────────────────────┘
          │                                  ↓
┌─────────┴──────────────────────────────────────────────────────────┐
│                         CLOUD (Docker)                              │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌─────────────────────────┐│
│  │ Mosquitto    │──→│ FastAPI      │──→│ PostgreSQL 16           ││
│  │ MQTT/TLS     │   │ Backend      │   │ + retention policy      ││
│  └──────────────┘   │ + WebSocket  │   │ + partitioning          ││
│                     │ + Firebase   │   └─────────────────────────┘│
│                     └──────▲───────┘                               │
│                            │ WebSocket                             │
│                            │                                       │
│  ┌─────────────────────────┴─────────────────────────────────────┐ │
│  │                     Dashboard React (refactored)               │ │
│  │  ┌─────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌───────────┐  │ │
│  │  │Login│ │Pazien│ │Time- │ │Alert │ │Task  │ │Sistema    │  │ │
│  │  │     │ │te    │ │line  │ │      │ │      │ │           │  │ │
│  │  └─────┘ └──────┘ └──────┘ └──────┘ └──────┘ └───────────┘  │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────────────────────┐  │ │
│  │  │Routine   │ │Valutazioni│ │Report + Morning Brief       │  │ │
│  │  └──────────┘ └──────────┘ └──────────────────────────────┘  │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 14. ROADMAP

### FASE 1 — Fondamenta (5-7 giorni)

| # | Task | Priorità | Complessità | Dipende da |
|---|------|----------|-------------|------------|
| 1.1 | Validation set per modelli AI | CRITICA | Bassa | Nulla |
| 1.2 | Metriche ML (precision, recall, F1) | CRITICA | Bassa | 1.1 |
| 1.3 | Confidence score | ALTA | Bassa | Nulla |
| 1.4 | Feature importance (permutazione) | ALTA | Media | Nulla |
| 1.5 | Test edge_ai (training, inferenza, fusion) | CRITICA | Media | Nulla |

### FASE 2 — Qualità codice (7-10 giorni)

| # | Task | Priorità | Complessità | Dipende da |
|---|------|----------|-------------|------------|
| 2.1 | Dashboard refactoring (split App.jsx) | CRITICA | Alta | Nulla |
| 2.2 | Error boundaries React | ALTA | Bassa | 2.1 |
| 2.3 | Test edge_ingest | ALTA | Media | Nulla |
| 2.4 | Test backend API | ALTA | Media | Nulla |

### FASE 3 — Funzionalità AI (5-7 giorni)

| # | Task | Priorità | Complessità | Dipende da |
|---|------|----------|-------------|------------|
| 3.1 | Anomaly explanation (linguaggio naturale) | ALTA | Media | 1.4 |
| 3.2 | Alert assenza prolungata | ALTA | Bassa | Nulla |
| 3.3 | Alert degradazione progressiva | ALTA | Bassa | Nulla |
| 3.4 | Retraining automatico con drift | ALTA | Media | 1.1 |

### FASE 4 — Dashboard avanzata (5-7 giorni)

| # | Task | Priorità | Complessità | Dipende da |
|---|------|----------|-------------|------------|
| 4.1 | Giornata tipo vs oggi | ALTA | Media | Nulla |
| 4.2 | Report settimanale automatico | ALTA | Media | Nulla |
| 4.3 | Morning Brief | MEDIA | Bassa | Nulla |
| 4.4 | Composite wellness index | MEDIA | Media | Nulla |

### FASE 5 — Infrastruttura (3-5 giorni)

| # | Task | Priorità | Complessità | Dipende da |
|---|------|----------|-------------|------------|
| 5.1 | Database retention policy | ALTA | Bassa | Nulla |
| 5.2 | Backup automatizzato | ALTA | Bassa | Nulla |
| 5.3 | Secrets management | ALTA | Bassa | Nulla |
| 5.4 | Monitoring basics | MEDIA | Bassa | Nulla |

**Totale stimato: 35-45 giorni**

---

## 15. RISPOSTE FINALI

### A. Cosa abbiamo già fatto bene?

L'architettura a 3 modelli con fusion è **innovativa e ben implementata**. Il debounce
anti-alarm-fatigue è **clinicamente sensato**. La coda offline MQTT garantisce
**resilienza reale**. L'integrazione Google Health con OAuth refresh è **solida**.
La documentazione è **eccellente** (la parte meglio documentata del progetto).
Il backend FastAPI con 16 tabelle, auth JWT, WebSocket e audit logging è
**completo e professionale**. L'app Android con Foreground Service BLE è
**funzionale e ben strutturata**.

### B. Cosa è attualmente incompleto o debole?

Il **testing** è quasi assente (3 test nell'edge node). La **dashboard** è un monolite
di 5467 righe. Il **modello ML** non ha metriche di validazione. Il **forecasting**
non è implementato. Il **database** non ha retention policy. Il **monitoring**
dell'infrastruttura è inesistente. I **secrets** sono hardcoded in alcune
configurazioni. **I sensori MAX30102, MPU6050 e GSR non esistono nel codice.**

### C. Quali sono i problemi più importanti da risolvere?

1. **Nessuna validazione ML** — non puoi dire "il modello funziona" senza metriche
2. **Dashboard monolitica** — impossibile manutenere o testare
3. **Nessuna feature importance** — il modello è una black box
4. **Nessun confidence score** — le predizioni non hanno misura di affidabilità
5. **Testing inesistente** — il sistema non è verificabile

### D. Quali nuove funzionalità possiamo aggiungere con l'hardware e i dati che abbiamo già?

**27 funzionalità** identificate che utilizzano esclusivamente dati già disponibili:
- 6 Data Features (wellness index, circadiano, ADL, sonno, mobilità, attività)
- 7 AI/ML Features (importance, confidence, explanation, retraining, forecasting, prediction vs actual, clustering)
- 4 Analytics Features (correlazione, confronto settimanale, distribuzione oraria, giorni anomali)
- 4 Alert Features (adattivi, degradazione, assenza, compositi)
- 3 Reporting Features (settimanale, morning brief, conversazione clinica)
- 3 Dashboard Features (giornata tipo, trend overlay, multi-patient)

### E. Quali sono le 3-5 feature che aggiungerebbero più valore al progetto?

1. **Confidence Score** (1 giorno) — il medico sa quanto fidarsi del risultato
2. **Anomaly Explanation** (2 giorni) — da JSON tecnico a frase clinica
3. **Alert Assenza Insolita** (1 giorno) — rileva emergenze che il modello non cattura
4. **Giornata Tipo vs Oggi** (2 giorni) — il confronto più importante in geriatria
5. **Retraining Automatico** (3 giorni) — il sistema si auto-migliora

### F. Quali funzionalità sfrutterebbero meglio la combinazione dei sensori già presenti?

Il sistema sfrutta già in modo intelligente la combinazione:
- **Google Health + BLE**: fisiologia + posizione = "cosa fa il paziente e come sta"
- **BLE + Shelly**: posizione + energia = "quali attività domestiche svolge"
- **Google Health + BLE + Shelly**: i 3 modelli AI catturano prospettive diverse

Le funzionalità che sfruttano MEGGIO questa combinazione:
1. **Composite Wellness Index** — combina HR + HRV + SpO2 + activity + sleep + mobility
2. **Indice ADL** — combina BLE (dove) + Shelly (cosa) + wearable (come)
3. **Alert Compositi** — combina segnali da tutte le fonti per decisioni più affidabili
4. **Profilo Circadiano** — mostra il ritmo 24h combinando tutti i dati
5. **Anomaly Explanation** — interpreta la combinazione di feature anomale

### G. Se dovessi portare il progetto alla versione finale, cosa cambierei, migliorei e lasceresti invariato?

**Lascerei invariato:**
- L'architettura a 3 modelli con fusion (è innovativa e funziona)
- Il debounce anti-alarm-fatigue (è clinicamente sensato)
- La coda offline MQTT (garantisce resilienza)
- La documentazione (è eccellente)
- Il backend FastAPI (è completo)
- L'app Android (è funzionale)

**Migliorerei:**
- Aggiungere validation set e metriche a ogni modello
- Aggiungere confidence score a ogni predizione
- Aggiungere feature importance al decision JSON
- Refactorare App.jsx in 10+ componenti
- Aggiungere test per tutti i moduli critici

**Aggiungerei:**
- Alert assenza prolungata (1 giorno, impatto enorme)
- Alert degradazione progressiva (1 giorno)
- Giornata tipo vs oggi (2 giorni)
- Report settimanale automatico (2 giorni)
- Retraining automatico con drift (3 giorni)
- Morning Brief (1 giorno)

**Rimuoverei:**
- `fall_events` dal modello (sempre 0, inutile)
- CSS duplicato (fondere styles.css e modern.css)
- La riga duplicata `include_router` in `main.py`
- L'idea stessa di usare MAX30102/MPU6050/GSR (il sistema attuale è più robusto)
