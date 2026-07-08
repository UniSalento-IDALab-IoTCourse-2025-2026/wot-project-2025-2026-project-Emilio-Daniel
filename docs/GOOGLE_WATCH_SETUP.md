# Google Pixel Watch 2 / Google Health API Setup

Questa guida documenta tutta la procedura fatta per collegare Google Pixel Watch 2 al
progetto tramite Google Health API: creazione API, OAuth, refresh token, file locali,
configurazione e comandi di raccolta.

## Cosa stiamo raccogliendo

Il Pixel Watch 2 non viene letto come sensore BLE grezzo. Il flusso reale e':

```text
Google Pixel Watch 2
  -> telefono con account Google/Fitbit sincronizzato
  -> Google Health API cloud
  -> OAuth con consenso dell'utente
  -> token salvati su PC/Raspberry
  -> edge_node/edge_ingest/google_health_adapter.py
  -> data/processed/latest_window.csv
```

L'adapter prova a leggere tutte le feature wearable previste dallo schema del progetto:

```text
wearable_present
wearable_battery_pct
heart_rate_mean
heart_rate_std
resting_heart_rate
hrv_rmssd
spo2_mean
sleep_minutes
awake_minutes
steps
sedentary_minutes
```

Questo non significa che ogni campo sara' sempre valorizzato. Google Health restituisce
solo i dati disponibili per quell'account, per quel device, per gli scope concessi e per
la finestra temporale richiesta. Per esempio:

- `heart_rate_mean` e `heart_rate_std` arrivano se il watch ha sincronizzato battito recente;
- `steps` puo' restare vuoto se negli ultimi 4 minuti non ci sono passi o se l'endpoint non
  restituisce punti in quella finestra;
- `sleep_minutes`, `awake_minutes`, HRV e SpO2 sono spesso dati giornalieri/notturni;
- `wearable_battery_pct` arriva dai paired devices quando Google Health espone il device.

Nel test reale fatto sul PC sono arrivati, ad esempio:

```text
wearable_battery_pct = 96.0
heart_rate_mean = 64.9
spo2_mean = 95.0
sleep_minutes = 439.0
awake_minutes = 64.0
```

## Come funziona l'autenticazione

Google Health API usa OAuth 2.0.

Ci sono due livelli:

```text
OAuth client
  -> identifica la nostra applicazione/progetto Google Cloud

Token utente
  -> autorizza la nostra app a leggere i dati salute di uno specifico account Google
```

Il file client contiene le credenziali dell'app:

```text
edge_node/config/google_health_client.json
```

Il file token contiene l'autorizzazione dell'utente:

```text
edge_node/config/google_health_token.json
```

Il `refresh_token` e' il valore piu' importante: permette al Raspberry/PC di generare
nuovi `access_token` senza rifare login ogni volta. Gli access token scadono; il refresh
token serve proprio a rinnovarli.

Questi file sono ignorati da Git e non vanno mai committati.

## Domande importanti

### Devo rifare la creazione API ogni volta?

No, non per ogni avvio.

La creazione del progetto Google Cloud e dell'OAuth client si fa una volta per il progetto.
Poi puoi riusare lo stesso client OAuth.

### Se aggiungo un nuovo dispositivo con lo stesso account?

In genere no: se il nuovo watch e' collegato allo stesso account Google autorizzato e
sincronizza dati in Google Health/Fitbit, il token esistente continua a rappresentare
quell'account. Il codice legge i dati dell'account, non si lega manualmente al singolo
orologio.

### Se uso un account Google diverso?

Serve un nuovo consenso OAuth per quell'account.

Non devi per forza creare una nuova API/app Google Cloud, ma devi:

1. aggiungere l'email come test user se l'app e' ancora in testing;
2. rifare l'autorizzazione OAuth con quell'account;
3. ottenere un nuovo `refresh_token`;
4. sostituire o creare un nuovo `google_health_token.json`.

