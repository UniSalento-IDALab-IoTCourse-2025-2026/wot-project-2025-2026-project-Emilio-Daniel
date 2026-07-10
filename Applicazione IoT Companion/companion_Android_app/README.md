# IoT Edge Companion Android

Questa app e' il client mobile che useremo per la localizzazione indoor BLE.

Il receiver Python e il modello AI non sono in questa cartella: stanno in `../edge_node/`.

## Scopo

Nel progetto reale avremo:

```text
Beacon BLE fissi nelle stanze
        |
        v
Telefono Android come scanner mobile
        |
        v
Raspberry Pi receiver
        |
        v
data/raw/ble_samples.csv
```

L'app Android deve:

1. scansionare i beacon BLE vicini;
2. associare ogni beacon a una stanza;
3. scegliere la stanza con RSSI piu' forte;
4. inviare un campione HTTP al Raspberry.

## Modalita disponibili

### Configurazione protetta

La configurazione modificabile e' protetta da login amministratore.

I campi protetti sono:

```text
Receiver URL
Phone ID
Mappa beacon
```

Credenziali provvisorie:

```text
username: admin
password: admin
```

Per modificare gateway o mappa beacon:

1. premere `Modifica gateway` oppure `Sblocca modifica`;
2. inserire `admin` / `admin`;
3. modificare i campi necessari;
4. premere `Salva gateway` oppure `Salva mappa beacon`;
5. la sezione torna bloccata automaticamente.

Nella schermata normale l'app non mostra i campi come testo modificabile: mostra
riepiloghi leggibili e compatti, mentre i dettagli tecnici restano nel pannello admin.

La mappa attuale dei 3 BlueBeacon 01 e':

```text
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14592=kitchen
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14582=bedroom
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14599=bathroom
```

### BLE reale

Serve con i BlueBeacon fisici e un telefono Android reale.

La mappa beacon va scritta cosi':

```text
IDENTIFICATIVO_BEACON_1=kitchen
IDENTIFICATIVO_BEACON_2=bedroom
IDENTIFICATIVO_BEACON_3=bathroom
```

Per i BlueBeacon 01 conviene usare l'identificativo iBeacon nel formato:

```text
uuid-major-minor
```

Mappa reale attuale:

```text
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14592=kitchen
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14582=bedroom
acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14599=bathroom
```

L'app scansiona i beacon, sceglie quello con RSSI piu' alto e invia la stanza al receiver.

La scansione reale non resta dentro la schermata principale: viene avviata come
Foreground Service Android. In pratica:

1. quando l'app viene aperta prova ad avviare automaticamente il monitoraggio;
2. Android mostra una notifica persistente `IoT Edge Companion attivo`;
3. il servizio continua a fare cicli di scansione anche con app in background;
4. il pulsante `Avvia monitoraggio IoT` permette di riavviarlo manualmente;
5. il pulsante `Ferma monitoraggio IoT` richiede login `admin` / `admin`.

Questo e' il comportamento corretto per il progetto reale, perche' il telefono deve
restare vicino/addosso al paziente e inviare campioni senza tenere sempre aperta la
schermata dell'app.

Nota pratica: su telefono reale potrebbe essere necessario disattivare le ottimizzazioni
batteria per questa app, altrimenti Android puo' limitarla dopo molto tempo.

La versione attuale prova a risolvere automaticamente il problema:

- quando l'app viene aperta chiede di escludere `IoT Edge Companion` dal risparmio batteria;
- il Foreground Service usa un wakelock parziale, quindi mantiene attiva la CPU anche a schermo spento;
- la scansione BLE usa modalita `LOW_LATENCY`;
- la scansione resta continua e filtrata su iBeacon, evitando cicli stop/start che Android puo' bloccare in background;
- su Android 10/11 l'app guida anche verso la posizione in background, se necessaria.

Se il telefono continua a smettere di rilevare beacon in standby, controllare manualmente:

```text
Impostazioni Android
-> App
-> IoT Edge Companion
-> Batteria
-> Nessuna restrizione / Non ottimizzare
```

Su alcuni produttori Android puo' servire anche:

