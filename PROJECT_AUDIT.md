# PROJECT AUDIT - Sistema IoT per Monitoraggio ADL

> Analisi completa del progetto realizzata come se entrassi come nuovo sviluppatore.
> Tutte le raccomandazioni sono ordinate per priorità.

---

## Indice

- [1. Architettura](#1-architettura)
- [2. Analisi del Codice](#2-analisi-del-codice)
- [3. Hardware e Sensori](#3-hardware-e-sensori)
- [4. Database e Dati](#4-database-e-dati)
- [5. Machine Learning / AI](#5-machine-learning--ai)
- [6. Dashboard e Interfaccia](#6-dashboard-e-interfaccia)
- [7. Funzionalità Già Implementate](#7-funzionalità-già-implementate)
- [8. Cosa Manca per l'Esame](#8-cosa-manca-per-lesame)
- [9. Lista Feature da Aggiungere](#9-lista-feature-da-aggiungere)
- [10. Valutazione Finale](#10-valutazione-finale)
- [11. Roadmap](#11-roadmap)

---

## 1. Architettura

### 1.1 Struttura Generale

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLOUD (VPS/Server)                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐ │
│  │ Mosquitto│  │PostgreSQL│  │ FastAPI  │  │ React Dashboard      │ │
│  │  MQTT    │◄─┤ Database │◄─┤ Backend  │◄─┤ (static files)       │ │
│  │ :8883    │  │ :5432    │  │ :8000    │  │ servita da nginx     │ │
│  └────▲─────┘  └──────────┘  └────▲─────┘  └──────────────────────┘ │
│       │                           │                                  │
└───────┼───────────────────────────┼──────────────────────────────────┘
        │                           │
        │ MQTT/TLS                  │ WebSocket/REST
        │                           │
┌───────┴───────────────────────────┴──────────────────────────────────┐
│                      EDGE NODE (Raspberry Pi)                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐ │
│  │ edge_stack│  │edge_ingest│  │ edge_ai  │  │ edge_mqtt           │ │
│  │ Runtime   │──┤Aggregator │──┤ Fusione  │──┤ Publisher           │ │
│  │ 4min ciclo│  │BLE/GH/Shel│ │3 modelli │  │ + coda offline      │ │
│  └────▲─────┘  └────▲─────┘  └──────────┘  └──────────────────────┘ │
│       │              │                                               │
│  ┌────┴────┐   ┌─────┴──────┐   ┌──────────┐                        │
│  │edge_    │   │Shelly 3EM │   │ BLE      │                        │
│  │receiver │◄──┤ NILM      │   │ Beacons  │                        │
│  │ FastAPI │   │ (elettr.) │   │ Indoor   │                        │
│  └────▲────┘   └────────────┘   └──────────┘                        │
└───────┼──────────────────────────────────────────────────────────────┘
        │ HTTP POST
┌───────┴──────────────────────────────────────────────────────────────┐
│                     COMPANION APP (Mobile)                           │
│  ┌──────────────────────┐    ┌──────────────────────┐               │
│  │ Android (Java)       │    │ iOS (Swift/SwiftUI)  │               │
│  │ BLE scanning service │    │ BLE monitor          │               │
│  │ Firebase push        │    │ Beacon mapping       │               │
│  └──────────────────────┘    └──────────────────────┘               │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 Flusso dei Dati

```
Pixel Watch 2 → Google Health API → edge_ingest (heart_rate, HRV, SpO2, sleep)
Beacons BLE   → Android App      → edge_receiver → BLE CSV → aggregator
Shelly 3EM    → HTTP/MQTT locale → edge_ingest → NILM features
                                    ↓
                         Feature Window (4 min)
                                    ↓
                    ┌───────────────┼───────────────┐
                    ↓               ↓               ↓
            Generic Spatial  Generic Wearable  Personal Model
            (IsolationForest) (IsolationForest) (IsolationForest)
                    └───────────────┼───────────────┘
                                    ↓
                            Fusion + Debounce
                                    ↓
                            TriageDecision
                                    ↓
                            MQTT → Cloud → PostgreSQL
                                    ↓
                            Dashboard (React) + App (push)
```

### 1.3 Valutazione Architettura

L'architettura è **ben strutturata e modulare**. I componenti sono chiaramente separati:
- **Edge**: raccolta dati, inferenza locale, coda offline
- **Cloud**: storage, API, WebSocket, notifiche
- **Mobile**: scanning BLE, notifiche push

**Punti di forza:**
- Separazione netta Edge/Cloud
- Il Raspberry funziona anche offline grazie alla coda MQTT
- Il backend è unico ma modulare (non microservizi eccessivi)

**Punti deboli:**
- Manca un orchestratore (docker-compose non gestisce restart intelligenti)
- Nessun meccanismo di discovery tra componenti

---

## 2. Analisi del Codice

### 2.1 Modulo AI (edge_ai/)

**model.py - IsolationForest**

- L'addestramento usa `contamination=0.1` hardcoded. Dovrebbe essere configurabile in base al profilo del paziente
- Non esiste un validation split: il modello viene addestrato e valutato sugli stessi dati
- La conversione dello score IsolationForest in un range 0-100 è ben fatta usando ancore calcolate dalla baseline

**fusion.py - Fusione a 3 modelli**

- I pesi (15% spatial, 15% wearable, 70% personal) sono buoni
- Il `single_model_penalty` di 10 punti è conservativo e giusto
- L'`agreement_bonus` di 5 punti quando tutti i modelli concordano è una buona idea

**debounce.py - Anti-alarm-fatigue**

- **Ottima implementazione**: finestra di 48 ore, 3+ record arancioni per confermare
- Evita falsi allarmi che causano "alarm fatigue" nel personale sanitario
- La distinzione tra alert clinici e tecnici è fondamentale

**Problemi critici nel codice AI:**
1. Nessun test di validazione del modello (train e test sugli stessi dati)
2. Nessuna metrica di performance (precision, recall, F1)
3. Nessuna explanation method (feature importance, SHAP, ecc.)

### 2.2 Modulo Ingest (edge_ingest/)

**aggregator.py - Costruzione finestre**

- Le 22 feature sono inizializzate a `nan` se la sorgente non è disponibile
- La sincronizzazione temporale tra sorgenti diverse non è garantita
- L'adapter Google Health ha un lookback configurabile (default 5 minuti)

**google_health_adapter.py - Integrazione Google Health**

- OAuth con refresh token automatico è ben implementato
- La gestione degli errori è robusta (tolerante alle API failures)

**ble_adapter.py - BLE Indoor Positioning**

- L'aggregazione campioni BLE in feature temporali è corretta
- La scelta del beacon con RSSI più forte è lo standard

**shelly_adapter.py - NILM**

- L'approccio euristico (soglie per identificare appliance) è accettabile per un prototipo
- Potrebbe essere migliorato con ML dedicato NILM in futuro

### 2.3 Backend Cloud (cloud/backend/)

**mqtt/client.py - Subscriber MQTT**

- Riconnessione automatica al broker
- Gestione errori per messaggi non validi
- Logging strutturato

**mqtt/ingest.py - Ingestione dati**

- La deduplicazione tramite `unique constraint` su `message_id` è solida
- La creazione automatica di alert da decisioni AI arancioni/rosse è implementata
- L'anti-spam per alert (stessa finestra temporale) è presente

**api/routes/ - REST API**

- Completa: auth, patients, windows, decisions, alerts, tasks, notifications
- L'autenticazione JWT con refresh token è implementata
- Il rate limiting per login falliti è presente

**Problemi nel backend:**
1. La coda eventi è in-memory (`InMemoryEventBus`) - si perde con restart
2. Nessun rate limiting globale sulle API
3. Nessun backup automatico configurato

### 2.4 MQTT e Coda Offline (edge_mqtt/)

**queue.py - DiskMqttQueue**

- **Ottima idea**: persistenza su disco quando il broker non è raggiungibile
- I messaggi vengono inviati in ordine FIFO al prossimo ciclo
- Nessun limite massimo alla coda (potrebbe riempire il disco)

**publisher.py - EdgeMqttPublisher**

- La gestione TLS è corretta
- Il Last Will Message è implementato
- L'ACL previene che un Edge pubblichi su topic di altri pazienti

### 2.5 Dashboard React (Dashboard/)

**App.jsx - Componente monolitico**

- **Problema serio**: 5467 righe in un solo file
- Contiene 20+ componenti React, 80+ funzioni helper
- Impossibile da testare, difficile da manutenere

**api/client.js - Client API**

- Gestisce sessione e refresh token
- Retry automatico per errori di rete
- Manca: request timeout, deduplication, cache

**Problemi nella dashboard:**
1. Nessun error boundary - un crash blocca tutta l'app
2. Nessun test automatizzato
3. Nessuna gestione dell'offline mode
4. Nessuna notificazione browser per alert critici

### 2.6 App Mobile (Applicazione IoT Companion/)

**Android (Java)**
- Foreground Service per BLE scanning in background
- Firebase Cloud Messaging per push notification
- SecureTokenStore con Android Keystore
- **Completa e funzionale**

**iOS (Swift/SwiftUI)**
- BLE monitoring con CoreBluetooth
- Beacon mapping
- **Codice presente ma manca build config**

---

## 3. Hardware e Sensori

### 3.1 Sensori Integrati

| Sensore | Stato | Frequenza | Feature Estratte |
|---------|-------|-----------|------------------|
| Pixel Watch 2 | ✅ Integrato | ~4 min (Google Health API) | Heart rate, HRV, SpO2, sleep, steps |
| BLE Beacons (3x BlueUp) | ✅ Integrato | Real-time | Indoor positioning: kitchen, bedroom, bathroom |
| Shelly 3EM | ✅ Integrato | ~4 min | Consumo totale, eventi cucina/TV/caffè |

### 3.2 Problemi Rilevati

1. **Frequenze asimmetriche**: BLE è real-time, Google Health ha delay 5-30 min, Shelly è istantaneo. La finestra 4 minuti potrebbe avere dati parziali.

2. **Gestione sensori offline**: `wearable_present = ""` non distingue tra:
   - Smartwatch scarico
   - Smartwatch non indossato
   - Smartwatch fuori portata Bluetooth
   - Dati Google Health non ancora sincronizzati

3. **Calibrazione BLE**: La distanza è calcolata da RSSI ma non c'è calibrazione per-ambiente (muri, mobili, interferenze).

4. **NILM euristico**: Shelly misura consumo totale, gli "events" sono identificati con soglie. Potrebbero esserci falsi positivi/negativi.

5. **Feature `fall_events`**: Sempre a 0 nel codice attuale - non c'è integrazione con sensori caduta reali.

---

## 4. Database e Dati

### 4.1 Schema Identificato

```
users, patients, doctors, caregivers, patient_caregivers
feature_windows, edge_cycles, sensor_statuses, edge_devices
decisions, ai_explanations
alerts, alert_events
tasks, questionnaire_templates, questionnaire_schedules, questionnaire_results
refresh_tokens, audit_logs
```

### 4.2 Valutazione

- Lo schema è ben normalizzato
- L'uso di `UniqueConstraint` previene duplicati
- Gli indici sono presenti sulle colonne più queryate

### 4.3 Problemi

1. **Crescita indefinita**: `feature_windows` cresce di ~360 righe/giorno per paziente (4 min × 24 ore × 60/4). Dopo 1 anno: ~130K righe per paziente. Nessuna retention policy.

2. **Nessun archivio**: I dati vecchi non vengono compressi o archiviati.

3. **Event bus in-memory**: `InMemoryEventBus` si perde con il restart del backend.

---

## 5. Machine Learning / AI

### 5.1 Modelli Implementati

| Modello | Scope | Algoritmo | Feature |
|---------|-------|-----------|---------|
| Generic Spatial | Domestico/ambientale | IsolationForest | room_changes, bedroom_minutes, nilm_* |
| Generic Wearable | Fisiologico | IsolationForest | heart_rate, hrv_rmssd, spo2, sleep |
| Personal | Paziente-specifico | IsolationForest | Tutte le 22 feature |

### 5.2 Punti di Forza

1. Approccio a 3 modelli con fusion è **innovativo e ben documentato**
2. Il debounce previene alarm fatigue
3. La baseline personale viene addestrata progressivamente su dati reali
4. La calibrazione del generico wearable (normalizzazione HRV, soglie SpO2) è clinicamente sensata

### 5.3 Problemi Critici

1. **Nessun validation set**: Il modello personale viene addestrato su tutti i dati senza holdout. Impossibile valutare overfitting.

2. **Contamination fisso**: `contamination=0.1` assume 10% anomalie nei dati. Per un paziente in salute, potrebbe essere 1-5%.

3. **Nessun concept drift detection**: Il modello non viene rivalutato periodicamente. Se il paziente cambia abitudini legittimamente, il modello segnalerà anomalie false.

4. **Nessuna feature importance**: Non c'è modo di capire quali feature contribuiscono di più alle anomalie.

5. **Nessun confidence score**: Lo score restituito non ha una misura di confidenza.

6. **Nessuna valutazione quantitativa**: Manca un report con precision, recall, F1, AUC-ROC sul validation set.

### 5.4 Feature Utilizzate (22 totali)

```
Wearable: heart_rate_mean, heart_rate_std, resting_heart_rate, hrv_rmssd,
          spo2_mean, sleep_minutes, awake_minutes
Activity: steps, sedentary_minutes
Spatial:  room_changes, night_room_changes, bedroom_minutes, kitchen_minutes,
          bathroom_minutes, living_room_minutes, longest_single_room_minutes
NILM:     nilm_total_wh, nilm_kitchen_events, nilm_tv_minutes,
          nilm_coffee_events, nilm_stove_events, fall_events
```

---

## 6. Dashboard e Interfaccia

### 6.1 Schermate Implementate (8 tab)

1. **Quadro clinico** - AI score gauge, spiegazioni, grafici wearable/spaziali
2. **Timeline** - Eventi cronologici
3. **Valutazioni** - Questionari programmati (PHQ-2, MMSE, MoCA)
4. **Routine ambientale** - Grafici BLE per stanza
5. **Segnalazioni** - Alert con workflow acknowledge/resolve/task
6. **Attività** - Task clinici e messaggi paziente/caregiver
7. **Stato sistema** - RPi, MQTT, sensori, Google Health OAuth
8. **Report** - Export dati per report clinico

### 6.2 Punti di Forza

- Design clinico responsive
- Gerarchia visiva per livelli di rischio (verde/giallo/arancione/rosso/tecnico)
- Dialoghi interni per workflow operativi
- Supporto `prefers-reduced-motion`

### 6.3 Problemi

1. **Monolite**: 5467 righe in `App.jsx`. Refactoring urgente necessario.

2. **Nessun error boundary**: Se un componente fallisce, tutta la dashboard crasha.

3. **Nessun test**: Impossibile refactoring sicuro senza test.

4. **Real-time parziale**: WebSocket solo per paziente selezionato, non per alert globali.

5. **Nessun offline mode**: Se il backend cade, la dashboard mostra loading infinito.

6. **Nessuna notificazione browser**: Per alert critici.

---

## 7. Funzionalità Già Implementate

### Core IoT
- ✅ Data ingestion da 3 sorgenti (Google Health, BLE, Shelly)
- ✅ Aggregazione in finestre temporali 4 minuti
- ✅ Coda offline MQTT con persistenza su disco
- ✅ TLS su MQTT con certificati
- ✅ Deduplicazione messaggi su message_id
- ✅ ACL per paziente (un Edge non pubblica su topic di altri)

### AI/ML
- ✅ 3 modelli IsolationForest con fusione a pesi
- ✅ Debounce anti-alarm-fatigue (finestra 48h)
- ✅ Baseline personale progressiva (7 giorni)
- ✅ Quality checks sui dati prima del training
- ✅ Safety gate per baseline (modelli generici bloccano finestre sospette)
- ✅ Calibrazione clinica per modelli generici wearable

### Backend
- ✅ REST API completa (auth, patients, windows, decisions, alerts, tasks, notifications)
- ✅ WebSocket realtime per aggiornamenti
- ✅ Autenticazione JWT con access/refresh token
- ✅ Ruoli: doctor, caregiver, patient, admin
- ✅ Audit logging per azioni critiche
- ✅ Push notification Firebase (con fake mode per sviluppo)
- ✅ Questionari programmabili con template

### Dashboard
- ✅ 8 viste funzionali
- ✅ Grafici SVG interattivi
- ✅ Workflow alert (acknowledge → resolve → task)
- ✅ Template test clinici (PHQ-2, MMSE, MoCA)
- ✅ Messaggi paziente/caregiver con suggerimenti
- ✅ Report esportabile

### Mobile
- ✅ Android app completa con BLE foreground service
- ✅ Firebase Cloud Messaging
- ✅ iOS app (codice Swift completo, manca build config)

---

## 8. Cosa Manca per l'Esame

### 8.1 Critico (deve essere fatto)

| # | Cosa | Perché è importante | Difficoltà | Tempo stimato |
|---|------|---------------------|------------|---------------|
| 1 | **Test automatizzati** | Solo 3 test nel progetto. Impossibile dimostrare affidabilità senza test | Media | 3-4 giorni |
| 2 | **Dashboard refactoring** | 5467 righe in un file è inaccettabile per un esame. Dimostra cattiva pratica | Alta | 5-7 giorni |
| 3 | **Validation set per ML** | Non puoi dire "il modello funziona" senza metriche su dati non visti | Bassa | 1-2 giorni |
| 4 | **Documentazione tecnica** | Serve un documento che spieghi l'architettura al relatore | Bassa | 1 giorno |
| 5 | **Demo funzionante** | Devi poter mostrare il sistema funzionante dall'avvio al risultato | Media | 2-3 giorni |

### 8.2 Importante (migliora significativamente il voto)

| # | Cosa | Perché è importante | Difficoltà | Tempo stimato |
|---|------|---------------------|------------|---------------|
| 6 | **Monitoring basics** | Health check, metriche, log strutturati | Bassa | 1-2 giorni |
| 7 | **Backup automatizzato** | Script già esiste, va solo automatizzato | Bassa | 0.5 giorno |
| 8 | **Feature importance / Explainability** | Dimostra che il modello non è una "black box" | Media | 2-3 giorni |
| 9 | **Concept drift detection** | Mostra che il sistema si adatta nel tempo | Media | 2-3 giorni |
| 10 | **Confidence score** | Le predizioni hanno una misura di affidabilità | Bassa | 1 giorno |
| 11 | **Database retention** | Policy per dati vecchi (archiviazione/compressione) | Bassa | 1 giorno |

### 8.3 Utile (fa la differenza)

| # | Cosa | Perché è importante | Difficoltà | Tempo stimato |
|---|------|---------------------|------------|---------------|
| 12 | **Error boundaries React** | La dashboard non crasha più | Bassa | 0.5 giorno |
| 13 | **Browser notifications** | Alert critici nel browser | Bassa | 1 giorno |
| 14 | **Offline mode** | Dashboard funziona anche senza backend | Media | 2 giorni |
| 15 | **Dark mode** | UX migliore | Bassa | 1 giorno |
| 16 | **iOS build config** | L'app iOS funziona realmente | Media | 1-2 giorni |
| 17 | **Performance benchmarks** | Quanto tempo impiega un ciclo? Quanta RAM? | Bassa | 1 giorno |

---

## 9. Lista Feature da Aggiungere

### PRIORITÀ ALTA - Assolutamente Necessarie per l'Esame

#### 9.1 Test Automatizzati
**Cosa**: Aggiungere test per tutti i moduli principali
**Perché**: Un progetto senza test non è credibile
**Cosa testare**:
- `edge_ai`: training, inferenza, fusion, debounce
- `edge_ingest`: aggregazione finestre, quality checks
- `cloud/backend`: API REST, MQTT ingest, auth
- `edge_mqtt`: costruzione messaggi, coda offline
**Difficoltà**: Media
**Tempo**: 3-4 giorni
**Dipende da**: Nulla

#### 9.2 Validation Set per Modello AI
**Cosa**: Splittare i dati in train/validation prima dell'addestramento
**Perché**: Dimostrare che il modello generalizza
**Come**:
- 80% train, 20% validation
- Calcolare precision, recall, F1, AUC-ROC
- Salvare le metriche nel report del modello
**Difficoltà**: Bassa
**Tempo**: 1-2 giorni
**Dipende da**: Nulla

#### 9.3 Dashboard Refactoring
**Cosa**: Spezzare `App.jsx` (5467 righe) in componenti separati
**Perché**: Un monolite dimostra cattiva pratica di sviluppo
**Struttura proposta**:
```
src/
  components/
    Login/
    Dashboard/
    PatientView/
    AiExplanationPanel/
    AlertsView/
    TasksView/
    TimelineView/
    SystemView/
    RoutineView/
    ReportView/
    EvaluationsView/
  hooks/
    usePatientData.js
    useWebSocket.js
  api/
    client.js
    errors.js
    realtime.js
  utils/
    format.js
  App.jsx (circa 100 righe)
```
**Difficoltà**: Alta
**Tempo**: 5-7 giorni
**Dipende da**: Nulla

#### 9.4 Documentazione Architettura
**Cosa**: Documento che spieghi l'architettura al relatore
**Contenuto**:
- Diagramma architetturale completo
- Flusso dei dati
- Scelte progettuali e motivazioni
- Tecnologie usate e perché
- Risultati ottenuti
**Difficoltà**: Bassa
**Tempo**: 1 giorno
**Dipende da**: Nulla

#### 9.5 Demo Funzionante
**Cosa**: Script che avvii tutto il sistema in locale
**Cosa mostrare**:
1. Avvio backend + broker + database
2. Inserimento dati simulati
3. Esecuzione inferenza AI
4. Dashboard che mostra risultati
5. Alert generato automaticamente
**Difficoltà**: Media
**Tempo**: 2-3 giorni
**Dipende da**: Test (punto 9.1)

---

### PRIORITÀ MEDIA - Migliorano Significativamente il Progetto

#### 9.6 Feature Importance / Explainability
**Cosa**: Mostrare quali feature contribuiscono alle anomalie
**Perché**: Il modello non deve essere una "black box"
**Come**:
- Calcolare importanza feature dopo training
- Salvare top-3 feature nel decision JSON
- Mostrare nella dashboard
**Difficoltà**: Media
**Tempo**: 2-3 giorni
**Dipende da**: Validation set (punto 9.2)

#### 9.7 Concept Drift Detection
**Cosa**: Rilevare quando il modello personale non è più accurato
**Perché**: Le abitudini del paziente cambiano nel tempo
**Come**:
- Confrontare score di finestre recenti con baseline
- Se la media degli score supera una soglia, segnalare drift
- Opzionale: retraining automatico
**Difficoltà**: Media
**Tempo**: 2-3 giorni
**Dipende da**: Validation set (punto 9.2)

#### 9.8 Confidence Score
**Cosa**: Aggiungere una misura di confidenza a ogni predizione
**Perché**: Il medico deve sapere quanto affidabile è il risultato
**Come**:
- Calcolare quante feature sono presenti (vs mancanti)
- Se > 50% feature mancanti → confidenza bassa
- Se il modello è stato addestrato con pochi dati → confidenza bassa
- Includere nel decision JSON
**Difficoltà**: Bassa
**Tempo**: 1 giorno
**Dipende da**: Nulla

#### 9.9 Monitoring Basics
**Cosa**: Endpoint `/health`, `/metrics`, log strutturati
**Perché**: Un sistema production deve essere monitorabile
**Cosa aggiungere**:
- `/health/live` e `/health/ready` (già presenti, da verificare)
- Metriche Prometheus per cicli edge, alert, connessioni WebSocket
- Log JSON strutturati (già parzialmente implementati)
**Difficoltà**: Bassa
**Tempo**: 1-2 giorni
**Dipende da**: Nulla

#### 9.10 Backup Automatico
**Cosa**: Automatizzare il backup PostgreSQL
**Perché**: I dati del paziente sono critici
**Come**:
- Cron job che esegue `backupPostgres.ps1` ogni 6 ore
- Retention 7 giorni
- Test di restore periodico
**Difficoltà**: Bassa
**Tempo**: 0.5 giorno
**Dipende da**: Nulla

#### 9.11 Database Retention
**Cosa**: Policy per gestire dati vecchi
**Perché**: Il database cresce di ~130K righe/anno per paziente
**Come**:
- Archiviare finestre > 90 giorni in tabella separata
- Opzionale: comprimere dati grezzi > 30 giorni
**Difficoltà**: Bassa
**Tempo**: 1 giorno
**Dipende da**: Nulla

---

### PRIORITÀ BASSA - Fanno la Differenza

#### 9.12 Error Boundary React
**Cosa**: Componente che cattura errori nei figli
**Perché**: La dashboard non crasha più per un errore in un componente
**Difficoltà**: Bassa
**Tempo**: 0.5 giorno
**Dipende da**: Dashboard refactoring (punto 9.3)

#### 9.13 Browser Notifications
**Cosa**: Notifiche push nel browser per alert critici
**Perché**: Il medico viene avvisato anche se non sta guardando la dashboard
**Difficoltà**: Bassa
**Tempo**: 1 giorno
**Dipende da**: Nulla

#### 9.14 Offline Mode
**Cosa**: Dashboard funziona anche senza backend
**Perché**: In una rete ospedaliera instabile, i dati devono restare visibili
**Come**:
- Cache locale degli ultimi dati caricati
- Service worker per le API
**Difficoltà**: Media
**Tempo**: 2 giorni
**Dipende da**: Dashboard refactoring (punto 9.3)

#### 9.15 Dark Mode
**Cissa**: Tema scuro per la dashboard
**Perché**: UX migliore, specialmente in ambienti clinici notturni
**Difficoltà**: Bassa
**Tempo**: 1 giorno
**Dipende da**: Dashboard refactoring (punto 9.3)

#### 9.16 iOS Build Config
**Cosa**: Configurare il progetto Xcode per l'app iOS
**Perché**: L'app iOS è completa nel codice ma non è buildabile
**Difficoltà**: Media
**Tempo**: 1-2 giorni
**Dipende da**: Nulla

#### 9.17 Performance Benchmarks
**Cosa**: Misurare e documentare le performance del sistema
**Metriche**:
- Tempo medio di un ciclo edge
- RAM utilizzata dal Raspberry
- Latenza MQTT Edge → Dashboard
- Throughput massimo di messaggi MQTT
**Difficoltà**: Bassa
**Tempo**: 1 giorno
**Dipende da**: Nulla

---

## 10. Valutazione Finale

### 10.1 Punteggi per Area

| Aspetto | Score | Note |
|---------|-------|------|
| Architettura | 8/10 | Ben strutturata, modulare, scalabile |
| Codice Python | 7/10 | Funzionale, ben commentato, ma mancano test |
| Codice React | 5/10 | Funzionale ma monolitico |
| Hardware integration | 7/10 | 3 sorgenti integrate, BLE ben gestito |
| Database | 6/10 | Schema buono, niente retention |
| Backend API | 8/10 | Completa, auth, WebSocket, alert workflow |
| ML/AI | 7/10 | Approccio innovativo, mancano validation e drift |
| Dashboard | 6/10 | Funzionale e completa, ma monolitica |
| Sicurezza | 5/10 | TLS OK, auth OK, ma secrets hardcoded |
| Testing | 2/10 | **Critico** - solo 3 test |
| Documentazione | 9/10 | Eccellente, dettagliata, ben organizzata |
| Mobile | 7/10 | Android completa, iOS parziale |

**Score complessivo: 6.5/10** - Ottima base, ma servono test e refactoring per essere credibili.

### 10.2 Punti di Forza (per l'esame)

1. **Architettura a 3 modelli** con fusion - innovativa e ben documentata
2. **Debounce anti-alarm-fatigue** - dimostra comprensione del dominio clinico
3. **Coda offline MQTT** - resilienza reale, non solo teorica
4. **Integrazione hardware completa** - Google Health, BLE beacons, Shelly
5. **Documentazione eccellente** - il relatore può seguire tutto
6. **App Android completa** - con foreground service per BLE
7. **Dashboard con 8 viste** - workflow clinico completo

### 10.3 Punti Deboli (da migliorare prima dell'esame)

1. **Testing quasi inesistente** - solo 3 test nel progetto
2. **Dashboard monolitica** - 5467 righe in un file
3. **Nessuna metrica ML** - non puoi dire "il modello funziona" senza dati
4. **Secrets hardcoded** - le credenziali non dovrebbero essere nel codice
5. **Nessun monitoring** - non c'è osservabilità del sistema

---

## 11. Roadmap

### FASE 1: Fondamenta (1 settimana)

```
Giorno 1-2: Validation set per modelli AI
  - Splittare dati in train/validation
  - Calcolare metriche (precision, recall, F1, AUC-ROC)
  - Salvare report nel modello

Giorno 3-4: Test automatizzati (minimo)
  - edge_ai: test training, inferenza, fusion
  - edge_ingest: test aggregazione, quality checks
  - cloud/backend: test API principali, MQTT ingest

Giorno 5: Backup automatizzato
  - Automatizzare backupPostgres
  - Test restore
```

### FASE 2: Credibilità (1 settimana)

```
Giorno 1-3: Dashboard refactoring
  - Spezzare App.jsx in 10+ componenti
  - Aggiungere error boundaries
  - Aggiungere test componenti

Giorno 4-5: Feature importance
  - Calcolare importanza feature
  - Salvare nel decision JSON
  - Mostrare nella dashboard

Giorno 6-7: Confidence score
  - Calcolare affidabilità predizione
  - Includere nel JSON
  - Mostrare nella dashboard
```

### FASE 3: Raffinamento (1 settimana)

```
Giorno 1-2: Monitoring
  - Verificare health check
  - Metriche Prometheus
  - Log strutturati

Giorno 3: Database retention
  - Policy archiviazione dati vecchi

Giorno 4-5: Concept drift detection
  - Monitorare degradazione modello

Giorno 6-7: Documentazione
  - Documento architettura per relatore
  - Demo script avvio completo
```

### FASE 4: Extra (se c'è tempo)

```
Browser notifications
Offline mode
Dark mode
iOS build
Performance benchmarks
```

---

## 12. Riepilogo per l'Esame

### Cosa mostrare al relatore

1. **Architettura**: il diagramma dell'architettura completa
2. **Flusso dati**: come i dati passano dai sensori alla dashboard
3. **AI**: i 3 modelli, la fusion, il debounce, le metriche
4. **Demo**: avvio completo, raccolta dati, inferenza, dashboard
5. **Resilienza**: coda offline, riconnessione, gestione errori
6. **Mobile**: app Android con BLE service in background
7. **Test**: dimostrare che il sistema è testato

### Cosa dire sulla qualità del codice

- "Il sistema è testato con X test che coprono Y%"
- "Il modello ha una precision del Z% su dati di validazione"
- "La dashboard è stata refactored in N componenti"
- "Il sistema gestisce errori e fallback in modo robusto"

### Domande probabili del relatore

1. "Come gestite i dati mancanti?" → Imputer + nan handling + confidence score
2. "Come evitate falsi allarmi?" → Debounce + soglie cliniche + dual threshold
3. "Cosa succede se cade la rete?" → Coda offline MQTT su disco
4. "Come si adatta il modello al paziente?" → Baseline 7 giorni + retraining
5. "Perché IsolationForest?" → Unsupervised, non serve labels, adatto a dati normali
