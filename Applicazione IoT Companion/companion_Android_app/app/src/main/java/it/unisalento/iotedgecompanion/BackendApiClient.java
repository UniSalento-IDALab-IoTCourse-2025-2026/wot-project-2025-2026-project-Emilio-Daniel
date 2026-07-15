package it.unisalento.iotedgecompanion;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Client REST centralizzato per autenticazione, task e stato dell'app. */
final class BackendApiClient {
    private final AppPreferences preferences;

    BackendApiClient(Context context) {
        preferences = AppPreferences.get(context);
    }

    JSONObject authenticateCompanion(String email, String password) throws Exception {
        JSONObject credentials = new JSONObject()
                .put("email", email.trim())
                .put("password", password);
        JSONObject session = request("POST", "/auth/login", credentials, false, false);
        JSONObject user = session.optJSONObject("user");
        if (user == null) {
            throw new ApiException(403, "Profilo non disponibile.");
        }
        String role = user.optString("role");
        if (!"patient".equals(role) && !"caregiver".equals(role)) {
            throw new ApiException(403, "Questo account non e' abilitato all'app companion.");
        }
        preferences.saveTokens(session.getString("access_token"), session.optString("refresh_token"));
        preferences.saveUserRole(role);
        try {
            JSONObject patients = request("GET", "/patients?page_size=20", null, true, true);
            JSONArray items = patients.optJSONArray("items");
            if (items == null || items.length() == 0) {
                throw new ApiException(409, "Nessun paziente associato a questo account.");
            }
            if ("patient".equals(role) && items.length() != 1) {
                throw new ApiException(409, "L'account paziente deve essere associato a un solo profilo.");
            }
            JSONObject patient = items.getJSONObject(0);
            String patientId = patient.getString("patient_id");
            preferences.savePatient(patientId, patient.optString("display_name", patientId));
            return new JSONObject()
                    .put("role", role)
                    .put("patient", patient)
                    .put("patients", items);
        } catch (Exception exception) {
            preferences.clearSession();
            throw exception;
        }
    }

    JSONObject authenticatePatient(String email, String password) throws Exception {
        JSONObject session = authenticateCompanion(email, password);
        if (!"patient".equals(session.optString("role"))) {
            preferences.clearSession();
            throw new ApiException(403, "Questo account non appartiene a un paziente.");
        }
        return session.getJSONObject("patient");
    }

    JSONObject fetchCurrent() throws Exception {
        return request("GET", "/patients/" + patientId() + "/current", null, true, true);
    }

    JSONObject fetchTasks() throws Exception {
        return request("GET", "/patients/" + patientId() + "/tasks?page_size=100", null, true, true);
    }

    JSONObject fetchNotifications() throws Exception {
        return request("GET", "/notifications?patient_id=" + patientId() + "&page_size=100", null, true, true);
    }

    JSONObject fetchCaregiverOverview() throws Exception {
        return request("GET", "/alerts/caregiver", null, true, true);
    }

    JSONObject fetchWindows() throws Exception {
        return request("GET", "/telemetry/patients/" + patientId() + "/windows?limit=90", null, true, true);
    }

    JSONObject updateTaskState(String taskId, String state, String occurredAt) throws Exception {
        JSONObject payload = new JSONObject()
                .put("state", state)
                .put("occurred_at", occurredAt)
                .put("device_id", preferences.deviceId());
        return request("PATCH", "/tasks/" + taskId + "/state", payload, true, true);
    }

    JSONObject submitTaskResult(String taskId, JSONObject payload) throws Exception {
        return request("POST", "/tasks/" + taskId + "/results", payload, true, true);
    }

    JSONObject markNotificationSeen(String notificationId) throws Exception {
        return request("PATCH", "/notifications/" + notificationId + "/seen", new JSONObject(), true, true);
    }

    JSONObject acknowledgeAlert(String alertId) throws Exception {
        return request("PATCH", "/alerts/" + alertId + "/acknowledge", new JSONObject(), true, true);
    }

    JSONObject dismissNotification(String notificationId) throws Exception {
        return request("DELETE", "/notifications/" + notificationId, null, true, true);
    }

    JSONObject dismissTask(String taskId) throws Exception {
        return request("DELETE", "/tasks/" + taskId, null, true, true);
    }

    JSONObject registerDevice(String fcmToken, boolean notificationsEnabled) throws Exception {
        JSONObject payload = baseDevicePayload()
                .put("fcm_token", fcmToken == null ? "" : fcmToken)
                .put("notifications_enabled", notificationsEnabled);
        return request("POST", "/notifications/devices/register", payload, true, true);
    }

