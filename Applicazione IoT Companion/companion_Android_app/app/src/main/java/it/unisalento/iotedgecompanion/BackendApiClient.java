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

    JSONObject authenticatePatient(String email, String password) throws Exception {
        JSONObject credentials = new JSONObject()
                .put("email", email.trim())
                .put("password", password);
        JSONObject session = request("POST", "/auth/login", credentials, false, false);
        JSONObject user = session.optJSONObject("user");
        if (user == null || !"patient".equals(user.optString("role"))) {
            throw new ApiException(403, "Questo account non appartiene a un paziente.");
        }
        preferences.saveTokens(session.getString("access_token"), session.optString("refresh_token"));
        try {
            JSONObject patients = request("GET", "/patients?page_size=10", null, true, true);
            JSONArray items = patients.optJSONArray("items");
            if (items == null || items.length() != 1) {
                throw new ApiException(409, "L'account deve essere associato a un solo paziente.");
            }
            JSONObject patient = items.getJSONObject(0);
            String patientId = patient.getString("patient_id");
            preferences.savePatient(patientId, patient.optString("display_name", patientId));
            return patient;
        } catch (Exception exception) {
            preferences.clearSession();
            throw exception;
        }
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

    JSONObject registerDevice(String fcmToken, boolean notificationsEnabled) throws Exception {
        JSONObject payload = baseDevicePayload()
                .put("fcm_token", fcmToken == null ? "" : fcmToken)
                .put("notifications_enabled", notificationsEnabled);
        return request("POST", "/notifications/devices/register", payload, true, true);
    }

    JSONObject sendHeartbeat(double batteryPct, boolean notificationsEnabled) throws Exception {
        JSONObject payload = baseDevicePayload()
                .put("status", "online")
                .put("battery_pct", batteryPct)
                .put("notifications_enabled", notificationsEnabled);
        return request("POST", "/notifications/devices/status", payload, true, true);
    }

    private JSONObject baseDevicePayload() throws JSONException, ApiException {
        return new JSONObject()
                .put("patient_id", patientId())
                .put("device_id", preferences.deviceId())
                .put("platform", "android")
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
