# Test BLE reale con BlueBeacon e app Android

Questo file serve come checklist operativa per il test reale con:

- 3 beacon BlueBeacon 01;
- telefono Android con app `IoT Edge Companion`;
- PC o Raspberry Pi come receiver locale;
- pipeline edge gia' pronta con modelli generici.

Obiettivo del test:

```text
Beacon reali
-> app Android
-> receiver locale edge_receiver
-> data/raw/ble_samples.csv
-> edge_runtime
-> latest_window.csv
-> decisione AI JSON
```

## 1. Controllare la mappa beacon

Prima di avviare tutto, verificare che la mappa reale sia questa:

```text
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14592=kitchen
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14582=bedroom
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14599=bathroom
```

Significato:

```text
Beacon 1 -> cucina          -> kitchen
Beacon 2 -> stanza da letto -> bedroom
Beacon 3 -> bagno           -> bathroom
```

Controllare anche:

```text
BlueBeaconMap.md
Documenti/BEACON_SETUP.md
Applicazione IoT Companion/companion_Android_app/README.md
```

## 2. Pulizia prima del test

Da root progetto:

```powershell
cd "C:\Users\emili\OneDrive\Desktop\Secondo Semestre\IoT\Progetto IoT 2026"
```

Entrare nell'edge node:

```powershell
cd edge_node
```

Pulire solo i file di test BLE/runtime, se presenti:

```powershell
Remove-Item data\raw\ble_samples.csv -Force -ErrorAction SilentlyContinue
Remove-Item data\processed\latest_window.csv -Force -ErrorAction SilentlyContinue
Remove-Item outputs\patient-001-decision.json -Force -ErrorAction SilentlyContinue
Remove-Item outputs\last-cycle.json -Force -ErrorAction SilentlyContinue
Remove-Item outputs\last-quality-report.json -Force -ErrorAction SilentlyContinue
Remove-Item data\state\patient-001-debounce.json -Force -ErrorAction SilentlyContinue
```

Opzionale: eliminare i vecchi output creati solo per testare i modelli generici:

```powershell
Remove-Item outputs\test-generic-*.json -Force -ErrorAction SilentlyContinue
```

Non cancellare:

```text
data/processed/generic_spatial_dataset.csv
data/processed/generic_spatial_dataset_train.csv
data/processed/generic_wearable_dataset.csv
models/generic_spatial.pkl
models/generic_wearable.pkl
```

## 3. Avviare il receiver locale

Sempre da `edge_node/`:

```powershell
..\.venv\Scripts\python.exe -m edge_receiver.cli --config config\edge.example.yml --host 0.0.0.0 --port 8000
```

Il terminale deve restare aperto.

Output atteso:

```text
Uvicorn running on http://0.0.0.0:8000
```

Questo significa che il PC/Raspberry sta ascoltando le richieste HTTP dell'app Android.

## 4. Trovare l'IP del PC o Raspberry

Su Windows:

```powershell
ipconfig
```

Cercare l'IPv4 della rete Wi-Fi o Ethernet, ad esempio:

```text
192.168.5.227
```

Nell'app Android il receiver URL deve essere:

```text
http://192.168.5.227:8000/ble/sample
```

Se si usa emulatore Android Studio:

```text
http://10.0.2.2:8000/ble/sample
```

Pero' per il BLE reale serve telefono Android fisico, non emulatore.

## 5. Configurare l'app Android

Aprire l'app `IoT Edge Companion` sul telefono Android.

Inserire:

```text
Receiver URL:
http://IP_DEL_PC_O_RPI:8000/ble/sample

Phone ID:
android-phone
```

Per modificare la mappa beacon, usare le credenziali provvisorie:

```text
username: admin
password: admin
```

Inserire la mappa:

```text
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14592=kitchen
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14582=bedroom
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14599=bathroom
```

Salvare la configurazione.

## 6. Avviare il monitoraggio BLE

Nell'app Android:

```text
Avvia monitoraggio BLE
```

Controllare che Android mostri una notifica persistente del foreground service.

Concedere tutte le autorizzazioni richieste:

```text
Bluetooth
Posizione
Notifiche
Esecuzione in background, se richiesta
```

Nota: su Android moderno la scansione BLE richiede spesso anche i permessi di posizione.

## 7. Test fisico stanza per stanza

Fare il test con calma:

