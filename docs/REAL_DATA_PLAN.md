# Real Data Plan

## Decisione architetturale

Il modello va addestrato principalmente sulla baseline reale del soggetto, non su un dataset pubblico
generico. I dataset pubblici possono servire per validare codice e metodologia, ma non descrivono
la routine domestica individuale del paziente.

## Ordine di lavoro

1. Preparare Edge AI e schema feature.
2. Appena arriva il Raspberry Pi, installare ambiente e servizi.
3. Creare l'app OAuth Fitbit per il Pixel Watch 2 e salvare token/client sul Raspberry.
4. Collegare BLE scanner per vettori di permanenza.
5. Collegare Shelly EM o misuratore equivalente.
6. Raccogliere baseline silenziosa per circa 5/6 giorni.
   Questa e' una baseline compatta per i tempi del progetto; una baseline piu' lunga
   sarebbe piu' robusta.
7. Addestrare Isolation Forest per singolo paziente.
8. Attivare inferenza e debounce.
9. Pubblicare solo decisioni aggregate verso backend/cloud.

## Vincoli pratici gia' emersi

Google Health API e Fitbit Web API forniscono dati sanitari via autorizzazione OAuth e non come
stream BLE grezzo dal Pixel Watch. Quindi il watcher biometrico deve restare un adapter cloud-to-edge.

Per il setup Fitbit abbiamo gia' predisposto `edge_auth`: genera il login OAuth con PKCE,
salva `config/fitbit_client.json` e `config/fitbit_token.json`, e permette refresh manuale
o automatico del token. I dati veri arriveranno solo dopo consenso dell'account usato dal
Google Pixel Watch 2.

La localizzazione indoor non dovrebbe dipendere dal Pixel Watch come beacon BLE se non riusciamo a
controllarne l'advertising. La scelta piu' robusta sara' usare un tag BLE dedicato indossato o
agganciato al cinturino, oppure un'app Wear OS dedicata se tecnicamente sostenibile.