### Devo fare refresh manuale ogni volta?

No.

Il codice prova a rinfrescare automaticamente l'access token quando serve. Il comando
manuale:

```powershell
python -m edge_auth.cli google-health refresh
```

serve solo per test/debug, per verificare che client id, client secret e refresh token
siano corretti.

## 1. Preparare il Watch

1. Collegare Google Pixel Watch 2 al telefono.
2. Usare lo stesso account Google che verra' autorizzato su Google Health API.
3. Indossare il watch.
4. Aprire/sincronizzare l'app Fitbit/Google sul telefono.
5. Controllare che nell'app si vedano dati recenti, soprattutto frequenza cardiaca.

## 2. Creare progetto Google Health API

Aprire:

```text
https://developers.google.com/health/setup
```

Seguire il setup guidato:

1. creare o selezionare un progetto Google Cloud;
2. abilitare Google Health API;
3. creare un OAuth 2.0 Client ID;
4. scegliere il tipo richiesto dalla procedura Google, nel nostro caso Web Server;
5. configurare i redirect URI HTTPS.

Durante la procedura Google puo' rifiutare redirect `http://127.0.0.1` per client Web
Server. Per questo abbiamo usato redirect HTTPS.

Redirect URI usati:

```text
https://www.google.com
https://developers.google.com/oauthplayground
```

`https://developers.google.com/oauthplayground` e' fondamentale per usare OAuth Playground
e ottenere il refresh token.

## 3. Configurare test user e scope

Se l'app Google Cloud e' in modalita testing, aggiungere come test user l'email Google
collegata al Pixel Watch.

Nella schermata OAuth/scopes aggiungere gli scope read-only necessari:

```text
https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly
https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly
https://www.googleapis.com/auth/googlehealth.sleep.readonly
https://www.googleapis.com/auth/googlehealth.profile.readonly
https://www.googleapis.com/auth/googlehealth.settings.readonly
```

Questi scope coprono passi/attivita', battito, HRV, SpO2, sonno, profilo e impostazioni
supportate.

## 4. Ottenere refresh token con OAuth Playground

Aprire:

```text
https://developers.google.com/oauthplayground/
```

In alto a destra aprire le impostazioni e abilitare:

```text
Use your own OAuth credentials
```

Inserire:

```text
OAuth Client ID
OAuth Client secret
```

Poi incollare/selezionare gli scope:

```text
https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly
https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly
https://www.googleapis.com/auth/googlehealth.sleep.readonly
https://www.googleapis.com/auth/googlehealth.profile.readonly
https://www.googleapis.com/auth/googlehealth.settings.readonly
```

Premere:

```text
Authorize APIs
```

Fare login con l'account Google collegato al Pixel Watch 2 e dare il consenso.

Poi premere:

```text
Exchange authorization code for tokens
```

Il Playground restituisce:

```text
access_token
refresh_token
expires_in
scope
token_type
```

Salvare `access_token` e soprattutto `refresh_token` nei file locali del progetto.

## 5. Creare i file locali

Dentro:

```text
edge_node/config/
```

creare `google_health_client.json`:

```json
{
  "client_id": "CLIENT_ID",
  "client_secret": "CLIENT_SECRET",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

creare `google_health_token.json`:

```json
{
  "access_token": "ACCESS_TOKEN_DA_PLAYGROUND",
  "refresh_token": "REFRESH_TOKEN_DA_PLAYGROUND",
  "expires_in": 3599,
  "scope": "SCOPES_AUTORIZZATI",
  "token_type": "Bearer"
}
```

I file sono gia' ignorati in `.gitignore`:

```text
edge_node/config/google_health_token.json
edge_node/config/google_health_client.json
```

## 6. Installare dipendenze Python

Da `edge_node/`:

```powershell
python -m pip install -r requirements.txt
```

Questo risolve anche l'errore:

```text
ModuleNotFoundError: No module named 'yaml'
```

perche' installa `PyYAML`.

## 7. Verificare token e refresh

Da:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\edge_node
```