```text
1. Mettersi vicino al beacon cucina per 1-2 minuti.
2. Mettersi vicino al beacon camera per 1-2 minuti.
3. Mettersi vicino al beacon bagno per 1-2 minuti.
4. Tornare vicino alla cucina.
```

Durante il test osservare nell'app:

```text
beacon rilevato
RSSI
stanza stimata
stato invio al receiver
```

Se l'app segnala errore invio:

```text
- controllare IP;
- controllare che PC/RPi e telefono siano nella stessa rete;
- controllare che il receiver sia ancora acceso;
- controllare firewall Windows;
- controllare che l'URL finisca con /ble/sample.
```

## 8. Verificare che il receiver riceva dati

Nel terminale del receiver si dovrebbero vedere richieste HTTP `POST /ble/sample`.

In un secondo terminale, da `edge_node/`:

```powershell
Get-Content data\raw\ble_samples.csv
```

Output atteso:

```csv
timestamp,room,rssi,beacon_id,beacon_name,phone_id
...
```

Devono comparire stanze tipo:

```text
kitchen
bedroom
bathroom
```

Se il file non esiste:

```text
- l'app non sta inviando;
- l'URL e' sbagliato;
- il receiver non e' raggiungibile;
- il firewall blocca la porta 8000.
```

## 9. Creare la finestra edge da 4 minuti

Dopo almeno qualche minuto di campioni BLE:

```powershell
..\.venv\Scripts\python.exe -m edge_runtime.cli --config config\edge.example.yml
```

Output atteso:

```text
status: cycle_completed
generic_spatial_model_exists: true
generic_wearable_model_exists: true
inference: completed_generic_spatial_plus_generic_wearable
decision_output: outputs\patient-001-decision.json
```

Se `quality_status` e' ancora `error`, leggere:

```powershell
Get-Content outputs\last-quality-report.json
```

Possibili cause:

```text
- pochi campioni BLE nella finestra;
- timestamp fuori dalla finestra da 4 minuti;
- nessuna stanza riconosciuta;
- file ble_samples.csv vuoto.
```

## 10. Controllare latest_window.csv

```powershell
Get-Content data\processed\latest_window.csv
```

Controllare colonne BLE:

```text
room_changes
night_room_changes
bedroom_minutes
kitchen_minutes
bathroom_minutes
living_room_minutes
longest_single_room_minutes
```

Per il test con tre beacon devono valorizzarsi almeno:

```text
kitchen_minutes
bedroom_minutes
bathroom_minutes
longest_single_room_minutes
```

Le colonne Fitbit potranno restare `nan` finche' il collega non collega Google Watch 2.

## 11. Controllare decisione AI

```powershell
Get-Content outputs\patient-001-decision.json
```

Per ora la decisione puo' essere:

```text
green
yellow
red
technical
```

Durante i test brevi, `green` o `technical` sono normali.

Importante:

```text
Questo non e' ancora un test clinico.
E' un test tecnico end-to-end:
beacon -> app -> receiver -> CSV -> runtime -> AI.
```

## 12. Cosa documentare durante il test

Annotare:

```text
Data e ora del test
Telefono Android usato
IP del receiver
Beacon cucina: minor/RSSI medio
Beacon camera: minor/RSSI medio
Beacon bagno: minor/RSSI medio
Stanze riconosciute correttamente?
Invio HTTP stabile?
Campioni salvati in ble_samples.csv?
latest_window.csv corretto?
decision JSON creato?
Problemi incontrati
```

## 13. Problemi comuni

### L'app non trova beacon

Controllare:

```text
- Bluetooth acceso;
- posizione attiva;
- permessi concessi;
- beacon accesi;
- telefono vicino al beacon;
- app non ottimizzata/bloccata dal risparmio batteria.
```

Se i beacon spariscono solo quando lo schermo va in standby:

```text
1. Installare l'APK aggiornato.
2. Accettare la richiesta "non ottimizzare batteria" mostrata dall'app.
3. Aprire Impostazioni Android -> App -> IoT Edge Companion -> Batteria.
4. Impostare "Nessuna restrizione" o "Non ottimizzare".
5. Verificare che la notifica "IoT Edge Companion attivo" resti visibile.
6. Su Android 10/11 impostare la posizione su "Consenti sempre", se disponibile.
7. Su telefoni Xiaomi/Oppo/Realme/Huawei/Samsung controllare anche "avvio automatico"
   e "attivita in background".
```

