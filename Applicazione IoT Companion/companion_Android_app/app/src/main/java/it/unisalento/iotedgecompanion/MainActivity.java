package it.unisalento.iotedgecompanion;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.ContextCompat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.DateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Schermata quotidiana del paziente, separata dalla configurazione tecnica. */
public class MainActivity extends Activity {
    private static final int REQUEST_PERMISSIONS = 1001;
    private static final String ADMIN_USERNAME = "admin";
    private static final String ADMIN_PASSWORD = "admin";

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private AppPreferences preferences;
    private LinearLayout loginPanel;
    private LinearLayout dailyPanel;
    private EditText emailInput;
    private EditText passwordInput;
    private TextView loginStatusText;
    private TextView welcomeText;
    private TextView patientBindingText;
    private TextView monitoringStatusText;
    private TextView connectionStatusText;
    private TextView offlineQueueText;
    private LinearLayout tasksContainer;
    private LinearLayout notificationsContainer;

    private final BroadcastReceiver syncReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            renderScreen();
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        preferences = AppPreferences.get(this);
        bindViews();
        configureActions();
        ensureMonitoringStarted();
        requestBatteryOptimizationExemptionIfNeeded();
        requestBackgroundLocationSettingsIfNeeded();
        FcmRegistration.ensureToken(this);
        renderScreen();
        if (preferences.isAuthenticated()) {
            synchronizeNow();
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        IntentFilter filter = new IntentFilter(PatientSyncManager.ACTION_SYNC_UPDATED);
        ContextCompat.registerReceiver(
                this,
                syncReceiver,
                filter,
                ContextCompat.RECEIVER_NOT_EXPORTED
        );
    }

