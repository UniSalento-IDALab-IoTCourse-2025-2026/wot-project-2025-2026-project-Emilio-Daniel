# Demo esame - Progetto IoT

## Obiettivo demo

Mostrare il percorso completo:

```text
sensori/app Android -> Edge/Raspberry -> MQTT -> backend -> dashboard medico -> app paziente/caregiver
```

## Scaletta consigliata

1. Avvia Docker, backend, subscriber MQTT, Edge receiver e dashboard.
2. Mostra che il telefono Android e' collegato al paziente `patient-001`.
3. Genera o acquisisci una nuova finestra dati.
4. Mostra nella dashboard il quadro clinico, lo score AI e il grafico storico.
5. Apri "Valutazione comportamentale" e spiega:
   - score AI;
   - confidenza dato;
   - affidabilita' modello;
   - fattori che aumentano o riducono l'indice;
   - trend e drift.
6. Apri "Giornata tipo" e confronta oggi con ieri/baseline.
7. Crea una attivita per il paziente e completala dall'app Android.
8. Invia un messaggio al caregiver e mostra che arriva solo al caregiver.
9. Apri "Stato sistema" e usa "Diagnostica rapida".
10. Esporta o mostra il report finale.

## Piano B se hardware o rete non collaborano

- Usare dati gia' salvati nel backend.
- Se il backend cade, mostrare la cache offline della dashboard.
- Se Firebase non invia push, mostrare messaggi e task dentro l'app dopo refresh.
- Se i beacon BLE non producono campioni, spiegare lo stato tecnico da "Stato sistema".

## Frase chiave da ripetere

Il sistema non sostituisce il medico: raccoglie segnali IoT, produce indicatori e rende
tracciabile il workflow di triage, task, alert e caregiver.
