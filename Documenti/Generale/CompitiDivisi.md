# Compiti divisi tra Emilio e Daniel

Questo documento trasforma l'architettura descritta in
`DASHBOARD_ARCHITECTURE.md` in un piano di lavoro concreto. La divisione e'
pensata per permettere a Emilio e Daniel di procedere in parallelo, usando contratti e
dati di prova condivisi fino al momento dell'integrazione.

## Indice

1. Obiettivo della prima versione
2. Divisione generale delle responsabilita'
3. Contratti da fissare prima dello sviluppo
4. Compiti di Emilio
5. Compiti di Daniel
6. Attivita' condivise di integrazione
7. Ordine di lavoro parallelo
8. Criteri di completamento
9. Attivita' successive alla prima versione

## Come usare questa checklist

Questo file viene usato come piano operativo. Ogni punto resta con `[ ]` finche' non
esiste un risultato verificabile. Quando il punto e' completato, si cambia in `[x]`.

Regola pratica:

```text
[ ] = da fare
[x] = completato e verificato
```

Non segnare un punto come completato solo perche' e' stato iniziato. Prima devono esserci
file, codice, configurazione, test o documentazione che dimostrano il completamento.

Quando un punto di Daniel dipende da un output di Emilio, Daniel puo' preparare struttura,
mock e contratti, ma il punto resta aperto finche' l'integrazione con l'output reale non
e' verificata.

Esempio:

```text
Emilio prepara payload reali Edge
Daniel prepara schema/API/backend usando mock
Punto completato solo quando payload reale e schema backend combaciano
```

Ordine consigliato per Daniel:

```text
1. Contratti condivisi
2. Backend FastAPI base
3. Database PostgreSQL
4. Broker MQTT
5. Subscriber MQTT
6. API REST
7. WebSocket
8. Auth/ruoli
9. Alert
10. Task/test paziente
11. Push notification
12. Deployment
```

## 1. Obiettivo della prima versione

La prima versione completa deve realizzare questo flusso:

```text
Beacon + Google Health
-> Raspberry Pi 5
-> finestra aggregata ogni 4 minuti
-> inferenza AI e decisione locale
-> pubblicazione MQTT protetta da TLS
-> backend Cloud
-> database
-> dashboard medico via REST e WebSocket
-> notifiche e task verso app paziente/caregiver
```

La versione e' completa quando consente di:

- mantenere operativo l'Edge Node anche senza connessione Internet;
- pubblicare sul Cloud cicli, finestre, decisioni, alert e stato dei sensori;
- salvare lo storico senza duplicare i messaggi;
- mostrare al medico dati correnti, storico, spiegazione AI e stato tecnico;
- inviare un task o test al paziente;
- ricevere il risultato del task nell'applicazione medico;
- notificare al caregiver un allarme importante;
- registrare chi ha preso in carico e risolto un allarme;
- separare chiaramente problemi tecnici e segnali comportamentali.

## 2. Divisione generale delle responsabilita'

| Area | Responsabile principale | Risultato atteso |
|---|---|---|
| Edge Node e publisher MQTT | Emilio | Il Raspberry pubblica dati affidabili e continua a funzionare offline |
| Dashboard medico web | Emilio | Interfaccia clinica completa, collegata a REST e WebSocket |
| App Android paziente | Emilio | BLE, stato monitoraggio, notifiche, task e invio risultati |
| Interfaccia caregiver | Emilio | Stato sintetico, notifiche e presa in carico |
| Broker MQTT e sicurezza topic | Daniel | Broker TLS con utenti e ACL separate |
| Backend Cloud FastAPI | Daniel | API, WebSocket, subscriber MQTT e logica applicativa |
| Database PostgreSQL | Daniel | Persistenza di pazienti, finestre, decisioni, alert e task |
| Autenticazione e ruoli | Daniel | Accesso separato per medico, paziente, caregiver ed Edge Node |
| Notifiche push | Daniel | Invio FCM per task, problemi tecnici e alert importanti |
| Deployment Cloud | Daniel | Backend, broker e database avviabili automaticamente |
| Test end-to-end e documentazione finale | Entrambi | Flusso verificato dal Beacon fino alla dashboard |