    JSONObject registerCaregiverDevice(String patientId, String fcmToken, boolean notificationsEnabled) throws Exception {
        JSONObject payload = baseCaregiverDevicePayload(patientId)
                .put("fcm_token", fcmToken == null ? "" : fcmToken)
                .put("notifications_enabled", notificationsEnabled);
        return request("POST", "/notifications/caregiver/devices/register", payload, true, true);
    }

    JSONObject sendHeartbeat(double batteryPct, boolean notificationsEnabled) throws Exception {
        JSONObject payload = baseDevicePayload()
                .put("status", "online")
                .put("battery_pct", batteryPct)
                .put("notifications_enabled", notificationsEnabled);
        return request("POST", "/notifications/devices/status", payload, true, true);
    }

    JSONObject sendCaregiverHeartbeat(String patientId, double batteryPct, boolean notificationsEnabled) throws Exception {
        JSONObject payload = baseCaregiverDevicePayload(patientId)
                .put("status", "online")
                .put("battery_pct", batteryPct)
                .put("notifications_enabled", notificationsEnabled);
        return request("POST", "/notifications/caregiver/devices/status", payload, true, true);
    }

    private JSONObject baseDevicePayload() throws JSONException, ApiException {
        return new JSONObject()
                .put("patient_id", patientId())
                .put("device_id", preferences.deviceId())
                .put("platform", "android")
                .put("app_version", BuildConfig.VERSION_NAME);
    }

    private JSONObject baseCaregiverDevicePayload(String patientId) throws JSONException, ApiException {
        if (patientId == null || patientId.trim().isEmpty()) {
            throw new ApiException(422, "Paziente caregiver non disponibile.");
        }
        return new JSONObject()
                .put("patient_id", patientId)
                .put("device_id", preferences.deviceId())
                .put("platform", "android_caregiver")
                .put("app_version", BuildConfig.VERSION_NAME);
    }

    private String patientId() throws ApiException {
        String patientId = preferences.patientId();
        if (patientId == null || patientId.isEmpty()) {
            throw new ApiException(401, "Dispositivo non associato a un paziente.");
        }
        return patientId;
    }

    private JSONObject request(
            String method,
            String path,
            JSONObject body,
            boolean authorized,
            boolean retryAfterRefresh
    ) throws Exception {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(preferences.backendUrl() + path).openConnection();
            connection.setRequestMethod(method);
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(10000);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            if (authorized) {
                String token = preferences.accessToken();
                if (token == null) {
                    throw new ApiException(401, "Sessione non disponibile.");
                }
                connection.setRequestProperty("Authorization", "Bearer " + token);
            }
            if (body != null && !"GET".equals(method)) {
                connection.setDoOutput(true);
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(bytes);
                }
            }
            int status = connection.getResponseCode();
            String responseText = readResponse(status >= 400 ? connection.getErrorStream() : connection.getInputStream());
            if (status == 401 && authorized && retryAfterRefresh && refreshAccessToken()) {
                return request(method, path, body, true, false);
            }
            if (status < 200 || status >= 300) {
                throw new ApiException(status, extractError(responseText, status));
            }
            return responseText.isEmpty() ? new JSONObject() : new JSONObject(responseText);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private boolean refreshAccessToken() {
        String refreshToken = preferences.refreshToken();
        if (refreshToken == null || refreshToken.isEmpty()) {
            return false;
        }
        try {
            JSONObject response = request(
                    "POST",
                    "/auth/refresh",
                    new JSONObject().put("refresh_token", refreshToken),
                    false,
                    false
            );
            preferences.saveTokens(response.getString("access_token"), refreshToken);
            return true;
        } catch (Exception exception) {
            preferences.clearSession();
            return false;
        }
    }

    private String readResponse(InputStream input) throws Exception {
        if (input == null) {
            return "";
        }
        StringBuilder text = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                text.append(line);
            }
        }
        return text.toString();
    }

    private String extractError(String responseText, int status) {
        try {
            JSONObject payload = new JSONObject(responseText);
            Object detail = payload.opt("detail");
            if (detail != null) {
                return String.valueOf(detail);
            }
            JSONObject error = payload.optJSONObject("error");
            if (error != null) {
                return error.optString("message", "Errore backend " + status);
            }
        } catch (JSONException ignored) {
            // Il server puo' restituire testo non JSON durante un errore infrastrutturale.
        }
        return "Errore backend " + status;
    }
}
