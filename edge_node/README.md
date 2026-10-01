# Triage IoT - Edge e gateway

Questo componente gira sul Raspberry Pi 5. Riceve i campioni BLE dall'app Android,
acquisisce i dati Google Health, costruisce finestre temporali, esegue i modelli AI e
pubblica i risultati verso il PC tramite MQTT TLS.

Il progetto completo comprende anche backend FastAPI, PostgreSQL, dashboard medico e
app Android per paziente e caregiver.

## Architettura

```text
Pixel Watch / Google Health ----+
                                +-> aggregazione 4 min -> AI -> coda MQTT -> PC
Beacon BLE -> app -> receiver ---+
```

Repository del progetto:

- [integrazione](https://github.com/emipasca12/ProgettoIoT)
- [Edge](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-edge-Pascadopoli-Spedicato)
- [Cloud](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-cloud-Pascadopoli-Spedicato)
- [Dashboard](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-dashboard-Pascadopoli-Spedicato)
- [Android](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-android-Pascadopoli-Spedicato)
- [Presentazione](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-presentation-Pascadopoli-Spedicato)

I link dell'organizzazione diventano disponibili dopo la creazione dei repository per
la consegna.

## Moduli

```text
edge_auth/       OAuth per sorgenti wearable
edge_ingest/     adapter, receiver BLE e aggregazione
edge_ai/         modelli, score, confidenza e baseline
edge_mqtt/       payload, TLS e coda locale
edge_runtime/    ciclo periodico completo
edge_stack/      supervisore receiver + runtime
edge_deploy/     preparazione e diagnostica Raspberry
deploy/          template systemd
tests/           test automatici Edge
```

## Configurazione

`config/edge.example.yml` e' versionato. Il setup genera invece
`config/edge.rpi.yml` e `config/edge-service.env`, che rimangono locali e sono ignorati
da Git.

Devono restare fuori dal repository:

- token e client OAuth;
- password MQTT;
- certificati locali;
- dati grezzi e processati;
- output clinici e modello personale.

La demo usa soltanto i beacon validati di Cucina e Bagno. Camera da letto non e'
monitorata.

## Installazione sul Raspberry

Nel repository integrato:

```bash
sudo apt update
sudo apt install -y git python3-venv python3-dev build-essential ca-certificates openssl
git clone https://github.com/emipasca12/ProgettoIoT.git ~/progetto-iot
cd ~/progetto-iot
bash Script/rpi/setup-rpi \
  --pc-host 192.168.1.100 \
  --ca-file "$HOME/progetto-iot/edge_node/config/certs/ca.crt"
```

Prima del setup trasferire localmente il certificato pubblico del broker e i file OAuth
Google Health. Il comando verifica configurazione e modelli, installa
`iot-edge.service` e lo abilita al boot.

## Esecuzione e diagnostica

```bash
sudo systemctl status iot-edge --no-pager
sudo journalctl -u iot-edge -f
bash Script/rpi/stato-rpi --network
```

Il receiver ascolta sulla porta `8000`; il runtime produce una finestra ogni quattro
minuti. In assenza del broker, la coda in `data/state/mqtt_queue` conserva i payload e
li ritenta quando la connessione torna disponibile.

Avvio manuale, solo per sviluppo e con il servizio fermo:

```bash
cd edge_node
../.venv/bin/python -m edge_stack.cli --config config/edge.rpi.yml --host 0.0.0.0 --port 8000
```

## Test

```bash
cd ~/progetto-iot
.venv/bin/python -m pytest edge_node/tests -q
```

## Baseline e modello personale

Dal repository integrato, sul Raspberry:

```bash
bash Script/rpi/modello-paziente status
```

Per archiviare i dati Edge precedenti e iniziare una baseline nuova, fermare prima il
servizio:

```bash
sudo systemctl stop iot-edge
bash Script/rpi/modello-paziente reset patient-001
sudo systemctl start iot-edge
```

Un modello provvisorio puo essere creato dopo almeno 50 finestre reali valide:

```bash
sudo systemctl stop iot-edge
bash Script/rpi/modello-paziente train-provisional patient-001
sudo systemctl start iot-edge
```

Il modello definitivo richiede almeno 1000 finestre valide e la baseline pianificata di
sette giorni. I modelli personali sono locali e non vengono pubblicati su Git.

## Limiti

Il modello e' un supporto al triage e non un dispositivo medico. L'associazione del
paziente e le autorizzazioni cliniche sono verificate dal backend; il receiver BLE e'
un endpoint tecnico previsto per la LAN controllata della demo.