Le responsabilita' principali indicano chi modifica e approva quella parte. L'altro
componente del gruppo puo' fare review e test, ma evita di cambiare direttamente gli
stessi file durante lo sviluppo ordinario.

## 3. Contratti da fissare prima dello sviluppo

Questa fase richiede poche ore e impedisce che frontend, backend ed Edge usino formati
diversi. Emilio prepara esempi derivati dai file reali; Daniel li trasforma nei contratti
API e MQTT definitivi. Dopo l'approvazione, entrambi possono lavorare con mock locali.

### 3.1 Regole comuni

- [x] Usare sempre `patient_id` come identificatore del paziente.
- [x] Aggiungere un `edge_id` per distinguere i Raspberry installati.
- [x] Usare timestamp ISO 8601 in UTC nei messaggi e convertire l'orario solo nella UI.
- [x] Aggiungere `schema_version` a ogni payload MQTT.
- [x] Aggiungere `message_id` univoco per deduplicare le ritrasmissioni.
- [x] Non inviare token OAuth, password o segreti nei payload.
- [x] Distinguere `event_type` da `level` e da `should_publish`.
- [x] Conservare i valori mancanti come `null`, non come stringhe `"nan"`.
- [x] Stabilire un formato di errore API comune con `code`, `message` e `details`.

### 3.2 Topic MQTT condivisi

```text
iot/patients/{patient_id}/edge/status
iot/patients/{patient_id}/telemetry/window
iot/patients/{patient_id}/telemetry/decision
iot/patients/{patient_id}/alerts/critical
iot/patients/{patient_id}/sensors/watch
iot/patients/{patient_id}/sensors/ble
```

Per la prima versione MQTT e' usato soltanto nel verso Edge -> Cloud. I task destinati
all'app paziente rimangono gestiti dal backend tramite REST, WebSocket e notifiche push.
Eventuali comandi diretti al Raspberry saranno definiti in un contratto separato solo se
serviranno davvero per la gestione tecnica dell'Edge.

### 3.3 API minime condivise

```text
POST   /api/v1/auth/login
GET    /api/v1/patients
GET    /api/v1/patients/{patient_id}/current
GET    /api/v1/patients/{patient_id}/windows
GET    /api/v1/patients/{patient_id}/decisions
GET    /api/v1/patients/{patient_id}/alerts
PATCH  /api/v1/alerts/{alert_id}/acknowledge
PATCH  /api/v1/alerts/{alert_id}/resolve
POST   /api/v1/patients/{patient_id}/tasks
GET    /api/v1/patients/{patient_id}/tasks
POST   /api/v1/tasks/{task_id}/results
PATCH  /api/v1/tasks/{task_id}/cancel
GET    /api/v1/patients/{patient_id}/system-status
WS     /ws/v1/patients/{patient_id}
```

### 3.4 Eventi WebSocket minimi

```text
edge_cycle_completed
patient_window_updated
decision_updated
alert_created
alert_acknowledged
alert_resolved
task_created
task_completed
task_cancelled
pong
system_status_updated
```

### 3.5 File di esempio per lavorare senza dipendenze

- [x] Emilio prepara payload anonimizzati da `last-cycle.json`.
- [x] Emilio prepara payload anonimizzati da `patient-001-decision.json`.
- [x] Emilio prepara una riga JSON equivalente a `latest_window.csv`.
- [x] Emilio prepara esempi green, yellow, orange, red e technical.
- [x] Daniel prepara il file OpenAPI prodotto dal backend.
- [x] Daniel prepara esempi di task, risultato test, alert e acknowledgement.
- [x] I file condivisi vengono salvati in `Documenti/contracts/examples/`.

## 4. Compiti di Emilio

Emilio e' responsabile delle parti vicine ai dati reali gia' funzionanti, delle
interfacce utente e dell'integrazione Edge. Durante lo sviluppo usa un backend mock per
non dipendere dallo stato dei servizi di Daniel.

### E1. Publisher MQTT sul Raspberry Pi 5

