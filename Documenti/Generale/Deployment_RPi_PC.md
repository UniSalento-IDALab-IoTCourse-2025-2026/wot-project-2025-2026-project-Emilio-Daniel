# Deployment PC + Raspberry Pi

Revisione: 26 settembre 2026. Questa e' la procedura di riferimento per la
distribuzione su due macchine. Le guide precedenti con `avviaSistema -Completo`
restano utili solo per eseguire tutto sul PC: non vanno sommate a questa procedura.

## Distribuzione

| Dove | Cosa gira |
| --- | --- |
| PC Windows | Docker Desktop: PostgreSQL, Mosquitto, migrazioni, backend e worker MQTT; dashboard locale |
| Raspberry Pi 5 | `iot-edge.service`: receiver HTTP e runtime con Google Health, aggregazione, AI, baseline e coda MQTT |
| Android paziente | Scanner BLE, invio al Pi, login e attivita' verso il backend PC |
| Android caregiver | Login, messaggi e alert verso il backend PC |

La demo usa due beacon validi, Cucina e Bagno. Camera non e' monitorata.
Non occorre avviare Docker o la dashboard sul Pi, anche se il repository completo
viene scaricato li'. Il PC deve rimanere acceso, con Docker operativo e senza
sospensione, perche' backend e dashboard siano raggiungibili. Il Pi non puo'
accendere automaticamente il PC; se questo e' spento, continua localmente e prova
a consegnare via MQTT ai cicli successivi.

## Prima di iniziare

Scegliere due indirizzi LAN stabili, preferibilmente con prenotazione DHCP sul
router. Qui `IP_PC`, `IP_RPI` e `UTENTE_RPI` sono segnaposto da sostituire.
Non usare `0.0.0.0` o `localhost` come destinazione sul telefono.

La configurazione guidata riguarda `patient-001`. Altri pazienti richiedono anche
account, associazioni e ACL MQTT dedicate; non si cambia solo il nome nel YAML.

Le modifiche devono essere prima committate e inviate al repository remoto dal
PC. `git pull` sul Pi non recupera modifiche ancora solo locali. I segreti non
devono entrare nel commit. Nessuno script qui esegue commit/push automaticamente.

## 1. Preparare il PC

Conservare le configurazioni esistenti che gia' funzionano. Non sovrascrivere
`.env`, password Mosquitto o volume PostgreSQL con gli example. Fare un backup
prima di cambiare l'infrastruttura. Fermare il vecchio Edge sul PC e le eventuali
istanze native di backend/worker: da ora ci deve essere un solo produttore per
`patient-001` e un solo worker con il client ID configurato.

Sono necessari Docker Desktop avviato, Node compatibile con Vite 7, Python
disponibile e Git for Windows con OpenSSL (o OpenSSL nel PATH).

I file locali richiesti sono:

- `cloud/.env`: password PostgreSQL e `MQTT_BACKEND_PASSWORD` del broker;
- `cloud/backend/.env`: chiave auth, utenti demo se usati, Firebase e altre impostazioni;
- `cloud/mqtt/passwd`: utenti MQTT gia' configurati, inclusi `backend` ed `edge_patient_001`;
- `cloud/firebase/service-account.json`, se Firebase e' abilitato;
- `Dashboard/.env` con gli URL reali seguenti.

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8080/api/v1
VITE_WS_BASE_URL=ws://127.0.0.1:8080/ws/v1
VITE_DATA_SOURCE=real
```

Il browser del medico in questa procedura gira sul PC stesso. La dashboard
ascolta solo su loopback; non e' esposta a Internet. Le origini CORS del backend
devono comprendere `http://127.0.0.1:5173`.

### Certificato MQTT per la LAN

Il certificato deve riconoscere l'IP/nome del PC usato dal Pi e il nome `mqtt`
usato internamente da Docker. Dalla radice del progetto:

```powershell
.\Script\avvio\preparaCertificatiLAN.ps1 -PcHost IP_PC
```

Il comando riusa certificati validi senza modificarli. Se trova file esistenti
incompatibili, si ferma. Solo dopo aver fermato broker e worker:

```powershell
cd cloud
docker compose stop backend-mqtt-worker mqtt
cd ..
.\Script\avvio\preparaCertificatiLAN.ps1 -PcHost IP_PC -Replace
```

La sostituzione crea una copia in `cloud/mqtt/cert-backups/`, ignorata da Git.
Il certificato autofirmato di demo dura 365 giorni e comprende PC, `mqtt`,
`localhost` e `127.0.0.1`. La chiave resta sul PC. A ogni sostituzione della CA
occorre ricopiare `ca.crt` sul Pi e riavviare i client. Non disabilitare TLS o la
verifica del nome host. L'utility non modifica utenti o password del broker.

