# Da aggiungere al progetto IoT

Questo file raccoglie solo le aggiunte che vale davvero la pena realizzare dopo
l'audit tecnico dei file `ANALISI_COMPLETA.md`, `FEATURE_EXPANSION.md` e
`PROJECT_AUDIT.md`.

L'obiettivo non e' aggiungere funzionalita' a caso, ma rendere il progetto piu'
credibile per esame, demo e manutenzione: modelli AI verificabili, dashboard piu'
manutenibile, alert piu' intelligenti, report piu' utili e sistema piu' robusto.

## Regola generale di lavoro

Emilio e Daniel possono lavorare in parallelo, ma ogni funzionalita' deve rispettare
questa divisione:

- Daniel prepara backend, database, endpoint, edge, AI, job automatici e test server-side.
- Emilio prepara dashboard, app Android, esperienza medico/paziente/caregiver,
  documentazione operativa e test frontend/mobile.

Ogni blocco sotto indica cosa deve fare ciascuno e quale output deve esistere alla fine.

---

## Priorita' 1 - Credibilita' tecnica prima dell'esame

### D21 - Validazione dei modelli AI e metriche

Responsabile principale: Daniel.

Perche' serve: oggi il sistema produce score AI, ma bisogna dimostrare che i modelli
sono stati valutati e non solo addestrati.

Cosa fare:

- aggiungere split train/validation per i dataset generici;
- salvare un report JSON per ogni modello addestrato;
- calcolare metriche almeno su dataset sintetici/controllati: precision, recall, F1,
  falsi positivi e falsi negativi;
- per il modello personale, usare holdout temporale: una parte delle finestre baseline
  resta fuori dal training e viene usata per controllo;
- rendere configurabile `contamination` invece di lasciarlo fisso;
- salvare in `models/` anche un file tipo `generic_wearable_metrics.json`,
  `generic_spatial_metrics.json`, `patient-001_metrics.json`;
- aggiungere comando CLI tipo:

```powershell
python -m edge_ai.cli evaluate --model models/generic_wearable.pkl --input data/processed/... --output outputs/model_metrics.json
```

Output atteso:

- ogni modello ha un file metriche leggibile;
- il progetto puo' dire: "questo modello e' stato valutato su dati non visti";
- i test dimostrano che un caso normale resta normale e un caso critico viene rilevato.

### E21 - Visualizzazione metriche AI nella Dashboard

Responsabile principale: Emilio.

Dipende da: D21.

Cosa fare:

- aggiungere nella pagina "Valutazione comportamentale" una sezione "Affidabilita' modello";
- mostrare ultimo training, numero finestre usate, validation rows, precision/recall/F1;
- mostrare una scritta prudente quando le metriche non sono disponibili;
- evitare linguaggio assoluto: non scrivere "modello corretto", ma "validazione disponibile";
- aggiungere nel report PDF le metriche sintetiche del modello.

Output atteso:

- il medico/docente vede non solo lo score, ma anche quanto il modello e' stato validato.

---

## Priorita' 2 - Confidence score e qualita' del dato

### D22 - Confidence score per ogni decisione AI

Responsabile principale: Daniel.

Perche' serve: uno score calcolato con pochi dati non deve avere lo stesso peso di uno
score calcolato con dati completi.

Cosa fare:

- calcolare percentuale di feature disponibili nella finestra;
- calcolare completezza per sorgente: BLE, Google Health, Shelly, app paziente;
- penalizzare la confidenza quando:
  - mancano troppe feature;
  - il wearable non e' presente;
  - i campioni BLE sono pochi;
  - MQTT e' in coda da troppo tempo;
  - il modello personale non esiste ancora;
- aggiungere al JSON decisionale:

```json
{
  "confidence": {
    "score": 82,
    "level": "alta",
    "reasons": [
      "BLE completo",
      "Google Health parziale",
      "modello personale disponibile"
    ]
  }
}
```

- salvare il campo anche nel backend;
- esporlo su decisioni, current, timeline e report.

Output atteso:

- ogni decisione ha un indice di affidabilita' separato dall'indice AI.

### E22 - UI confidenza e dati mancanti

Responsabile principale: Emilio.

Dipende da: D22.

Cosa fare:

- mostrare vicino allo score AI un badge "Affidabilita' alta/media/bassa";
- aggiungere tooltip o dettaglio con i motivi della confidenza;
- nei grafici distinguere chiaramente:
  - dato acquisito;
  - dato non acquisito;
  - dato imputato;