- [x] Creare un modulo `edge_mqtt` separato dal runtime e dall'AI.
- [x] Leggere host, porta, client ID, utente, password e certificati da configurazione.
- [x] Pubblicare `last-cycle.json` sul topic `edge/status` a ogni ciclo completato.
- [x] Pubblicare `latest_window.csv` come JSON sul topic `telemetry/window`.
- [x] Pubblicare `patient-001-decision.json` sul topic `telemetry/decision`.
- [x] Pubblicare sul topic `alerts/critical` solo quando la logica stabilita lo richiede.
- [x] Generare `message_id`, `schema_version`, `patient_id`, `edge_id` e timestamp UTC.
- [x] Impostare Quality of Service coerente: QoS 1 per decisioni e alert.
- [x] Pubblicare un Last Will per segnalare una disconnessione improvvisa dell'Edge.
- [x] Mantenere una coda locale su disco quando Internet o broker non sono disponibili.
- [x] Ritrasmettere la coda in ordine senza bloccare il ciclo locale di quattro minuti.
- [x] Evitare che un errore MQTT interrompa receiver, baseline o inferenza AI.
- [x] Nascondere password e certificati dai log e da Git.
- [x] Aggiungere test con broker simulato o Mosquitto locale.
- [x] Integrare il publisher nel comando unico di avvio Windows e Raspberry.
- [x] Documentare configurazione, log e procedura di verifica.

Output: il Raspberry continua a produrre i file locali e, quando la rete e' disponibile,
pubblica gli stessi eventi sul broker in modo affidabile.

### E2. Mock backend per sviluppo frontend

- [x] Creare risposte JSON locali conformi alle API concordate.
- [x] Simulare paziente normale, alert severo, problema tecnico e dati mancanti.
- [x] Simulare eventi WebSocket a intervalli configurabili.
- [x] Consentire alla dashboard di cambiare URL tra mock e backend reale tramite `.env`.
- [x] Non inserire dati personali reali nei mock versionati.

Output: dashboard e app possono essere sviluppate anche quando il backend Cloud e'
spento o non ancora completo.

### E3. Struttura della dashboard medico web

- [x] Creare il progetto frontend React con configurazione separata per sviluppo e produzione.
- [x] Realizzare login e gestione della sessione.
- [x] Realizzare navigazione con lista pazienti, dettaglio paziente, alert, task e sistema.
- [x] Gestire loading, assenza dati, errore rete, dati obsoleti e permessi insufficienti.
- [x] Usare componenti accessibili e responsive per PC e tablet.
- [x] Centralizzare client REST, client WebSocket e gestione degli errori.
- [x] Non mostrare messaggi diagnostici assoluti: indicare sempre che si tratta di triage.

Output: una base navigabile che funziona prima con mock e poi cambiando soltanto l'URL
del backend.

### E4. Overview e lista pazienti

- [x] Mostrare la lista pazienti ordinabile per severita' e ultimo aggiornamento.
- [x] Mostrare semaforo green, yellow, orange, red e technical.
- [x] Mostrare stanza corrente, watch presente e Raspberry online/offline.
- [x] Evidenziare dati vecchi rispetto all'ultima finestra attesa.
- [x] Separare chiaramente anomalia comportamentale e guasto tecnico.
- [x] Aprire il dettaglio del paziente selezionato senza perdere i filtri.

### E5. Pagina alert e presa in carico

- [x] Visualizzare timestamp, livello, score, motivi e stato dell'alert.
- [x] Implementare filtri per livello, intervallo temporale e stato.
- [x] Aggiungere azione `Prendi in carico` con conferma.
- [x] Aggiungere azione `Risolvi` con nota obbligatoria.
- [x] Aggiornare la UI quando arriva un evento WebSocket di acknowledgement.
- [x] Mostrare chi ha preso in carico l'alert e quando.
- [x] Consentire dal dettaglio alert di creare un task per il paziente.

### E6. Dati wearable e spaziali

- [x] Creare grafici per frequenza cardiaca media e deviazione standard.
- [x] Creare grafici per SpO2, passi, sonno e sedentarieta' quando disponibili.
- [x] Mostrare HRV specificando la provenienza e la disponibilita' del dato.
- [x] Creare timeline delle stanze e grafico dei minuti per stanza.
- [x] Mostrare cambi stanza, cambi notturni e permanenza massima.
- [x] Consentire intervalli temporali giornalieri e settimanali.
- [x] Non interpretare automaticamente un valore mancante come zero.
- [x] Indicare visivamente quando una feature e' stata imputata o non acquisita.