### Firewall e avvio

Una volta sola, da PowerShell come amministratore, sulla rete domestica fidata
classificata come Privata:

```powershell
.\Script\avvio\abilitaFirewallLAN.ps1
```

La regola consente TCP 8080 e 8883 dalla sottorete locale, non apre PostgreSQL o
la dashboard e non disabilita il firewall. Non configurare port forwarding sul
router. Il receiver non e' autenticato: deve restare nella LAN controllata.

Dalla radice, in PowerShell normale:

```powershell
.\Script\avvio\avviaPC.ps1
```

Avvia i container, attende `/ready`, installa e compila la dashboard e avvia una
preview locale su **http://127.0.0.1:5173**. La preview serve la build per la demo,
non e' un hosting di produzione. Nessuna pipeline Edge parte sul PC.

Avvii successivi senza modifiche frontend: `avviaPC.ps1 -SkipBuild`. Dopo modifiche
alle variabili Vite o ai sorgenti non usare `-SkipBuild`.

```powershell
.\Script\avvio\avviaPC.ps1 -Stop
```

Ferma la dashboard avviata dallo script e i servizi Compose senza cancellare
volumi. Non tocca il Raspberry. La dashboard usa un file locale con PID e istante
di avvio per evitare di terminare un processo diverso con un PID riutilizzato.
I suoi log sono in `Dashboard/dist/preview.stdout.log` e `preview.stderr.log`.

## 2. Preparare il Raspberry

Usare Raspberry Pi OS a 64 bit con Python >= 3.11, SSH abilitato e un utente
ordinario. Non serve desktop o login grafico per il servizio. Collegare il Pi
alla stessa LAN e verificare l'ora con `timedatectl`.

Da SSH, una volta sola:

```bash
sudo apt update
sudo apt install -y git python3-venv python3-dev build-essential ca-certificates openssl
```

Clonare il repository in `~/progetto-iot`, oppure eseguire `git pull --ff-only`
se e' gia' presente. Non copiare `.venv` da Windows: il setup la crea per Linux.
I due modelli generici sono versionati nel repository; dataset personali,
credenziali, baseline e coda non lo sono.

```bash
cd ~/progetto-iot
git pull --ff-only
mkdir -p edge_node/config/certs
```

