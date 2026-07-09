# Real API Constraints

## Google Health / Fitbit biometrics

Il Google Pixel Watch 2 non va trattato come sorgente BLE grezza per i dati biometrici.
La strada robusta e' cloud-to-edge: autorizzazione OAuth, lettura Google Health/Fitbit,
normalizzazione sul Raspberry Pi.

Riferimenti ufficiali:

- Fitbit OAuth Authorization Code Grant Flow with PKCE:
  https://dev.fitbit.com/build/reference/web-api/developer-guide/authorization/
- Google Health API migration/specifications:
  https://developers.google.com/health/migration/api-specifications
- Fitbit Heart Rate Intraday:
  https://dev.fitbit.com/build/reference/web-api/intraday/get-heartrate-intraday-by-date-range/
- Fitbit Activity Intraday:
  https://dev.fitbit.com/build/reference/web-api/intraday/get-activity-intraday-by-date-range/

Per nuove credenziali usiamo Google Health API. Il flusso pratico usato nel progetto e':

```text
Google Cloud OAuth client
-> consenso account Google collegato al Pixel Watch
-> refresh_token salvato in locale
-> access_token rinnovato automaticamente dal runtime
-> chiamate Google Health dal Raspberry/PC
```

File locali Google Health:

```text
edge_node/config/google_health_client.json
edge_node/config/google_health_token.json
```

Comandi Google Health:

```bash
python -m edge_auth.cli google-health status
python -m edge_auth.cli google-health refresh
python -m edge_runtime.cli --config config/edge.yml --loop
```

Fitbit Web API resta supportata come compatibilita legacy. Richiede OAuth 2.0 per
accedere ai dati utente; il vecchio flusso locale preparato nel progetto salva access
token e refresh token in file ignorati da Git.

File locali previsti:

```text
edge_node/config/fitbit_client.json
edge_node/config/fitbit_token.json
```

Comandi:

```bash
python -m edge_auth.cli fitbit setup --client-id CLIENT_ID --client-secret CLIENT_SECRET
python -m edge_auth.cli fitbit status
python -m edge_auth.cli fitbit refresh
```

Nota temporale: Google indica Google Health API come nuova generazione/evoluzione della
Fitbit Web API. Il vecchio form Fitbit non accetta piu' nuove applicazioni, quindi per
nuove credenziali usiamo Google Health API e manteniamo l'adapter Fitbit solo come
compatibilita' con setup gia' esistenti.

## Dati disponibili per il modello

Google Health API espone data type utili per il progetto: heart rate, HRV, SpO2,
sleep, steps, sedentary periods e altri dati aggregabili nel contratto feature.
La disponibilita' effettiva dipende da device, consenso OAuth, qualita' misura e policy API.

Google Health non e' uno stream real-time come il receiver BLE. Il watch misura, il
telefono sincronizza e il cloud espone i dati quando sono disponibili. Per ridurre i buchi:

- `google_health.data_delay_minutes` legge dal cloud una finestra gia' consolidata;
- il delay e' applicato solo a Google Health, non alla finestra BLE;
- `google_health.heart_rate_lookback_minutes` recupera battiti recenti quando la finestra
  esatta da 4 minuti non contiene punti;
- se Google Health e' attivo, il battito e' valido e `steps` non arriva, il progetto usa
  `steps = 0.0` come segnale di assenza passi nella finestra.

Questa scelta evita di spostare indietro tutto il sistema: BLE, Shelly e output AI
restano allineati alla finestra corrente, mentre solo la chiamata cloud usa una finestra
interna piu' vecchia.

## BLE indoor positioning

Per la localizzazione indoor, non conviene assumere che il Pixel Watch 2 emetta advertising
BLE controllabile come un beacon. Il piano piu' solido e':

1. usare beacon fissi nelle stanze e un tag BLE dedicato indossato dal paziente; oppure
2. sviluppare e verificare una piccola app Wear OS se serve usare davvero lo smartwatch
   come broadcaster.

Il modulo AI non dipende da questa scelta: riceve solo vettori di permanenza gia' aggregati.
