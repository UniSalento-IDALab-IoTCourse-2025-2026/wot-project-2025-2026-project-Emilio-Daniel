# Real API Constraints

## Google/Fitbit biometrics

Il Google Pixel Watch 2 non va trattato come sorgente BLE grezza per i dati biometrici.
La strada robusta e' cloud-to-edge: autorizzazione OAuth, lettura Google Health/Fitbit,
normalizzazione sul Raspberry Pi.

Riferimenti ufficiali:

- Google Health API migration/specifications:
  https://developers.google.com/health/migration/api-specifications
- Fitbit Heart Rate Intraday:
  https://dev.fitbit.com/build/reference/web-api/intraday/get-heartrate-intraday-by-date-range/

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