Se il repository non e' ancora clonato, prima usare `git clone URL_DEL_REPOSITORY
~/progetto-iot`, sostituendo l'URL reale. Per un repository privato configurare
anche l'accesso Git: e' distinto dall'accesso SSH al Pi.

## 3. Trasferire i file che Git non deve contenere

Dal PC, nella radice del progetto, con OpenSSH/scp:

```powershell
scp .\cloud\mqtt\certs\ca.crt UTENTE_RPI@IP_RPI:~/progetto-iot/edge_node/config/certs/ca.crt
scp .\edge_node\config\google_health_token.json UTENTE_RPI@IP_RPI:~/progetto-iot/edge_node/config/google_health_token.json
scp .\edge_node\config\google_health_client.json UTENTE_RPI@IP_RPI:~/progetto-iot/edge_node/config/google_health_client.json
```

Non trasferire `server.key`, `cloud/.env`, service account Firebase o database
sul Pi. Prima fermare il vecchio runtime sul PC, per non avere due processi
che rinnovano lo stesso token OAuth. I file devono essere gia' validi per
l'account del Watch; copiarli non rende valido un refresh token revocato.

Sul Pi:

```bash
cd ~/progetto-iot
chmod 600 edge_node/config/google_health_token.json edge_node/config/google_health_client.json
```

Per un nuovo inizio con copertura di due stanze si lascia partire la nuova
baseline. Non si copiano alla cieca campioni di test, decisioni, coda o modello
personale di un'altra installazione. Una migrazione dello storico Edge va
decisa esplicitamente; lo storico gia' nel database PC non viene cancellato.

## 4. Setup e installazione del servizio

Dal Pi, come utente ordinario:

```bash
cd ~/progetto-iot
bash Script/rpi/setup-rpi --pc-host IP_PC --ca-file "$HOME/progetto-iot/edge_node/config/certs/ca.crt"
```

Il setup crea/aggiorna la virtualenv, installa i requirements, verifica i modelli
e i file OAuth, genera `config/edge.rpi.yml` e il servizio con i percorsi reali.
Chiede la password MQTT di **edge_patient_001**, non quella del medico,
di Google o dell'utente `backend`. La salva nel file locale
`edge_node/config/edge-service.env` con permessi 600, senza stamparla.
Alle esecuzioni successive riusa il file; `--rotate-secret` consente di
sostituire la password esplicitamente.

Il file `edge.rpi.yml` e' distinto da `edge.yml`, cosi' le configurazioni PC e Pi
non si sovrascrivono. MQTT usa TLS sulla porta 8883 e la CA locale; receiver e
runtime usano lo stesso file. Google Health rimane abilitato nell'example:
senza le credenziali richieste il setup si ferma, non inventa dati sostitutivi.

Il setup si ferma se il servizio e' gia' attivo oppure la porta 8000 e' occupata
da un vecchio receiver: fermare l'istanza precedente, non avviarne una seconda.
Se un requisito manca, correggerlo e ripetere il comando. Il setup non abilita
il servizio prima che i controlli locali siano superati. Richiede `sudo` per
installare l'unita' e abilitarla. **Questa password amministrativa puo' essere
richiesta una volta durante il setup; al boot non viene chiesta alcuna password.**

Il servizio gira con l'utente ordinario, non root. `systemd` legge il file delle
credenziali, avvia i due processi e li arresta come gruppo. In caso di uscita
imprevista riparte dopo 15 secondi. Un guasto del PC o della rete non richiede
un nuovo login: il runtime ritenta ai cicli successivi e conserva la coda.
Un errore ripetuto dentro il ciclo puo' lasciare il processo vivo: la diagnostica
della freschezza serve proprio a rilevarlo.

L'unita' e' in `/etc/systemd/system/iot-edge.service`; il template versionato e'
`edge_node/deploy/iot-edge.service.in`. Non spostare la cartella del repository
dopo l'installazione senza reinstallare l'unita'. Nessun cron o secondo launcher
deve avviare la stessa pipeline.

## 5. Android e due beacon

Nelle impostazioni amministrative del Companion:

```text
Receiver:         http://IP_RPI:8000/ble/sample
Backend clinico:  http://IP_PC:8080/api/v1
```

Mantenere solo le associazioni gia' verificate Cucina e Bagno, rimuovendo la
riga Camera e quella provvisoria `blueup-01-014593=bedroom`, se inserita.
Non dedurre il Minor dal nome stampato del beacon. Il setup del Pi non modifica
le preferenze gia' salvate nel telefono. Non serve un nuovo APK per cambiare URL
e mappa. Concedere Bluetooth, localizzazione e notifiche richiesti dall'app e
verificare che il foreground service resti attivo.

La Camera e' non monitorata: uno zero in `bedroom_minutes` non prova l'assenza
della persona. L'algoritmo puo' ricevere uno dei due beacon anche da una stanza
vicina; questo setup non offre localizzazione affidabile dell'intera casa.

## 6. Stato e log via SSH

```bash
cd ~/progetto-iot
systemctl is-enabled iot-edge
systemctl status iot-edge --no-pager
bash Script/rpi/stato-rpi --network
sudo journalctl -u iot-edge -f
```

`stato-rpi` controlla servizio, file locali, aggiornamento dell'ultimo ciclo,
campioni BLE e coda. Con `--network` verifica receiver, backend e connessione
MQTT con TLS e CONNACK, usando un client diagnostico distinto: non pubblica
telemetria finta e non sottrae il client ID al runtime. `--models` aggiunge la
verifica di caricamento dei pickle. Il codice d'uscita 0 indica controlli
superati; 1 segnala almeno un problema/dato assente. Nei primissimi minuti e'
normale che non esistano ancora campioni e un ciclo completo.

La prova MQTT verifica connessione e autenticazione, non tutte le ACL di
pubblicazione ne' l'inserimento nel DB: il collaudo sottostante resta necessario.
La freschezza del CSV controlla l'aggiornamento del file, non una diagnosi di
qualita' di ogni campione. I segreti non vengono mostrati dalla diagnostica.

```bash
sudo journalctl -u iot-edge -b --no-pager -n 100
sudo systemctl restart iot-edge
sudo systemctl stop iot-edge
sudo systemctl start iot-edge
```

Lo stop manuale non causa restart immediato, ma il servizio abilitato torna al
boot. Per disattivarlo anche ai riavvii: `sudo systemctl disable --now iot-edge`.
Non eseguire `avviaSistema` manualmente mentre il servizio e' attivo.

Per SSH senza reinserire la password del Pi, configurare una chiave pubblica
OpenSSH nel suo `~/.ssh/authorized_keys`. Sul PC `ssh-keygen -t ed25519` permette
di crearla se non esiste gia': non sovrascrivere chiavi esistenti. Conservare la
chiave privata sul PC, preferibilmente protetta da passphrase e agente SSH.
Questo e' distinto dal servizio, che parte anche senza alcuna sessione SSH.
Non disabilitare le password di sistema e non concedere sudo globale senza
password per ottenere l'autostart.

## 7. Collaudo obbligatorio prima della demo

1. Avviare il PC e aprire la dashboard reale. Controllare `docker compose ps -a`
   da `cloud`; `backend-migrations` deve terminare con codice 0. Leggere i log
   del worker e verificare che sia connesso.
2. Sul Pi eseguire `stato-rpi --network`, poi muovere il telefono fra Cucina e
   Bagno. Attendere almeno un ciclo completo, indicativamente 4-5 minuti oltre
   il primo avvio. Devono aggiornarsi CSV, `last-cycle.json` e decisione.
3. Controllare in PostgreSQL che arrivino finestre e score nuovi, e nella
   dashboard che la data non sia quella dei vecchi dati demo. Un esempio di
   query di sola lettura dal PC, nella directory `cloud`:

   ```powershell
   docker compose exec -T postgres psql -U iot_backend -d progetto_iot -c "select patient_id, window_start, created_at from decisions order by created_at desc limit 5;"
   ```

4. Riavviare il Pi con `sudo reboot`. Non aprire un terminale per lanciare
   l'app: dopo il boot collegarsi via SSH solo per verificare. `is-enabled`
   deve restituire `enabled`, `is-active` deve restituire `active` e dopo un
   ciclo devono esserci nuovi dati.
5. Durante un test controllato fermare MQTT sul PC, attendere un ciclo e
   osservare la crescita della coda. Riavviarlo, attendere i cicli di recupero
   e verificare coda in diminuzione e righe nel DB. Il primo ciclo di ripresa
   non deve necessariamente svuotare una coda molto grande (flush massimo 50).
6. Inviare un task al paziente, completarlo e verificarlo sul PC. Provare
   separatamente il caregiver, idealmente con un altro telefono. Le limitazioni
   note delle registrazioni push al cambio account non sono risolte da systemd.

Questi test hardware/rete non sono stati eseguiti su un Raspberry collegato
durante la preparazione. Non considerare un semplice `active` equivalente a
una prova end-to-end riuscita. Il supervisore recupera i processi terminati,
non garantisce il recupero da qualunque blocco interno o esaurimento disco.

## 8. Aggiornamenti, metriche e manutenzione

Sul Pi, quando arrivano nuovi commit:

```bash
cd ~/progetto-iot
sudo systemctl stop iot-edge
git pull --ff-only
.venv/bin/python -m pip install -r edge_node/requirements.txt
sudo systemctl start iot-edge
bash Script/rpi/stato-rpi --network
```

Se cambia il template dell'unita', rieseguire `setup-rpi` mentre il servizio e'
fermo: riutilizza credenziali e configurazione. Non pulire `data/state` o la
coda per aggiornare. Se cambia IP_PC o CA, riconfigurare con il nuovo host/CA;
la sola modifica del DNS non aggiorna un certificato emesso per un altro IP.

Per esporre nella dashboard report di validazione prodotti sul Pi, copiare
solo i `*_metrics.json` in `cloud/model-metrics` sul PC. Compose monta ora
questa directory in sola lettura nel backend:

```powershell
New-Item -ItemType Directory -Force .\cloud\model-metrics
scp "UTENTE_RPI@IP_RPI:~/progetto-iot/edge_node/models/*_metrics.json" .\cloud\model-metrics\
```

La copia e' manuale e funziona solo se i report esistono; il training automatico
non garantisce da solo che ogni report di validazione sia stato prodotto.
L'AI continua a girare sul Pi, non nel backend. I JSON non contengono la chiave
del modello e non e' necessario spostare i pickle personali sul PC.

Monitorare spazio disco con `df -h`, orologio con `timedatectl`, riavvii con
`systemctl show iot-edge -p NRestarts` e log tramite journald. Conservare backup
del DB PC e, separatamente, di configurazioni/stato/modello personale del Pi.
Il backup dei CSV non sostituisce quello di PostgreSQL.

## Verifiche eseguite qui e riferimenti

Il 26 settembre 2026 sono passati 138 test Edge, inclusi 30 test in
`edge_node/tests/test_edge_deploy.py` per
configurazione, file dei segreti, template, stop/restart del supervisore,
diagnostica e certificati OpenSSL temporanei. I test non installano servizi
di sistema e non modificano le credenziali reali. Su Windows vengono inoltre
controllate sintassi PowerShell e Bash e validata la configurazione Compose;
il boot reale resta da collaudare sul Pi. Non sono stati riavviati i servizi
reali o sostituiti i certificati locali durante questi test.

Riferimenti primari per le scelte del servizio:
[systemd.service](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml),
[systemd.exec](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml).
`Restart=on-failure` governa i guasti del processo e `EnvironmentFile` separa la
configurazione privata dal template versionato.
