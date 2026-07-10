# IoT Edge Companion iOS

Questa cartella contiene i sorgenti Swift/SwiftUI per creare su Mac l'app iPhone
equivalente alla companion app Android del progetto.

L'app serve a:

- configurare l'URL del receiver Raspberry;
- inviare un campione BLE manuale per testare la pipeline senza beacon;
- scansionare beacon BLE reali dall'iPhone;
- scegliere il beacon con RSSI piu' forte;
- inviare al Raspberry la stanza stimata.

## Perche' il progetto Xcode si crea sul Mac

Su Windows prepariamo i file sorgente, ma il progetto `.xcodeproj` conviene crearlo
direttamente su Mac. Xcode deve infatti configurare:

- Bundle Identifier;
- Team Apple;
- firma dell'app;
- provisioning per installazione su iPhone;
- capabilities iOS come Bluetooth background mode.

## File inclusi

```text
Applicazione IoT Companion/companion_iOS_app/
  README.md
  Info.plist
  Sources/
    IoTEdgeCompanionIOS/
      IoTEdgeCompanionIOSApp.swift
      ContentView.swift
      EdgeSettings.swift
      BeaconMapping.swift
      EdgeReceiverClient.swift
      BleMonitor.swift
```

## Creazione progetto su Mac

1. Copia la cartella `Applicazione IoT Companion/companion_iOS_app` sul Mac.
2. Apri Xcode.
3. Seleziona `File > New > Project`.
4. Scegli `iOS > App`.
5. Imposta:

```text
Product Name: IoTEdgeCompanionIOS
Team: il tuo Apple Account
Organization Identifier: it.unisalento
Bundle Identifier: it.unisalento.IoTEdgeCompanionIOS
Interface: SwiftUI
Language: Swift
```

6. Crea il progetto dove preferisci.
7. Nel navigatore Xcode elimina i file Swift creati automaticamente se hanno lo stesso
   nome dei nostri.
8. Trascina dentro il progetto i file Swift presenti in:

```text
Applicazione IoT Companion/companion_iOS_app/Sources/IoTEdgeCompanionIOS/
```

Quando Xcode chiede come aggiungerli, seleziona:

```text
Copy items if needed: true
Add to targets: IoTEdgeCompanionIOS
```

## Permessi iOS da configurare

Nel target Xcode apri `Info` e aggiungi queste chiavi, oppure usa il file
`Info.plist` incluso come riferimento:

```text
NSBluetoothAlwaysUsageDescription
NSBluetoothPeripheralUsageDescription
NSLocalNetworkUsageDescription
NSLocationWhenInUseUsageDescription
NSAppTransportSecurity
UIBackgroundModes -> bluetooth-central
```

Nel target Xcode apri anche `Signing & Capabilities` e aggiungi:

```text
Background Modes
```

Poi abilita:

```text
Uses Bluetooth LE accessories
```

## Installazione su iPhone

1. Collega l'iPhone al Mac con cavo USB.
2. Sblocca l'iPhone e premi `Trust This Computer` se richiesto.
3. In Xcode seleziona il tuo iPhone come destinazione di run.
4. Vai in `Signing & Capabilities`.
5. Seleziona il tuo Team Apple e abilita `Automatically manage signing`.
6. Premi `Run`.

Se Xcode segnala problemi di firma, di solito basta controllare:

- Apple Account aggiunto in `Xcode > Settings > Accounts`;
- Bundle Identifier unico;
- iPhone sbloccato e autorizzato;
- Team selezionato nel target.

## Test manuale senza beacon

Sul PC o Raspberry avvia il receiver:

```powershell
cd edge_node
python -m edge_receiver.cli --config config\edge.example.yml --host 0.0.0.0 --port 8000
```

Trova l'IP del PC/Raspberry nella stessa rete Wi-Fi dell'iPhone.

Su Windows:

```powershell
ipconfig
```

Nell'app iOS imposta:

```text
Receiver URL: http://IP_DEL_PC_O_RPI:8000/ble/sample
Phone ID: iphone-emili
```

Poi usa la sezione `Campione manuale` e premi `Invia manuale`.

Controlla che il Raspberry/PC abbia scritto:

```text
edge_node/data/raw/ble_samples.csv
```

## Test BLE reale

Il test BLE non funziona bene sul simulatore: serve un iPhone fisico.

Procedura:

1. Accendi i beacon BLE.
2. Apri l'app su iPhone.
3. Premi `Avvia monitoraggio BLE`.
4. Guarda la sezione `Beacon rilevati`.
5. Copia nella mappa il nome o l'identificativo rilevato associandolo alla stanza.

Esempio:

```text
BeaconCucina=kitchen
BeaconCamera=bedroom
BeaconBagno=bathroom
BeaconSoggiorno=living_room
```

Oppure, se il beacon non espone un nome chiaro, usa l'identificativo CoreBluetooth
mostrato dall'app:

```text
E7B2E5A1-1111-2222-3333-ABCDEABCDE1=kitchen
```

Nota importante: iOS non espone il MAC address BLE reale come fa Android. Per questo
la mappa iOS deve usare nome pubblicizzato o identificativo CoreBluetooth. Quando avremo
i beacon veri, se saranno iBeacon, potremo aggiungere una versione ancora piu' precisa
basata su UUID/major/minor tramite CoreLocation.

## Limiti iOS da ricordare

iOS gestisce il Bluetooth in background in modo piu' restrittivo rispetto ad Android.
La capability `bluetooth-central` permette al sistema di svegliare l'app per eventi BLE,
ma le scansioni non filtrate possono essere rallentate o sospese quando l'app resta a
lungo in background.

Per il progetto universitario va bene partire cosi':

```text
iPhone fisico
-> app aperta o in background controllato
-> beacon reali
-> receiver Raspberry
```

Poi, se i beacon scelti saranno iBeacon, conviene evolvere il modulo verso CoreLocation.
