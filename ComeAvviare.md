# Come Avviare Il Sistema IoT

Questo file spiega come avviare il sistema completo con un comando semplice.

## Cosa Abbiamo Preparato

Abbiamo creato un launcher chiamato `avviaSistema`.

L'obiettivo e' evitare di dover scrivere ogni volta comandi lunghi come:

```powershell
cd edge_node
..\.venv\Scripts\python.exe -m edge_stack.cli --config config\edge.yml
```

Ora dalla root del progetto basta avviare:

```powershell
.\avviaSistema
```

Il launcher entra automaticamente nella cartella `edge_node/`, usa il Python corretto
e avvia lo stack completo.

## Cosa Parte Con `avviaSistema`

Il comando avvia due componenti in contemporanea.

```text
edge_receiver
-> resta in ascolto su http://0.0.0.0:8000
-> riceve i dati BLE inviati dall'app Android
-> salva i campioni in data/raw/ble_samples.csv

edge_runtime --loop
-> ogni 4 minuti legge Google Health / Google Watch 2
-> legge i campioni BLE gia' ricevuti
-> aggrega tutto in data/processed/latest_window.csv
-> esegue i modelli AI disponibili
-> salva la decisione in outputs/patient-001-decision.json
-> salva lo stato ciclo in outputs/last-cycle.json
```

In parole povere: il telefono Android manda la stanza rilevata tramite beacon, il
Google Watch 2 fornisce i dati biometrici tramite Google Health, e il Raspberry/PC
unisce tutto ogni 4 minuti.

## Requisiti Prima Di Avviare

Da PC o Raspberry devono esistere:

```text
edge_node/config/edge.yml
edge_node/config/google_health_client.json
edge_node/config/google_health_token.json
edge_node/models/generic_spatial.pkl
edge_node/models/generic_wearable.pkl
```

Nel file `edge_node/config/edge.yml` devono essere attive le due sorgenti reali:

```yaml
google_health:
  enabled: true
  data_delay_minutes: 0

ble:
  enabled: true
```

Con `data_delay_minutes: 0`, Google Watch 2 e BLE vengono letti sulla stessa finestra
corrente da 4 minuti. Se Google Health non ha ancora sincronizzato un valore, quel
campo puo' restare temporaneamente vuoto o `nan`, ma il sistema non ritarda l'analisi.

## Avvio Su Windows

Dalla root del progetto:

```powershell
.\avviaSistema
```

Se PowerShell non esegue lo script senza estensione:

```powershell
.\avviaSistema.cmd
```

Alternativa PowerShell esplicita:

```powershell
.\avviaSistema.ps1
```

Per fermare il sistema:

```text
CTRL+C
```

## Avvio Su Raspberry Pi

Dopo il clone del progetto sul Raspberry:

```bash
chmod +x avviaSistema
./avviaSistema
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
.\avviaSistema --append-baseline
```

Su Raspberry:

```bash
./avviaSistema --append-baseline
```

In questa modalita' ogni finestra valida viene aggiunta a:

```text
edge_node/data/processed/baseline.csv
```

La finestra viene salvata nella baseline solo se supera i controlli qualita. Se i
dati sono rotti, mancanti o tecnicamente non affidabili, il sistema non sporca la
baseline.

## Come Controllare Che Stia Funzionando

Dopo almeno un ciclo da 4 minuti, controllare:

```powershell
Get-Content edge_node\data\processed\latest_window.csv
```

In quel file ci aspettiamo campi BLE come:

```text
kitchen_minutes
bedroom_minutes
bathroom_minutes
room_changes
longest_single_room_minutes
```

e campi wearable come:

```text
heart_rate_mean
heart_rate_std
steps
sedentary_minutes
wearable_present
```

Poi controllare la decisione AI:

```powershell
Get-Content edge_node\outputs\patient-001-decision.json
```

E lo stato dell'ultimo ciclo:

```powershell
Get-Content edge_node\outputs\last-cycle.json
```

## Cosa Significa Se Alcuni Campi Sono `nan`

`nan` significa che in quella finestra il dato non era disponibile.

Esempi:

- se i campi BLE sono `nan`, probabilmente l'app Android non sta inviando dati o il receiver non li sta ricevendo;
- se i campi wearable sono `nan`, probabilmente Google Health non ha ancora sincronizzato quel dato;
- se alcuni campi sono compilati e altri no, il sistema sta comunque lavorando con le sorgenti disponibili.

## Comando Tecnico Interno

Il comando breve `avviaSistema` esegue internamente:

```bash
python -m edge_stack.cli --config config/edge.yml
```

Normalmente non serve lanciarlo a mano. Lo teniamo documentato solo per debug.
