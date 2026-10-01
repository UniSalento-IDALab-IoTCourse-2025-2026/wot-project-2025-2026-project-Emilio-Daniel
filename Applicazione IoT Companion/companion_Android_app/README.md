# Triage IoT - App Android

Applicazione Android per paziente e caregiver. Il ruolo restituito dal backend decide
l'interfaccia e i dati accessibili; il `patient_id` non viene scelto manualmente
dall'utente.

## Progetto completo

```text
Beacon BLE -> App -> Raspberry Edge -> MQTT -> Backend -> Dashboard medico
                \---------------- REST / FCM ----------------/
```

Repository del progetto:

- [integrazione](https://github.com/emipasca12/ProgettoIoT)
- [Edge](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-edge-Pascadopoli-Spedicato)
- [Cloud](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-cloud-Pascadopoli-Spedicato)
- [Dashboard](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-dashboard-Pascadopoli-Spedicato)
- [Android](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-android-Pascadopoli-Spedicato)
- [Presentazione](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-presentation-Pascadopoli-Spedicato)

I link dell'organizzazione diventano disponibili dopo la creazione dei repository per
la consegna.

## Modalita paziente

- login e associazione server-side al paziente autorizzato;
- monitoraggio BLE tramite Foreground Service;
- ripartenza dopo il riavvio del telefono;
- stato connessione Raspberry e ultimo aggiornamento;
- dati sintetici e grafici personali;
- messaggi e notifiche del medico;
- task e questionari guidati;
- eventi `seen`, `started` e `completed`;
- coda locale dei risultati durante l'assenza di rete;
- invio periodico dello stato app e della batteria.

I messaggi possono essere rimossi dalla vista. Le notifiche legate a un'attivita possono
essere eliminate solo quando l'attivita e' completata o scaduta, mantenendo l'audit nel
backend.

## Modalita caregiver

- mostra solo i pazienti associati all'account;
- visualizza stato generale e problemi tecnici semplici;
- espone soltanto alert autorizzati e pubblicabili;
- consente la presa in carico con conferma;
- mostra chi ha gia preso in carico l'evento;
- riceve messaggi e notifiche destinati al caregiver;
- non espone feature AI grezze, token o configurazioni tecniche.

## Identita e sicurezza

Il flusso di associazione e':

```text
account autenticato -> ruolo -> pazienti autorizzati dal backend
                    -> patient_id verificato a ogni richiesta
                    -> registrazione device_id e token FCM
```

Il `device_id` viene generato dall'app. Access token e refresh token sono conservati
con Android Keystore. Il token FCM non viene scritto nei log.

Le impostazioni tecniche e lo stop del monitoraggio sono nella schermata
amministrativa. Le credenziali dimostrative non devono essere usate in produzione.

## Configurazione

Requisiti:

- Android SDK 35;
- Java 17;
- dispositivo Android 8.0/API 26 o successivo;
- Bluetooth e posizione abilitati;
- PC, Raspberry e telefono sulla stessa rete.

Nelle impostazioni amministrative inserire:

```text
Receiver Raspberry: http://IP_RPI:8000/ble/sample
Backend clinico:    http://IP_PC:8080/api/v1
```

La demo usa soltanto Cucina e Bagno. Rimuovere dalla mappa eventuali beacon non
validati. Il file Firebase `app/google-services.json` e' locale e ignorato da Git.

## Build APK

Da PowerShell:

```powershell
cd "Applicazione IoT Companion\companion_Android_app"
.\gradlew.bat clean test assembleDebug
```

APK:

```text
app/build/outputs/apk/debug/app-debug.apk
```

Installazione con ADB:

```powershell
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

## Collaudo

Verificare almeno:

1. login paziente e caregiver;
2. ricezione di una sola notifica per destinatario corretto;
3. monitoraggio con schermo bloccato e risparmio energetico;
4. ripartenza dopo riavvio del telefono;
5. invio BLE al Raspberry;
6. task completato e risultato visibile al medico;
7. risultato accodato senza rete e inviato al ritorno della connessione;
8. impossibilita di accedere a un paziente non associato.

La checklist estesa e' in [TEST_CHECKLIST.md](TEST_CHECKLIST.md).