controllare lo stato:

```powershell
python -m edge_auth.cli google-health status
```

Provare il refresh manuale:

```powershell
python -m edge_auth.cli google-health refresh
```

Ricontrollare:

```powershell
python -m edge_auth.cli google-health status
```

Lo status deve indicare:

```text
token_exists: true
client_exists: true
has_access_token: true
has_refresh_token: true
```

Il refresh manuale non va fatto a ogni avvio: serve solo per test. Durante il runtime il
refresh viene gestito automaticamente quando l'access token scade o sta per scadere.

## 8. Configurare `edge.yml`

Creare il file reale partendo dall'esempio:

```powershell
Copy-Item config\edge.example.yml config\edge.yml
```

Per testare solo Google Watch, usare:

```yaml
fitbit:
  enabled: false

google_health:
  enabled: true
  token_file: config/google_health_token.json
  client_file: config/google_health_client.json
  api_base_url: https://health.googleapis.com
  data_delay_minutes: 12
  heart_rate_lookback_minutes: 30

ble:
  enabled: false

shelly:
  enabled: false
```

Quando il BLE sara' pronto, `ble.enabled` potra' tornare a `true`.

Nota importante: `data_delay_minutes` deve stare sotto `google_health`, non sotto
`window`. Il CSV finale continua a rappresentare la finestra corrente comune a tutte le
sorgenti; solo la chiamata Google Health usa internamente una finestra cloud piu'
vecchia, perche' il Watch non sincronizza in tempo reale come il receiver BLE.

## 9. Avviare raccolta dati

Con il watch indossato e sincronizzato:

```powershell
python -m edge_runtime.cli --config config\edge.yml
```

Output atteso:

```text
status: cycle_completed
quality_status: ok
decision_level: green/yellow/red/technical
```

File da controllare:

```text
data/processed/latest_window.csv
outputs/last-cycle.json
outputs/last-quality-report.json
outputs/patient-001-decision.json
```

Per vedere rapidamente il CSV:

```powershell
Import-Csv data\processed\latest_window.csv | ConvertTo-Json -Depth 4
```

## 10. Warning visti durante i test

Durante i primi test apparivano molti warning `scikit-learn`, ad esempio:

```text
InconsistentVersionWarning
Skipping features without any observed values
```

Il ciclo completava comunque correttamente. Abbiamo filtrato questi warning nel runtime
per rendere leggibile l'output. La causa e':

- modelli `.pkl` salvati con una versione diversa di `scikit-learn`;
- alcune colonne vuote nella finestra corrente, cosa normale quando BLE/Shelly o alcune
  metriche wearable non sono disponibili.

Piu' avanti conviene rigenerare i modelli con la stessa versione Python/scikit-learn che
useremo sul Raspberry Pi.

## 11. Comandi principali

Setup dipendenze:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\edge_node
python -m pip install -r requirements.txt
```

Controllo token:

```powershell
python -m edge_auth.cli google-health status
```

Refresh manuale di test:

```powershell
python -m edge_auth.cli google-health refresh
```

Ciclo runtime:

```powershell
python -m edge_runtime.cli --config config\edge.yml
```

Controllo ultima finestra:

```powershell
Import-Csv data\processed\latest_window.csv | ConvertTo-Json -Depth 4
```

## Riferimenti ufficiali

- Setup Google Health API: https://developers.google.com/health/setup
- OAuth Playground codelab: https://developers.google.com/health/codelabs/make-your-first-api-call-using-oauth2-playground
- OAuth Playground: https://developers.google.com/oauthplayground/
- Scope Google Health API: https://developers.google.com/health/scopes
- Data types Google Health API: https://developers.google.com/health/data-types
- Endpoint Google Health API: https://developers.google.com/health/endpoints
- Paired devices: https://developers.google.com/health/reference/rest/v4/users.pairedDevices
