package it.unisalento.iotedgecompanion;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.UUID;

/** Punto unico per configurazione, identita' dispositivo e cache dell'app. */
final class AppPreferences {
    private static final String PREFS = "iot-edge";
    private final SharedPreferences preferences;
    private final SecureTokenStore tokenStore;

    private AppPreferences(Context context) {
        Context appContext = context.getApplicationContext();
        preferences = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        tokenStore = new SecureTokenStore(appContext);
    }

    static AppPreferences get(Context context) {
        return new AppPreferences(context);
    }

    String backendUrl() {
        String value = preferences.getString("backendUrl", "http://10.0.2.2:8080/api/v1");
        return value == null ? "" : value.replaceAll("/+$", "");
    }

    String deviceId() {
        String value = preferences.getString("deviceId", null);
        if (value == null || value.isEmpty()) {
            value = "android-" + UUID.randomUUID();
            preferences.edit().putString("deviceId", value).putString("phoneId", value).apply();
        }
        return value;
    }

    void saveTokens(String accessToken, String refreshToken) {
        tokenStore.put("access_token", accessToken);
        tokenStore.put("refresh_token", refreshToken);
    }

    String accessToken() {
        return tokenStore.get("access_token");
    }

    String refreshToken() {
        return tokenStore.get("refresh_token");
    }

    boolean isAuthenticated() {
        return accessToken() != null && patientId() != null;
    }

    void savePatient(String patientId, String displayName) {
        preferences.edit()
                .putString("patientId", patientId)
                .putString("patientDisplayName", displayName)
                .apply();
    }

    void saveUserRole(String role) {
        preferences.edit().putString("userRole", role == null ? "" : role).apply();
    }

    String userRole() {
        return preferences.getString("userRole", "");
    }

    String patientId() {
        return preferences.getString("patientId", null);
    }

    String patientDisplayName() {
        return preferences.getString("patientDisplayName", "Paziente");
    }

    void clearSession() {
        tokenStore.clear();
        preferences.edit()
                .remove("patientId")
                .remove("patientDisplayName")
                .remove("userRole")
                .remove("cachedCaregiverOverview")
                .remove("cachedCurrent")
                .remove("cachedTasks")
                .remove("cachedNotifications")
                .remove("cachedWindows")
                .apply();
    }

    void cacheSnapshot(String current, String tasks, String notifications, String windows) {
        preferences.edit()
                .putString("cachedCurrent", current)
                .putString("cachedTasks", tasks)
                .putString("cachedNotifications", notifications)
                .putString("cachedWindows", windows)
                .putLong("lastBackendSyncAt", System.currentTimeMillis())
                .putString("backendSyncStatus", "online")
                .apply();
    }

    String cachedCurrent() {
        return preferences.getString("cachedCurrent", "{}");
    }

    String cachedTasks() {
        return preferences.getString("cachedTasks", "{\"items\":[]}");
    }

    String cachedNotifications() {
        return preferences.getString("cachedNotifications", "{\"items\":[]}");
    }

    String cachedWindows() {
        return preferences.getString("cachedWindows", "{\"items\":[]}");
    }

    void cacheCaregiverOverview(String overview) {
        preferences.edit()
                .putString("cachedCaregiverOverview", overview)
                .putLong("lastBackendSyncAt", System.currentTimeMillis())
                .putString("backendSyncStatus", "online")
                .apply();
    }

    String cachedCaregiverOverview() {
        return preferences.getString("cachedCaregiverOverview", "{\"items\":[]}");
    }

    long lastBackendSyncAt() {
        return preferences.getLong("lastBackendSyncAt", 0L);
    }

    void setBackendError(String message) {
        preferences.edit()
                .putString("backendSyncStatus", message == null ? "offline" : message)
                .apply();
    }

    String backendSyncStatus() {
        return preferences.getString("backendSyncStatus", "non connesso");
    }

    void setServiceRunning(boolean running) {
        preferences.edit().putBoolean("serviceRunning", running).apply();
    }

    boolean serviceRunning() {
        return preferences.getBoolean("serviceRunning", false);
    }

    void setBleUploadStatus(boolean success, String room) {
        SharedPreferences.Editor editor = preferences.edit()
                .putBoolean("bleConnected", success)
                .putString("lastBleRoom", room == null ? "" : room);
        if (success) {
            editor.putLong("lastBleUploadAt", System.currentTimeMillis());
        }
        editor.apply();
    }

    boolean bleConnected() {
        return preferences.getBoolean("bleConnected", false);
    }

    long lastBleUploadAt() {
        return preferences.getLong("lastBleUploadAt", 0L);
    }

    String lastBleRoom() {
        return preferences.getString("lastBleRoom", "");
    }

    void saveFcmToken(String token) {
        preferences.edit().putString("fcmToken", token).putBoolean("fcmTokenRegistered", false).apply();
    }

    String fcmToken() {
        return preferences.getString("fcmToken", "");
    }

    boolean fcmTokenRegistered() {
        return preferences.getBoolean("fcmTokenRegistered", false);
    }

    void markFcmTokenRegistered() {
        preferences.edit().putBoolean("fcmTokenRegistered", true).apply();
    }

    boolean shouldSendHeartbeat() {
        return System.currentTimeMillis() - preferences.getLong("lastAppHeartbeatAt", 0L) >= 240_000L;
    }

    void markHeartbeatSent() {
        preferences.edit().putLong("lastAppHeartbeatAt", System.currentTimeMillis()).apply();
    }

    SharedPreferences raw() {
        return preferences;
    }
}