La versione aggiornata dell'app usa anche:

```text
- scansione BLE continua, non piu' cicli stop/start;
- filtro iBeacon esplicito, piu' stabile in background;
- wakelock parziale;
- richiesta posizione in background su Android 10/11;
- richiesta esclusione da ottimizzazione batteria.
```

### L'app vede beacon ma non invia

Controllare:

```text
- URL corretto;
- telefono e PC/RPi nella stessa rete;
- receiver acceso;
- firewall;
- endpoint /ble/sample.
```

### Il receiver riceve ma latest_window resta vuoto

Controllare:

```text
- timestamp dei campioni;
- finestra runtime da 4 minuti;
- config BLE abilitata;
- path data/raw/ble_samples.csv corretto.
```

### La stanza e' sbagliata

Controllare:

```text
- mappa uuid-major-minor;
- RSSI troppo simili tra beacon;
- beacon troppo vicini;
- beacon dietro muri/spigoli;
- telefono troppo lontano dal beacon stanza;
- potenza TX dei beacon.
```

## 14. Pulizia dopo il test

Se il test e' solo tecnico e non vogliamo conservare i campioni:

```powershell
Remove-Item data\raw\ble_samples.csv -Force -ErrorAction SilentlyContinue
Remove-Item data\processed\latest_window.csv -Force -ErrorAction SilentlyContinue
Remove-Item outputs\patient-001-decision.json -Force -ErrorAction SilentlyContinue
Remove-Item outputs\last-cycle.json -Force -ErrorAction SilentlyContinue
Remove-Item outputs\last-quality-report.json -Force -ErrorAction SilentlyContinue
Remove-Item data\state\patient-001-debounce.json -Force -ErrorAction SilentlyContinue
```

Se invece il test e' riuscito bene, prima di pulire salvare almeno:

```text
data/raw/ble_samples.csv
data/processed/latest_window.csv
outputs/patient-001-decision.json
outputs/last-quality-report.json
outputs/last-cycle.json
```

## 15. Quando il test BLE e' considerato riuscito

Il test e' riuscito se:

```text
1. L'app Android rileva i 3 beacon reali.
2. Ogni beacon viene associato alla stanza corretta.
3. L'app invia campioni al receiver.
4. Il receiver salva data/raw/ble_samples.csv.
5. edge_runtime crea data/processed/latest_window.csv.
6. Le colonne dei minuti stanza sono valorizzate.
7. edge_runtime produce outputs/patient-001-decision.json.
8. Il runtime vede i due modelli generici:
   - models/generic_spatial.pkl
   - models/generic_wearable.pkl
```

Se questi punti funzionano, la parte BLE reale del progetto e' pronta per essere
portata su Raspberry Pi 5.

## 16. Comando unico BLE + Google Health

Quando vogliamo far partire insieme receiver Android BLE e runtime Google Health,
usiamo il comando breve dalla root del progetto:

```powershell
.\avviaSistema
```

Se PowerShell non lo esegue senza estensione:

```powershell
.\avviaSistema.cmd
```

Sul Raspberry Pi:

```bash
chmod +x avviaSistema
./avviaSistema
```

Questo comando avvia nello stesso terminale:

```text
edge_receiver
  -> riceve i campioni BLE dall'app Android
  -> scrive data/raw/ble_samples.csv

edge_runtime --loop
  -> ogni 4 minuti legge Google Health / Pixel Watch 2
  -> legge i campioni BLE gia' ricevuti
  -> crea data/processed/latest_window.csv
  -> crea outputs/patient-001-decision.json
```

Per fermare tutto:

```text
CTRL+C
```

Il file `config/edge.yml` deve avere entrambe le sorgenti abilitate:

```yaml
google_health:
  enabled: true
  data_delay_minutes: 0

ble:
  enabled: true
```

Con `google_health.data_delay_minutes: 0`, il runtime non guarda piu' finestre
passate: ogni 4 minuti aggrega la finestra corrente sia per Google Watch 2 sia per
BLE. In `latest_window.csv` ci aspettiamo quindi, nello stesso ciclo, campi
wearable e campi stanza. Se il cloud Google non ha ancora sincronizzato un valore,
quel singolo campo puo' restare vuoto/`nan`, ma il sistema non ritarda piu'
l'intera analisi.

Durante la baseline il comando diventa:

```powershell
.\avviaSistema --append-baseline
```
