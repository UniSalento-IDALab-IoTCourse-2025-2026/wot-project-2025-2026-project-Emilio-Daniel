# Collaudo ufficiale Triage IoT

Questa checklist verifica la versione distribuita usata all'esame: backend e dashboard
sul PC, acquisizione e AI sul Raspberry Pi, app sul telefono Android.

## Prerequisiti

- PC, Raspberry e telefono sulla stessa LAN;
- Docker Desktop attivo;
- file `.env`, password MQTT, certificati, OAuth e Firebase presenti solo localmente;
- due beacon validati: Cucina e Bagno;
- nessuna seconda pipeline Edge avviata sul PC;
- orario di PC, Pi e telefono sincronizzato.

## 1. Test automatici

### Edge

Dalla radice del repository:

```powershell
.\.venv\Scripts\python.exe -m pytest edge_node\tests -q
```

### Backend

```powershell
cd cloud\backend
.\.venv\Scripts\python.exe -m pytest -q
```

I test includono anche la pulizia selettiva di un paziente:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_patient_reset.py -q
```

Se l'ambiente backend non esiste ancora:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Dashboard

```powershell
cd Dashboard
npm ci
npm test
npm run build
```

### Android

```powershell
cd "Applicazione IoT Companion\companion_Android_app"
.\gradlew.bat clean test assembleDebug
```

## 2. Avvio del sistema

Sul PC:

```powershell
.\Script\avvio\avviaPC.ps1
```

Verificare:

```text
Dashboard: http://127.0.0.1:5173
Backend:   http://127.0.0.1:8080/ready
OpenAPI:   http://127.0.0.1:8080/docs
```

Sul Raspberry, via SSH:

```bash
cd ~/progetto-iot
bash Script/rpi/stato-rpi --network
sudo systemctl status iot-edge --no-pager
```

Il controllo deve confermare servizio attivo, receiver locale raggiungibile, backend e
broker accessibili. Se fallisce:

```bash
sudo journalctl -u iot-edge -n 100 --no-pager
```

## 3. Flusso dati completo

1. Accedere all'app con l'account paziente associato a `patient-001`.
2. Verificare gli URL del receiver Raspberry e del backend PC.
3. Avviare il monitoraggio BLE.
4. Avvicinare il telefono al beacon Cucina e poi al beacon Bagno.
5. Attendere almeno un ciclo Edge completo, circa quattro o cinque minuti.
6. Aprire la dashboard e aggiornare il paziente.
7. Controllare che la finestra piu recente abbia un timestamp nuovo.
8. Controllare score AI, confidenza, fattori esplicativi e stato delle sorgenti.
9. Verificare che Camera da letto sia trattata come non monitorata, non come assenza.

Esito positivo: campioni BLE ricevuti, finestra generata, payload MQTT persistito e
dashboard aggiornata senza duplicati.

## 4. Attivita e questionari

1. Dal medico creare un'attivita per il paziente.
2. Verificare una sola notifica sul dispositivo paziente.
3. Aprire l'attivita e controllare gli eventi `seen` e `started`.
4. Completare le domande e inviare il risultato.
5. Controllare `completed`, durata e risultato nella dashboard.
6. Eliminare la notifica dall'app solo dopo completamento o scadenza.
7. Eliminare definitivamente l'attivita dal medico e verificare che non ricompaia dopo
   il refresh.

## 5. Paziente e caregiver

1. Inviare un messaggio personalizzato al paziente.
2. Verificare testo corretto e una sola notifica.
3. Accedere con il caregiver associato.
4. Inviare un messaggio caregiver dal medico.
5. Verificare che non compaia nell'account paziente.
6. Pubblicare un alert autorizzato e controllare la presa in carico caregiver.
7. Controllare che il caregiver non veda feature AI grezze o configurazioni tecniche.

Se lo stesso telefono viene usato per ruoli diversi, disconnettere il ruolo precedente
e verificare le registrazioni FCM: token rimasti associati a entrambi i profili possono
far ricevere notifiche di entrambi i ruoli sullo stesso dispositivo.

## 6. Alert e dashboard

Verificare dalla dashboard:

- soglie score: Normalita `0-40`, Attenzione `40-60`, Rischio `60-80`, Massima Allerta
  `80-100`;
- un solo record visuale per lo stesso alert;
- presa in carico, risoluzione e storico;
- cancellazione definitiva di alert risolti con conferma;
- grafici apribili, centrati, navigabili e con valore e finestra temporale selezionati;
- timeline, riepilogo 24 ore, routine ambientale e report;
- stato tecnico coerente con Raspberry, wearable, qualita dati e MQTT.

## 7. Prove di resilienza

### Backend temporaneamente assente

1. Fermare lo stack PC con `avviaPC.ps1 -Stop`.
2. Lasciare il Raspberry acceso per almeno un ciclo.
3. Verificare la presenza di payload nella coda MQTT locale.
4. Riavviare il PC.
5. Verificare lo svuotamento progressivo della coda e la comparsa dei dati nel backend.

### Telefono senza rete

1. Aprire e completare un'attivita con rete disabilitata.
2. Verificare che il risultato resti nella coda locale.
3. Riattivare la rete.
4. Controllare che il risultato venga inviato una sola volta.

### Riavvio Raspberry

```bash
sudo reboot
```

Dopo il ritorno via SSH:

```bash
systemctl is-active iot-edge
bash ~/progetto-iot/Script/rpi/stato-rpi --network
```

Il servizio deve essere partito senza login interattivo.

### Riavvio telefono

Riavviare Android e verificare che il monitoraggio riparta, che la notifica persistente
sia presente e che il receiver continui a ricevere campioni con schermo bloccato.

## 8. Controllo sicurezza Git

Prima di ogni push:

```powershell
git status --short
git diff --cached
```

Non devono comparire:

- `.env` reali;
- `passwd` Mosquitto o backup;
- `server.key` e certificati locali;
- token OAuth;
- service account Firebase o `google-services.json`;
- CSV raccolti, output paziente, database o modelli personali.

## 9. Checklist pre-esame

- [ ] Tutti i test automatici passano.
- [ ] I repository dei componenti e quello di presentazione esistono nell'organizzazione.
- [ ] Ogni repository contiene un README con architettura, link e componente descritto.
- [ ] La documentazione finale e' stata consegnata entro la scadenza.
- [ ] La GitHub Page e' pubblicata.
- [ ] Il PC usa un IP LAN stabile.
- [ ] Il Pi parte automaticamente e risponde via SSH.
- [ ] Una finestra recente arriva fino alla dashboard.
- [ ] Task, paziente e caregiver sono stati provati end-to-end.
- [ ] E' disponibile un piano B con dati gia presenti nel backend.

## Arresto dopo il collaudo

Sul PC:

```powershell
.\Script\avvio\avviaPC.ps1 -Stop
```

Il Raspberry puo essere lasciato attivo oppure fermato esplicitamente:

```bash
sudo systemctl stop iot-edge
```

Nessuno dei due comandi elimina i dati persistenti.