```text
Consenti attivita in background
Consenti avvio automatico
Disattiva risparmio energetico per questa app
```

## Payload inviato

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

## Come aprirla in Android Studio

1. Aprire Android Studio.
2. `File -> Open`.
3. Selezionare la cartella `Applicazione IoT Companion/companion_Android_app`.
4. Attendere il sync Gradle.
5. Collegare un telefono Android fisico.
6. Premere `Run`.

Se Android Studio propone di aggiornare Android Gradle Plugin o Gradle, si puo' accettare.

## Come creare un APK installabile

Da Android Studio:

1. `Build -> Build Bundle(s) / APK(s) -> Build APK(s)`.
2. Al termine cliccare `locate`.
3. Installare l'APK sul telefono Android.

Il file debug viene generato qui:

```text
Applicazione IoT Companion/companion_Android_app/app/build/outputs/apk/debug/app-debug.apk
```

Per una versione firmata:

1. `Build -> Generate Signed Bundle / APK`.
2. Scegliere `APK`.
3. Creare un nuovo keystore.
4. Selezionare build type `release`.
5. Generare l'APK firmato.

## Test end-to-end con beacon reali

1. Avviare il receiver:

```bash
cd ../edge_node
python -m edge_receiver.cli --config config/edge.example.yml --host 0.0.0.0 --port 8000
```

2. Installare/aprire l'app su telefono Android reale.
3. Usare URL del PC/Raspberry nella stessa rete Wi-Fi:

```text
http://IP_DEL_PC_O_RASPBERRY:8000/ble/sample
```

4. Se serve, modificare gateway o mappa beacon con `admin` / `admin`.
5. Verificare che la notifica persistente sia attiva.
6. Se non e' attiva, premere `Avvia monitoraggio IoT`.
7. Controllare:

```text
data/raw/ble_samples.csv
```

8. Generare le feature:

```bash
cd ../edge_node
python -m edge_runtime.cli --config config/edge.example.yml
```

9. Controllare il report qualita:

```text
../edge_node/outputs/last-quality-report.json
```

## Procedura con i beacon reali

Useremo questa procedura:

1. configurare un beacon per stanza;
2. annotare UUID, major, minor, nome e stanza associata;
3. inserire nell'app la mappa:

```text
CHIAVE_BEACON_CUCINA=kitchen
CHIAVE_BEACON_CAMERA=bedroom
CHIAVE_BEACON_BAGNO=bathroom
```

La chiave consigliata e':

```text
uuid-major-minor
```

4. avviare il receiver sul Raspberry:

```bash
cd ../edge_node
python -m edge_receiver.cli --config config/edge.yml --host 0.0.0.0 --port 8000
```

5. impostare nell'app:

```text
http://IP_DEL_RASPBERRY:8000/ble/sample
```

6. avviare monitoraggio BLE reale;
7. testare cucina, camera e bagno;
8. controllare `data/raw/ble_samples.csv`;
9. calibrare posizione beacon, RSSI e filtro anti-rimbalzo;
10. iniziare raccolta baseline quando la stima stanza e' stabile.

La baseline reale si avvia dal modulo edge:

Per i tempi del progetto useremo una baseline compatta da 5/6 giorni.

```bash
cd ../edge_node
python -m edge_baseline.cli --config config/edge.yml start --days 6
python -m edge_runtime.cli --config config/edge.yml --append-baseline
```

Lo stato si controlla con:

```bash
python -m edge_baseline.cli --config config/edge.yml status
```

## Foreground Service BLE

Il servizio in background si trova in:

```text
app/src/main/java/it/unisalento/iotedgecompanion/BleMonitoringService.java
```

Fa cicli periodici:

```text
scansione BLE continua filtrata su iBeacon
invio periodico ogni 15 secondi
invio del beacon/stanza con RSSI piu' forte
```

I permessi Android usati sono:

- Bluetooth scan/connect;
- localizzazione, necessaria per la scansione BLE;
- notifiche, necessarie per mostrare la notifica persistente;
- foreground service, necessario per lavorare in background;
- wakelock, necessario per ridurre blocchi in standby.
