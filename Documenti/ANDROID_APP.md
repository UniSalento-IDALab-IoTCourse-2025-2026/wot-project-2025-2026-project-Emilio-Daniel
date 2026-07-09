# Android App

L'app Android del progetto si trova in:

```text
companion_app/
```

Nome app:

```text
IoT Edge Companion
```

## Obiettivo

L'app serve a collegare la localizzazione BLE al Raspberry Pi.

Nota sui percorsi: il codice Raspberry/AI si trova in `edge_node/`. Quindi i comandi
Python sotto vanno eseguiti entrando prima in quella cartella.

Nel sistema reale:

```text
Beacon BLE fissi nelle stanze
        |
        v
Telefono Android come scanner mobile
        |
        v
Receiver locale sul Raspberry Pi
        |
        v
data/raw/ble_samples.csv
```

## Modalita manuale

Serve per testare subito senza beacon fisici e senza telefono Android reale.

L'app permette di inserire:

- `room`;
- `rssi`;
- `beacon_id`;
- `beacon_name`;
- `phone_id`;
- URL del receiver.

Poi invia un payload HTTP a:

```text
POST /ble/sample
```

## Modalita BLE reale

Serve quando avremo:

- telefono Android fisico;
- beacon BLE nelle stanze;
- Raspberry Pi nella stessa rete locale.

L'app scansiona i beacon, usa la mappa `beacon_id=room`, sceglie il beacon con RSSI
piu' forte e invia la stanza stimata al Raspberry.

La modalita BLE reale usa un Foreground Service Android. Quindi, dopo il comando
`Avvia monitoraggio BLE`, il telefono mantiene attivo il monitoraggio in background e
mostra una notifica persistente. Questo e' necessario per il nostro scenario reale,
perche' il telefono deve continuare a inviare campioni anche se l'utente spegne lo schermo
o passa ad altre app.

Il servizio esegue cicli periodici:

```text
scansione BLE per alcuni secondi
scelta del beacon/stanza con RSSI piu' forte
invio HTTP al receiver Raspberry
pausa breve
nuova scansione
```

Sul telefono reale potra' essere utile disattivare le ottimizzazioni batteria per questa
app, cosi' Android non limita il servizio dopo molto tempo.

## Payload HTTP

```json
{
  "timestamp": "2026-06-25T10:00:00Z",
  "room": "kitchen",
  "rssi": -61,
  "beacon_id": "AA:BB:CC:DD:EE:01",
  "beacon_name": "KitchenBeacon",
  "phone_id": "android-phone"
}
```

## Test con emulatore

1. Avviare il receiver sul PC:

```bash
cd edge_node
python -m edge_receiver.cli --config config/edge.example.yml --host 0.0.0.0 --port 8000
```

2. Aprire Android Studio.
3. Aprire la cartella `companion_app`.
4. Avviare un emulatore.
5. Nell'app usare:

```text
http://10.0.2.2:8000/ble/sample
```

6. Premere `Invia campione manuale`.
7. Controllare:

```text
data/raw/ble_samples.csv
```

8. Generare la finestra edge con il comando unico:

```bash
cd edge_node
python -m edge_runtime.cli --config config/edge.example.yml
```

9. Controllare il report qualita:

```text
edge_node/outputs/last-quality-report.json
```

Senza beacon reali e' normale vedere errori come `ble_raw_missing` o
`ble_no_samples_in_window`: significa che il sistema non userebbe quei dati per
addestrare la baseline.

## Test con telefono fisico

1. Avviare il receiver sul Raspberry:

```bash
cd edge_node
python -m edge_receiver.cli --config config/edge.yml --host 0.0.0.0 --port 8000
```

2. Trovare l'IP del Raspberry.
3. Nell'app usare:

```text
http://IP_DEL_RASPBERRY:8000/ble/sample
```

4. Configurare la mappa beacon:

```text
AA:BB:CC:DD:EE:01=kitchen
AA:BB:CC:DD:EE:02=bedroom
AA:BB:CC:DD:EE:03=bathroom
AA:BB:CC:DD:EE:04=living_room
```

