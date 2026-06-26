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
        networkExecutor.shutdownNow();
        super.onDestroy();
    }

    private void loadConfig() {
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
        saveConfig();
        String room = manualRoomInput.getText().toString().trim();
        String beaconId = manualBeaconInput.getText().toString().trim();
        int rssi = parseRssi(manualRssiInput.getText().toString().trim());
        sendBleSample(room, rssi, beaconId, "ManualBeacon");
    }

    private void startMonitoringService() {
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
        stopService(new Intent(this, BleMonitoringService.class));
        setStatus("Monitoraggio BLE fermato");
    }

    private void sendBleSample(String room, int rssi, String beaconId, String beaconName) {
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
        try {
            return Integer.parseInt(text);
        } catch (NumberFormatException exception) {
            return -70;
        }
    }

    private boolean hasRequiredPermissions() {
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
        statusText.setText(message);
    }
}