### E7. Spiegazione AI

- [x] Mostrare anomaly score finale e livello risultante.
- [x] Mostrare score di modello spaziale, wearable e personale.
- [x] Mostrare i pesi effettivi della fusione, inclusi 15/15/70 dopo la baseline.
- [x] Mostrare le feature principali con valore, direzione e z-score.
- [x] Spiegare che `model_value` e' il valore dopo il preprocessing.
- [x] Mostrare se il modello personale non e' ancora disponibile.
- [x] Mostrare avanzamento baseline, giorni trascorsi e finestre valide su 1000.
- [x] Evitare termini come diagnosi, malattia confermata o emergenza medica automatica.

### E8. Stato tecnico del sistema

- [x] Mostrare ultimo ciclo Edge e durata della finestra.
- [x] Mostrare stato BLE, Google Health, MQTT e qualita' dati.
- [x] Mostrare ultimo contatto del Raspberry e stato online/offline.
- [x] Mostrare batteria e presenza wearable quando disponibili.
- [x] Mostrare errori OAuth senza visualizzare token o segreti.
- [x] Mostrare eventuali messaggi rimasti nella coda MQTT locale.
- [x] Distinguere warning temporanei da guasti persistenti.

### E9. Task e test cognitivi nella dashboard medico

- [x] Creare schermata elenco task con stato created, sent, seen, completed ed expired.
- [x] Creare form per tipo, priorita', scadenza e istruzioni.
- [x] Implementare almeno check-in benessere, PHQ-2 e un test dimostrativo breve.
- [ ] Verificare con il docente quali test possono essere riprodotti e con quali licenze.
- [x] Mostrare risposte, score previsto, durata e data di completamento.
- [x] Consentire al medico di aggiungere una nota al risultato.
- [x] Aggiornare l'elenco in tempo reale quando il paziente completa il task.

### E10. Estensione dell'app Android paziente

- [x] Conservare il Foreground Service BLE e l'avvio automatico del monitoraggio.
- [x] Separare configurazione amministrativa e schermata quotidiana del paziente.
- [x] Mostrare monitoraggio attivo, connessione Raspberry e ultimo aggiornamento.
- [x] Mostrare notifiche e task ricevuti dal backend.
- [x] Registrare seen, started e completed per ogni task.
- [x] Realizzare l'interfaccia dei test concordati.
- [x] Inviare risultati, durata e identificatore dispositivo al backend.
- [x] Salvare localmente risultati non inviati e ritentare quando torna la rete.
- [x] Registrare il token FCM senza inserirlo nei log.
- [x] Inviare periodicamente lo stato dell'app e la batteria del telefono.
- [x] Mantenere protette da credenziali admin le impostazioni tecniche e lo stop del servizio.
- [ ] Testare blocco schermo, risparmio energetico, riavvio telefono e rete assente.

### E11. Interfaccia caregiver

- [ ] Realizzare una prima versione Android con login caregiver.
- [ ] Mostrare stato generale, ultimo aggiornamento e problemi tecnici semplici.
- [ ] Mostrare solo alert autorizzati e realmente pubblicabili.
- [ ] Ricevere notifiche push quando l'app e' chiusa.
- [ ] Consentire la presa in carico di un alert con conferma.
- [ ] Mostrare quando medico o altro caregiver ha gia' preso in carico l'evento.
- [ ] Non mostrare feature AI, dati clinici grezzi o token tecnici.
- [ ] Rimandare la versione iOS a una fase successiva se non e' necessaria alla demo.

### E12. Test frontend, Android e documentazione

- [ ] Testare dashboard su desktop e tablet.
- [ ] Testare WebSocket disconnesso e riconnessione automatica.
- [ ] Testare token scaduto e logout.
- [ ] Testare dati mancanti e timestamp obsoleti.
- [ ] Testare accessibilita' di colori, testi e controlli principali.
- [ ] Creare APK di test firmato.
- [ ] Aggiornare README di Edge, dashboard e app Android.

## 5. Compiti di Daniel

Daniel e' responsabile dell'infrastruttura Cloud e dei servizi condivisi. Durante lo
sviluppo usa payload MQTT di prova e client API automatici, quindi non deve aspettare le
interfacce di Emilio.

