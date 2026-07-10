# Broker MQTT Mosquitto

Questa cartella contiene la configurazione iniziale del broker MQTT per il progetto.

Scelta D1:

```text
Mosquitto in Docker
```

Motivazione:

- e' semplice da testare in locale;
- puo' essere portato su VPS/Cloud senza cambiare tecnologia;
- supporta TLS, utenti/password, ACL, persistence, retained message e Last Will;
- e' adatto a Raspberry Pi e backend IoT.

## File

```text
cloud/docker-compose.yml
cloud/mqtt/mosquitto.conf
cloud/mqtt/aclfile
cloud/mqtt/passwd.example
cloud/mqtt/certs/
cloud/mqtt/data/
cloud/mqtt/log/
```

`passwd`, certificati reali, dati e log sono ignorati da Git.

## Utenti previsti

```text
edge_patient_001  -> Raspberry/Edge Node del paziente 001
backend           -> backend Cloud
mqtt_test         -> client manuale di test
```

## Generare password locali

Da root progetto:

```powershell
docker run --rm -it `
  -v ${PWD}\cloud\mqtt:/mosquitto/config `
  eclipse-mosquitto:2.0 `
  mosquitto_passwd -c /mosquitto/config/passwd edge_patient_001
```

Aggiungere gli altri utenti:

```powershell
docker run --rm -it `
  -v ${PWD}\cloud\mqtt:/mosquitto/config `
  eclipse-mosquitto:2.0 `
  mosquitto_passwd /mosquitto/config/passwd backend
```

```powershell
docker run --rm -it `
  -v ${PWD}\cloud\mqtt:/mosquitto/config `
  eclipse-mosquitto:2.0 `
  mosquitto_passwd /mosquitto/config/passwd mqtt_test
```

## Avviare broker locale

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud
docker compose up -d mqtt
```

Log:

```powershell
docker compose logs -f mqtt
```

Stop:

```powershell
docker compose down
```

## Test publish/subscribe

Terminale 1, subscribe:

```powershell
docker run --rm -it --network host eclipse-mosquitto:2.0 `
  mosquitto_sub -h localhost -p 1883 `
  -u mqtt_test -P PASSWORD_TEST `
  -t "iot/patients/patient-001/#" -v
```

Terminale 2, publish:

```powershell
docker run --rm -it --network host eclipse-mosquitto:2.0 `
  mosquitto_pub -h localhost -p 1883 `
  -u edge_patient_001 -P PASSWORD_EDGE `
  -t "iot/patients/patient-001/edge/status" `
  -m "{""schema_version"":1,""message_id"":""manual-test-001"",""event_type"":""edge_cycle_completed"",""patient_id"":""patient-001"",""edge_id"":""edge-rpi5-001"",""timestamp"":""2026-07-10T10:00:00Z"",""payload"":{""online"":true}}"
```

Nota Windows: `--network host` puo' non funzionare su Docker Desktop. In quel caso usare
il client installato localmente oppure un container nella stessa network del compose.

## TLS

Per sviluppo locale restano attivi:

```text
1883 -> MQTT locale con username/password
8883 -> MQTT protetto da TLS
9001 -> MQTT over secure WebSockets, cioe' WSS
```

I certificati locali di test si generano con Docker:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT

docker run --rm `
  -v ${PWD}\cloud\mqtt\certs:/certs `
  alpine/openssl req -x509 -newkey rsa:2048 -days 365 -nodes `
  -keyout /certs/server.key `
  -out /certs/server.crt `
  -subj "/CN=localhost" `
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

Copy-Item cloud\mqtt\certs\server.crt cloud\mqtt\certs\ca.crt -Force

docker run --rm `
  -v ${PWD}\cloud\mqtt\certs:/certs `
  alpine chmod 644 /certs/ca.crt /certs/server.crt /certs/server.key
```

Per Cloud/VPS bisogna sostituire questi certificati locali con certificati reali:

```text
cloud/mqtt/certs/ca.crt
cloud/mqtt/certs/server.crt
cloud/mqtt/certs/server.key
```

Il test locale verifica gia' `8883`. In produzione dovremo solo sostituire i certificati
self-signed con certificati validi per il dominio pubblico.

## WSS

Il listener `9001` espone MQTT over secure WebSockets. Serve solo se in futuro un client
browser o un tool web dovesse parlare direttamente MQTT. La dashboard principale dovrebbe
comunque parlare con il backend tramite WebSocket applicativo, non direttamente con MQTT.

Il test automatico fa una handshake WSS e controlla che Mosquitto risponda con:

```text
HTTP/1.1 101 Switching Protocols
```

## ACL

Le ACL impediscono a un Edge Node di pubblicare sui topic di altri pazienti.

Regola:

```text
edge_patient_001 -> solo patient-001
edge_patient_002 -> solo patient-002
backend          -> legge tutti i pazienti e pubblica comandi autorizzati
mqtt_test        -> solo test patient-001
```

Quando aggiungiamo un paziente, va aggiunto un utente Edge dedicato e una sezione ACL
separata. Il backend usa `+` nei topic per ricevere eventi da tutti i pazienti; la
dashboard medico non si collega direttamente a MQTT, ma legge dal backend solo i pazienti
assegnati a quel medico.

Esempio nuovo paziente:

```text
user edge_patient_002
topic write iot/patients/patient-002/edge/status
topic write iot/patients/patient-002/telemetry/window
topic write iot/patients/patient-002/telemetry/decision
topic write iot/patients/patient-002/alerts/critical
topic write iot/patients/patient-002/sensors/watch
topic write iot/patients/patient-002/sensors/ble
topic read iot/patients/patient-002/commands/#
```

## Test automatico locale

Dopo aver creato `passwd` e avviato il broker:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT
.\Script\test\test_mqtt_local.ps1
```

Il test verifica:

```text
publish Edge autorizzato su patient-001
publish Edge non consegnato su patient-999
comando backend ricevuto dall'Edge
Last Will pubblicato se l'Edge cade male
publish MQTT/TLS su 8883
handshake WSS su 9001
retained solo per stato corrente, non per telemetry
```

## Retained message policy

Per la prima versione:

```text
retained consentito solo per stato corrente / online-offline
retained non usato per finestre, decisioni, alert o dati sanitari
```

Motivo: decisioni e alert devono essere salvati dal backend con `message_id` e timestamp,
non recuperati da retained message potenzialmente vecchi.

Nota tecnica: con Mosquitto e ACL file semplice non esiste una regola per vietare retained
per singolo topic. Per questo la policy viene applicata dai publisher del progetto e
verificata dallo script locale:

```text
edge/status puo' essere retained
telemetry/window viene pubblicato senza retained
```

## Rinnovo certificati e revoca credenziali

Ambiente locale:

```text
porta 1883
username/password
nessun TLS
```

Ambiente Cloud/VPS:

```text
porta 8883
TLS obbligatorio
certificati validi
password robuste
ACL per paziente
```

Revoca credenziali Edge:

1. rimuovere o cambiare password dell'utente Edge in `passwd`;
2. riavviare Mosquitto;
3. aggiornare credenziali sul Raspberry autorizzato;
4. verificare che il vecchio client non possa piu' pubblicare.

Rinnovo certificati TLS:

1. generare o rinnovare `server.crt` e `server.key`;
2. sostituirli in `cloud/mqtt/certs/`;
3. riavviare Mosquitto;
4. testare connessione su `8883`;
5. documentare data scadenza e prossima rotazione.