5. Premere `Avvia monitoraggio BLE`.
6. Verificare che compaia la notifica persistente `IoT Edge Companion attivo`.
7. Controllare che i campioni arrivino in `data/raw/ble_samples.csv`.

## Procedura quando avremo i beacon reali

Quando avremo i beacon fisici, useremo questa checklist.

### 1. Configurare i beacon

Mettere un beacon per stanza:

- cucina;
- camera;
- bagno;
- soggiorno.

Per ogni beacon annotare:

- MAC address o UUID;
- nome beacon, se disponibile;
- stanza associata.

### 2. Inserire la mappa nell'app Android

Nell'app Android scrivere la mappa beacon-stanza:

```text
AA:BB:CC:DD:EE:01=kitchen
AA:BB:CC:DD:EE:02=bedroom
AA:BB:CC:DD:EE:03=bathroom
AA:BB:CC:DD:EE:04=living_room
```

### 3. Avviare il receiver sul Raspberry

```bash
cd edge_node
python -m edge_receiver.cli --config config/edge.yml --host 0.0.0.0 --port 8000
```

### 4. Configurare l'URL nell'app

Nell'app Android inserire:

```text
http://IP_DEL_RASPBERRY:8000/ble/sample
```

### 5. Avviare monitoraggio BLE reale

Il telefono Android:

1. vede i beacon;
2. legge RSSI;
3. sceglie il beacon con segnale piu' forte;
4. stima la stanza;
5. invia il campione al Raspberry.

Questo flusso avviene dentro il Foreground Service BLE, quindi puo' continuare anche
quando l'app non e' visibile in primo piano.

Payload previsto:

```json
{
  "room": "kitchen",
  "rssi": -61,
  "beacon_id": "AA:BB:CC:DD:EE:01"
}
```

### 6. Verificare il CSV sul Raspberry

```bash
cat data/raw/ble_samples.csv
```

### 7. Testare stanza per stanza

Fare un test controllato:

1. portare il telefono in cucina e verificare che venga scritto `kitchen`;
2. portare il telefono in camera e verificare `bedroom`;
3. portare il telefono in bagno e verificare `bathroom`;
4. portare il telefono in soggiorno e verificare `living_room`.

### 8. Calibrare

Se il sistema sbaglia stanza, verificare:

- posizione dei beacon;
- potenza TX dei beacon;
- soglie RSSI;
- logica di scelta del beacon piu' forte;
- eventuale filtro anti-rimbalzo tra stanze vicine.

### 9. Avviare raccolta baseline

Quando il rilevamento e' stabile:

Per i tempi del progetto useremo una baseline compatta da 5/6 giorni.

```bash
cd edge_node
python -m edge_baseline.cli --config config/edge.yml start --days 6
python -m edge_runtime.cli --config config/edge.yml --append-baseline
```

Durante i 6 giorni si controlla l'avanzamento con:

```bash
python -m edge_baseline.cli --config config/edge.yml status
```

Alla fine della baseline:

```bash
python -m edge_baseline.cli --config config/edge.yml finalize
python -m edge_baseline.cli --config config/edge.yml train
```

Il flusso finale sara':

```text
Beacon veri
    -> app Android BLE reale
    -> Raspberry receiver
    -> data/raw/ble_samples.csv
    -> edge_runtime
    -> data/processed/latest_window.csv
    -> outputs/last-quality-report.json
    -> outputs/patient-001-decision.json, dopo training modello
```

## Creare APK installabile

Da Android Studio:

1. `File -> Open`.
2. Selezionare `companion_app`.
3. Attendere il sync Gradle.
4. `Build -> Build Bundle(s) / APK(s) -> Build APK(s)`.
5. Cliccare `locate` quando Android Studio ha finito.

## Creare APK firmato

Da Android Studio:

1. `Build -> Generate Signed Bundle / APK`.
2. Scegliere `APK`.
3. Creare un nuovo keystore o selezionarne uno esistente.
4. Scegliere build type `release`.
5. Generare l'APK.

L'APK firmato e' quello da usare per una consegna piu' formale o per installazioni
ripetibili senza Android Studio.