### D1. Broker MQTT Cloud

- [x] Scegliere tra Mosquitto su VPS e servizio MQTT gestito.
- [x] Configurare listener MQTT protetto da TLS.
- [x] Configurare eventuale listener MQTT over WebSockets protetto da WSS.
- [x] Creare credenziali separate per Edge Node, backend e client di test.
- [x] Definire ACL per impedire l'accesso ai topic di altri pazienti.
- [x] Consentire al Raspberry di pubblicare soltanto sui propri topic.
- [x] Consentire al backend di leggere gli eventi e pubblicare comandi autorizzati.
- [x] Configurare retained message solo per stato corrente, non per tutti gli alert.
- [x] Configurare persistenza, limiti dei messaggi e log essenziali.
- [x] Provare connessione, disconnessione e Last Will del Raspberry simulato.
- [x] Documentare rinnovo certificati e revoca delle credenziali.

Output: un endpoint MQTT/TLS raggiungibile dal Raspberry e dal backend con permessi
minimi e verificabili.

### D2. Struttura del backend FastAPI

- [x] Creare un backend modulare unico, senza microservizi separati.
- [x] Separare moduli auth, patients, telemetry, alerts, tasks, notifications e realtime.
- [x] Configurare variabili d'ambiente e validazione della configurazione.
- [x] Esporre endpoint health e readiness.
- [x] Generare documentazione OpenAPI.
- [x] Aggiungere gestione centralizzata degli errori.
- [x] Aggiungere log strutturati senza dati sensibili.
- [x] Aggiungere test automatici eseguibili senza broker Cloud reale.

### D3. Database PostgreSQL

- [x] Configurare PostgreSQL e migrazioni versionate.
- [x] Creare tabella `users` con ruoli e credenziali protette.
- [x] Creare tabelle `patients`, `doctors`, `caregivers` e relative associazioni.
- [x] Creare tabella `edge_devices` con ultimo contatto e stato.
- [x] Creare tabelle `edge_cycles` e `feature_windows`.
- [x] Creare tabelle `decisions`, `alerts` e `alert_events`.
- [x] Creare tabelle `sensor_status` e `patient_app_status`.
- [x] Creare tabelle `tasks`, `task_results` e `notifications`.
- [x] Aggiungere indici su patient_id, timestamp, level e status.
- [x] Conservare `message_id` con vincolo univoco per la deduplicazione.
- [x] Stabilire retention e cancellazione dei dati di prova.
- [x] Preparare backup e ripristino del database.

### D4. Subscriber MQTT e ingestione

- [x] Connettere il backend al broker con riconnessione automatica.
- [x] Iscriversi ai topic Edge necessari.
- [x] Validare schema e versione di ogni payload.
- [x] Rifiutare payload senza patient_id, message_id o timestamp valido.
- [x] Deduplicare i messaggi tramite message_id.
- [x] Salvare cicli, finestre, decisioni, alert e stato sensori nelle tabelle corrette.
- [x] Gestire messaggi fuori ordine senza sovrascrivere uno stato piu' recente.
- [x] Registrare gli errori di parsing senza interrompere il subscriber.
- [x] Pubblicare eventi interni verso il gestore WebSocket.
- [x] Testare QoS 1, duplicati, ritardi e riconnessione.

### D5. API REST per dashboard e app

- [x] Implementare tutti gli endpoint definiti nel contratto condiviso.
- [x] Aggiungere paginazione a finestre, decisioni, alert e task.
- [x] Aggiungere filtri temporali e per livello/stato.
- [x] Costruire `/current` aggregando ultima finestra, decisione e stato tecnico.
- [x] Restituire valori mancanti come null.
- [x] Impedire a caregiver e paziente di leggere dati non autorizzati.
- [x] Validare input, scadenze e transizioni di stato dei task.
- [x] Pubblicare esempi OpenAPI utilizzabili da Emilio.
- [x] Scrivere test di autorizzazione per ogni ruolo.
- [x] Implementare endpoint profilo corrente `GET /api/v1/auth/me`.
- [x] Implementare endpoint admin per creare pazienti.
- [x] Implementare endpoint admin per creare utenti doctor, caregiver, patient e admin.
- [x] Implementare endpoint admin per associare utenti ai pazienti autorizzati.
- [x] Estendere paginazione con `page` e `page_size` coerenti su tutte le liste.
- [x] Aggiungere filtri task per tipo, scadenza e priorita'.

