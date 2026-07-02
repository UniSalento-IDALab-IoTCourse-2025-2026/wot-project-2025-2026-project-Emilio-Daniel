# Real API Constraints

## Google/Fitbit biometrics

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

Fitbit Web API richiede OAuth 2.0 per accedere ai dati utente. Il flusso che prepariamo
nel progetto e' Authorization Code con PKCE: il setup apre il browser, l'utente concede
gli scope, il Raspberry salva access token e refresh token in file locali ignorati da Git.

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
Fitbit Web API. Per il progetto manteniamo l'adapter Fitbit Web API perche' e' gia'
integrato nella pipeline, ma questa scelta va tenuta sotto controllo se il progetto deve
vivere oltre la demo.

## Dati disponibili per il modello

Google Health API espone data type utili per il progetto: heart rate, HRV, SpO2,
sleep, steps, sedentary periods e altri dati aggregabili nel contratto feature.
La disponibilita' effettiva dipende da device, consenso OAuth, qualita' misura e policy API.

## BLE indoor positioning

Per la localizzazione indoor, non conviene assumere che il Pixel Watch 2 emetta advertising
BLE controllabile come un beacon. Il piano piu' solido e':

1. usare beacon fissi nelle stanze e un tag BLE dedicato indossato dal paziente; oppure
2. sviluppare e verificare una piccola app Wear OS se serve usare davvero lo smartwatch
   come broadcaster.

Il modulo AI non dipende da questa scelta: riceve solo vettori di permanenza gia' aggregati.
