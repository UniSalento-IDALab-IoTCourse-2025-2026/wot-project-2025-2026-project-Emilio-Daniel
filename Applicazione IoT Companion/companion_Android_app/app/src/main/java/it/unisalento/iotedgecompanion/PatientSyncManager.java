package it.unisalento.iotedgecompanion;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;

import org.json.JSONObject;

/** Sincronizza stato, task, notifiche e coda locale con il backend. */
final class PatientSyncManager {
    static final String ACTION_SYNC_UPDATED = "it.unisalento.iotedgecompanion.SYNC_UPDATED";

    private PatientSyncManager() {
    }

    static void synchronize(Context sourceContext) {
        Context context = sourceContext.getApplicationContext();
        AppPreferences preferences = AppPreferences.get(context);
        if (!preferences.isAuthenticated()) {
            return;
        }
        BackendApiClient client = new BackendApiClient(context);
        try {
            new OfflineResultQueue(context).flush(client);
            JSONObject current = client.fetchCurrent();
            JSONObject tasks = client.fetchTasks();
            JSONObject notifications = client.fetchNotifications();
            JSONObject windows = new JSONObject(preferences.cachedWindows());
            try {
                windows = client.fetchWindows();
            } catch (Exception ignored) {
                // Lo storico arricchisce la home, ma non deve bloccare task e monitoraggio.
            }
            boolean notificationsEnabled = PatientNotificationHelper.notificationsEnabled(context);
            String fcmToken = preferences.fcmToken();
            if (!preferences.fcmTokenRegistered()) {
                client.registerDevice(fcmToken, notificationsEnabled);
                preferences.markFcmTokenRegistered();
            }
            if (preferences.shouldSendHeartbeat()) {
                client.sendHeartbeat(readBatteryPercentage(context), notificationsEnabled);
                preferences.markHeartbeatSent();
            }
            preferences.cacheSnapshot(
                    current.toString(),
                    tasks.toString(),
                    notifications.toString(),
                    windows.toString()
            );
            PatientNotificationHelper.notifyNewItems(context, tasks, notifications);
        } catch (Exception exception) {
            preferences.setBackendError("connessione non disponibile");
        } finally {
            context.sendBroadcast(new Intent(ACTION_SYNC_UPDATED).setPackage(context.getPackageName()));
        }
    }

    private static double readBatteryPercentage(Context context) {
        Intent battery = context.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (battery == null) {
            return 0.0;
        }
        int level = battery.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
        int scale = battery.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
        if (level < 0 || scale <= 0) {
            return 0.0;
        }
        return Math.round((level * 1000.0 / scale)) / 10.0;
    }
}
