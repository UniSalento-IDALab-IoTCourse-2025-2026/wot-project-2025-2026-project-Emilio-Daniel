# IoT Edge Companion Android

Questa app e' il client mobile del paziente. Mantiene la localizzazione indoor BLE,
riceve messaggi e attivita' dal team di cura e invia i risultati al backend.

Il receiver Python e il modello AI non sono in questa cartella: stanno in `../edge_node/`.

## Versione 0.3: esperienza quotidiana e andamento personale

La home paziente e' stata riprogettata come un cruscotto semplice da consultare. Dopo
il login mostra:

- stato sintetico del monitoraggio e stanza corrente;
- frequenza cardiaca media, SpO2, passi rilevati e sonno, solo quando acquisiti;
- andamento interattivo di frequenza cardiaca e SpO2 nelle ultime finestre Edge;
- messaggi del team di cura con stato nuovo/letto;
- attivita' aperte con tipologia, priorita', scadenza e azione chiara;
- stato delle connessioni e degli eventuali risultati in coda offline.

I grafici sono disegnati nativamente dall'app, senza una libreria esterna: toccando la
linea viene mostrata l'ora e il valore della rilevazione. I campioni mancanti restano
mancanti e non vengono convertiti in zero.

Lo storico arriva esclusivamente dall'endpoint autorizzato del paziente:

```text
GET /api/v1/telemetry/patients/{patient_id}/windows?limit=90
```

L'app visualizza al massimo le 30 finestre piu' recenti nei grafici e conserva 90
finestre in cache per il riepilogo. Le informazioni sono presentate come supporto al
monitoraggio e non come diagnosi.

La schermata delle attivita' e' ora un percorso guidato con numero di passaggi,
scadenza, domande in schede leggibili, nota facoltativa e conferma finale. Invio,
tracciamento `seen/started/completed` e coda offline restano invariati.

### Eliminazione controllata di notifiche e messaggi

L'app consente al paziente di pulire la propria vista senza perdere tracciabilita'
clinica:

- i messaggi liberi del team di cura possono essere eliminati subito;
- le notifiche collegate a una attivita' possono essere eliminate solo quando
  l'attivita' e' stata completata;
- se una attivita' e' ancora aperta, la notifica resta visibile e l'app indica che
  potra' essere rimossa dopo il completamento;
- lato backend lo stato diventa `dismissed`, quindi il record resta auditabile.

## Versione 0.2: app paziente completa

La schermata iniziale non espone piu' la configurazione tecnica. Presenta invece:

- stato del monitoraggio BLE in background;
- connessione del Raspberry e ultimo aggiornamento disponibile;
- messaggi inviati dal medico;
- task e test assegnati al paziente;
- risultati ancora salvati sul telefono in attesa di rete.

La configurazione di Raspberry, backend e beacon si trova nella schermata
`Impostazioni amministrative`, protetta per il prototipo da `admin` / `admin`.

### Associazione corretta tra account, paziente e telefono

Il `patient_id` non viene scritto a mano nell'app. Il flusso e':

```text
amministratore crea patient-001 nel backend
-> crea un account con ruolo patient
-> associa quell'account a patient-001
-> il paziente esegue il login sul telefono
-> GET /patients restituisce soltanto patient-001
-> l'app registra device_id + patient-001 nel backend
```

Se l'account non e' di tipo `patient`, non e' associato a nessun paziente o e'
associato in modo ambiguo a piu' pazienti, l'app rifiuta l'accesso. Cambiare il valore
nel traffico HTTP non permette di leggere o completare task altrui, perche' il backend
ricontrolla l'associazione presente nel database a ogni richiesta.

Il `device_id` viene generato una sola volta dall'app e non e' modificabile dal
paziente. Access token e refresh token sono cifrati con Android Keystore.

### Sincronizzazione e lavoro offline

Il Foreground Service continua a:

- inviare il BLE al Raspberry ogni 15 secondi;
- sincronizzare task e messaggi ogni 60 secondi;
- inviare stato app e batteria ogni 4 minuti;
- ritentare i risultati rimasti nella coda locale quando torna la rete;
- ripartire dopo il riavvio del telefono tramite `BootReceiver`.

Un risultato viene prima salvato nella coda locale e poi inviato. Vengono trasmessi
`patient_id`, `task_id`, `message_id`, `started_at`, `completed_at`, durata e
`device_id`. Il backend registra gli stati `seen`, `started` e `completed`.

### Firebase Cloud Messaging

L'integrazione FCM e' predisposta. Senza Firebase l'app resta funzionante grazie alla
sincronizzazione REST periodica. Per attivare le push reali:

1. completare il compito Cloud D10;
2. scaricare da Firebase `google-services.json`;
3. inserirlo localmente in `app/google-services.json`;
4. ricompilare l'app.

Il file e' ignorato da Git. Il token FCM viene registrato nel backend senza comparire
nei log e senza essere restituito dalle API.

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
Backend clinico URL
Device ID in sola lettura
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

Il progetto forza Gradle a usare il Java incluso in Android Studio:

```text
C:/Program Files/Android/Android Studio/jbr
```

Questo evita l'errore `IllegalArgumentException: 25.0.1`, causato quando il
terminale usa Java 25 invece del JBR compatibile con Android Gradle Plugin.

Da terminale Windows, il modo piu' semplice e':

```powershell
cd "Applicazione IoT Companion\companion_Android_app"
.\CreaAPK.ps1
```

Lo script produce:

```text
app/build/outputs/apk/debug/app-debug.apk
```

Per provare manualmente Gradle:

```powershell
.\gradlew.bat :app:assembleDebug
```

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
