# Checklist test Android paziente e caregiver

## Paziente

- Login con credenziali paziente associate a `patient-001`.
- Verifica che nella home compaiano monitoraggio attivo, Raspberry, ultimo aggiornamento
  e andamento personale.
- Ricezione task dal backend.
- Stato task: seen, started, completed.
- Compilazione check-in, PHQ-2, test demo, MMSE/MoCA solo come modulo supervisionato se
  autorizzato/licenziato.
- Invio risultato con durata e device id.
- Rete assente: risultato salvato localmente e reinviato al ritorno della rete.
- Notifiche: il titolo deve essere quello scritto dal medico, non un testo generico.
- Cancellazione consentita solo per messaggi e task completati o scaduti.

## Caregiver

- Login caregiver.
- Registrazione FCM senza stampare token nei log.
- Ricezione notifiche push anche ad app chiusa.
- Messaggi dal medico visibili e cancellabili.
- Alert visibili solo se pubblicabili/autorizzati.
- Presa in carico alert con conferma.
- Se un medico o altro caregiver ha gia' preso in carico, mostrarlo chiaramente.
- Nessuna feature AI grezza, nessun token tecnico, nessuna credenziale.

## Robustezza

- Blocco schermo durante monitoraggio BLE.
- Risparmio energetico Android attivo.
- Riavvio telefono.
- Cambio rete Wi-Fi/dati mobili.
- Backend spento e poi riacceso.
- Firebase non configurato: l'app deve restare usabile con polling/refresh.
