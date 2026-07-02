package it.unisalento.iotedgecompanion;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.TextUtils;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final int REQUEST_PERMISSIONS = 1001;
    private boolean startServiceAfterPermissionGrant = false;

    private final ExecutorService networkExecutor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private EditText receiverUrlInput;
    private EditText phoneIdInput;
    private EditText beaconMapInput;
    private EditText manualRoomInput;
    private EditText manualRssiInput;
    private EditText manualBeaconInput;
    private TextView statusText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        /*
         * Metodo principale dell'Activity Android.
         * Inizializza la schermata, collega i campi XML alle variabili Java e
         * associa i pulsanti alle azioni di configurazione, invio manuale e
         * gestione del servizio BLE in background.
         */
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        receiverUrlInput = findViewById(R.id.receiverUrlInput);
        phoneIdInput = findViewById(R.id.phoneIdInput);
        beaconMapInput = findViewById(R.id.beaconMapInput);
        manualRoomInput = findViewById(R.id.manualRoomInput);
        manualRssiInput = findViewById(R.id.manualRssiInput);
        manualBeaconInput = findViewById(R.id.manualBeaconInput);
        statusText = findViewById(R.id.statusText);

        Button saveConfigButton = findViewById(R.id.saveConfigButton);
        Button sendManualButton = findViewById(R.id.sendManualButton);
        Button startScanButton = findViewById(R.id.startScanButton);
        Button stopScanButton = findViewById(R.id.stopScanButton);

        loadConfig();

        saveConfigButton.setOnClickListener(view -> saveConfig());
        sendManualButton.setOnClickListener(view -> sendManualSample());
        startScanButton.setOnClickListener(view -> startMonitoringService());
        stopScanButton.setOnClickListener(view -> stopMonitoringService());
    }

    @Override
    protected void onDestroy() {
        /*
         * Chiusura controllata dell'Activity.
         * Spegne l'executor usato per le richieste HTTP, evitando che thread di
         * rete rimangano attivi dopo la chiusura dell'interfaccia.
         */
        networkExecutor.shutdownNow();
        super.onDestroy();
    }

    private void loadConfig() {
        /*
         * Carica da SharedPreferences l'ultima configurazione salvata.
         * In questo modo l'utente non deve reinserire ogni volta URL del
         * Raspberry, identificativo telefono e mappa beacon-stanza.
         */
        SharedPreferences preferences = getSharedPreferences("iot-edge", MODE_PRIVATE);
        receiverUrlInput.setText(preferences.getString("receiverUrl", "http://10.0.2.2:8000/ble/sample"));
        phoneIdInput.setText(preferences.getString("phoneId", "android-emulator"));
        beaconMapInput.setText(preferences.getString("beaconMap",
                "AA:BB:CC:DD:EE:01=kitchen\n" +
                "AA:BB:CC:DD:EE:02=bedroom\n" +
                "AA:BB:CC:DD:EE:03=bathroom\n" +
                "AA:BB:CC:DD:EE:04=living_room"));
        manualRoomInput.setText(preferences.getString("manualRoom", "kitchen"));
        manualRssiInput.setText(preferences.getString("manualRssi", "-61"));
        manualBeaconInput.setText(preferences.getString("manualBeacon", "AA:BB:CC:DD:EE:01"));
    }

    private void saveConfig() {
        /*
         * Salva localmente la configurazione inserita nella schermata.
         * I valori salvati vengono riutilizzati sia dal test manuale sia dal
         * Foreground Service BLE che lavora in background.
         */
        getSharedPreferences("iot-edge", MODE_PRIVATE)
                .edit()
                .putString("receiverUrl", receiverUrlInput.getText().toString().trim())
                .putString("phoneId", phoneIdInput.getText().toString().trim())
                .putString("beaconMap", beaconMapInput.getText().toString())
                .putString("manualRoom", manualRoomInput.getText().toString().trim())
                .putString("manualRssi", manualRssiInput.getText().toString().trim())
                .putString("manualBeacon", manualBeaconInput.getText().toString().trim())
                .apply();
        setStatus("Configurazione salvata");
    }

    private void sendManualSample() {
        /*
         * Invia un campione BLE manuale al receiver.
         * Questa modalita serve per testare l'intera pipeline anche da
         * emulatore, quando non abbiamo ancora beacon fisici disponibili.
         */
        saveConfig();
        String room = manualRoomInput.getText().toString().trim();
        String beaconId = manualBeaconInput.getText().toString().trim();
        int rssi = parseRssi(manualRssiInput.getText().toString().trim());
        sendBleSample(room, rssi, beaconId, "ManualBeacon");
    }

    private void startMonitoringService() {
        /*
         * Avvia il Foreground Service responsabile della scansione BLE reale.
         * Prima controlla i permessi Android necessari; se mancano, li richiede
         * e riparte automaticamente dopo la concessione.
         */
        saveConfig();
        if (!hasRequiredPermissions()) {
            startServiceAfterPermissionGrant = true;
            requestRequiredPermissions();
            return;
        }

        Intent intent = new Intent(this, BleMonitoringService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
        setStatus("Monitoraggio BLE avviato in background");
    }

    private void stopMonitoringService() {
        /*
         * Ferma il servizio BLE in background.
         * Questa azione interrompe la scansione periodica e aggiorna lo stato
         * mostrato nell'interfaccia utente.
         */
        stopService(new Intent(this, BleMonitoringService.class));
        setStatus("Monitoraggio BLE fermato");
    }

    private void sendBleSample(String room, int rssi, String beaconId, String beaconName) {
        /*
         * Costruisce e invia via HTTP un campione BLE al Raspberry.
         * L'invio avviene su thread separato per non bloccare la UI Android; il
         * risultato viene poi riportato sul main thread tramite Handler.
         */
        String receiverUrl = receiverUrlInput.getText().toString().trim();
        String phoneId = phoneIdInput.getText().toString().trim();
        if (TextUtils.isEmpty(receiverUrl)) {
            setStatus("URL receiver mancante");
            return;
        }

        networkExecutor.execute(() -> {
            HttpURLConnection connection = null;
            try {
                JSONObject payload = new JSONObject();
                payload.put("timestamp", Instant.now().toString());
                payload.put("room", room);
                payload.put("rssi", rssi);
                payload.put("beacon_id", beaconId);
                payload.put("beacon_name", beaconName == null ? "" : beaconName);
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
                mainHandler.post(() -> setStatus("Inviato " + room + " (" + responseCode + ")"));
            } catch (Exception exception) {
                mainHandler.post(() -> setStatus("Errore invio: " + exception.getMessage()));
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
        });
    }

    private int parseRssi(String text) {
        /*
         * Converte il valore RSSI inserito manualmente in intero.
         * Se il testo non e' valido, usa un valore di default realistico per un
         * segnale BLE medio-debole, cosi' il test manuale non si blocca.
         */
        try {
            return Integer.parseInt(text);
        } catch (NumberFormatException exception) {
            return -70;
        }
    }

    private boolean hasRequiredPermissions() {
        /*
         * Verifica se l'app possiede i permessi necessari alla scansione BLE.
         * Android richiede permessi diversi in base alla versione, quindi il
         * controllo distingue localizzazione, Bluetooth e notifiche.
         */
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            return false;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED) {
                return false;
            }
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
                return false;
            }
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            return checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
        }
        return true;
    }

    private void requestRequiredPermissions() {
        /*
         * Richiede all'utente i permessi Android necessari.
         * La lista viene costruita dinamicamente per restare compatibile con
         * versioni Android diverse, evitando richieste non supportate.
         */
        List<String> permissions = new ArrayList<>();
        permissions.add(Manifest.permission.ACCESS_FINE_LOCATION);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            permissions.add(Manifest.permission.BLUETOOTH_SCAN);
            permissions.add(Manifest.permission.BLUETOOTH_CONNECT);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS);
        }
        requestPermissions(permissions.toArray(new String[0]), REQUEST_PERMISSIONS);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        /*
         * Gestisce la risposta dell'utente alla richiesta permessi.
         * Se tutti i permessi sono concessi e l'utente voleva avviare il servizio,
         * il monitoraggio BLE parte automaticamente.
         */
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQUEST_PERMISSIONS) {
            return;
        }
        if (hasRequiredPermissions()) {
            setStatus("Permessi concessi");
            if (startServiceAfterPermissionGrant) {
                startServiceAfterPermissionGrant = false;
                startMonitoringService();
            }
        } else {
            startServiceAfterPermissionGrant = false;
            setStatus("Permessi BLE/notifiche mancanti");
        }
    }

    private void setStatus(String message) {
        /*
         * Aggiorna il messaggio di stato visibile nell'app.
         * Centralizzare questa operazione rende piu' semplice modificare in
         * futuro il modo in cui comunichiamo errori o successi all'utente.
         */
        statusText.setText(message);
    }
}
