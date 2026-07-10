# Come Avviare Il Sistema IoT

Questo file spiega come avviare lo stack completo del progetto distinguendo
l'avvio su Windows dall'avvio su Raspberry Pi.

Lo stack completo avvia insieme:

```text
edge_receiver
-> resta in ascolto su http://0.0.0.0:8000
-> riceve i dati BLE inviati dall'app Android
-> salva i campioni in data/raw/ble_samples.csv

edge_runtime --loop
-> ogni 4 minuti legge le sorgenti abilitate
-> aggrega BLE, Google Health / Watch e altre sorgenti disponibili
-> scrive data/processed/latest_window.csv
-> esegue i modelli AI disponibili
-> salva outputs/patient-001-decision.json
-> salva outputs/last-cycle.json
```

In parole povere: il telefono Android invia la stanza rilevata tramite beacon, il
Watch fornisce i dati biometrici tramite Google Health quando abilitato, e il
Raspberry/PC unisce tutto ogni 4 minuti.

## Requisiti Prima Di Avviare

Devono esistere questi file/cartelle:

```text
edge_node/config/edge.yml
edge_node/models/generic_spatial.pkl
edge_node/models/generic_wearable.pkl
```

Se Google Health / Pixel Watch 2 e' abilitato in `edge.yml`, devono esistere anche:

```text
edge_node/config/google_health_client.json
edge_node/config/google_health_token.json
```

Nel file `edge_node/config/edge.yml` le sorgenti reali si abilitano cosi':

```yaml
google_health:
  enabled: true

ble:
  enabled: true
```

Durante i test solo BLE su Raspberry si puo' lasciare:

```yaml
google_health:
  enabled: false

ble:
  enabled: true
```

## Avvio Su Windows

La versione Windows dei launcher e' nella cartella:

```text
Script/avvio/
```

Da PowerShell, dalla root del progetto:

```powershell
.\Script\avvio\avviaSistema.cmd
```

Alternativa PowerShell esplicita:

```powershell
.\Script\avvio\avviaSistema.ps1
```

Se serve avviare senza launcher, il comando tecnico equivalente e':

```powershell
cd edge_node
..\.venv\Scripts\python.exe -m edge_stack.cli --config config\edge.yml
```

Per fermare il sistema:

```text
CTRL+C
```

## Avvio Su Raspberry Pi

La versione Raspberry/Linux del launcher e' nella cartella:

```text
Script/avvio/
```

Da terminale, dalla root del progetto:

```bash
./Script/avvio/avviaSistema
```

Se il file non fosse eseguibile:

```bash
chmod +x Script/avvio/avviaSistema
./Script/avvio/avviaSistema
```

Se serve avviare senza launcher, il comando tecnico equivalente e':

```bash
cd edge_node
../.venv/bin/python -m edge_stack.cli --config config/edge.yml
```

Per fermare il sistema:

```text
CTRL+C
```

## Avvio Durante La Baseline

Quando vogliamo raccogliere dati per costruire il modello personale del paziente,
avviamo lo stesso sistema in modalita' baseline.

Su Windows:

```powershell
.\Script\avvio\avviaSistema.cmd --append-baseline
```

Su Raspberry Pi:

```bash
./Script/avvio/avviaSistema --append-baseline
```

In questa modalita' ogni finestra valida viene aggiunta a:

```text
edge_node/data/processed/baseline.csv
```

La finestra viene salvata nella baseline solo se supera i controlli qualita. Se i
dati sono rotti, mancanti o tecnicamente non affidabili, il sistema non sporca la
baseline.

## Come Controllare Che Stia Funzionando

Dopo almeno un ciclo da 4 minuti, controllare `latest_window.csv`.

Su Windows:

```powershell
Get-Content edge_node\data\processed\latest_window.csv
```

Su Raspberry Pi:

```bash
cat edge_node/data/processed/latest_window.csv
```

In quel file ci aspettiamo campi BLE come:

```text
kitchen_minutes
bedroom_minutes
bathroom_minutes
room_changes
longest_single_room_minutes
```

e campi wearable, se Google Health e' abilitato, come:

```text
heart_rate_mean
heart_rate_std
steps
sedentary_minutes
wearable_present
```

Poi controllare la decisione AI.

Su Windows:

```powershell
Get-Content edge_node\outputs\patient-001-decision.json
Get-Content edge_node\outputs\last-cycle.json
```

Su Raspberry Pi:

```bash
cat edge_node/outputs/patient-001-decision.json
cat edge_node/outputs/last-cycle.json
```

## Cosa Significa Se Alcuni Campi Sono `nan`

`nan` significa che in quella finestra il dato non era disponibile.

Esempi:

- se i campi BLE sono `nan`, probabilmente l'app Android non sta inviando dati o il receiver non li sta ricevendo;
- se i campi wearable sono `nan`, probabilmente Google Health non ha ancora sincronizzato quel dato o non e' abilitato;
- se alcuni campi sono compilati e altri no, il sistema sta comunque lavorando con le sorgenti disponibili.

## Comando Tecnico Interno

Entrambi i launcher eseguono internamente:

```bash
python -m edge_stack.cli --config config/edge.yml
```

Normalmente non serve lanciarlo a mano. Lo teniamo documentato solo per debug.
