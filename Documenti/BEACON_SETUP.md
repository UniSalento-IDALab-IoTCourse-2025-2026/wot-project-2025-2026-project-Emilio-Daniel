# Setup BlueBeacon 01

Questa guida descrive come configurare i 3 BlueBeacon 01 BlueUp per il progetto.

## Mappa fisica scelta

```text
Beacon 1 -> Cucina          -> kitchen
Beacon 2 -> Stanza da letto -> bedroom
Beacon 3 -> Bagno           -> bathroom
```

I nomi interni restano in inglese perche' coincidono con le feature del modello:

```text
kitchen_minutes
bedroom_minutes
bathroom_minutes
```

## Prima cosa da fare

Mettere un'etichetta fisica sui beacon:

```text
B1 Cucina
B2 Camera
B3 Bagno
```

Poi accenderli uno alla volta o tenerli molto distanti tra loro durante la prima
identificazione. Questo evita di confondere beacon con RSSI simile.

## App consigliata per leggere/configurare i beacon

Usare l'app ufficiale BlueUp:

```text
BlueBeacon Manager
```

Serve per vedere i BlueBeacon vicini e leggere i parametri principali. Per il nostro
progetto interessano soprattutto:

```text
Nome BLE
MAC address, se mostrato
iBeacon UUID
iBeacon Major
iBeacon Minor
RSSI
Battery, se disponibile
```

## Identificativo migliore per la nostra app Android

La nostra app Android ora supporta tre tipi di chiave nella mappa:

1. identificativo iBeacon:

```text
uuid-major-minor
```

2. MAC address BLE:

```text
AA:BB:CC:DD:EE:01
```

3. nome pubblicizzato:

```text
BlueBeacon-01-Cucina
```

La scelta migliore e' usare `uuid-major-minor`, perche' e' stabile e distingue bene
beacon diversi anche se hanno lo stesso nome.

Esempio:

```text
acfd065e-c3c0-11e3-9bbe-1a514932ac01-1-1=kitchen
acfd065e-c3c0-11e3-9bbe-1a514932ac01-1-2=bedroom
acfd065e-c3c0-11e3-9bbe-1a514932ac01-1-3=bathroom
```

I valori sopra sono solo esempio: dobbiamo sostituirli con quelli letti dai tuoi beacon.

## Tabella da compilare

| Beacon | Stanza fisica | Nome interno | UUID | Major | Minor | Chiave app Android |
| --- | --- | --- | --- | --- | --- | --- |
| B1 | Cucina | kitchen | da leggere | da leggere | da leggere | da compilare |
| B2 | Stanza da letto | bedroom | da leggere | da leggere | da leggere | da compilare |
| B3 | Bagno | bathroom | da leggere | da leggere | da leggere | da compilare |

## Procedura pratica

1. Aprire `BlueBeacon Manager` su Android.
2. Tenere vicino al telefono solo il beacon B1, oppure allontanare B2 e B3.
3. Annotare UUID, Major, Minor e nome del B1.
4. Ripetere per B2.
5. Ripetere per B3.
6. Aprire la nostra app Android `IoT Edge Companion`.
7. Inserire nella mappa:

```text
CHIAVE_B1=kitchen
CHIAVE_B2=bedroom
CHIAVE_B3=bathroom
```

8. Salvare configurazione.
9. Avviare il receiver sul PC/Raspberry.
10. Avviare monitoraggio BLE reale dall'app Android.
11. Spostarsi vicino a ogni beacon e verificare che arrivi la stanza corretta.

## Receiver da avviare durante il test

Da `edge_node`:

```bash
python -m edge_receiver.cli --config config/edge.example.yml --host 0.0.0.0 --port 8000
```

Sul telefono Android l'URL deve essere:

```text
http://IP_DEL_PC_O_RPI:8000/ble/sample
```

## File da controllare

Dopo il test, controllare:

```text
edge_node/data/raw/ble_samples.csv
```

Le righe devono contenere:

```text
room = kitchen oppure bedroom oppure bathroom
rssi = valore negativo, per esempio -55
beacon_id = identificativo iBeacon o MAC
phone_id = telefono Android
```

## Vedere se l'alert parte dai beacon

Dopo aver ricevuto campioni BLE e aver lanciato il runtime:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\edge_node
python -m edge_runtime.cli --config config\edge.yml
```

controllare la decisione finale:

```powershell
Get-Content outputs\patient-001-decision.json
```

Nel JSON la parte Beacon/BLE corrisponde al modello spaziale:

```text
evidence.fusion.models.generic_spatial
```

Per vedere singolarmente perche' i beacon hanno alzato o abbassato lo score:

```powershell
$d = Get-Content outputs\patient-001-decision.json | ConvertFrom-Json
$d.evidence.fusion.models.generic_spatial.feature_explanation | ConvertTo-Json -Depth 8
```

Le feature principali da guardare sono:

```text
room_changes
night_room_changes
bedroom_minutes
kitchen_minutes
bathroom_minutes
living_room_minutes
longest_single_room_minutes
```

Se l'alert nasce solo dai beacon, nel JSON potrai vedere:

```text
model_label = generic_spatial_anomaly_only
```

Se invece beacon e orologio confermano insieme l'anomalia, la fusione puo' produrre:

```text
model_label = multi_model_agreement_orange
model_label = multi_model_agreement_red
```

