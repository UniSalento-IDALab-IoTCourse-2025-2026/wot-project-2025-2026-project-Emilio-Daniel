package it.unisalento.iotedgecompanion;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.InputType;
import android.text.TextUtils;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

public class MainActivity extends Activity {
    private static final int REQUEST_PERMISSIONS = 1001;
    private static final String ADMIN_USERNAME = "admin";
    private static final String ADMIN_PASSWORD = "admin";
    private static final String DEFAULT_BEACON_MAP =
            "acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14592=kitchen\n" +
            "acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14582=bedroom\n" +
            "acfd065e-c3c0-11e3-9bbe-1a514932ac01-0-14599=bathroom";
    private boolean startServiceAfterPermissionGrant = false;

    private EditText receiverUrlInput;
    private EditText phoneIdInput;
    private EditText beaconMapInput;
    private LinearLayout gatewayConfigPanel;
    private TextView gatewaySummaryText;
    private LinearLayout beaconConfigPanel;
    private TextView beaconSummaryText;
    private TextView statusText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        /*
         * Metodo principale dell'Activity Android.
         * Inizializza la schermata, collega i campi XML alle variabili Java e
         * associa i pulsanti alle azioni di configurazione e monitoraggio BLE.
         */
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        receiverUrlInput = findViewById(R.id.receiverUrlInput);
        phoneIdInput = findViewById(R.id.phoneIdInput);
        beaconMapInput = findViewById(R.id.beaconMapInput);
        gatewayConfigPanel = findViewById(R.id.gatewayConfigPanel);
        gatewaySummaryText = findViewById(R.id.gatewaySummaryText);
        beaconConfigPanel = findViewById(R.id.beaconConfigPanel);
        beaconSummaryText = findViewById(R.id.beaconSummaryText);
        statusText = findViewById(R.id.statusText);

        Button saveConfigButton = findViewById(R.id.saveConfigButton);
        Button unlockGatewayConfigButton = findViewById(R.id.unlockGatewayConfigButton);
        Button lockGatewayConfigButton = findViewById(R.id.lockGatewayConfigButton);
        Button unlockBeaconConfigButton = findViewById(R.id.unlockBeaconConfigButton);
        Button saveBeaconMapButton = findViewById(R.id.saveBeaconMapButton);
        Button lockBeaconConfigButton = findViewById(R.id.lockBeaconConfigButton);
        Button startScanButton = findViewById(R.id.startScanButton);
        Button stopScanButton = findViewById(R.id.stopScanButton);

        loadConfig();

        saveConfigButton.setOnClickListener(view -> saveConfig());
        unlockGatewayConfigButton.setOnClickListener(view -> showAdminLoginDialog(
                "Accesso gateway",
                "Sblocca",
                this::unlockGatewayConfigEditor
        ));
        lockGatewayConfigButton.setOnClickListener(view -> lockGatewayConfigEditor());
        unlockBeaconConfigButton.setOnClickListener(view -> showAdminLoginDialog(
                "Accesso mappa beacon",
                "Sblocca",
                this::unlockBeaconMapEditor
        ));
        saveBeaconMapButton.setOnClickListener(view -> saveBeaconMap());
        lockBeaconConfigButton.setOnClickListener(view -> lockBeaconMapEditor());
        startScanButton.setOnClickListener(view -> startMonitoringService());
        stopScanButton.setOnClickListener(view -> showAdminLoginDialog(
                "Ferma monitoraggio",
                "Ferma",
                this::stopMonitoringService
        ));