### D6. WebSocket realtime

- [x] Implementare autenticazione della connessione WebSocket.
- [x] Iscrivere ogni connessione solo ai pazienti autorizzati.
- [x] Inviare gli eventi concordati con event_type e payload.
- [x] Gestire heartbeat, timeout e rimozione delle connessioni chiuse.
- [x] Evitare perdita del servizio quando un client e' lento.
- [x] Documentare riconnessione e recupero degli eventi persi tramite REST.
- [x] Testare piu' client collegati allo stesso paziente.
- [x] Implementare ping/pong applicativo esplicito per verificare client vivi.
- [x] Documentare e testare recupero eventi persi dopo riconnessione tramite REST.
- [x] Documentare in modo esplicito evento `task_completed`.

### D7. Autenticazione, autorizzazione e audit

- [x] Implementare login e password hash sicuro.
- [x] Implementare access token breve e refresh token revocabile.
- [x] Definire ruoli doctor, caregiver, patient e admin.
- [x] Associare ogni utente ai soli pazienti autorizzati.
- [x] Registrare login, creazione/completamento task, ack e resolve; predisporre helper audit per modifiche amministrative future.
- [x] Non registrare password, token Google Health o token FCM nei log.
- [x] Preparare utenti demo separati per Emilio e Daniel.
- [x] Documentare come revocare un dispositivo smarrito.
- [x] Implementare cambio password utente.
- [x] Implementare revoca refresh token per dispositivo/sessione specifica.
- [x] Salvare `last_login_at` sugli utenti.
- [x] Registrare audit dei login falliti senza salvare password.
- [x] Aggiungere rate limit base sul login.

### D8. Logica alert e presa in carico

- [x] Creare un alert quando arriva un evento pubblicabile dal Raspberry.
- [x] Non trasformare automaticamente ogni livello yellow in notifica urgente.
- [x] Supportare stati new, acknowledged e resolved.
- [x] Salvare utente, ruolo, timestamp e nota per ogni cambio stato.
- [x] Rendere idempotente la presa in carico ripetuta.
- [x] Inviare aggiornamenti WebSocket dopo ogni cambiamento.
- [x] Definire quali livelli vengono notificati a medico e caregiver.
- [x] Mantenere separati alert clinical/behavioral e technical.
- [x] Aggiungere anti-spam per non creare alert simili gia' aperti da poco.
- [x] Separare severita' clinica da severita' tecnica.
- [x] Aggiungere campo sorgente alert: `ai`, `edge`, `manual`, `system`.
- [x] Implementare escalation se un alert resta `new` troppo a lungo.
- [x] Definire destinatari diversi per alert clinici, comportamentali e tecnici.

### D9. Task, test e risultati

- [x] Implementare creazione, invio, visualizzazione, completamento e scadenza dei task.
- [x] Validare che solo il medico possa creare determinati test clinici.
- [x] Salvare contenuto del task con versione per mantenere lo storico.
- [x] Impedire risultati duplicati per lo stesso completamento.
- [x] Calcolare score solo quando la regola del test e' definita e verificata.
- [x] Inviare evento WebSocket quando il risultato viene ricevuto.
- [x] Rendere disponibili task e risultati tramite API filtrate per ruolo.
- [x] Conservare un audit delle modifiche e delle note del medico.
- [x] Implementare annullamento task non ancora completato.
- [x] Supportare stato `cancelled`.
- [x] Aggiornare o calcolare automaticamente stato `expired`.
- [x] Assegnare task a destinatario specifico: paziente o caregiver.
- [x] Restituire dettagli score, ad esempio `correct`, `total` e motivazione.
- [x] Salvare note medico associate al task.
- [x] Strutturare risultati diversi per tipo test.

### D10. Firebase Cloud Messaging

- [x] Creare o configurare il progetto Firebase del sistema.
- [x] Implementare registrazione e aggiornamento dei token dispositivo.
- [x] Associare token a utente, dispositivo e ambiente.
- [x] Inviare push per task, alert severi e problemi tecnici selezionati.
- [x] Usare testi diversi per paziente, caregiver e medico.
- [x] Evitare dati clinici sensibili nel testo visibile sulla schermata bloccata.
- [x] Gestire token scaduti o non validi.
- [x] Registrare esito dell'invio senza salvare il token nei log applicativi.
- [x] Preparare una modalita' fake per test senza credenziali Firebase.

