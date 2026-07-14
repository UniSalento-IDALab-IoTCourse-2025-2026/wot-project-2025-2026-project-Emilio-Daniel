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

import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
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
    private TextView wellnessTitle;
    private TextView wellnessDetail;
    private TextView roomText;
    private TextView heartRateValue;
    private TextView heartRateHint;
    private TextView spo2Value;
    private TextView spo2Hint;
    private TextView stepsValue;
    private TextView stepsHint;
    private TextView sleepValue;
    private TextView sleepHint;
    private TextView trendSummaryText;
    private TextView connectionStatusText;
    private TextView offlineQueueText;
    private LinearLayout tasksContainer;
    private LinearLayout notificationsContainer;
    private HealthTrendView heartRateChart;
    private HealthTrendView spo2Chart;

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
        wellnessTitle = findViewById(R.id.wellnessTitle);
        wellnessDetail = findViewById(R.id.wellnessDetail);
        roomText = findViewById(R.id.roomText);
        heartRateValue = findViewById(R.id.heartRateValue);
        heartRateHint = findViewById(R.id.heartRateHint);
        spo2Value = findViewById(R.id.spo2Value);
        spo2Hint = findViewById(R.id.spo2Hint);
        stepsValue = findViewById(R.id.stepsValue);
        stepsHint = findViewById(R.id.stepsHint);
        sleepValue = findViewById(R.id.sleepValue);
        sleepHint = findViewById(R.id.sleepHint);
        trendSummaryText = findViewById(R.id.trendSummaryText);
        connectionStatusText = findViewById(R.id.connectionStatusText);
        offlineQueueText = findViewById(R.id.offlineQueueText);
        tasksContainer = findViewById(R.id.tasksContainer);
        notificationsContainer = findViewById(R.id.notificationsContainer);
        heartRateChart = findViewById(R.id.heartRateChart);
        spo2Chart = findViewById(R.id.spo2Chart);
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
        String patientName = firstName(preferences.patientDisplayName());
        welcomeText.setText(patientName.isEmpty() ? greeting() : greeting() + ", " + patientName);
        patientBindingText.setText("Il tuo spazio personale • " + formatSyncTime());
        monitoringStatusText.setText(
                preferences.serviceRunning() ? "Monitoraggio attivo" : "Monitoraggio da riavviare"
        );
        renderWellnessAndMetrics();
        renderTrends();
        renderConnections();
        renderTasksAndMessages();
        int pending = new OfflineResultQueue(this).size();
        offlineQueueText.setText(
                pending == 0
                        ? "Tutto sincronizzato. I risultati inviati sono al sicuro."
                        : pending + " risultati protetti sul telefono, in attesa di connessione."
        );
    }

    private void renderWellnessAndMetrics() {
        JSONObject current = cachedObject(preferences.cachedCurrent());
        JSONObject features = latestFeatures();
        String level = current.optString("level", "green");
        if ("green".equals(level)) {
            wellnessTitle.setText("Tutto procede regolarmente");
            wellnessDetail.setText("Le ultime informazioni disponibili sono coerenti con il tuo andamento abituale.");
        } else if ("yellow".equals(level)) {
            wellnessTitle.setText("Qualche dato merita attenzione");
            wellnessDetail.setText("Il team di cura può rivedere le ultime rilevazioni. Non è una diagnosi.");
        } else if ("orange".equals(level) || "red".equals(level)) {
            wellnessTitle.setText("Il team sta verificando i dati");
            wellnessDetail.setText("Continua a seguire le indicazioni ricevute e contatta il team se non ti senti bene.");
        } else {
            wellnessTitle.setText("Aggiornamento dei dati in corso");
            wellnessDetail.setText("Alcune informazioni non sono ancora disponibili. Il monitoraggio continua in background.");
        }

        String room = current.optString("current_room", preferences.lastBleRoom());
        roomText.setText("Stanza\n" + prettyRoom(room));

        setMetric(heartRateValue, heartRateHint, features, "heart_rate_mean", " bpm", "Media dell'ultima finestra");
        setMetric(spo2Value, spo2Hint, features, "spo2_mean", " %", "Ultimo valore disponibile");

        JSONArray windows = cachedItems(preferences.cachedWindows());
        double stepTotal = 0.0;
        int stepSamples = 0;
        for (int index = 0; index < windows.length(); index++) {
            JSONObject item = windows.optJSONObject(index);
            JSONObject windowFeatures = item == null ? null : item.optJSONObject("features");
            Double steps = numberOrNull(windowFeatures, "steps");
            if (steps != null) {
                stepTotal += Math.max(0.0, steps);
                stepSamples++;
            }
        }
        if (stepSamples > 0) {
            stepsValue.setText(String.format(Locale.ITALY, "%,.0f", stepTotal));
            stepsHint.setText("Nelle rilevazioni mostrate");
        } else {
            stepsValue.setText("--");
            stepsHint.setText("Dato non disponibile");
        }

        Double sleep = numberOrNull(features, "sleep_minutes");
        if (sleep != null) {
            sleepValue.setText(formatDuration(sleep));
            sleepHint.setText("Ultimo riepilogo disponibile");
        } else {
            sleepValue.setText("--");
            sleepHint.setText("Dato non disponibile");
        }
    }

    private void renderTrends() {
        JSONArray windows = cachedItems(preferences.cachedWindows());
        int start = Math.max(0, windows.length() - 30);
        int count = windows.length() - start;
        float[] heartRate = new float[count];
        float[] spo2 = new float[count];
        String[] labels = new String[count];
        int validHeartRate = 0;
        int validSpo2 = 0;
        for (int index = 0; index < count; index++) {
            JSONObject window = windows.optJSONObject(start + index);
            JSONObject features = window == null ? null : window.optJSONObject("features");
            Double heart = numberOrNull(features, "heart_rate_mean");
            Double oxygen = numberOrNull(features, "spo2_mean");
            heartRate[index] = heart == null ? Float.NaN : heart.floatValue();
            spo2[index] = oxygen == null ? Float.NaN : oxygen.floatValue();
            if (heart != null) {
                validHeartRate++;
            }
            if (oxygen != null) {
                validSpo2++;
            }
            labels[index] = formatChartTime(window == null ? null : window.optString("window_end", null));
        }
        heartRateChart.setSeries("bpm", getColor(R.color.coral), heartRate, labels);
        spo2Chart.setSeries("%", getColor(R.color.sky), spo2, labels, 88f, 100f);
        int totalValid = Math.max(validHeartRate, validSpo2);
        trendSummaryText.setText(totalValid == 0
                ? "In attesa di dati"
                : totalValid + (totalValid == 1 ? " rilevazione" : " rilevazioni"));
    }

    private void renderConnections() {
        boolean edgeOnline = false;
        String lastUpdate = null;
        try {
            JSONObject current = new JSONObject(preferences.cachedCurrent());
            edgeOnline = current.optJSONObject("edge") != null
                    && current.optJSONObject("edge").optBoolean("online", false);
            lastUpdate = current.optString("last_update", null);
        } catch (Exception ignored) {
            // La cache puo' essere vuota prima della prima sincronizzazione.
        }
        connectionStatusText.setText(
                "Collegamento di casa  •  " + (edgeOnline ? "attivo" : "in aggiornamento")
                        + "\nPosizione indoor  •  " + (preferences.bleConnected() ? "attiva" : "in attesa")
                        + (preferences.lastBleRoom().isEmpty() ? "" : " · " + prettyRoom(preferences.lastBleRoom()))
                        + "\nServizi clinici  •  " + ("online".equals(preferences.backendSyncStatus()) ? "connessi" : "temporaneamente offline")
                        + "\nUltimo dato  •  " + formatTimestamp(lastUpdate)
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
            tasksContainer.addView(emptyText("Nessuna attività da completare. Ti avviseremo quando ce ne sarà una nuova."));
        }
        if (messageCount == 0) {
            notificationsContainer.addView(emptyText("Nessun nuovo messaggio."));
        }
    }

    private void addTask(JSONObject task) {
        String title = task.optString("title", "Nuova attività");
        String subtitle = task.optString("instructions", "Apri per visualizzare i dettagli.");
        View row = taskRow(task, title, subtitle);
        row.setOnClickListener(view -> openTask(task));
        tasksContainer.addView(row);
        markTaskSeenOnce(task);
    }

    private void addPatientMessage(JSONObject task) {
        JSONObject message = task.optJSONObject("payload") == null
                ? null : task.optJSONObject("payload").optJSONObject("message");
        String title = message == null ? task.optString("title", "Messaggio") : message.optString("title", "Messaggio");
        String body = message == null ? task.optString("instructions", "") : message.optString("body", "");
        notificationsContainer.addView(informationRow(title, body, "Dal team di cura", true));
        markTaskSeenOnce(task);
    }

    private void addNotification(JSONObject notification) {
        View row = informationRow(
                notification.optString("title", "Messaggio"),
                notification.optString("body", "Apri per i dettagli."),
                "seen".equals(notification.optString("status")) ? "Letto" : "Nuovo",
                false
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

    private View taskRow(JSONObject task, String title, String subtitle) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setBackgroundResource(R.drawable.bg_task_card);
        int padding = dp(14);
        row.setPadding(padding, padding, padding, padding);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        params.bottomMargin = dp(8);
        row.setLayoutParams(params);

        TextView metaView = new TextView(this);
        metaView.setText(taskLabel(task));
        metaView.setTextColor(getColor(R.color.primary));
        metaView.setTextSize(11);
        metaView.setTypeface(null, android.graphics.Typeface.BOLD);
        row.addView(metaView);

        TextView titleView = new TextView(this);
        titleView.setText(title);
        titleView.setTextColor(getColor(R.color.text_primary));
        titleView.setTextSize(16);
        titleView.setTypeface(null, android.graphics.Typeface.BOLD);
        titleView.setPadding(0, dp(7), 0, 0);
        row.addView(titleView);

        TextView subtitleView = new TextView(this);
        subtitleView.setText(subtitle);
        subtitleView.setTextColor(getColor(R.color.text_secondary));
        subtitleView.setTextSize(13);
        subtitleView.setPadding(0, dp(5), 0, 0);
        subtitleView.setMaxLines(3);
        row.addView(subtitleView);

        LinearLayout footer = new LinearLayout(this);
        footer.setOrientation(LinearLayout.HORIZONTAL);
        footer.setGravity(android.view.Gravity.CENTER_VERTICAL);
        footer.setPadding(0, dp(11), 0, 0);
        TextView dueView = new TextView(this);
        dueView.setLayoutParams(new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
        dueView.setText(taskDueLabel(task));
        dueView.setTextColor(getColor(R.color.text_secondary));
        dueView.setTextSize(11);
        footer.addView(dueView);
        TextView actionView = new TextView(this);
        actionView.setText("Inizia attività");
        actionView.setTextColor(getColor(R.color.primary));
        actionView.setTextSize(12);
        actionView.setTypeface(null, android.graphics.Typeface.BOLD);
        footer.addView(actionView);
        row.addView(footer);
        row.setContentDescription(title + ". " + taskDueLabel(task) + ". Inizia attività.");
        return row;
    }

    private View informationRow(String title, String subtitle, String action, boolean fromCareTeam) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setBackgroundResource(fromCareTeam ? R.drawable.bg_health_status : R.drawable.bg_task_card);
        int padding = dp(14);
        row.setPadding(padding, padding, padding, padding);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        params.bottomMargin = dp(8);
        row.setLayoutParams(params);

        TextView badge = new TextView(this);
        badge.setText(action);
        badge.setTextColor(getColor(R.color.primary));
        badge.setTextSize(11);
        badge.setTypeface(null, android.graphics.Typeface.BOLD);
        row.addView(badge);

        TextView titleView = new TextView(this);
        titleView.setText(title);
        titleView.setTextColor(getColor(R.color.text_primary));
        titleView.setTextSize(15);
        titleView.setTypeface(null, android.graphics.Typeface.BOLD);
        titleView.setPadding(0, dp(7), 0, 0);
        row.addView(titleView);

        TextView subtitleView = new TextView(this);
        subtitleView.setText(subtitle);
        subtitleView.setTextColor(getColor(R.color.text_secondary));
        subtitleView.setTextSize(13);
        subtitleView.setLineSpacing(0, 1.08f);
        subtitleView.setPadding(0, dp(5), 0, 0);
        row.addView(subtitleView);
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

    private JSONObject cachedObject(String source) {
        try {
            return new JSONObject(source);
        } catch (Exception ignored) {
            return new JSONObject();
        }
    }

    private JSONArray cachedItems(String source) {
        JSONArray items = cachedObject(source).optJSONArray("items");
        return items == null ? new JSONArray() : items;
    }

    private JSONObject latestFeatures() {
        JSONArray windows = cachedItems(preferences.cachedWindows());
        for (int index = windows.length() - 1; index >= 0; index--) {
            JSONObject item = windows.optJSONObject(index);
            JSONObject features = item == null ? null : item.optJSONObject("features");
            if (features != null) {
                return features;
            }
        }
        return new JSONObject();
    }

    private Double numberOrNull(JSONObject object, String key) {
        if (object == null || !object.has(key) || object.isNull(key)) {
            return null;
        }
        Object value = object.opt(key);
        if (value instanceof Number) {
            double number = ((Number) value).doubleValue();
            return Double.isFinite(number) ? number : null;
        }
        try {
            double number = Double.parseDouble(String.valueOf(value));
            return Double.isFinite(number) ? number : null;
        } catch (Exception ignored) {
            return null;
        }
    }

    private void setMetric(
            TextView valueView,
            TextView hintView,
            JSONObject features,
            String key,
            String suffix,
            String availableHint
    ) {
        Double value = numberOrNull(features, key);
        if (value == null) {
            valueView.setText("--" + suffix);
            hintView.setText("Dato non disponibile");
            return;
        }
        String formatted = Math.abs(value - Math.rint(value)) < 0.05
                ? String.format(Locale.ITALY, "%.0f", value)
                : String.format(Locale.ITALY, "%.1f", value);
        valueView.setText(formatted + suffix);
        hintView.setText(availableHint);
    }

    private String greeting() {
        int hour = java.time.LocalTime.now().getHour();
        if (hour < 12) {
            return "Buongiorno";
        }
        if (hour < 18) {
            return "Buon pomeriggio";
        }
        return "Buonasera";
    }

    private String firstName(String displayName) {
        if (displayName == null || displayName.trim().isEmpty()) {
            return "";
        }
        String value = displayName.trim();
        if (value.toLowerCase(Locale.ITALY).startsWith("patient-")) {
            return "";
        }
        return value.split("\\s+")[0];
    }

    private String formatSyncTime() {
        long timestamp = preferences.lastBackendSyncAt();
        if (timestamp == 0L) {
            return "primo aggiornamento in corso";
        }
        String value = java.time.Instant.ofEpochMilli(timestamp)
                .atZone(ZoneId.systemDefault())
                .format(DateTimeFormatter.ofPattern("HH:mm", Locale.ITALY));
        return "aggiornato alle " + value;
    }

    private String formatTimestamp(String value) {
        if (value == null || value.isEmpty()) {
            return "non ancora disponibile";
        }
        try {
            OffsetDateTime dateTime = OffsetDateTime.parse(value);
            DateTimeFormatter formatter = DateTimeFormatter.ofPattern("dd MMM, HH:mm", Locale.ITALY);
            return dateTime.atZoneSameInstant(ZoneId.systemDefault()).format(formatter);
        } catch (Exception ignored) {
            return value;
        }
    }

    private String formatChartTime(String value) {
        if (value == null || value.isEmpty()) {
            return "";
        }
        try {
            return OffsetDateTime.parse(value)
                    .atZoneSameInstant(ZoneId.systemDefault())
                    .format(DateTimeFormatter.ofPattern("HH:mm", Locale.ITALY));
        } catch (Exception ignored) {
            return "";
        }
    }

    private String formatDuration(double minutes) {
        int rounded = Math.max(0, (int) Math.round(minutes));
        int hours = rounded / 60;
        int remainder = rounded % 60;
        if (hours > 0) {
            return hours + " h " + remainder + " min";
        }
        return remainder + " min";
    }

    private String prettyRoom(String room) {
        if (room == null || room.isEmpty() || "null".equals(room)) {
            return "--";
        }
        switch (room) {
            case "kitchen":
                return "Cucina";
            case "bedroom":
                return "Camera";
            case "bathroom":
                return "Bagno";
            case "living_room":
                return "Soggiorno";
            default:
                return room.replace('_', ' ');
        }
    }

    private String taskLabel(JSONObject task) {
        String type = task.optString("type", "activity");
        String label;
        if ("check_in".equals(type)) {
            label = "CHECK-IN BENESSERE";
        } else if ("cognitive_test".equals(type)) {
            label = "ATTIVITÀ COGNITIVA";
        } else if ("medication_reminder".equals(type)) {
            label = "PROMEMORIA";
        } else {
            label = "ATTIVITÀ";
        }
        String priority = task.optString("priority", "normal");
        if ("high".equals(priority) || "urgent".equals(priority)) {
            return label + "  •  PRIORITÀ ALTA";
        }
        return label;
    }

    private String taskDueLabel(JSONObject task) {
        String due = task.optString("due_at", task.optString("expires_at", null));
        if (due == null || due.isEmpty() || "null".equals(due)) {
            return "Nessuna scadenza";
        }
        return "Entro " + formatTimestamp(due);
    }

    private String userMessage(Exception exception) {
        String message = exception.getMessage();
        return message == null || message.isEmpty() ? "Connessione non disponibile." : message;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