        startMonitoringService();
        requestBatteryOptimizationExemptionIfNeeded();
        requestBackgroundLocationSettingsIfNeeded();
    }

    @Override
    protected void onDestroy() {
        /*
         * Chiusura controllata dell'Activity.
         * L'Activity non mantiene risorse pesanti: il monitoraggio reale viene
         * gestito dal Foreground Service separato.
         */
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
        String savedBeaconMap = preferences.getString("beaconMap", DEFAULT_BEACON_MAP);
        if (shouldUseDefaultBeaconMap(savedBeaconMap)) {
            savedBeaconMap = DEFAULT_BEACON_MAP;
            preferences.edit().putString("beaconMap", DEFAULT_BEACON_MAP).apply();
        }
        beaconMapInput.setText(savedBeaconMap);
        renderGatewaySummary();
        renderBeaconSummary();
        lockGatewayConfigEditor();
        lockBeaconMapEditor();
    }

    private boolean shouldUseDefaultBeaconMap(String savedBeaconMap) {
        /*
         * Se sul telefono era installata una vecchia versione dell'app, possono
         * essere rimasti placeholder o MAC fittizi. In quel caso ripristiniamo
         * automaticamente la mappa reale dei tre BlueBeacon del progetto.
         */
        if (savedBeaconMap == null || savedBeaconMap.trim().isEmpty()) {
            return true;
        }
        String normalized = savedBeaconMap.toLowerCase();
        return normalized.contains("identificativo_beacon")
                || normalized.contains("aa:bb:cc:dd:ee");
    }

    private void saveConfig() {
        /*
         * Salva localmente la configurazione inserita nella schermata.
         * I valori salvati vengono riutilizzati dal Foreground Service BLE che
         * lavora in background.
         */
        getSharedPreferences("iot-edge", MODE_PRIVATE)
                .edit()
                .putString("receiverUrl", receiverUrlInput.getText().toString().trim())
                .putString("phoneId", phoneIdInput.getText().toString().trim())
                .apply();
        renderGatewaySummary();
        lockGatewayConfigEditor();
        setStatus("Gateway salvato e monitoraggio aggiornato");
        startMonitoringService();
    }

    private void saveBeaconMap() {
        /*
         * Salva la mappa beacon dopo l'accesso amministratore.
         * Separare questo salvataggio dalla configurazione base impedisce che la
         * mappa venga modificata accidentalmente durante l'uso normale dell'app.
         */
        getSharedPreferences("iot-edge", MODE_PRIVATE)
                .edit()
                .putString("beaconMap", beaconMapInput.getText().toString().trim())
                .apply();
        renderBeaconSummary();
        lockBeaconMapEditor();
        setStatus("Mappa beacon salvata");
        startMonitoringService();
    }

    private void showAdminLoginDialog(String title, String positiveLabel, AdminAction action) {
        /*
         * Mostra una finestra di login prima di eseguire un'azione protetta.
         * Per ora le credenziali sono fisse admin/admin, come richiesto per il
         * prototipo. In futuro potranno essere sostituite da credenziali reali.
         */
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        int padding = dp(18);
        container.setPadding(padding, padding / 2, padding, 0);

        EditText usernameInput = new EditText(this);
        usernameInput.setHint("Username");
        usernameInput.setSingleLine(true);
        usernameInput.setInputType(InputType.TYPE_CLASS_TEXT);
        container.addView(usernameInput);

        EditText passwordInput = new EditText(this);
        passwordInput.setHint("Password");
        passwordInput.setSingleLine(true);
        passwordInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        container.addView(passwordInput);

        new AlertDialog.Builder(this)
                .setTitle(title)
                .setView(container)
                .setNegativeButton("Annulla", null)
                .setPositiveButton(positiveLabel, (dialog, which) -> {
                    String username = usernameInput.getText().toString().trim();
                    String password = passwordInput.getText().toString().trim();
                    if (ADMIN_USERNAME.equals(username) && ADMIN_PASSWORD.equals(password)) {
                        action.run();
                    } else {
                        setStatus("Credenziali non valide");
                    }
                })
                .show();
    }

    private void unlockGatewayConfigEditor() {
        /*
         * Mostra i campi tecnici del gateway solo dopo autenticazione admin.
         * Nell'uso normale l'utente vede il riepilogo, non i campi modificabili.
         */
        gatewayConfigPanel.setVisibility(View.VISIBLE);
        setStatus("Modifica gateway sbloccata");
    }

    private void lockGatewayConfigEditor() {
        /*
         * Nasconde i campi tecnici del gateway.
         * Questo rende la schermata piu' pulita e impedisce modifiche casuali
         * all'URL del receiver o all'identificativo del telefono.
         */
        gatewayConfigPanel.setVisibility(View.GONE);
    }

    private void unlockBeaconMapEditor() {
        /*
         * Mostra il pannello di modifica della mappa beacon.
         * L'utente normale vede solo il riepilogo; l'amministratore puo'
         * correggere UUID/Major/Minor e stanze.
         */
        beaconConfigPanel.setVisibility(View.VISIBLE);
        setStatus("Modifica mappa sbloccata");
    }

    private void lockBeaconMapEditor() {
        /*
         * Nasconde il pannello di modifica della mappa beacon.
         * Questo mantiene la schermata pulita e riduce il rischio di modifiche
         * accidentali durante i test reali in casa.
         */
        beaconConfigPanel.setVisibility(View.GONE);
    }

    private void renderBeaconSummary() {
        /*
         * Mostra la mappa beacon in forma leggibile.
         * Le chiavi tecniche restano disponibili nell'editor, ma nel riepilogo
         * l'attenzione va alle stanze configurate.
         */
        String[] lines = beaconMapInput.getText().toString().split("\\n");
        StringBuilder summary = new StringBuilder();
        for (String line : lines) {
            String trimmed = line.trim();
            if (trimmed.isEmpty() || !trimmed.contains("=")) {
                continue;
            }
            String[] parts = trimmed.split("=", 2);
            String key = parts[0].trim();
            String room = parts[1].trim();
            summary.append(prettyRoomName(room))
                    .append("  ->  ")
                    .append(shortenBeaconKey(key))
                    .append("\n");
        }
        beaconSummaryText.setText(summary.length() == 0 ? "Mappa beacon non configurata" : summary.toString().trim());
    }

    private void renderGatewaySummary() {
        /*
         * Mostra la configurazione gateway in forma compatta e leggibile.
         * I valori completi restano modificabili nel pannello admin.
         */
        String receiverUrl = receiverUrlInput.getText().toString().trim();
        String phoneId = phoneIdInput.getText().toString().trim();
        StringBuilder summary = new StringBuilder();
        summary.append("Receiver\n")
                .append(TextUtils.isEmpty(receiverUrl) ? "Non configurato" : receiverUrl)
                .append("\n\nDispositivo\n")
                .append(TextUtils.isEmpty(phoneId) ? "android-phone" : phoneId);
        gatewaySummaryText.setText(summary.toString());
    }

    private String prettyRoomName(String room) {
        /*
         * Traduce i nomi interni del modello in etichette piu' leggibili.
         * Nel CSV e nel modello rimangono `kitchen`, `bedroom`, `bathroom`.
         */
        String normalized = room.toLowerCase();
        if ("kitchen".equals(normalized)) {
            return "Cucina";
        }
        if ("bedroom".equals(normalized)) {
            return "Camera";
        }
        if ("bathroom".equals(normalized)) {
            return "Bagno";
        }
        return room;
    }

    private String shortenBeaconKey(String key) {
        /*
         * Accorcia la chiave tecnica del beacon per non sporcare il riepilogo.
         * L'identificativo completo resta modificabile nel pannello admin.
         */
        if (key.length() <= 18) {
            return key;
        }
        return key.substring(0, 8) + "..." + key.substring(key.length() - 8);
    }

    private int dp(int value) {
        /*
         * Converte un valore in density-independent pixels in pixel reali.
         * Serve per dare al dialog di login una spaziatura coerente sui diversi
         * schermi Android.
         */
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void startMonitoringService() {
        /*
         * Avvia il Foreground Service responsabile della scansione BLE reale.
         * Prima controlla i permessi Android necessari; se mancano, li richiede
         * e riparte automaticamente dopo la concessione.
         */
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
        setStatus("Monitoraggio IoT avviato in background");
    }

    private void stopMonitoringService() {
        /*
         * Ferma il servizio BLE in background.
         * Questa azione interrompe la scansione periodica e aggiorna lo stato
         * mostrato nell'interfaccia utente.
         */
        stopService(new Intent(this, BleMonitoringService.class));
        setStatus("Monitoraggio IoT fermato");
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
        permissions.add(Manifest.permission.ACCESS_COARSE_LOCATION);
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

    private void requestBatteryOptimizationExemptionIfNeeded() {
        /*
         * Chiede ad Android di non limitare l'app in standby.
         * Su molti telefoni il Foreground Service resta visibile, ma la scansione
         * BLE viene comunque ridotta dal risparmio energetico dopo schermo spento.
         */
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return;
        }
        PowerManager powerManager = (PowerManager) getSystemService(POWER_SERVICE);
        if (powerManager == null || powerManager.isIgnoringBatteryOptimizations(getPackageName())) {
            return;
        }

        new AlertDialog.Builder(this)
                .setTitle("Monitoraggio in background")
                .setMessage(
                        "Per continuare a rilevare i beacon anche a schermo spento, " +
                        "consenti a IoT Edge Companion di non essere ottimizzata dalla batteria."
                )
                .setNegativeButton("Dopo", null)
                .setPositiveButton("Consenti", (dialog, which) -> {
                    Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                    intent.setData(Uri.parse("package:" + getPackageName()));
                    startActivity(intent);
                })
                .show();
    }

    private void requestBackgroundLocationSettingsIfNeeded() {
        /*
         * Su Android 10/11 la scansione BLE a schermo spento puo' richiedere
         * anche la posizione in background. Android non sempre consente di
         * chiederla con un popup diretto, quindi accompagniamo l'utente nella
         * schermata impostazioni dell'app.
         */
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q || Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            return;
        }
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            return;
        }
        if (checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED) {
            return;
        }

        new AlertDialog.Builder(this)
                .setTitle("Posizione in background")
                .setMessage(
                        "Per rilevare i beacon anche quando lo schermo e' spento, " +
                        "imposta la posizione su 'Consenti sempre' nelle autorizzazioni dell'app."
                )
                .setNegativeButton("Dopo", null)
                .setPositiveButton("Apri impostazioni", (dialog, which) -> {
                    Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
                    intent.setData(Uri.parse("package:" + getPackageName()));
                    startActivity(intent);
                })
                .show();
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

    private interface AdminAction {
        /*
         * Piccola interfaccia usata per riutilizzare lo stesso dialog admin.
         * Permette di proteggere configurazione gateway, mappa beacon e stop
         * del monitoraggio senza duplicare codice di login.
         */
        void run();
    }
}
