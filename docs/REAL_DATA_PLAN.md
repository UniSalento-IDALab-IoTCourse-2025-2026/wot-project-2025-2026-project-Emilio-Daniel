# Real Data Plan

## Decisione architetturale

Useremo un approccio a tre modelli:

- un modello generico spaziale/domestico, addestrato da CASAS;
- un modello generico wearable/fisiologico, addestrato da WESAD/PAMAP2 o dataset equivalente;
- un modello personale, addestrato sulla baseline reale del paziente raccolta in casa.

I modelli generici non descrivono la routine domestica individuale, ma permettono al
Raspberry di non restare cieco nei primi giorni. Il modello personale resta invece il
riferimento piu' importante per capire cosa e' anomalo per quella specifica persona.

Durante la baseline il sistema usa i modelli generici disponibili. Dopo la baseline
esegue anche il modello personale, confronta `generic_spatial_score`,
`generic_wearable_score` e `personal_score`, poi produce una decisione finale tramite
la logica di fusione.

Nei primi giorni i modelli generici non vengono riaddestrati automaticamente sui dati del
paziente. Vengono usati come safety gate: se una finestra reale appare troppo anomala,
il sistema puo' segnalarla ma non la inserisce nella baseline personale. Questo evita
di insegnare al modello personale che un comportamento potenzialmente problematico e'
normale.

## Ordine di lavoro

1. Preparare Edge AI e schema feature.
2. Appena arriva il Raspberry Pi, installare ambiente e servizi.
3. Creare l'app OAuth Fitbit per il Pixel Watch 2 e salvare token/client sul Raspberry.
4. Collegare BLE scanner per vettori di permanenza.
5. Collegare Shelly EM o misuratore equivalente.
6. Preparare `models/generic_spatial.pkl` da CASAS, se disponibile.
7. Preparare `models/generic_wearable.pkl` da WESAD/PAMAP2, se disponibile.
8. Raccogliere baseline silenziosa per circa 5/6 giorni, filtrata dal safety gate generico.
   Questa e' una baseline compatta per i tempi del progetto; una baseline piu' lunga
   sarebbe piu' robusta.
9. Addestrare Isolation Forest per singolo paziente.
10. Attivare inferenza tripla: generico spaziale + generico wearable + personale + fusione.
11. Pubblicare solo decisioni aggregate verso backend/cloud.

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