- nella timeline evidenziare le decisioni a bassa confidenza;
- nel report finale includere una nota sulla qualita' dei dati.

Output atteso:

- il medico capisce quando uno score alto e' affidabile e quando invece va letto con cautela.

---

## Priorita' 3 - Explainable AI reale

### D23 - Feature importance dei modelli

Responsabile principale: Daniel.

Perche' serve: il modello non deve essere percepito come una scatola nera.

Cosa fare:

- implementare una feature importance compatibile con Isolation Forest;
- usare una prima versione basata su:
  - z-score rispetto al training;
  - differenza dello score se una feature viene sostituita con valore mediano;
  - ranking delle feature piu' influenti;
- salvare nel decision JSON:

```json
{
  "feature_importance": [
    {
      "feature": "heart_rate_mean",
      "label": "Frequenza cardiaca media",
      "impact": "aumenta_indice",
      "weight": 0.42,
      "value": 108,
      "reference": 74
    }
  ]
}
```

- distinguere feature spaziali, wearable, personali e NILM;
- aggiungere test su casi controllati: HR alto, SpO2 basso, isolamento in camera,
  assenza movimento.

Output atteso:

- lo score AI viene accompagnato da una spiegazione quantitativa.

### E23 - Spiegazione clinica in linguaggio naturale

Responsabile principale: Emilio.

Dipende da: D23.

Cosa fare:

- trasformare la feature importance in frasi comprensibili:
  - "La frequenza cardiaca e' sopra il riferimento personale";
  - "La permanenza in camera e' piu' lunga del solito";
  - "La saturazione e' sotto il range atteso";
- mostrare separatamente:
  - fattori che aumentano l'indice;
  - fattori che riducono l'indice;
  - dati mancanti;
- eliminare dai pannelli principali nomi tecnici come `kitchen_minutes`;
- mantenere sempre la dicitura "supporto al triage".

Output atteso:

- il medico legge una spiegazione utile senza aprire JSON o interpretare feature grezze.

---

## Priorita' 4 - Alert clinicamente piu' utili

### D24 - Alert di assenza insolita

Responsabile principale: Daniel.

Perche' serve: un paziente fermo per ore potrebbe non generare score AI alto, ma resta
un segnale importante da verificare.

Cosa fare:

- calcolare da BLE e finestre storiche:
  - tempo senza cambi stanza;
  - tempo senza accesso a cucina;
  - tempo senza accesso a bagno;
  - permanenza continua nella stessa stanza;
- definire regole iniziali prudenti:
  - nessun movimento per oltre 4 ore durante il giorno;
  - nessun accesso a bagno/cucina per oltre 12 ore;
  - permanenza in camera molto oltre baseline;
- generare alert tecnico/comportamentale con motivo esplicito;
- evitare duplicati con debounce dedicato;
- non generare alert se il BLE e' assente o non affidabile: in quel caso creare guasto tecnico.

Output atteso:

- il sistema segnala "assenza insolita da verificare" anche quando lo score AI non supera
  soglia critica.

### E24 - Visualizzazione alert assenza e workflow caregiver

Responsabile principale: Emilio.

Dipende da: D24.

Cosa fare:

- nella Dashboard mostrare un alert con titolo chiaro:
  "Assenza di movimento da verificare";
- mostrare:
  - ultima stanza rilevata;
  - ultima transizione;
  - durata assenza;
  - qualita' BLE;
- aggiungere azioni rapide:
  - invia messaggio al paziente;
  - avvisa caregiver;
  - prendi in carico;
  - risolvi con nota;
- nell'app caregiver mostrare solo messaggio operativo, senza feature AI grezze.

Output atteso:

- il medico e il caregiver hanno un workflow pratico per controllare il paziente.

---

## Priorita' 5 - Giornata tipo vs oggi

### D25 - Profilo circadiano e giornata tipo

Responsabile principale: Daniel.

Perche' serve: in geriatria il confronto piu' utile e' "oggi e' simile al solito?".

Cosa fare:

- calcolare profilo medio per fascia oraria usando le finestre storiche;
- creare aggregazioni per:
  - score AI;
  - battito medio;
  - passi;
  - sedentarieta';
  - stanza prevalente;
  - cambi stanza;
  - sonno se disponibile;
- esporre endpoint:

```text
GET /api/v1/patients/{patient_id}/day-profile
```