### D11. Stato sistema e integrazione Google Health

- [x] Salvare nel backend disponibilita' delle feature Google Health ricevute dall'Edge.
- [x] Mostrare come stato tecnico eventuali errori OAuth o dati non aggiornati.
- [x] Non trasferire al Cloud refresh token o credenziali Google presenti sul Raspberry.
- [x] Calcolare online/offline del Raspberry usando heartbeat e ultimo ciclo.
- [x] Calcolare stale/active di watch, BLE e app paziente con soglie configurabili.
- [x] Esporre lo stato aggregato tramite `/system-status`.

### D12. Deployment e osservabilita'

- [ ] Preparare avvio automatico di backend, database e broker.
- [ ] Usare Docker Compose per sviluppo e, se opportuno, per la demo Cloud.
- [ ] Separare configurazioni development, test e production.
- [ ] Configurare HTTPS/WSS con certificati validi.
- [ ] Configurare CORS soltanto per gli host delle applicazioni autorizzate.
- [ ] Aggiungere metriche minime: messaggi ricevuti, errori, client connessi e latenza.
- [ ] Configurare rotazione dei log.
- [ ] Documentare installazione, aggiornamento, backup e ripristino.
- [ ] Preparare uno script di smoke test dell'intera infrastruttura.

## 6. Attivita' condivise di integrazione

Queste sono le sole attivita' che richiedono il lavoro congiunto. Devono essere brevi e
programmate quando entrambi i lati hanno superato i propri test indipendenti.

### I1. Verifica dei contratti

- [ ] Confrontare payload reali Edge e schemi backend.
- [ ] Verificare null, timestamp, livelli alert e nomi delle feature.
- [ ] Bloccare la versione `schema_version: 1`.
- [ ] Salvare esempi validi ed esempi che devono essere rifiutati.

### I2. Primo collegamento Raspberry-Broker-Backend

- [ ] Avviare il sistema reale con il comando unico.
- [ ] Verificare TLS e autenticazione MQTT.
- [ ] Controllare che una finestra venga salvata una sola volta nel database.
- [ ] Spegnere Internet e verificare la coda locale.
- [ ] Riattivare Internet e verificare ritrasmissione e deduplicazione.

### I3. Collegamento backend-dashboard

- [ ] Sostituire URL mock con URL reale.
- [ ] Confrontare risposta `/current` con i file presenti sul Raspberry.
- [ ] Verificare grafici e valori null.
- [ ] Verificare ricezione WebSocket senza refresh pagina.
- [ ] Verificare scadenza token e riconnessione.

### I4. Flusso task paziente

- [ ] Il medico crea un task dalla dashboard.
- [ ] Il backend salva il task e invia la push.
- [ ] L'app paziente apre e completa il task.
- [ ] Il backend salva il risultato.
- [ ] La dashboard riceve l'evento e mostra il risultato.

### I5. Flusso alert caregiver

- [ ] Inviare un alert di test con should_publish true.
- [ ] Verificare salvataggio e notifica push.
- [ ] Prendere in carico l'alert dall'app caregiver.
- [ ] Verificare aggiornamento immediato della dashboard medico.
- [ ] Risolvere l'alert con nota e controllare l'audit.

### I6. Test finale sul Raspberry Pi 5

- [ ] Avviare tutto senza comandi manuali aggiuntivi.
- [ ] Verificare BLE reale e Google Health nella stessa finestra.
- [ ] Verificare decisione generica durante baseline.
- [ ] Verificare stato e avanzamento baseline nella dashboard.
- [ ] Riavviare il Raspberry e controllare la ripresa automatica.
- [ ] Spegnere il backend Cloud e controllare che l'Edge continui a funzionare.
- [ ] Ripristinare il Cloud e controllare riallineamento dei dati.

## 7. Ordine di lavoro parallelo

### Fase 0 - Contratti e struttura

