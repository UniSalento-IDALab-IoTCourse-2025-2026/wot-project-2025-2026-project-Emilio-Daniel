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

### Manuale / Emulatore

Serve per testare subito senza beacon fisici.

Si inseriscono:

- stanza;
- RSSI;
- beacon id;
- URL del receiver Raspberry.

Poi si preme `Invia campione manuale`.

Sull'emulatore Android, l'URL verso il receiver sul PC e':

```text
http://10.0.2.2:8000/ble/sample
```

Su telefono fisico, l'URL sara':

```text
http://IP_DEL_RASPBERRY:8000/ble/sample
```

### BLE reale

Serve quando avremo beacon fisici e un telefono Android reale.

La mappa beacon va scritta cosi':

```text
AA:BB:CC:DD:EE:01=kitchen
AA:BB:CC:DD:EE:02=bedroom
AA:BB:CC:DD:EE:03=bathroom
AA:BB:CC:DD:EE:04=living_room
```

L'app scansiona i beacon, sceglie quello con RSSI piu' alto e invia la stanza al receiver.

La scansione reale non resta dentro la schermata principale: viene avviata come
Foreground Service Android. In pratica:

1. si salva la configurazione;
2. si preme `Avvia monitoraggio BLE`;
3. Android mostra una notifica persistente `IoT Edge Companion attivo`;
4. il servizio continua a fare cicli di scansione anche con app in background;
5. per fermarlo si preme `Ferma monitoraggio BLE`.

Questo e' il comportamento corretto per il progetto reale, perche' il telefono deve
restare vicino/addosso al paziente e inviare campioni senza tenere sempre aperta la
schermata dell'app.

Nota pratica: su telefono reale potrebbe essere necessario disattivare le ottimizzazioni
batteria per questa app, altrimenti Android puo' limitarla dopo molto tempo.

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
3. Selezionare la cartella `companion_app`.
4. Attendere il sync Gradle.
5. Avviare un emulatore oppure collegare un telefono Android.
6. Premere `Run`.

Se Android Studio propone di aggiornare Android Gradle Plugin o Gradle, si puo' accettare.

## Come creare un APK installabile

Da Android Studio:

1. `Build -> Build Bundle(s) / APK(s) -> Build APK(s)`.
2. Al termine cliccare `locate`.
3. Installare l'APK sul telefono Android.

Per una versione firmata:

1. `Build -> Generate Signed Bundle / APK`.
2. Scegliere `APK`.
3. Creare un nuovo keystore.
4. Selezionare build type `release`.
5. Generare l'APK firmato.

## Test end-to-end senza beacon

1. Avviare il receiver:

```bash
cd ../edge_node
python -m edge_receiver.cli --config config/edge.example.yml --host 0.0.0.0 --port 8000
```

2. Avviare l'app in emulatore.
3. Usare URL:

```text
http://10.0.2.2:8000/ble/sample
```

4. Premere `Invia campione manuale`.
5. Controllare:

```text
data/raw/ble_samples.csv
```

6. Generare le feature:

```bash
cd ../edge_node
python -m edge_ingest.cli --config config/edge.example.yml
```

## Quando avremo i beacon reali

Useremo questa procedura:

1. configurare un beacon per stanza;
2. annotare MAC address/UUID, nome e stanza associata;
3. inserire nell'app la mappa:

```text
AA:BB:CC:DD:EE:01=kitchen
AA:BB:CC:DD:EE:02=bedroom
AA:BB:CC:DD:EE:03=bathroom
AA:BB:CC:DD:EE:04=living_room
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
7. testare cucina, camera, bagno e soggiorno;
8. controllare `data/raw/ble_samples.csv`;
9. calibrare posizione beacon, RSSI e filtro anti-rimbalzo;
10. iniziare raccolta baseline quando la stima stanza e' stabile.

## Foreground Service BLE

Il servizio in background si trova in:

```text
app/src/main/java/it/unisalento/iotedgecompanion/BleMonitoringService.java
```

Fa cicli periodici:

```text
5 secondi di scansione BLE
10 secondi di pausa
invio del beacon/stanza con RSSI piu' forte
```

I permessi Android usati sono:

- Bluetooth scan/connect;
- localizzazione, necessaria per la scansione BLE;
- notifiche, necessarie per mostrare la notifica persistente;
- foreground service, necessario per lavorare in background.