- payload consigliato:

```json
{
  "today": [],
  "baseline_day": [],
  "yesterday": [],
  "bands": ["00-06", "06-10", "10-14", "14-18", "18-22", "22-24"]
}
```

- gestire baseline non disponibile con `baseline_available: false`.

Output atteso:

- il backend restituisce dati pronti per grafici "oggi vs giornata tipo".

### E25 - Grafici overlay giornata tipo

Responsabile principale: Emilio.

Dipende da: D25.

Cosa fare:

- aggiungere nella Dashboard una scheda "Giornata tipo";
- mostrare grafico overlay:
  - linea oggi;
  - linea ieri;
  - linea media baseline;
- usare colori leggibili e legenda chiara;
- permettere selezione metrica: AI, battito, passi, sedentarieta', movimento indoor;
- evidenziare differenze importanti con testo prudente:
  "oggi risulta meno attivo della routine nella fascia 10-14";
- aggiungere il grafico anche nel report.

Output atteso:

- il medico vede a colpo d'occhio se la giornata corrente si discosta dalla routine.

---

## Priorita' 6 - Degradazione progressiva e drift

### D26 - Alert di degradazione progressiva

Responsabile principale: Daniel.

Perche' serve: non basta guardare lo score assoluto. Uno score che sale lentamente per
giorni puo' essere piu' interessante di un singolo picco.

Cosa fare:

- calcolare trend lineare dello score AI sugli ultimi 3, 7 e 14 giorni;
- calcolare trend di:
  - passi;
  - sedentarieta';
  - sonno;
  - permanenza in camera;
  - HR medio;
- generare alert se il trend supera soglie configurabili;
- aggiungere campo:

```json
{
  "trend": {
    "score_slope_per_day": 4.8,
    "direction": "in_aumento",
    "window_days": 7
  }
}
```

- evitare alert se i dati hanno bassa confidenza.

Output atteso:

- il sistema segnala peggioramenti progressivi prima della soglia rossa.

### D27 - Drift detection e retraining controllato

Responsabile principale: Daniel.

Perche' serve: dopo settimane o mesi la routine del paziente puo' cambiare. Il modello
personale deve capire quando non e' piu' aggiornato.

Cosa fare:

- monitorare distribuzione degli score personali;
- rilevare drift se media e varianza cambiano stabilmente;
- non fare retraining automatico cieco su finestre sospette;
- introdurre stato:
  - `stable`;
  - `possible_drift`;
  - `needs_review`;
  - `retrained`;
- salvare log del retraining;
- permettere al medico di approvare o bloccare un retraining.

Output atteso:

- il sistema non diventa obsoleto dopo il periodo iniziale.

### E26 - UI trend e drift

Responsabile principale: Emilio.

Dipende da: D26 e D27.

Cosa fare:

- aggiungere nella spiegazione AI una sezione "Andamento nel tempo";
- mostrare se l'indice e' stabile, in aumento o in diminuzione;
- mostrare eventuale stato di drift del modello personale;
- se serve approvazione medico, aggiungere pulsante:
  "Approva aggiornamento modello";
- visualizzare nel report quando il modello e' stato aggiornato.

Output atteso:

- il medico capisce non solo il valore attuale, ma anche la direzione del paziente.

---

## Priorita' 7 - Report automatici

### D28 - Report settimanale automatico

Responsabile principale: Daniel.

Perche' serve: un medico non puo' leggere centinaia di finestre. Serve un riassunto
automatico.

Cosa fare:

- creare job settimanale o comando manuale che genera report;
- calcolare:
  - media e massimo score AI;
  - numero giorni con attenzione/rischio/allerta;
  - alert creati e risolti;
  - task inviati e completati;
  - sonno medio;
  - passi medi;
  - stanza prevalente;
  - cambi notturni;
- confrontare con settimana precedente;
- salvare report in tabella o JSON persistente;
- esporre endpoint:

```text
GET /api/v1/patients/{patient_id}/reports/weekly
```

Output atteso:

- ogni settimana esiste un riepilogo clinico-operativo pronto.

### D29 - Morning brief

Responsabile principale: Daniel.

Perche' serve: il medico apre la dashboard al mattino e vede subito com'e' andata la
notte.

Cosa fare:

- calcolare dalle 22:00 alle 08:00:
  - sonno;
  - risvegli;
  - HR notturno;
  - SpO2 se disponibile;
  - movimenti notturni;
  - permanenza fuori camera;
