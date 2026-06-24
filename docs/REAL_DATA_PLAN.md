# Real Data Plan

## Decisione architetturale

Il modello va addestrato principalmente sulla baseline reale del soggetto, non su un dataset pubblico
generico. I dataset pubblici possono servire per validare codice e metodologia, ma non descrivono
la routine domestica individuale del paziente.

## Ordine di lavoro

1. Preparare Edge AI e schema feature.
2. Appena arriva il Raspberry Pi, installare ambiente e servizi.
3. Collegare Fitbit/Google Health OAuth e scaricare dati reali.
4. Collegare BLE scanner per vettori di permanenza.
5. Collegare Shelly EM o misuratore equivalente.
6. Raccogliere baseline silenziosa per circa due settimane.
7. Addestrare Isolation Forest per singolo paziente.
8. Attivare inferenza e debounce.
9. Pubblicare solo decisioni aggregate verso backend/cloud.

## Vincoli pratici gia' emersi

Google Health API e Fitbit Web API forniscono dati sanitari via autorizzazione OAuth e non come
stream BLE grezzo dal Pixel Watch. Quindi il watcher biometrico deve restare un adapter cloud-to-edge.

La localizzazione indoor non dovrebbe dipendere dal Pixel Watch come beacon BLE se non riusciamo a
controllarne l'advertising. La scelta piu' robusta sara' usare un tag BLE dedicato indossato o
agganciato al cinturino, oppure un'app Wear OS dedicata se tecnicamente sostenibile.
