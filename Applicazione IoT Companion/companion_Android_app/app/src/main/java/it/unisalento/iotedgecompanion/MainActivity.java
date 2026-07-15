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
import android.os.BatteryManager;
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
    private LinearLayout caregiverPanel;
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
    private TextView caregiverWelcomeText;
    private TextView caregiverPatientText;
    private TextView caregiverStatusBadge;
    private TextView caregiverStatusText;
    private TextView caregiverUpdateText;
    private TextView caregiverTechnicalText;
    private LinearLayout caregiverAlertsContainer;
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
        if ("caregiver".equals(preferences.userRole())) {
            synchronizeCaregiverNow();
        } else if (preferences.isAuthenticated()) {
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
        caregiverPanel = findViewById(R.id.caregiverPanel);
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
        caregiverWelcomeText = findViewById(R.id.caregiverWelcomeText);
        caregiverPatientText = findViewById(R.id.caregiverPatientText);
        caregiverStatusBadge = findViewById(R.id.caregiverStatusBadge);
        caregiverStatusText = findViewById(R.id.caregiverStatusText);
        caregiverUpdateText = findViewById(R.id.caregiverUpdateText);
        caregiverTechnicalText = findViewById(R.id.caregiverTechnicalText);
        caregiverAlertsContainer = findViewById(R.id.caregiverAlertsContainer);
        heartRateChart = findViewById(R.id.heartRateChart);
        spo2Chart = findViewById(R.id.spo2Chart);
    }

    private void configureActions() {
        findViewById(R.id.loginButton).setOnClickListener(view -> login());
        findViewById(R.id.refreshButton).setOnClickListener(view -> synchronizeNow());
        findViewById(R.id.caregiverRefreshButton).setOnClickListener(view -> synchronizeCaregiverNow());
        findViewById(R.id.logoutButton).setOnClickListener(view -> confirmLogout());
        findViewById(R.id.caregiverLogoutButton).setOnClickListener(view -> confirmLogout());
        findViewById(R.id.adminSettingsButton).setOnClickListener(view -> requestAdminAccess());
        findViewById(R.id.caregiverAdminSettingsButton).setOnClickListener(view -> requestAdminAccess());
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
                JSONObject session = new BackendApiClient(this).authenticateCompanion(email, password);
                runOnUiThread(() -> {
                    passwordInput.setText("");
                    renderScreen();
                    if ("caregiver".equals(session.optString("role"))) {
                        synchronizeCaregiverNow();
                    } else {
                        synchronizeNow();
                    }
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

    private void synchronizeCaregiverNow() {
        caregiverStatusText.setText("Aggiornamento in corso");
        executor.execute(() -> {
            try {
                BackendApiClient client = new BackendApiClient(this);
                JSONObject overview = client.fetchCaregiverOverview();
                registerCaregiverDevices(client, overview);
                preferences.cacheCaregiverOverview(overview.toString());
                runOnUiThread(this::renderScreen);
            } catch (Exception exception) {
                preferences.setBackendError(userMessage(exception));
                runOnUiThread(() -> {
                    caregiverStatusText.setText("Connessione non disponibile");
                    caregiverUpdateText.setText(userMessage(exception));
                    renderCaregiverScreen();
                });
            }
        });
    }

    private void renderScreen() {
        boolean authenticated = preferences.isAuthenticated();
        boolean caregiver = authenticated && "caregiver".equals(preferences.userRole());
        loginPanel.setVisibility(authenticated ? View.GONE : View.VISIBLE);
        caregiverPanel.setVisibility(caregiver ? View.VISIBLE : View.GONE);
        dailyPanel.setVisibility(authenticated && !caregiver ? View.VISIBLE : View.GONE);
        if (!authenticated) {
            return;
        }
        if (caregiver) {
            renderCaregiverScreen();
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

    private void renderCaregiverScreen() {
        JSONObject overview = cachedObject(preferences.cachedCaregiverOverview());
        JSONArray patients = overview.optJSONArray("items");
        JSONObject patient = patients == null || patients.length() == 0 ? new JSONObject() : patients.optJSONObject(0);
        if (patient == null) {
            patient = new JSONObject();
        }
        caregiverWelcomeText.setText("Area caregiver");
        caregiverPatientText.setText(patient.optString("display_name", preferences.patientDisplayName()) + "  •  " + formatSyncTime());
        String level = patient.optString("level", "green");
        caregiverStatusBadge.setText(caregiverLevelLabel(level));
        caregiverStatusText.setText(patient.optString("general_status", "Monitoraggio in aggiornamento."));
        caregiverUpdateText.setText("Ultimo aggiornamento: " + formatTimestamp(patient.optString("last_update", null)));

        JSONObject technical = patient.optJSONObject("technical_status");
        caregiverTechnicalText.setText(caregiverTechnicalLabel(technical));
        renderCaregiverAlerts(patient.optJSONArray("alerts"));
    }

    private void renderCaregiverAlerts(JSONArray alerts) {
        caregiverAlertsContainer.removeAllViews();
        if (alerts == null || alerts.length() == 0) {
            caregiverAlertsContainer.addView(emptyText("Nessuna segnalazione importante pubblicata."));
            return;
        }
        for (int index = 0; index < alerts.length(); index++) {
            JSONObject alert = alerts.optJSONObject(index);
            if (alert == null) {
                continue;
            }
            caregiverAlertsContainer.addView(caregiverAlertRow(alert));
        }
    }

    private View caregiverAlertRow(JSONObject alert) {
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

        TextView badge = new TextView(this);
        badge.setText(caregiverLevelLabel(alert.optString("level", "orange")) + "  •  " + caregiverAlertStatus(alert));
        badge.setTextColor(getColor(R.color.primary));
        badge.setTextSize(11);
        badge.setTypeface(null, android.graphics.Typeface.BOLD);
        row.addView(badge);

        TextView title = new TextView(this);
        title.setText(alert.optString("title", "Segnalazione importante"));
        title.setTextColor(getColor(R.color.text_primary));
        title.setTextSize(16);
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        title.setPadding(0, dp(7), 0, 0);
        row.addView(title);

        TextView description = new TextView(this);
        description.setText(alert.optString("description", "Apri la dashboard o contatta il team se richiesto."));
        description.setTextColor(getColor(R.color.text_secondary));
        description.setTextSize(13);
        description.setPadding(0, dp(5), 0, 0);
        row.addView(description);

        addInfoHint(row, "Aperta: " + formatTimestamp(alert.optString("opened_at", null)));
        if (!alert.optString("acknowledged_by", "").isEmpty()) {
            addInfoHint(row, "Gia' presa in carico da " + alert.optString("acknowledged_by")
                    + " (" + caregiverRoleLabel(alert.optString("acknowledged_role", "")) + ").");
        } else {
            addInlineAction(row, "Prendi in carico", view -> confirmAcknowledgeAlert(alert));
        }
        return row;
    }

    private void registerCaregiverDevices(BackendApiClient client, JSONObject overview) throws Exception {
        JSONArray patients = overview.optJSONArray("items");
        if (patients == null) {
            return;
        }
        boolean notificationsEnabled = PatientNotificationHelper.notificationsEnabled(this);
        String fcmToken = preferences.fcmToken();
        for (int index = 0; index < patients.length(); index++) {
            JSONObject patient = patients.optJSONObject(index);
            if (patient == null) {
                continue;
            }
            String patientId = patient.optString("patient_id");
            if (patientId.isEmpty()) {
                continue;
            }
            if (!fcmToken.isEmpty()) {
                client.registerCaregiverDevice(patientId, fcmToken, notificationsEnabled);
            } else if (preferences.shouldSendHeartbeat()) {
                client.sendCaregiverHeartbeat(patientId, readBatteryPercentageForCaregiver(), notificationsEnabled);
            }
        }
        preferences.markHeartbeatSent();
    }

    private void confirmAcknowledgeAlert(JSONObject alert) {
        new AlertDialog.Builder(this)
                .setTitle("Prendere in carico?")
                .setMessage("Il medico e gli altri caregiver vedranno che stai seguendo questa segnalazione.")
                .setNegativeButton("Annulla", null)
                .setPositiveButton("Conferma", (dialog, which) -> acknowledgeAlert(alert))
                .show();
    }

    private void acknowledgeAlert(JSONObject alert) {
        executor.execute(() -> {
            try {
                new BackendApiClient(this).acknowledgeAlert(alert.getString("alert_id"));
                synchronizeCaregiverNow();
                runOnUiThread(() -> Toast.makeText(this, "Segnalazione presa in carico.", Toast.LENGTH_SHORT).show());
            } catch (Exception exception) {
                runOnUiThread(() -> Toast.makeText(this, userMessage(exception), Toast.LENGTH_SHORT).show());
            }
        });
    }

    private double readBatteryPercentageForCaregiver() {
        Intent battery = registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (battery == null) {
            return -1.0;
        }
        int level = battery.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
        int scale = battery.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
        if (level < 0 || scale <= 0) {
            return -1.0;
        }
        return (level * 100.0) / scale;
    }

    private String caregiverLevelLabel(String level) {
        if ("red".equals(level)) {
            return "Massima allerta";
        }
        if ("orange".equals(level)) {
            return "Rischio";
        }
        if ("technical".equals(level)) {
            return "Problema tecnico";
        }
        return "Situazione stabile";
    }

    private String caregiverAlertStatus(JSONObject alert) {
        String status = alert.optString("status", "new");
        if ("acknowledged".equals(status)) {
            return "Presa in carico";
        }
        if ("resolved".equals(status)) {
            return "Risolta";
        }
        return "Da seguire";
    }

    private String caregiverRoleLabel(String role) {
        if ("doctor".equals(role)) {
            return "medico";
        }
        if ("caregiver".equals(role)) {
            return "caregiver";
        }
        if ("admin".equals(role)) {
            return "amministratore";
        }
        return "operatore";
    }

    private String caregiverTechnicalLabel(JSONObject technical) {
        if (technical == null) {
            return "Stato tecnico in aggiornamento.";
        }
        JSONArray issues = technical.optJSONArray("issues");
        if (issues == null || issues.length() == 0) {
            return "Raspberry e dispositivi risultano operativi.";
        }
        StringBuilder builder = new StringBuilder("Da verificare: ");
        for (int index = 0; index < issues.length(); index++) {
            if (index > 0) {
                builder.append(" ");
            }
            builder.append(issues.optString(index));
        }
        return builder.toString();
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
                    if ("dismissed".equals(task.optString("status"))) {
                        continue;
                    }
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
        LinearLayout row = informationRow(title, body, "Dal team di cura", true);
        addInlineAction(row, "Elimina", view -> confirmDismissTask(task));
        notificationsContainer.addView(row);
        markTaskSeenOnce(task);
    }

    private void addNotification(JSONObject notification) {
        LinearLayout row = informationRow(
                notification.optString("title", "Messaggio"),
                notification.optString("body", "Apri per i dettagli."),
                "seen".equals(notification.optString("status")) ? "Letto" : "Nuovo",
                false
        );
        if (canDismissNotification(notification)) {
            addInlineAction(row, "Elimina", view -> dismissNotification(notification));
        } else if (isTaskNotification(notification)) {
            addInfoHint(row, "Potrai eliminarla dopo aver completato l'attivita'.");
        }
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

    private LinearLayout informationRow(String title, String subtitle, String action, boolean fromCareTeam) {
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

    private void addInlineAction(LinearLayout row, String label, View.OnClickListener listener) {
        LinearLayout footer = new LinearLayout(this);
        footer.setGravity(android.view.Gravity.END | android.view.Gravity.CENTER_VERTICAL);
        footer.setPadding(0, dp(10), 0, 0);

        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextSize(12);
        button.setTextColor(getColor(R.color.primary));
        button.setBackgroundResource(R.drawable.bg_button_secondary);
        button.setMinHeight(0);
        button.setMinimumHeight(0);
        button.setPadding(dp(14), dp(7), dp(14), dp(7));
        button.setOnClickListener(listener);
        footer.addView(button);
        row.addView(footer);
    }

    private void addInfoHint(LinearLayout row, String text) {
        TextView hint = new TextView(this);
        hint.setText(text);
        hint.setTextColor(getColor(R.color.text_secondary));
        hint.setTextSize(11);
        hint.setPadding(0, dp(9), 0, 0);
        row.addView(hint);
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

    private boolean isTaskNotification(JSONObject notification) {
        JSONObject payload = notification.optJSONObject("payload");
        return payload != null && !payload.optString("task_id", "").isEmpty();
    }

    private boolean canDismissNotification(JSONObject notification) {
        JSONObject payload = notification.optJSONObject("payload");
        if (payload == null || payload.optString("task_id", "").isEmpty()) {
            return true;
        }
        JSONObject task = findCachedTask(payload.optString("task_id"));
        return task != null && (isPatientMessage(task) || "completed".equals(task.optString("status")));
    }

    private JSONObject findCachedTask(String taskId) {
        if (taskId == null || taskId.isEmpty()) {
            return null;
        }
        try {
            JSONArray tasks = new JSONObject(preferences.cachedTasks()).optJSONArray("items");
            if (tasks == null) {
                return null;
            }
            for (int index = 0; index < tasks.length(); index++) {
                JSONObject task = tasks.optJSONObject(index);
                if (task != null && taskId.equals(task.optString("task_id"))) {
                    return task;
                }
            }
        } catch (Exception ignored) {
            // Se la cache non e' pronta, la notifica resta visibile.
        }
        return null;
    }

    private void confirmDismissTask(JSONObject task) {
        new AlertDialog.Builder(this)
                .setTitle("Eliminare il messaggio?")
                .setMessage("Il messaggio sparira' da questa app, ma restera' tracciato nei sistemi clinici.")
                .setNegativeButton("Annulla", null)
                .setPositiveButton("Elimina", (dialog, which) -> dismissTask(task))
                .show();
    }

    private void dismissTask(JSONObject task) {
        executor.execute(() -> {
            try {
                new BackendApiClient(this).dismissTask(task.getString("task_id"));
                PatientSyncManager.synchronize(this);
                runOnUiThread(() -> Toast.makeText(this, "Messaggio eliminato.", Toast.LENGTH_SHORT).show());
            } catch (Exception exception) {
                runOnUiThread(() -> Toast.makeText(this, userMessage(exception), Toast.LENGTH_SHORT).show());
            }
        });
    }

    private void dismissNotification(JSONObject notification) {
        executor.execute(() -> {
            try {
                new BackendApiClient(this).dismissNotification(notification.getString("notification_id"));
                PatientSyncManager.synchronize(this);
                runOnUiThread(() -> Toast.makeText(this, "Notifica eliminata.", Toast.LENGTH_SHORT).show());
            } catch (Exception exception) {
                runOnUiThread(() -> Toast.makeText(this, userMessage(exception), Toast.LENGTH_SHORT).show());
            }
        });
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