- confrontare con baseline personale;
- esporre endpoint:

```text
GET /api/v1/patients/{patient_id}/morning-brief
```

Output atteso:

- la dashboard mostra una frase del tipo:
  "Notte complessivamente stabile, con 2 movimenti notturni e sonno leggermente ridotto".

### E27 - UI report settimanale e morning brief

Responsabile principale: Emilio.

Dipende da: D28 e D29.

Cosa fare:

- aggiungere in Dashboard un pannello "Brief del mattino";
- aggiungere nella pagina Report una sezione "Report settimanali";
- consentire selezione settimana;
- esportare report settimanale in PDF;
- evidenziare differenze con settimana precedente;
- mantenere linguaggio prudente e non diagnostico.

Output atteso:

- il progetto produce un output professionale facilmente presentabile al docente.

---

## Priorita' 8 - Test automatizzati e demo solida

### D30 - Test backend, edge e MQTT

Responsabile principale: Daniel.

Perche' serve: il progetto deve essere dimostrabile senza paura di rompere qualcosa.

Cosa fare:

- aumentare copertura test su:
  - edge_ai training/inference/fusion/debounce;
  - edge_ingest aggregazione finestre;
  - edge_quality controlli dati;
  - edge_mqtt coda offline e retry;
  - backend auth, MQTT ingest, WebSocket, alerts, tasks, questionnaires;
- aggiungere test per duplicati `message_id`;
- aggiungere test per utente non autorizzato;
- aggiungere dati fixture realistici ma non personali;
- documentare comando unico:

```powershell
python -m pytest edge_node/tests cloud/backend/tests
```

Output atteso:

- il progetto ha una suite minima ma credibile.

### E28 - Test frontend e mobile

Responsabile principale: Emilio.

Dipende parzialmente da: D30.

Cosa fare:

- aggiungere test di rendering per Dashboard:
  - login;
  - lista pazienti;
  - quadro clinico;
  - segnalazioni;
  - task;
  - timeline;
  - report;
- aggiungere test o checklist Android per:
  - login paziente;
  - login caregiver;
  - ricezione task;
  - compilazione check-in;
  - rete assente;
  - BLE in background;
- aggiornare `Test.md` con sezione "test automatici" e "test manuali demo".

Output atteso:

- la demo ha una procedura ripetibile e verificabile.

---

## Priorita' 9 - Refactoring Dashboard

### E29 - Spezzare `App.jsx` in componenti

Responsabile principale: Emilio.

Perche' serve: `App.jsx` e' troppo grande. Funziona, ma e' difficile da mantenere e
spiegare a un docente.

Cosa fare:

- creare struttura:

```text
Dashboard/src/
  components/
    layout/
    patient/
    ai/
    alerts/
    tasks/
    timeline/
    evaluations/
    routine/
    system/
    report/
  hooks/
    usePatientData.js
    usePatientRealtime.js
  utils/
    format.js
    clinicalLabels.js
```

- spostare un componente alla volta, verificando build dopo ogni passaggio;
- non cambiare comportamento mentre si refactora;
- aggiungere `ErrorBoundary` per evitare pagina bianca;
- mantenere `App.jsx` come orchestratore piccolo.

Output atteso:

- Dashboard piu' pulita, manutenibile e difendibile all'esame.

### E30 - Offline mode leggero per Dashboard

Responsabile principale: Emilio.

Dipende da: E29 consigliato, ma non obbligatorio.

Cosa fare:

- salvare in localStorage l'ultimo payload paziente caricato;
- se il backend non risponde, mostrare "dati non aggiornati" invece di pagina vuota;
- impedire azioni operative offline, ma lasciare consultazione;
- mostrare ora dell'ultimo dato sincronizzato.

Output atteso:

- se il backend cade durante la demo, la dashboard resta leggibile.

---

## Priorita' 10 - Robustezza infrastrutturale

### D31 - Database retention e archiviazione

Responsabile principale: Daniel.

Perche' serve: le finestre ogni 4 minuti crescono rapidamente.

Cosa fare:

- definire retention:
  - raw data BLE/Google/Shelly: conservazione breve;
  - feature windows: conservazione completa per periodo dimostrativo, poi archivio;
  - decisioni, alert, task e report: conservazione lunga;
- creare job/manual command per archiviare dati vecchi;
- documentare cosa viene cancellato e cosa no;
- evitare cancellazione di audit, alert e task clinici.

