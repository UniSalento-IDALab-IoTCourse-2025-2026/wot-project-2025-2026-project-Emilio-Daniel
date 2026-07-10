Per far comunicare il nostro ambiente locale (Raspberry Pi) con i dispositivi esterni (PC del medico, Smartphone di Caregiver e Paziente) in tempo reale e in modo bidirezionale, passeremo da un'architettura puramente "locale" a un'architettura Cloud-Broker.


Il primo livello si lega al livello Edge Node (RPi5). Il funzionamento interno sul Raspberry rimane invariato (aggregazione, inferenza, produzione del file JSON). La novità è l'aggiunta di un Client MQTT. Al termine di ogni ciclo (quando viene generato patient-001-decision.json), uno script Python sul Raspberry agisce da Publisher. Esso pubblica il JSON (o payload specifici) su un Broker MQTT remoto, utilizzando topic ben definiti. Un topic potrebbe essere "iot/patients/001/telemetry/decision". 


Il cuore della comunicazione sarà un Broker MQTT (es. Mosquitto, AWS IoT Core, o HiveMQ) ospitato su un server Cloud/VPS. Il Broker non esegue logica complessa: riceve i messaggi dal Raspberry e li "spinge" istantaneamente a chiunque sia iscritto a quei topic. Il vantaggio di tale scelta è che l'RPi5 invia il dato una volta sola al Broker, il quale si occupa di distribuirlo simultaneamente alle dashboard connesse, risparmiando banda e risorse sul nodo Edge.


Accanto al Broker MQTT, avremo bisogno di un componente Backend (es. Node.js, Python FastAPI) che funga anch'esso da Client MQTT. Il suo ruolo è quello di ascoltare tutti i messaggi MQTT in arrivo dal Raspberry per salvarli in un Database (per permettere lo storico). Inoltre, se il Raspberry pubblica un allarme "Red", ma l'app del Caregiver è chiusa (telefono in tasca), l'app non può ricevere il messaggio MQTT. Il Backend rileva l'allarme e utilizza servizi come Firebase Cloud Messaging (FCM) per inviare una Notifica Push di sistema che "sveglia" il telefono.


Le applicazioni finali si connetteranno all'infrastruttura utilizzando protocolli diversi a seconda della loro natura:

    1. Dashboard Medico (Web App su PC): sfruttiamo MQTT over WebSockets (WSS). I browser web tradizionali non supportano connessioni TCP pure (che il protocollo MQTT standard richiede). Pertanto, la Web App utilizzerà MQTT over WebSockets. Il suo funzionamento è il seguente: la pagina web apre un canale WebSocket persistente con il Broker MQTT. Riceve i dati JSON in tempo reale appena il Raspberry li produce (senza dover fare refresh della pagina). Usa invece normali chiamate API REST (HTTP) verso il Backend quando il medico vuole caricare lo storico passato di un paziente.
    
    2. Dashboard Caregiver & Paziente (App Mobile Android/iOS): sfruttiamo MQTT Nativo + Push. Quando l'app è aperta (Foreground), viene utilizzato un client MQTT nativo (o WebSocket, se sviluppato in React Native/Flutter) inscritto ai topic del paziente. I semafori e gli stati si aggiornano istantaneamente all'arrivo del payload dal Raspberry. Quando l'app è chiusa/in background, si affida alle Notifiche Push generate dal Backend per avvisare di eventi critici o messaggi in arrivo.

Il flusso di un evento critico diventa:
    
    1. L'Edge AI sul Raspberry calcola un'anomalia (es. SpO2 bassissima + sedentarietà) e genera il JSON con "should_publish: true" e "status: red";
    
    2. Il Raspberry pubblica il payload sul Broker MQTT al topic alerts/001;
    
    3. Il Broker smista il messaggio. Infatti, alla Web App del medico (via WebSocket), viene aggiornata l'interfaccia istantaneamente, mentre, allo stesso tempo, il messaggio viene smistato al Backend Cloud;
    
    4. Il Backend Cloud salva l'evento nel DB e invia una Notifica Push urgente allo smartphone del Caregiver;
    
    5. Il Medico, dal PC, preme un pulsante "Ricevuto". La Web App pubblica un messaggio MQTT al topic commands/001/ack. Caregiver e Backend lo ricevono istantaneamente, allineando lo stato di tutti.