    @Override
    protected void onStop() {
        unregisterReceiver(syncReceiver);
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private void bindViews() {
        loginPanel = findViewById(R.id.loginPanel);
        dailyPanel = findViewById(R.id.dailyPanel);
        emailInput = findViewById(R.id.emailInput);
        passwordInput = findViewById(R.id.passwordInput);
        loginStatusText = findViewById(R.id.loginStatusText);
        welcomeText = findViewById(R.id.welcomeText);
        patientBindingText = findViewById(R.id.patientBindingText);
        monitoringStatusText = findViewById(R.id.monitoringStatusText);
        connectionStatusText = findViewById(R.id.connectionStatusText);
        offlineQueueText = findViewById(R.id.offlineQueueText);
        tasksContainer = findViewById(R.id.tasksContainer);
        notificationsContainer = findViewById(R.id.notificationsContainer);
    }

    private void configureActions() {
        findViewById(R.id.loginButton).setOnClickListener(view -> login());
        findViewById(R.id.refreshButton).setOnClickListener(view -> synchronizeNow());
        findViewById(R.id.logoutButton).setOnClickListener(view -> confirmLogout());
        findViewById(R.id.adminSettingsButton).setOnClickListener(view -> requestAdminAccess());
        findViewById(R.id.loginAdminButton).setOnClickListener(view -> requestAdminAccess());
    }

    private void login() {
        String email = emailInput.getText().toString().trim();
        String password = passwordInput.getText().toString();
        if (email.isEmpty() || password.isEmpty()) {
            loginStatusText.setText("Inserisci email e password.");
            return;
        }
        loginStatusText.setText("Verifica del profilo in corso...");
        executor.execute(() -> {
            try {
                new BackendApiClient(this).authenticatePatient(email, password);
                runOnUiThread(() -> {
                    passwordInput.setText("");
                    renderScreen();
                    synchronizeNow();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> loginStatusText.setText(userMessage(exception)));
            }
        });
    }

    private void synchronizeNow() {
        connectionStatusText.setText("Aggiornamento in corso...");
        executor.execute(() -> PatientSyncManager.synchronize(this));
    }

    private void renderScreen() {
        boolean authenticated = preferences.isAuthenticated();
        loginPanel.setVisibility(authenticated ? View.GONE : View.VISIBLE);
        dailyPanel.setVisibility(authenticated ? View.VISIBLE : View.GONE);
        if (!authenticated) {
            return;
        }
        welcomeText.setText("Buongiorno, " + preferences.patientDisplayName());
        patientBindingText.setText(
                "Profilo verificato: " + preferences.patientId()
                        + "\nDispositivo: " + shortDeviceId(preferences.deviceId())
        );
        monitoringStatusText.setText(
                preferences.serviceRunning() ? "Monitoraggio attivo in background" : "Monitoraggio da riavviare"
        );
        renderConnections();
        renderTasksAndMessages();
        int pending = new OfflineResultQueue(this).size();
        offlineQueueText.setText(
                pending == 0
                        ? "Tutti i risultati sono stati sincronizzati."
                        : pending + " risultati salvati sul telefono in attesa di rete."
        );
    }

    private void renderConnections() {
        boolean edgeOnline = false;
        String lastUpdate = "non disponibile";
        try {
            JSONObject current = new JSONObject(preferences.cachedCurrent());
            edgeOnline = current.optJSONObject("edge") != null
                    && current.optJSONObject("edge").optBoolean("online", false);
            lastUpdate = current.optString("last_update", "non disponibile");
        } catch (Exception ignored) {
            // La cache puo' essere vuota prima della prima sincronizzazione.
        }
        String syncTime = preferences.lastBackendSyncAt() == 0
                ? "mai"
                : DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT)
                .format(new Date(preferences.lastBackendSyncAt()));
        connectionStatusText.setText(
                "Raspberry: " + (edgeOnline ? "online" : "non raggiungibile dal Cloud")
                        + "\nInvio BLE: " + (preferences.bleConnected() ? "attivo" : "in attesa")
                        + roomSuffix(preferences.lastBleRoom())
                        + "\nBackend: " + preferences.backendSyncStatus()
                        + "\nUltimo dato Edge: " + lastUpdate
                        + "\nUltima sincronizzazione app: " + syncTime
        );
    }

    private void renderTasksAndMessages() {
        tasksContainer.removeAllViews();
        notificationsContainer.removeAllViews();
        int taskCount = 0;
        int messageCount = 0;
        try {
            JSONArray tasks = new JSONObject(preferences.cachedTasks()).optJSONArray("items");
            if (tasks != null) {
                for (int index = 0; index < tasks.length(); index++) {
                    JSONObject task = tasks.getJSONObject(index);
                    if (isPatientMessage(task)) {
                        addPatientMessage(task);
                        messageCount++;
                    } else if (!"completed".equals(task.optString("status"))
                            && !"cancelled".equals(task.optString("status"))
                            && !"expired".equals(task.optString("status"))) {
                        addTask(task);
                        taskCount++;
                    }
                }
            }
            JSONArray notifications = new JSONObject(preferences.cachedNotifications()).optJSONArray("items");
            if (notifications != null) {
                for (int index = 0; index < notifications.length(); index++) {
                    addNotification(notifications.getJSONObject(index));
                    messageCount++;
                }
            }
        } catch (Exception ignored) {
            // Una cache incompleta non deve interrompere il monitoraggio BLE.
        }
        if (taskCount == 0) {
            tasksContainer.addView(emptyText("Nessuna attivita' da completare."));
        }
        if (messageCount == 0) {
            notificationsContainer.addView(emptyText("Nessun nuovo messaggio."));
        }
    }

    private void addTask(JSONObject task) {
        String title = task.optString("title", "Nuova attivita'");
        String subtitle = task.optString("instructions", "Apri per visualizzare i dettagli.");
        View row = informationRow(title, subtitle, "Apri");
        row.setOnClickListener(view -> openTask(task));
        tasksContainer.addView(row);
        markTaskSeenOnce(task);
    }

    private void addPatientMessage(JSONObject task) {
        JSONObject message = task.optJSONObject("payload") == null
                ? null : task.optJSONObject("payload").optJSONObject("message");
        String title = message == null ? task.optString("title", "Messaggio") : message.optString("title", "Messaggio");
        String body = message == null ? task.optString("instructions", "") : message.optString("body", "");
        notificationsContainer.addView(informationRow(title, body, "Dal team di cura"));
        markTaskSeenOnce(task);
    }

    private void addNotification(JSONObject notification) {
        View row = informationRow(
                notification.optString("title", "Messaggio"),
                notification.optString("body", "Apri per i dettagli."),
                "seen".equals(notification.optString("status")) ? "Letto" : "Nuovo"
        );
        row.setOnClickListener(view -> executor.execute(() -> {
            try {
                new BackendApiClient(this).markNotificationSeen(notification.getString("notification_id"));
                PatientSyncManager.synchronize(this);
            } catch (Exception ignored) {
                // La notifica resta disponibile e verra' ritentata al prossimo sync.
            }
        }));
        notificationsContainer.addView(row);
    }

    private View informationRow(String title, String subtitle, String action) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setBackgroundResource(R.drawable.bg_beacon_summary);
        int padding = dp(13);
        row.setPadding(padding, padding, padding, padding);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        params.bottomMargin = dp(8);
        row.setLayoutParams(params);

        TextView titleView = new TextView(this);
        titleView.setText(title);
        titleView.setTextColor(getColor(R.color.text_primary));
        titleView.setTextSize(15);
        titleView.setTypeface(null, android.graphics.Typeface.BOLD);
        row.addView(titleView);

        TextView subtitleView = new TextView(this);
        subtitleView.setText(subtitle);
        subtitleView.setTextColor(getColor(R.color.text_secondary));
        subtitleView.setTextSize(13);
        subtitleView.setPadding(0, dp(5), 0, 0);
        row.addView(subtitleView);

        TextView actionView = new TextView(this);
        actionView.setText(action);
        actionView.setTextColor(getColor(R.color.primary));
        actionView.setTextSize(12);
        actionView.setTypeface(null, android.graphics.Typeface.BOLD);
        actionView.setPadding(0, dp(8), 0, 0);
        row.addView(actionView);
        return row;
    }

