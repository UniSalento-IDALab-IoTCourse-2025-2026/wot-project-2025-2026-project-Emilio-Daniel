# FEATURE EXPANSION — Sfruttare al Massimo il Sistema Esistente

> Analisi delle funzionalità aggiuntive che possono essere implementate
> utilizzando **esclusivamente ciò che il progetto possiede già**.
> Nessun nuovo hardware, nessun nuovo sensore, nessun componente fisico aggiuntivo.

---

## Indice

- [Dati già a disposizione del sistema](#dati-già-a-disposizione-del-sistema)
- [1. Data Features](#1-data-features)
- [2. AI / ML Features](#2-ai--ml-features)
- [3. Analytics Features](#3-analytics-features)
- [4. Dashboard / UX Features](#4-dashboard--ux-features)
- [5. Alert / Monitoring Features](#5-alert--monitoring-features)
- [6. Reporting Features](#6-reporting-features)
- [Le 5 Feature "Wow"](#le-5-feature-wow)
- [Analisi Finale](#analisi-finale)

---

## Dati già a disposizione del sistema

Prima di proporre nuove funzionalità, elenchiamo tutto ciò che il sistema raccoglie
e memorizza attualmente.

### Dati Wearable (Google Health / Pixel Watch 2)

| Feature | Frequenza | Descrizione |
|---------|-----------|-------------|
| `heart_rate_mean` | Ogni 4 minuti | Media battiti nella finestra |
| `heart_rate_std` | Ogni 4 minuti | Deviazione standard battiti |
| `resting_heart_rate` | Giornaliero | Battito a riposo |
| `hrv_rmssd` | Ogni 4 minuti / giornaliero | Variabilità cardiaca |
| `spo2_mean` | Ogni 4 minuti / notturno | Saturazione ossigeno |
| `sleep_minutes` | Giornaliero | Minuti di sonno |
| `awake_minutes` | Giornaliero | Minuti di veglia durante il sonno |
| `steps` | Ogni 4 minuti | Passi stimati |
| `sedentary_minutes` | Ogni 4 minuti | Minuti sedentari |
| `wearable_present` | Ogni 4 minuti | Presenza del wearable |
| `wearable_battery_pct` | Ogni 4 minuti | Batteria del wearable |

### Dati Spaziali (BLE Beacons)

| Feature | Frequenza | Descrizione |
|---------|-----------|-------------|
| `room_changes` | Ogni 4 minuti | Cambi stanza nella finestra |
| `night_room_changes` | Ogni 4 minuti | Cambi stanza notturni (0-6h) |
| `bedroom_minutes` | Ogni 4 minuti | Minuti in camera |
| `kitchen_minutes` | Ogni 4 minuti | Minuti in cucina |
| `bathroom_minutes` | Ogni 4 minuti | Minuti in bagno |
| `living_room_minutes` | Ogni 4 minuti | Minuti in soggiorno |
| `longest_single_room_minutes` | Ogni 4 minuti | Permanga continua max stessa stanza |

### Dati NILM / Energetici (Shelly 3EM)

| Feature | Frequenza | Descrizione |
|---------|-----------|-------------|
| `nilm_total_wh` | Ogni 4 minuti | Energia totale consumata |
| `nilm_kitchen_events` | Ogni 4 minuti | Eventi rilevati in cucina |
| `nilm_tv_minutes` | Ogni 4 minuti | Minuti TV attiva |
| `nilm_coffee_events` | Ogni 4 minuti | Eventi macchina caffè |
| `nilm_stove_events` | Ogni 4 minuti | Eventi fornelli |

### Dati di Contesto

| Dato | Frequenza | Descrizione |
|------|-----------|-------------|
| `window_start / window_end` | Ogni 4 minuti | Finestra temporale |
| `patient_id` | Ogni 4 minuti | Identificativo paziente |
| Decisioni AI (score, level) | Ogni 4 minuti | Risultato inferenza |
| Stato sistema (edge, mqtt) | Ogni 4 minuti | Stato tecnico |

### Infrastruttura Disponibile

- Database PostgreSQL con storico crescente
- Backend FastAPI con WebSocket
- Dashboard React con 8 viste
- Modelli IsolationForest (3 livelli)
- Sistema di debounce con storia 48 ore
- Coda offline MQTT

---

## 1. Data Features

Nuove informazioni/statistiche ricavabili dai dati già raccolti.

### 1.1 Indice di Benessere Composito (Composite Wellness Index)

**Dati esistenti**: heart_rate_mean, hrv_rmssd, spo2_mean, steps, sedentary_minutes,
sleep_minutes, room_changes

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Feature singole (HR, HRV, SpO2, steps, sleep, movimento)
        ↓
Normalizzazione 0-100 per ogni feature
        ↓
Media pesata ponderata clinicamente
        ↓
Indice complessivo 0-100 con fascia colorata
        ↓
Il medico vede in un unico numero lo stato generale del paziente
```

**Utilità**: Il medico oggi deve guardare 7+ grafici separati per capire come sta
il paziente. Un indice composito riassume tutto in un numero comprensibile.

**Valore tecnico**: Richiede calibrazione delle soglie per ogni feature e dei pesi
relativi. Va costruito su basi cliniche, non arbitrariamente.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Composite Wellness Index | Tutti i wearable | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **ALTA** |

---

### 1.2 Profilo Circadiano del Paziente

**Dati esistenti**: heart_rate_mean per ogni finestra, bedroom_minutes, bathroom_minutes,
steps, sedentary_minutes, ora della finestra

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Dati per finestra (4 minuti) × 24 ore × giorni storici
        ↓
Media di ogni feature per fascia oraria (0-5h, 6-10h, 11-14h, 15-18h, 19-22h, 23h)
        ↓
Costruzione di un "profilo medio giornaliero"
        ↓
Grafico radar o a barre che mostra il ritmo tipico del paziente
        ↓
Il medico capisce quando il paziente dorme, mangia, si muove, è sedentario
```

**Utilità**: Il profilo circadiano è fondamentale in geriatria. Cambiamenti nel ritmo
sonno-veglia sono tra i primi indicatori di declino cognitivo o peggioramento clinico.

**Valore tecnico**: L'analisi circadiana è uno standard clinico. Implementarla con dati
reali di wearable posiziona il progetto a livello professionale.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Profilo Circadiano | HR, sleep, activity, spatial | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | **ALTA** |

---

### 1.3 Indice di Autonomia Funzionale (ADL Score)

**Dati esistenti**: room_changes, kitchen_minutes, bathroom_minutes, bedroom_minutes,
steps, sedentary_minutes, longest_single_room_minutes, nilm_kitchen_events,
nilm_coffee_events, nilm_stove_events

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Attività della vita quotidiana rilevate:
  cucina (cooking, caffè)
  bagno (igiene personale)
  movimento tra stanze (autonomia locomotoria)
  sonno (regolarità)
  passi (attività fisica)
        ↓
Punteggio ADL ponderato per importanza clinica
        ↓
Fascia: autonomo / lieve riduzione / riduzione moderata / dipendente
        ↓
Scheda paziente con livello di autonomia
        ↓
Il medico monitora il declino funzionale nel tempo
```

**Utilità**: L'ADL (Activities of Daily Living) è lo standard clinico per valutare
l'autonomia degli anziani. Questo sistema li misura indirettamente con i beacon
e il wearable, senza questionari.

**Valore tecnico**: Trasformare dati spaziali e wearable in un punteggio ADL è un
risultato concreto di IoT per la salute.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Indice ADL | BLE + NILM + wearable | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **ALTA** |

---

### 1.4 Analisi dei Pattern Sonno-Veglia

**Dati esistenti**: sleep_minutes, awake_minutes, bedroom_minutes, night_room_changes,
heart_rate_mean notturno, sedentary_minutes notturni

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Dati notturni (22h-6h) × giorni storici
        ↓
Estrazione metriche: durata sonno, qualità (risvegli), regolarità orario
        ↓
Confronto con baseline e con letteratura clinica
        ↓
Report sonno con punteggio qualità
        ↓
Il medico vede se il sonno sta peggiorando
```

**Utilità**: I disturbi del sonno sono correlati a depressione, demenza, dolore cronico.
Monitorarli oggettivamente con il wearable è clinicamente rilevante.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Analisi Sonno-Veglia | Sleep, HR, bedroom, night_activity | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **ALTA** |

---

### 1.5 Metriche di Attività Giornaliera

**Dati esistenti**: steps, sedentary_minutes, room_changes, longest_single_room_minutes

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Passi totali giornalieri + minuti sedentari + cambi stanza
        ↓
Classificazione giornata: attiva / moderata / sedentaria
        ↓
Trend settimanale/mensile dell'attività
        ↓
Grafico trend + confronto con media storica
        ↓
Il medico monitora se il paziente si muove meno del solito
```

**Utilità**: La riduzione dell'attività è un marker precoce di peggioramento.
Confrontare i passi di oggi con la media del mese scorso è immediatamente utile.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Metriche Attività | Steps, sedentary, BLE | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | **MEDIA** |

---

### 1.6 Indoor Mobility Index

**Dati esistenti**: room_changes, bedroom_minutes, kitchen_minutes, bathroom_minutes,
living_room_minutes, longest_single_room_minutes, night_room_changes

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Pattern di movimento intra-domestico nella giornata
        ↓
Calcolo: varietà di stanze visitate, frequenza spostamenti,
         permanenza media per stanza, mobilità notturna
        ↓
Indice 0-100 di mobilità indoor
        ↓
Grafico radar per stanza + trend nel tempo
        ↓
Rileva isolamento (solo camera) o iperattività (troppi spostamenti)
```

**Utilità**: Un paziente che sta solo in camera per giorni è a rischio. Un paziente
che cambia stanza 50 volte in 4 minuti potrebbe essere agitato. Il sistema può
distinguerli.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Indoor Mobility Index | BLE spatial data | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | **MEDIA** |

---

## 2. AI / ML Features

Nuove funzionalità basate sul modello ML o su elaborazioni dei dati già disponibili.

### 2.1 Trend Prediction (Forecasting a Breve Termine)

**Dati esistenti**: Storico feature windows (ogni 4 minuti), decisioni AI, score

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Ultimi N giorni di feature windows
        ↓
Serie temporali per feature principali (HR, SpO2, steps, room_changes)
        ↓
Modello di forecasting semplice (es. media mobile + trend lineare)
        ↓
Previsione prossime 4-12 ore
        ↓
Grafico con linee reali + linea prevista + intervallo confidenza
        ↓
Il medico vede dove sta andando il paziente, non solo dove è ora
```

**Utilità**: Attualmente il sistema mostra solo il presente e il passato. Prevedere
le prossime 4-12 ore è Clinicamente rilevante: "Se il trend continua, alle 16:00
la saturazione potrebbe scendere sotto il 92%".

**Complessità**: Non serve un modello LSTM complesso. Una media mobile esponenziale
+ intervallo di confidenza basato sulla varianza storica è sufficiente per una prima
versione.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Trend Prediction | Storico feature windows | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **ALTA** |

---

### 2.2 Confronto Predizione vs Realtà (Prediction vs Actual)

**Dati esistenti**: Storico decisioni AI + storico feature windows reali

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Ogni 4 minuti: il sistema predice (baseline) + poi misura il valore reale
        ↓
Calcolo errore predittivo: |predetto - reale| per ogni feature
        ↓
MAE (Mean Absolute Error) storico per feature
        ↓
Dashboard mostra: "HR previsto 72, reale 85, errore 13 bpm"
        ↓
Il medico capisce quanto è affidabile il modello
```

**Utilità**: Questa funzionalità serve a due scopi:
1. **Validare il modello**: se l'errore cresce, il modello si sta degradando
2. **Spiegare le predizioni**: il medico vede cosa il sistema si aspettava vs cosa è successo

**Nota tecnica**: Il modello IsolationForest non fa forecasting puro. Ma possiamo
usare la baseline personale come "predizione di normalità" e confrontarla con i
dati reali successivi.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Prediction vs Actual | Storico decisioni + windows | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | **ALTA** |

---

### 2.3 Feature Importance Clinica

**Dati esistenti**: Modelli IsolationForest già addestrati con 22 feature

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Modello IsolationForest già addestrato
        ↓
Calcolo feature importance:
  - Permutazione: shuffle una feature, misura cambio score
  - Z-score contribution: quanto ogni feature contribuisce allo score
        ↓
Ranking delle feature più influenti per ogni predizione
        ↓
Nella dashboard: "Questa anomalia è causata al 60% da HR alto, 25% da HRV basso"
        ↓
Il medico capisce il perché dell'allarme, non solo il risultato
```

**Utilità**: IsolationForest non ha un built-in `feature_importances_`, ma si può
calcolare la contribuzione di ogni feature allo score tramite permutazione.
Questo trasforma il modello da "black box" a sistema spiegabile.

**Complessità**: Richiede di salvare lo scaler e l'imputer nel modello (già fatto)
e di calcolare la differenza di score quando una feature viene randomizzata.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Feature Importance | Modelli già addestrati | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | **ALTA** |

---

### 2.4 Clustering Giornaliero

**Dati esistenti**: Feature windows × 360/giorno (una ogni 4 minuti)

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Feature windows di un giorno intero
        ↓
Media delle feature per giornata
        ↓
K-Means o similarità per raggruppare giorni simili
        ↓
Cluster: "giorno attivo", "giorno tranquillo", "giorno anomalo", "giorno di malattia"
        ↓
Dashboard mostra: "Oggi è un giorno tipo martedì" oppure "Oggi è diverso dal solito"
        ↓
Il medico capisce il pattern settimanale del paziente
```

**Utilità**: Classificare i giorni in tipi aiuta a rilevare cambiamenti. Se un paziente
ha tipicamente "giorni attivi" ma gli ultimi 5 giorni sono tutti "tranquilli", c'è
un peggioramento.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Clustering Giornaliero | Storico feature windows | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **MEDIA** |

---

### 2.5 Anomaly Explanation Automatica

**Dati esistenti**: Decisioni AI con feature_values e feature_explanation già nel JSON

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Decision JSON con score anomalo + feature_values
        ↓
Confronto con baseline storica per ogni feature
        ↓
Identificazione delle feature che si discostano di più
        ↓
Generazione automatica di testo in linguaggio naturale
        ↓
"Anomalia rilevata: battito cardiaco 25% sopra la media, permanenza in camera
 doppia rispetto al solito, nessun movimento in cucina per 2 ore"
        ↓
Il medico legge una frase, non deve interpretare grafici
```

**Utilità**: Oggi il JSON decisionale contiene dati tecnici. Tradurli in linguaggio
clinico automaticamente è un passo avanti enorme per l'usabilità.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Anomaly Explanation | Decision JSON + baseline | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **ALTA** |

---

### 2.6 Retraining Automatico con Drift Detection

**Dati esistenti**: Modelli addestrati, storico score, baseline personale

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Score delle ultime N finestre
        ↓
Calcolo statistiche: media score, varianza, trend
        ↓
Se la media score cresce per > 7 giorni → possibile drift
        ↓
Se il paziente ha cambiato abitudini legittimamente → retraining
        ↓
Nuovo modello addestrato su baseline aggiornata
        ↓
Log: "Modello retrained il [data] con [N] finestre. Drift rilevato: [descrizione]"
        ↓
Il sistema si mantiene accurato nel tempo senza intervento manuale
```

**Utilità**: Senza drift detection, dopo mesi il modello diventa inutile. Il
retraining automatico garantisce che il sistema si adatti ai cambiamenti naturali
del paziente.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Drift Detection + Retraining | Modelli + storico score | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **ALTA** |

---

### 2.7 Confidence Score delle Predizioni

**Dati esistenti**: Feature windows con dati parziali (nan), modelli addestrati

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Feature window in ingresso
        ↓
Conteggio: quante feature su 22 sono presenti (non nan)
        ↓
Se < 50% feature presenti → confidenza bassa
        ↓
Se il modello è stato addestrato con pochi dati → confidenza bassa
        ↓
Confidence score 0-100%
        ↓
Dashboard: "Score 65 (confidenza 82%)" oppure "Score 65 (confidenza 31% - dati insufficienti)"
        ↓
Il medico sa quanto può fidarsi del risultato
```

**Utilità**: Una predizione basata su 3 feature su 22 è inaffidabile. Il confidence
score avverte il medico di non prendere decisioni su dati incompleti.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Confidence Score | Feature windows + modelli | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | **ALTA** |

---

## 3. Analytics Features

Analisi avanzate dello storico, correlazioni, trend e pattern.

### 3.1 Matrice di Correlazione tra Feature

**Dati esistenti**: 22 feature × migliaia di finestre storiche

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Storico feature windows
        ↓
Calcolo correlazione di Pearson/Spearman per ogni coppia di feature
        ↓
Matrice di correlazione 22×22
        ↓
Heatmap interattiva nella dashboard
        ↓
Il medico scopre: "Quando HRV scende, i cambi stanza diminuiscono"
        ↓
Comprensione delle interazioni tra domini clinici
```

**Utilità**: Le correlazioni tra feature sono ignorate dal clinico ma sono preziose.
Scoprire che HRV bassa è correlata a mobilità ridotta può aiutare a capire il meccanismo
del peggioramento.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Matrice Correlazione | Storico feature windows | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | **MEDIA** |

---

### 3.2 Analisi Settimanale / Confronto Periodi

**Dati esistenti**: Feature windows storiche con timestamp

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Feature windows della settimana corrente vs settimana precedente
        ↓
Calcolo media per feature per settimana
        ↓
Confronto: +15% passi, -8% sonno, +20% tempo in camera
        ↓
Dashboard: "Questa settimana rispetto alla scorsa: meno attività, più riposo"
        ↓
Il medico vede l'evoluzione senza dover confrontare grafici manualmente
```

**Utilità**: Il confronto automatico tra settimane è un'analisi che i medici fanno
manualmente. Automatizzarla risparmia tempo e riduce errori.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Confronto Settimanale | Storico feature windows | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | **MEDIA** |

---

### 3.3 Distribuzione Oraria delle Attività

**Dati esistenti**: Feature windows con timestamp × 360/giorno

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Feature windows × giorno × ora
        ↓
Raggruppamento per fascia oraria (6-9, 9-12, 12-15, 15-18, 18-21, 21-24)
        ↓
Distribuzione di: cucina, bagno, soggiorno, camera per ora
        ↓
Grafico a barre impilato: quando il paziente fa cosa
        ↓
Rileva: "Il paziente non va più in cucina la mattina" (possibile anedonia)
```

**Utilità**: I cambi nei pattern orari sono indicatori clinici importanti. Un paziente
che smette di andare in cucina la mattina potrebbe essere depresso o malato.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Distribuzione Oraria | BLE spatial + timestamp | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | **MEDIA** |

---

### 3.4 Analisi Energia NILM vs Attività

**Dati esistenti**: nilm_total_wh, steps, room_changes, kitchen_minutes

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Consumo energetico + attività rilevata
        ↓
Calcolo energia per unità di attività (Wh per passo, Wh per cambio stanza)
        ↓
Se energia alta ma attività bassa → possibile appliance lasciata accesa
        ↓
Se energia bassa ma attività alta → possible problema Shelly
        ↓
Metriche di efficienza energetica domestica
        ↓
Il sistema monitora anche la casa, non solo la persona
```

**Utilità**: Correlare consumo energetico e attività umana è utile per:
- Rilevare anomalie domestiche (TV accesa per ore senza movimento)
- Monitorare pattern di utilizzo degli elettrodomestici
- Identificare POSSIBILI problemi di sicurezza (fornelli dimenticati accesi)

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| NILM vs Attività | NILM + BLE + wearable | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | **BASSA** |

---

### 3.5 Identificazione Giorni "Anomali" Storicamente

**Dati esistenti**: Score AI storico per ogni finestra (360/giorno)

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Score giornaliero medio per ogni giorno storico
        ↓
Confronto con media mobile a 30 giorni
        ↓
Se score > media + 2σ → giorno anomalo
        ↓
Lista giorni anomali con reason
        ↓
Dashboard: "I giorni 15, 18 e 22 marzo sono stati anomali. Motivo: HR elevato"
        ↓
Il medico vede i pattern di anomaly nel tempo, non solo il valore corrente
```

**Utilità**: Attualmente il sistema mostra solo l'ultimo score. Vedere quali giorni
nelle ultime settimane sono stati anomali è un'analisi storica fondamentale.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Giorni Anomali Storici | Storico decisioni AI | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | **MEDIA** |

---

## 4. Dashboard / UX Features

Funzionalità che migliorano il modo in cui l'utente comprende il sistema.

### 4.1 Trend Overlay Multi-Feature

**Dati esistenti**: Storico feature windows

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Feature windows storiche
        ↓
Selezione 2-3 feature da sovrapporre (es. HR + SpO2 + steps)
        ↓
Grafico multi-asse con linee colorate per ogni feature
        ↓
Hover mostra valori di tutte le feature per quella finestra
        ↓
Il medico vede le relazioni temporali tra feature
```

**Utilità**: Oggni grafico mostra una feature alla volta. Sovrapporre HR e SpO2
perché il medico veda che "quando il battito sale, la saturazione scende" è
estremamente utile.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Trend Overlay | Storico feature windows | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | **MEDIA** |

---

### 4.2 Vista "Giornata Tipo" (Day Profile)

**Dati esistenti**: Feature windows per ogni ora del giorno × giorni storici

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Media delle feature per fascia oraria su ultimi 30 giorni
        ↓
Grafico con profilo "tipico" del paziente
        ↓
Sovrapposto: profilo di oggi (linea tratteggiata)
        ↓
Il medico vede subito: "Oggi il paziente è uscito dalla routine"
```

**Utilità**: È il confronto immediato tra "come è normalmente" e "come è oggi".
La prima cosa che un geriatra guarda è la variazione dalla routine.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Giornata Tipo | Storico feature windows | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **ALTA** |

---

### 4.3 Grafici Interattivi Migliorati

**Dati esistenti**: Grafici SVG già esistenti nella dashboard

**Miglioramenti**:
- **Zoom temporale**: cliccare su un'ora per vedere i dettagli 4-minuti
- **Selezione feature**: scegliere quali feature mostrare
- **Confronto**: sovrapporre giorni diversi
- **Annotazioni**: evidenziare quando c'è stato un allarme

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Grafici Migliorati | Storico feature windows | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | **MEDIA** |

---

### 4.4 Multi-Patient Summary Dashboard

**Dati esistenti**: Backend supporta già più pazienti

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Stato di tutti i pazienti assegnati al medico
        ↓
Ordinamento per severità anomalie
        ↓
Riquadri: nome, score, livello, ultimo aggiornamento, stato sensori
        ↓
Il medico vede in un colpo d'occhio chi ha bisogno di attenzione
```

**Utilità**: Oggi la dashboard mostra un paziente alla volta. Per un medico con
5-10 pazienti, una vista riepilogativa è essenziale.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Multi-Patient Summary | Backend multi-patient | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | **MEDIA** |

---

## 5. Alert / Monitoring Features

Nuovi meccanismi per segnalare situazioni importanti con i dati esistenti.

### 5.1 Alert Adattivi (Soglie Dinamiche)

**Dati esistenti**: Baseline personale, score storico

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Baseline personale (7 giorni di normalità)
        ↓
Calcolo soglie personalizzate per ogni feature
        ↓
Invece di "HR > 100 = anomalia", si usa "HR > media_paziente + 2σ = anomalia"
        ↓
Alert adattivi al singolo paziente
        ↓
Riduzione falsi positivi: il sistema conosce il "normale" di quel paziente
```

**Utilità**: Le soglie fisse (HR > 100, SpO2 < 94) generano falsi positivi per
pazienti con valori normali diversi. Un atleta ha HR a riposo di 50, non 70.
Le soglie adattive risolvono questo problema.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Alert Adattivi | Baseline personale | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **ALTA** |

---

### 5.2 Alert di Degradazione Progressiva

**Dati esistenti**: Score AI storico per ogni finestra

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Score degli ultimi 7 giorni
        ↓
Trend lineare dello score
        ↓
Se slope > soglia (score cresce di > 5 punti/giorno) → alert degradazione
        ↓
"Inverti 7 giorni: lo score sta crescendo progressivamente. Possibile peggioramento."
        ↓
Il medico è avvisato PRIMA che il score raggiunga la soglia di allarme
```

**Utilità**: Oggi il sistema alerta solo quando il score supera 65 o 80. Ma se il
score cresce da 30 a 55 in una settimana, non c'è alert. Il trend è informativo
quanto il valore assoluto.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Alert Degradazione | Storico score AI | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **ALTA** |

---

### 5.3 Alert di Assenza Insolita

**Dati esistenti**: room_changes, kitchen_minutes, bathroom_minutes, bedroom_minutes

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Pattern spaziali delle ultime 24 ore
        ↓
Confronto con profilo circadiano medio
        ↓
Se per > 4 ore non c'è stato movimento → alert
        ↓
Se per > 12 ore non c'è stato accesso in cucina/bagno → alert
        ↓
Alert: "Nessuna attività rilevata da 5 ore. Verificare stato del paziente."
        ↓
Il medico/caregiver è avvisato di possibili emergenze silenziose
```

**Utilità**: Un paziente caduto a terra non genera un alert di score alto (il modello
non lo sa). Ma l'assenza di movimento per ore è un segnale fortissimo.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Alert Assenza Insolita | BLE spatial data | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **ALTA** |

---

### 5.4 Monitoraggio Salute del Sistema Edge

**Dati esistenti**: last_cycle.json, qualità dati, stato MQTT

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Cicli edge degli ultimi 7 giorni
        ↓
Conteggio: cicli ok, cicli errore, cicli qualità warning
        ↓
Calcolo uptime percentuale
        ↓
Se uptime < 90% → alert tecnico
        ↓
Dashboard mostra: "Raspberry ha completato il 97% dei cicli ultima settimana"
        ↓
Il medico sa che i dati sono affidabili o meno
```

**Utilità**: Se il Raspberry crasha per metà giornata, i dati mancanti possono
essere interpretati erroneamente. Mostrare l'affidabilità del sistema è trasparenza.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Monitoraggio Edge | Stato cicli + qualità | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | **MEDIA** |

---

### 5.5 Alert Compositi Intelligenti

**Dati esistenti**: Score AI + dati spaziali + dati wearable + NILM

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Multiplo segnali在同一 finestra:
  - Score AI > 50 (attenzione)
  - Nessun movimento da 2 ore
  - HRV in calo
  - NilM spento (nessuna attività domestica)
        ↓
Peso di ogni segnale nella decisione
        ↓
Alert composto: "Multipli segnali di allarme: [elenco]"
        ↓
Segnale + contesto completo per ogni segnale
        ↓
Il medico ha il quadro completo, non solo un numero
```

**Utilità**: Un singolo segnale ambiguo diventa un alert chiaro quando è confermato
da altri segnali. L'alert composto è più affidabile di quello singolo.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Alert Compositi | Tutti i dati | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **MEDIA** |

---

## 6. Reporting Features

Funzionalità per riassumere e interpretare automaticamente i dati raccolti.

### 6.1 Report Settimanale Automatico

**Dati esistenti**: Tutto lo storico feature windows + decisioni AI + alert

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Dati della settimana (1008 finestre)
        ↓
Calcolo: media, min, max, varianza per feature principale
        ↓
Confronto con settimana precedente
        ↓
Giorni anomali identificati
        ↓
Test cognitivi completati (se disponibili)
        ↓
Report testuale strutturato:
  "Settimana 12-18 marzo: media HR 78bpm (+3% vs scorsa settimana),
   2 giorni con score > 50, 1 alert risolto, 1 test completato.
   Sonno medio: 6.2h (-0.3h). Mobilità: 4200 passi/giorno (-8%)."
        ↓
Il medico riceve un riassunto leggibile ogni lunedì
```

**Utilità**: Il medico non ha tempo di guardare 1008 finestre. Un report automatico
settimanale è esattamente ciò che serve per il monitoraggio remoto.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Report Settimanale | Tutto lo storico | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **ALTA** |

---

### 6.2 Report di Inizio Giornata (Morning Brief)

**Dati esistenti**: Dati notturni (sonno, HR notturno, movimenti notturni)

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Dati notturni (22h-8h)
        ↓
Calcolo: qualità sonno, number of risvegli, HR notturno medio, mobilità notturna
        ↓
Confronto con media storica
        ↓
Generazione morning brief:
  "Notte: 6.5h sonno (media 6.8h), 2 risvegli (media 1.3),
   HR notturno 62bpm (normale). Mobilità notturna: 3 spostamenti."
        ↓
Disponibile al medico appena si collega la mattina
        ↓
Il medico inizia la giornata con un riepilogo della notte
```

**Utilità**: La qualità del sonno notturno è il primo indicatore della giornata.
Un morning brief automatico dà al medico il contesto immediato.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Morning Brief | Dati notturni wearable + BLE | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | **MEDIA** |

---

### 6.3 Report di Conversazione Clinica

**Dati esistenti**: Decisioni AI + alert + test cognitivi + activities

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Storico completo del paziente
        ↓
Identificazione eventi significativi:
  - Alert critiche
  - Test cognitivi completati
  - Cambiamenti major nelle abitudini
        ↓
Report in linguaggio naturale strutturato per area:
  "1. COMPORTAMENTO: 3 alert arancioni risolti nella scorsa settimana.
   2. ATTIVITÀ: riduzione media del 15% dei passi.
   3. SONNO: 2 notti con meno di 5 ore.
   4. COGNIZIONE: test PHQ-2 completato, punteggio 3/6."
        ↓
Il medico ha un briefing pronto per la visita
```

**Utilità**: Prima di una visita, il medico deve ricostruire il quadro. Questo
report automatizza quella ricostruzione.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Report Conversazione | Tutto lo storico | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **MEDIA** |

---

### 6.4 Dashboard Esportabile (PDF/Report)

**Dati esistenti**: Tutto il backend + dati demographici paziente

**Input → Elaborazione → Output → Visualizzazione → Valore**

```
Tutti i dati del paziente per un periodo
        ↓
Generazione layout PDF strutturato:
  - Intestazione con dati anagrafici
  - Riepilogo score AI
  - Grafici principali
  - Tabella metriche
  - Elenco eventi / alert
  - Note mediche
        ↓
PDF scaricabile dalla dashboard
        ↓
Il medico può portare il report in visita o inviarlo a un collega
```

**Utilità**: Un report PDF è il formato standard per la documentazione clinica.
Esportare i dati del sistema in un formato condivisibile è essenziale.

| Feature | Dati disponibili | Utilità | Valore tecnico | Complessità | Priorità |
|---------|-----------------|---------|----------------|-------------|----------|
| Export PDF | Tutto il backend | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | **MEDIA** |

---

## Le 5 Feature "Wow"

Queste sono le 5 funzionalità che, secondo l'analisi, hanno il maggior impatto
per la demo/presentazione dell'esame, rispettando i vincoli del progetto.

---

### 🏆 WOW #1: Anomaly Explanation Automatica (Linguaggio Naturale)

**Perché è wow**: Trasforma un JSON tecnico in una frase clinica comprensibile.
Il medico non deve interpretare grafici: legge una spiegazione.

```
DATI: Decision JSON con score, feature_values, feature_explanation
        ↓
ELABORAZIONE: Confronto feature con baseline + generazione testo
        ↓
OUTPUT: "Anomalia rilevata: battito cardiaco 25% sopra la media, permanenza
         in camera doppia rispetto al solito, nessun movimento in cucina per 2 ore"
        ↓
VALORE: Il medico capisce in 5 secondi cosa sta succedendo
```

**Motivazione**:
- Utilizza dati già presenti nel JSON decisionale
- L'implementazione è semplice (template + logica condizionale)
- L'impatto sulla demo è enorme
- Dimostra comprensione del dominio clinico

---

### 🏆 WOW #2: Giornata Tipo vs Oggi (Day Profile Overlay)

**Perché è wow**: È il primo sguardo che un geriatra fa: "Come è oggi rispetto al solito?"

```
DATI: Storico feature windows × 30 giorni × ore
        ↓
ELABORAZIONE: Media per fascia oraria → profilo tipico
              + profilo odierno sovrapposto
        ↓
OUTPUT: Grafico con 2 linee: "tipico" vs "oggi"
        ↓
VALORE: In un colpo d'occhio si vede se il paziente sta fuori dalla routine
```

**Motivazione**:
- È il confronto più importante in geriatria
- Richiede solo elaborazione su dati esistenti
- Il grafico è visivamente impattante
- È clinicamente rilevante

---

### 🏆 WOW #3: Alert di Assenza Insolita

**Perché è wow**: Rileva emergenze che il modello AI NON può rilevare.
Un paziente caduto a terra non genera un "score alto" - genera ZERO movimento.

```
DATI: room_changes, kitchen/bathroom/bedroom_minutes per le ultime 4 ore
        ↓
ELABORAZIONE: Confronto con profilo circadiano → assenza anormale
        ↓
OUTPUT: Alert: "Nessuna attività rilevata da 4 ore. Verificare stato del paziente."
        ↓
VALORE: Potenzialmente salva la vita a qualcuno
```

**Motivazione**:
- Rileva una tipologia di emergenza che nessun altro componente del sistema cattura
- L'implementazione è semplice (soglia temporale su dati BLE)
- L'impatto clinico è altissimo
- È una feature che nessun semplice sistema di monitoraggio ha

---

### 🏆 WOW #4: Retraining Automatico con Drift Detection

**Perché è wow**: Il sistema si auto-migliora senza intervento umano.

```
DATI: Score AI storici + baseline personale
        ↓
ELABORAZIONE: Trend score + varianza → rilevamento drift
        ↓
OUTPUT: Se drift confermato → retraining automatico + log
        ↓
VALORE: Il sistema resta accurato per mesi/anni senza intervento manuale
```

**Motivazione**:
- È una delle feature più difficili da implementare in un sistema IoT reale
- Dimostra maturità tecnica
- È un requisito reale per sistemi di monitoraggio clinico
- La demo: mostrare "il modello si è retrained ieri perché il paziente ha cambiato abitudini"

---

### 🏆 WOW #5: Report Settimanale Automatico

**Perché è wow**: Trasforma dati grezzi in informazione clinica immediatamente utilizzabile.

```
DATI: 1008 finestre della settimana + decisioni + alert
        ↓
ELABORAZIONE: Statistiche, confronti, identificazione eventi
        ↓
OUTPUT: Report testuale strutturato:
  "Settimana 12-18 marzo: 2 giorni anomali, media HR 78bpm,
   sonno medio 6.2h, 1 test completato, 1 alert risolto"
        ↓
VALORE: Il medico ha un briefing pronto ogni lunedì senza fare nulla
```

**Motivazione**:
- È il formato in cui i medici lavorano già (report cartacei)
- Automatizzare questo processo è un risparmio di tempo enorme
- Utilizza solo dati già nel database
- È un output concreto e dimostrabile

---

## Analisi Finale

### 1. Quali funzionalità possiamo aggiungere senza modificare l'hardware?

**Risposta**: Abbondantemente. Il sistema raccoglie 22 feature ogni 4 minuti
(+ dati di contesto), ma ne sfrutta direttamente solo una parte per l'AI.
Il 70-80% del valore informativo è ancora "nello storico" non elaborato.

**Feature aggiungibili** (tutte con dati esistenti):

| # | Feature | Richiede nuovi dati? | Richiede nuovi sensori? |
|---|---------|---------------------|------------------------|
| 1 | Composite Wellness Index | No | No |
| 2 | Profilo Circadiano | No | No |
| 3 | Indice ADL | No | No |
| 4 | Analisi Sonno-Veglia | No | No |
| 5 | Trend Prediction | No | No |
| 6 | Feature Importance | No | No |
| 7 | Anomaly Explanation | No | No |
| 8 | Retraining Automatico | No | No |
| 9 | Confidence Score | No | No |
| 10 | Alert Adattivi | No | No |
| 11 | Alert Degradazione | No | No |
| 12 | Alert Assenza Insolita | No | No |
| 13 | Report Settimanale | No | No |
| 14 | Giornata Tipo | No | No |
| 15 | Matrice Correlazione | No | No |
| 16 | Clustering Giornaliero | No | No |

**Nessuna richiede nuovo hardware.** Tutte lavorano su dati già nel sistema.

---

### 2. Quali di queste sfruttano meglio i dati che già raccogliamo?

**Top 5 per sfruttamento dei dati esistenti:**

1. **Report Settimanale** — usa TUTTO: 1008 finestre + decisioni + alert
2. **Giornata Tipo** — trasforma lo storico in informazione immediata
3. **Matrice Correlazione** — trova relazioni nascoste tra le 22 feature
4. **Anomaly Explanation** — rende leggibili i dati già nel JSON
5. **Composite Wellness Index** — riassume 7+ feature in un numero

---

### 3. Quali sfruttano maggiormente la componente AI/ML?

**Top 5 per impatto AI:**

1. **Feature Importance** — rende il modello trasparente (explainable AI)
2. **Retraining Automatico** — mantiene il modello accurato nel tempo
3. **Confidence Score** — misura l'affidabilità della predizione
4. **Prediction vs Actual** — valuta la qualità del modello
5. **Trend Prediction** — estende il modello al futuro

---

### 4. Quali migliorano maggiormente l'esperienza dell'utente?

**Top 5 per usabilità:**

1. **Anomaly Explanation** — il medico legge una frase, non un JSON
2. **Giornata Tipo** — il confronto immediato è ciò che serve
3. **Report Settimanale** — risparmia ore di lavoro al medico
4. **Morning Brief** — inizia la giornata con il contesto
5. **Alert Adattivi** — meno falsi allarmi, più fiducia nel sistema

---

### 5. Quali sono le 3-5 feature con il miglior rapporto impatto/utilità/complessità?

| # | Feature | Impatto | Utilità | Complessità | Rapporto |
|---|---------|---------|---------|-------------|----------|
| 1 | **Confidence Score** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | **Migliore** |
| 2 | **Anomaly Explanation** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | **Eccellente** |
| 3 | **Alert Assenza Insolita** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | **Eccellente** |
| 4 | **Giornata Tipo** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **Molto buono** |
| 5 | **Alert Degradazione** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **Molto buono** |

---

### 6. Se dovessi portare il progetto a una versione finale completa, cosa aggiungerei realmente?

**Aggiungerei (per l'esame, in ordine):**

1. **Confidence Score** (1 giorno) — semplice, impatto enorme, dimostra trasparenza
2. **Anomaly Explanation** (2 giorni) — trasforma dati tecnici in informazione clinica
3. **Alert Assenza Insolita** (1 giorno) — feature unica che salva vite
4. **Giornata Tipo** (2 giorni) — il confronto più importante in geriatria
5. **Alert Degradazione** (1 giorno) — monitora il trend, non solo il valore
6. **Feature Importance** (2 giorni) — rende il modello spiegabile
7. **Report Settimanale** (2 giorni) — output concreto per il medico
8. **Retraining Automatico** (3 giorni) — dimostra maturità del sistema

**Totalmente: ~14 giorni di sviluppo**

**Lascerei perdere** (per ora):
- Clustering Giornaliero (troppo sperimentale)
- Matrice Correlazione (interessante ma non clinica)
- Export PDF (utile ma non critico per l'esame)
- NILM vs Attività (troppo euristica)

---

### Conclusione

Il sistema ha una **quantità enorme di dati non ancora sfruttati**. Con le 8 feature
proposte (14 giorni di lavoro), il progetto passa da "sistema di monitoraggio" a
"sistema di monitoraggio, analisi e previsione clinica" — un salto qualitativo
enorme, tutto con lo stesso hardware.

Il punto chiave è che **ogni nuovo dato non costa nulla**: è già raccolto. Il costo
è solo nell'elaborazione e nella visualizzazione. Questo è il vero valore dell'IoT
nel progetto: non raccogliere più dati, ma **far parlare i dati che già hai**.