Output atteso:

- il database non cresce senza controllo.

### D32 - Backup automatico e restore testato

Responsabile principale: Daniel.

Perche' serve: senza backup, un sistema con dati paziente non e' credibile.

Cosa fare:

- creare script backup PostgreSQL automatico;
- conservare ultimi 7 backup;
- aggiungere comando restore su database temporaneo;
- documentare test di restore;
- evitare che i backup finiscano su Git.

Output atteso:

- si puo' dimostrare che i dati sono recuperabili.

### D33 - Monitoring e health operativo

Responsabile principale: Daniel.

Perche' serve: bisogna sapere se backend, MQTT, database, Edge e Firebase stanno
funzionando.

Cosa fare:

- verificare `/health/live` e `/health/ready`;
- aggiungere metriche essenziali:
  - cicli Edge completati;
  - messaggi MQTT ricevuti;
  - messaggi in coda;
  - WebSocket attivi;
  - errori Firebase;
- creare endpoint o pagina backend per stato operativo;
- mantenere log senza token o password.

Output atteso:

- si capisce subito perche' un dato non arriva.

### E31 - Stato sistema migliorato nella Dashboard

Responsabile principale: Emilio.

Dipende da: D33.

Cosa fare:

- mostrare salute di backend, MQTT, database, Edge e Firebase;
- distinguere warning temporaneo da guasto persistente;
- aggiungere pulsante "diagnostica rapida";
- mostrare suggerimento operativo:
  "MQTT non pubblica: controllare password edge o broker";
- non mostrare segreti.

Output atteso:

- la Dashboard diventa anche uno strumento di diagnosi semplice.

---

## Priorita' 11 - Sicurezza e segreti

### D34 - Pulizia credenziali e secrets management

Responsabile principale: Daniel.

Perche' serve: audit e file `.env` non devono contenere password reali versionate.

Cosa fare:

- controllare `.gitignore`;
- assicurarsi che `.env`, token OAuth, certificati privati e Firebase service account
  non vengano committati;
- lasciare solo `.env.example`;
- spostare password e token in variabili ambiente;
- aggiungere script/check che fallisce se trova password note nei file versionati;
- rigenerare eventuali segreti esposti durante lo sviluppo.

Output atteso:

- il repository puo' essere condiviso senza credenziali reali.

### E32 - Messaggi UI privacy-aware

Responsabile principale: Emilio.

Cosa fare:

- nella dashboard non mostrare token, password, certificati o dettagli sensibili;
- nell'app caregiver non mostrare feature AI grezze;
- nel report esportato includere solo dati necessari;
- aggiungere testi privacy brevi e chiari nelle schermate di configurazione.

Output atteso:

- l'interfaccia resta adatta a un contesto sanitario dimostrativo.

---

## Priorita' 12 - Automazione demo finale

### D35 - Script demo backend/edge affidabile

Responsabile principale: Daniel.

Cosa fare:

- creare comando unico per avviare:
  - Docker MQTT/PostgreSQL;
  - backend;
  - worker MQTT;
  - edge runtime;
  - receiver BLE;
- aggiungere controllo porte occupate;
- aggiungere log chiari;
- aggiungere comando di stop;
- aggiungere modalita' demo con dati controllati se manca hardware.

Output atteso:

- la demo parte con pochi comandi e non richiede ricordare sequenze lunghe.

### E33 - Guida demo e verifica visuale

Responsabile principale: Emilio.

Dipende da: D35.

Cosa fare:

- aggiornare `Test.md` con una scaletta demo definitiva;
- creare una guida breve "DemoEsame.md";
- indicare cosa mostrare al docente:
  - avvio sistema;
  - arrivo dati BLE/Google Health;
  - generazione score AI;
  - alert;
  - task paziente;
  - caregiver;
  - report;
- preparare screenshot o dati seed per evitare demo vuota.

Output atteso:

- la presentazione e' ripetibile e comprensibile anche sotto pressione.

---

## Cose da non mettere in priorita' ora

Queste idee sono interessanti, ma non sono essenziali rispetto al tempo e al valore
per l'esame:

- dark mode;
- clustering giornaliero;
- matrice di correlazione completa;
- app iOS completa, se la demo usa Android;
- NILM avanzato con modello dedicato;
- forecasting complesso tipo LSTM.

Meglio completare bene validazione, confidence score, alert assenza, giornata tipo,
report automatici, test e refactoring.