    private TextView emptyText(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(getColor(R.color.text_secondary));
        view.setTextSize(13);
        view.setPadding(0, dp(8), 0, dp(8));
        return view;
    }

    private void openTask(JSONObject task) {
        executor.execute(() -> {
            try {
                new BackendApiClient(this).updateTaskState(
                        task.getString("task_id"),
                        "seen",
                        java.time.Instant.now().toString()
                );
            } catch (Exception ignored) {
                // L'apertura resta possibile offline; lo started verra' ritentato dal test.
            }
        });
        startActivity(new Intent(this, TaskActivity.class).putExtra("task_json", task.toString()));
    }

    private void markTaskSeenOnce(JSONObject task) {
        String taskId = task.optString("task_id");
        if (taskId.isEmpty() || !"created".equals(task.optString("status"))) {
            return;
        }
        java.util.Set<String> seen = new java.util.HashSet<>(
                preferences.raw().getStringSet("locallySeenTaskIds", new java.util.HashSet<>())
        );
        if (seen.contains(taskId)) {
            return;
        }
        executor.execute(() -> {
            try {
                java.util.Set<String> latestSeen = new java.util.HashSet<>(
                        preferences.raw().getStringSet("locallySeenTaskIds", new java.util.HashSet<>())
                );
                if (latestSeen.contains(taskId)) {
                    return;
                }
                new BackendApiClient(this).updateTaskState(taskId, "seen", java.time.Instant.now().toString());
                latestSeen.add(taskId);
                preferences.raw().edit().putStringSet("locallySeenTaskIds", latestSeen).apply();
            } catch (Exception ignored) {
                // Il task verra' nuovamente marcato al prossimo aggiornamento utile.
            }
        });
    }

    private boolean isPatientMessage(JSONObject task) {
        JSONObject payload = task.optJSONObject("payload");
        return payload != null && "patient_message".equals(payload.optString("kind"));
    }

    private void confirmLogout() {
        new AlertDialog.Builder(this)
                .setTitle("Uscire dal profilo?")
                .setMessage("Il monitoraggio BLE resta attivo, ma task e messaggi non verranno sincronizzati.")
                .setNegativeButton("Annulla", null)
                .setPositiveButton("Esci", (dialog, which) -> {
                    preferences.clearSession();
                    renderScreen();
                })
                .show();
    }

    private void requestAdminAccess() {
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        container.setPadding(dp(20), dp(8), dp(20), 0);
        EditText username = new EditText(this);
        username.setHint("Nome utente");
        username.setSingleLine(true);
        EditText password = new EditText(this);
        password.setHint("Password");
        password.setSingleLine(true);
        password.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        container.addView(username);
        container.addView(password);
        new AlertDialog.Builder(this)
                .setTitle("Area amministrativa")
                .setView(container)
                .setNegativeButton("Annulla", null)
                .setPositiveButton("Continua", (dialog, which) -> {
                    if (ADMIN_USERNAME.equals(username.getText().toString().trim())
                            && ADMIN_PASSWORD.equals(password.getText().toString())) {
                        startActivity(new Intent(this, AdminSettingsActivity.class));
                    } else {
                        Toast.makeText(this, "Credenziali amministrative non valide.", Toast.LENGTH_SHORT).show();
                    }
                })
                .show();
    }

    private void ensureMonitoringStarted() {
        if (!hasRequiredPermissions()) {
            requestRequiredPermissions();
            return;
        }
        Intent service = new Intent(this, BleMonitoringService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(service);
        } else {
            startService(service);
        }
    }

    private boolean hasRequiredPermissions() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            return false;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                && (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED)) {
            return false;
        }
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU
                || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
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

    private void requestBatteryOptimizationExemptionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return;
        }
        PowerManager manager = (PowerManager) getSystemService(POWER_SERVICE);
        if (manager == null || manager.isIgnoringBatteryOptimizations(getPackageName())) {
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("Monitoraggio anche a schermo spento")
                .setMessage("Consenti all'app di lavorare senza limitazioni della batteria per mantenere attivi beacon e sincronizzazione.")
                .setNegativeButton("Dopo", null)
                .setPositiveButton("Consenti", (dialog, which) -> {
                    Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                    intent.setData(Uri.parse("package:" + getPackageName()));
                    startActivity(intent);
                })
                .show();
    }

    private void requestBackgroundLocationSettingsIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q || Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            return;
        }
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED) {
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("Rilevamento in background")
                .setMessage("Nelle autorizzazioni imposta la posizione su 'Consenti sempre' per rilevare i beacon anche a schermo spento.")
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
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_PERMISSIONS && hasRequiredPermissions()) {
            ensureMonitoringStarted();
        }
        renderScreen();
    }

    private String roomSuffix(String room) {
        return room == null || room.isEmpty() ? "" : " (" + room + ")";
    }

    private String shortDeviceId(String value) {
        return value.length() <= 20 ? value : value.substring(0, 12) + "...";
    }

    private String userMessage(Exception exception) {
        String message = exception.getMessage();
        return message == null || message.isEmpty() ? "Connessione non disponibile." : message;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
