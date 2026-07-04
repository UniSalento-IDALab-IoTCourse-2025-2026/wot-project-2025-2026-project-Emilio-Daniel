package it.unisalento.iotedgecompanion;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanResult;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.text.TextUtils;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class BleMonitoringService extends Service {
    private static final String CHANNEL_ID = "iot_edge_ble_monitoring";
    private static final int NOTIFICATION_ID = 2001;
    private static final long SCAN_DURATION_MS = 5000L;
    private static final long PAUSE_BETWEEN_SCANS_MS = 10000L;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService networkExecutor = Executors.newSingleThreadExecutor();
    private final Map<String, BeaconObservation> observations = new HashMap<>();

    private BluetoothLeScanner bleScanner;
    private boolean running = false;
    private boolean scanning = false;

    private final ScanCallback scanCallback = new ScanCallback() {
        @Override
        public void onScanResult(int callbackType, ScanResult result) {
            /*
             * Callback invocata dal sistema Android quando viene rilevato un
             * advertising BLE. Il risultato viene delegato a un metodo dedicato
             * per mantenere pulita la logica del servizio.
             */
            handleScanResult(result);
        }
    };

    @Override
    public void onCreate() {
        /*
         * Inizializza il servizio BLE.
         * Crea il canale notifiche e avvia il servizio in foreground, requisito
         * necessario affinche' Android permetta il lavoro continuativo in
         * background.
         */
        super.onCreate();
        createNotificationChannel();
        startAsForeground("Monitoraggio indoor in corso");
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        /*
         * Avvia o mantiene attivo il ciclo di monitoraggio.
         * START_STICKY indica ad Android che il servizio deve essere ricreato se
         * possibile dopo una chiusura del processo.
         */
        startAsForeground("Monitoraggio indoor in corso");
        if (!running) {
            running = true;
            scheduleNextScan(0L);
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        /*
         * Ferma il servizio in modo ordinato.
         * Interrompe eventuale scansione BLE, rimuove callback pianificate e
         * chiude l'executor di rete per evitare lavori residui.
         */
        running = false;
        stopCurrentScan();
        handler.removeCallbacksAndMessages(null);
        networkExecutor.shutdownNow();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        /*
         * Il servizio non espone binding ad altre componenti.
         * Viene usato solo come Foreground Service avviato e fermato
         * esplicitamente dall'Activity.
         */
        return null;
    }

    @SuppressLint("MissingPermission")
    private void startScanCycle() {
        /*
         * Avvia una singola finestra di scansione BLE.
         * Prima verifica permessi, Bluetooth e disponibilita dello scanner; poi
         * pulisce le osservazioni precedenti e ascolta beacon per alcuni secondi.
         */
        if (!running) {
            return;
        }
        if (!hasRequiredPermissions()) {
            startAsForeground("Permessi BLE mancanti");
            scheduleNextScan(PAUSE_BETWEEN_SCANS_MS);
            return;
        }

        BluetoothManager manager = (BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
        BluetoothAdapter adapter = manager != null ? manager.getAdapter() : null;
        if (adapter == null || !adapter.isEnabled()) {
            startAsForeground("Bluetooth non attivo");
            scheduleNextScan(PAUSE_BETWEEN_SCANS_MS);
            return;
        }

        bleScanner = adapter.getBluetoothLeScanner();
        if (bleScanner == null) {
            startAsForeground("Scanner BLE non disponibile");
            scheduleNextScan(PAUSE_BETWEEN_SCANS_MS);
            return;
        }

        observations.clear();
        scanning = true;
        bleScanner.startScan(scanCallback);
        handler.postDelayed(this::finishScanCycle, SCAN_DURATION_MS);
    }

    private void finishScanCycle() {
        /*
         * Conclude la finestra di scansione e decide cosa inviare.
         * Tra tutti i beacon mappati rilevati sceglie quello con RSSI piu' forte,
         * assumendo che rappresenti la stanza piu' vicina al telefono.
         */
        stopCurrentScan();
        BeaconObservation strongest = strongestObservation();
        if (strongest != null) {
            sendBleSample(strongest);
            startAsForeground("Ultima stanza: " + strongest.room);
        } else {
            startAsForeground("Nessun beacon mappato rilevato");
        }
        observations.clear();
        scheduleNextScan(PAUSE_BETWEEN_SCANS_MS);
    }

    @SuppressLint("MissingPermission")
    private void stopCurrentScan() {
        /*
         * Interrompe la scansione BLE corrente se e' attiva.
         * Il controllo dei permessi evita eccezioni su versioni Android che
         * richiedono autorizzazioni Bluetooth runtime.
         */
        if (bleScanner != null && scanning && hasRequiredPermissions()) {
            bleScanner.stopScan(scanCallback);
        }
        scanning = false;
    }

    @SuppressLint("MissingPermission")
    private void handleScanResult(ScanResult result) {
        /*
         * Elabora un singolo risultato BLE rilevato dallo scanner.
         * Il metodo risolve la stanza tramite mappa beacon-stanza e conserva
         * l'ultima osservazione valida. Per i beacon iBeacon prova a usare
         * l'identificativo stabile uuid-major-minor, piu' adatto di nome/MAC.
         */
        Map<String, String> beaconMap = parseBeaconMap();
        String address = result.getDevice().getAddress();
        String name = result.getDevice().getName();
        String iBeaconId = parseIBeaconIdentifier(result);
        int rssi = result.getRssi();

        String room = resolveRoom(beaconMap, address, name, iBeaconId);
        if (room == null) {
            return;
        }

        String beaconId = TextUtils.isEmpty(iBeaconId) ? address : iBeaconId;
        observations.put(beaconId, new BeaconObservation(beaconId, name, room, rssi));
    }

    private void sendBleSample(BeaconObservation observation) {
        /*
         * Invia al Raspberry la stanza stimata dal ciclo BLE.
         * La richiesta HTTP viene eseguita in background e aggiorna la notifica
         * del Foreground Service con l'esito dell'invio.
         */
        SharedPreferences preferences = getSharedPreferences("iot-edge", MODE_PRIVATE);
        String receiverUrl = preferences.getString("receiverUrl", "");
        String phoneId = preferences.getString("phoneId", "android-phone");
        if (TextUtils.isEmpty(receiverUrl)) {
            startAsForeground("URL receiver mancante");
            return;
        }

        networkExecutor.execute(() -> {
            HttpURLConnection connection = null;
            try {
                JSONObject payload = new JSONObject();
                payload.put("timestamp", Instant.now().toString());
                payload.put("room", observation.room);
                payload.put("rssi", observation.rssi);
                payload.put("beacon_id", observation.address);
                payload.put("beacon_name", observation.name);
                payload.put("phone_id", TextUtils.isEmpty(phoneId) ? "android-phone" : phoneId);

                byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
                connection = (HttpURLConnection) new URL(receiverUrl).openConnection();
                connection.setRequestMethod("POST");
                connection.setConnectTimeout(5000);
                connection.setReadTimeout(5000);
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setDoOutput(true);
                try (OutputStream outputStream = connection.getOutputStream()) {
                    outputStream.write(body);
                }
                int responseCode = connection.getResponseCode();
                handler.post(() -> startAsForeground(
                        "Inviata stanza: " + observation.room + " (" + responseCode + ")"
                ));
            } catch (Exception exception) {
                handler.post(() -> startAsForeground("Errore invio BLE"));
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
        });
    }

    private Map<String, String> parseBeaconMap() {
        /*
         * Legge dalle preferenze la mappa beacon-stanza inserita nell'app.
         * Ogni riga ha formato chiave=stanza; la chiave puo' essere indirizzo o
         * parte del nome BLE, cosi' la configurazione resta flessibile.
         */
        SharedPreferences preferences = getSharedPreferences("iot-edge", MODE_PRIVATE);
        String beaconMapText = preferences.getString("beaconMap", "");
        Map<String, String> mapping = new HashMap<>();
        String[] lines = beaconMapText.split("\\n");
        for (String line : lines) {
            String trimmed = line.trim();
            if (trimmed.isEmpty() || !trimmed.contains("=")) {
                continue;
            }
            String[] parts = trimmed.split("=", 2);
            mapping.put(parts[0].trim().toLowerCase(Locale.ROOT), parts[1].trim().toLowerCase(Locale.ROOT));
        }
        return mapping;
    }

    private String resolveRoom(Map<String, String> beaconMap, String address, String name, String iBeaconId) {
        /*
         * Determina la stanza associata a un beacon rilevato.
         * Prima prova l'identificativo iBeacon uuid-major-minor, poi indirizzo e
         * nome pubblicizzato. Se non trova corrispondenze, il beacon viene ignorato.
         */
        String normalizedIBeaconId = iBeaconId == null ? "" : iBeaconId.toLowerCase(Locale.ROOT);
        if (beaconMap.containsKey(normalizedIBeaconId)) {
            return beaconMap.get(normalizedIBeaconId);
        }

        String normalizedAddress = address == null ? "" : address.toLowerCase(Locale.ROOT);
        if (beaconMap.containsKey(normalizedAddress)) {
            return beaconMap.get(normalizedAddress);
        }

        String normalizedName = name == null ? "" : name.toLowerCase(Locale.ROOT);
        for (Map.Entry<String, String> entry : beaconMap.entrySet()) {
            if (!entry.getKey().isEmpty() && normalizedName.contains(entry.getKey())) {
                return entry.getValue();
            }
        }
        return null;
    }

    private String parseIBeaconIdentifier(ScanResult result) {
        /*
         * Estrae dai manufacturer data Apple l'identificativo iBeacon.
         * Il formato iBeacon contiene UUID, major e minor: insieme identificano
         * il beacon in modo piu' stabile e leggibile della sola potenza RSSI.
         */
        if (result.getScanRecord() == null) {
            return "";
        }
        byte[] data = result.getScanRecord().getManufacturerSpecificData(0x004C);
        if (data == null || data.length < 23) {
            return "";
        }
        int frameType = data[0] & 0xFF;
        int frameLength = data[1] & 0xFF;
        if (frameType != 0x02 || frameLength != 0x15) {
            return "";
        }

        StringBuilder compactUuid = new StringBuilder();
        for (int index = 2; index < 18; index++) {
            compactUuid.append(String.format(Locale.ROOT, "%02x", data[index] & 0xFF));
        }
        String uuid = compactUuid.substring(0, 8)
                + "-"
                + compactUuid.substring(8, 12)
                + "-"
                + compactUuid.substring(12, 16)
                + "-"
                + compactUuid.substring(16, 20)
                + "-"
                + compactUuid.substring(20);

        int major = unsignedShort(data[18], data[19]);
        int minor = unsignedShort(data[20], data[21]);
        return uuid + "-" + major + "-" + minor;
    }

    private int unsignedShort(byte high, byte low) {
        /*
         * Converte due byte big-endian in un intero positivo.
         * Major e minor iBeacon sono valori unsigned a 16 bit.
         */
        return ((high & 0xFF) << 8) | (low & 0xFF);
    }

    private BeaconObservation strongestObservation() {
        /*
         * Seleziona l'osservazione BLE con segnale RSSI maggiore.
         * Nel nostro scenario questa scelta approssima il beacon piu' vicino e
         * quindi la stanza piu' probabile in cui si trova il telefono/paziente.
         */
        BeaconObservation strongest = null;
        for (BeaconObservation observation : observations.values()) {
            if (strongest == null || observation.rssi > strongest.rssi) {
                strongest = observation;
            }
        }
        return strongest;
    }

    private void scheduleNextScan(long delayMs) {
        /*
         * Pianifica il prossimo ciclo di scansione.
         * Alternare scansione e pausa riduce consumo batteria e mantiene il
         * monitoraggio sufficientemente continuo per il progetto.
         */
        handler.postDelayed(this::startScanCycle, delayMs);
    }

    private boolean hasRequiredPermissions() {
        /*
         * Controlla i permessi minimi richiesti per usare BLE in background.
         * Android 12+ separa i permessi Bluetooth dalla localizzazione, quindi
         * il metodo gestisce esplicitamente le diverse versioni.
         */
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            return false;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED) {
                return false;
            }
            return checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED;
        }
        return true;
    }

    private void createNotificationChannel() {
        /*
         * Crea il canale notifiche richiesto da Android 8+.
         * Il canale a bassa importanza permette di mostrare una notifica
         * persistente senza disturbare eccessivamente l'utente.
         */
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "Monitoraggio BLE",
                NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription("Monitoraggio indoor BLE in background");
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            manager.createNotificationChannel(channel);
        }
    }

    private void startAsForeground(String contentText) {
        /*
         * Porta il servizio in foreground con una notifica persistente.
         * Questo e' necessario per rendere legittimo il monitoraggio BLE in
         * background e ridurre il rischio che Android fermi il servizio.
         */
        Notification notification = buildNotification(contentText);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                    NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
            );
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
    }

    private Notification buildNotification(String contentText) {
        /*
         * Costruisce la notifica visualizzata durante il monitoraggio BLE.
         * Toccando la notifica si riapre l'Activity, cosi' l'utente puo'
         * controllare configurazione e stato del servizio.
         */
        Intent intent = new Intent(this, MainActivity.class);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent pendingIntent = PendingIntent.getActivity(this, 0, intent, flags);

        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }
        return builder
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle("IoT Edge Companion attivo")
                .setContentText(contentText)
                .setContentIntent(pendingIntent)
                .setOngoing(true)
                .build();
    }

    private static class BeaconObservation {
        final String address;
        final String name;
        final String room;
        final int rssi;

        BeaconObservation(String address, String name, String room, int rssi) {
            /*
             * Rappresenta una singola osservazione di beacon durante una scansione.
             * La classe conserva solo i dati necessari per scegliere il segnale
             * piu' forte e inviare il campione al receiver.
             */
            this.address = address == null ? "" : address;
            this.name = name == null ? "" : name;
            this.room = room;
            this.rssi = rssi;
        }
    }
}