| Emilio | Daniel | Punto di incontro |
|---|---|---|
| Prepara payload reali anonimizzati e scenari mock | Prepara schemi API/MQTT e OpenAPI iniziale | Approvazione di schema_version 1 |
| Crea struttura dashboard e mock server | Crea struttura backend e database | Nessuna dipendenza durante lo sviluppo |

### Fase 1 - Dati Cloud e prima UI

| Emilio | Daniel | Punto di incontro |
|---|---|---|
| Implementa publisher MQTT e overview dashboard | Configura broker, subscriber e endpoint `/current` | Primo evento Edge visibile nella dashboard |
| Implementa pagine wearable/spatial | Implementa persistenza finestre e decisioni | Confronto dei dati con latest_window |

### Fase 2 - Alert e realtime

| Emilio | Daniel | Punto di incontro |
|---|---|---|
| Implementa lista alert, dettaglio e AI explanation | Implementa alert, WebSocket, auth e audit | Alert aggiornato senza refresh |
| Implementa stato tecnico | Implementa heartbeat e system-status | Distinzione clinical/technical verificata |

### Fase 3 - Task e applicazioni mobili

| Emilio | Daniel | Punto di incontro |
|---|---|---|
| Estende app paziente e crea UI caregiver | Implementa task, risultati e FCM | Task completo medico-paziente-medico |
| Gestisce push e coda offline lato app | Gestisce token, notifiche e scadenze | Alert caregiver preso in carico |

### Fase 4 - Affidabilita' e deployment

| Emilio | Daniel | Punto di incontro |
|---|---|---|
| Testa Edge offline, app in background e dashboard | Testa backup, sicurezza, carico e deployment | Test end-to-end su Raspberry Pi 5 |
| Completa README delle applicazioni | Completa README Cloud e runbook | Demo avviabile e documentata |

## 8. Criteri di completamento

### Emilio ha completato la propria parte quando

- [ ] Il Raspberry pubblica e accoda gli eventi senza interrompere il ciclo locale.
- [ ] La dashboard funziona con backend reale e gestisce la perdita di connessione.
- [ ] Medico e caregiver vedono soltanto informazioni adatte al proprio ruolo.
- [ ] L'app paziente continua il BLE in background e completa un task reale.
- [ ] APK, configurazione e procedure di test sono documentati.

### Daniel ha completato la propria parte quando

- [ ] Broker, backend e database partono automaticamente.
- [ ] TLS, autenticazione e ACL impediscono accessi non autorizzati.
- [ ] I messaggi duplicati non producono righe o alert duplicati.
- [ ] REST, WebSocket, task, audit e notifiche push sono testati.
- [ ] Backup, ripristino e configurazione sono documentati.

### Il sistema e' completato quando

- [ ] Una finestra reale BLE + Google Health compare nella dashboard.
- [ ] Un alert critico raggiunge medico e caregiver.
- [ ] La presa in carico viene sincronizzata e registrata.
- [ ] Un test inviato dal medico viene completato dal paziente e restituito.
- [ ] Edge, app e Cloud recuperano correttamente dopo una disconnessione.
- [ ] Nessun segreto e nessun dataset sensibile e' presente nel repository Git.

## 9. Attivita' successive alla prima versione

Queste attivita' non devono bloccare il prototipo iniziale:

- [ ] Versione iOS dell'app caregiver e, se necessaria, dell'app paziente.
- [ ] Interoperabilita' HL7 FHIR con sistemi sanitari esterni.
- [ ] Supporto multi-struttura e gestione di molti Raspberry.
- [ ] Retention avanzata e Time-Series Database dedicato.
- [ ] Override medico per richiedere dati Edge ad alta frequenza.
- [ ] Integrazione NILM/Shelly quando l'hardware sara' definito.
- [ ] Report clinici esportabili e firma dei referti.
- [ ] Valutazione formale GDPR, DPIA e consenso informato.
- [ ] Validazione clinica delle soglie e dei test con personale sanitario.
- [ ] Suddivisione in microservizi soltanto se il carico o il deployment lo richiedono.

La regola operativa rimane semplice: Emilio sviluppa le applicazioni e il collegamento
con l'Edge usando mock stabili; Daniel sviluppa Cloud e backend usando publisher e client
di test. I due rami si incontrano soltanto ai punti di integrazione definiti sopra.
