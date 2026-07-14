package it.unisalento.iotedgecompanion;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.HashSet;
import java.util.Set;

/** Crea notifiche discrete senza dati clinici visibili sul blocco schermo. */
final class PatientNotificationHelper {
    private static final String CHANNEL_ID = "patient_updates";

    private PatientNotificationHelper() {
    }

    static void notifyNewItems(Context context, JSONObject tasks, JSONObject notifications) {
        AppPreferences preferences = AppPreferences.get(context);
        Set<String> announced = new HashSet<>(
                preferences.raw().getStringSet("announcedItems", new HashSet<>())
        );
        int newCount = collectNewTasks(tasks.optJSONArray("items"), announced)
                + collectNewNotifications(notifications.optJSONArray("items"), announced);
        preferences.raw().edit().putStringSet("announcedItems", announced).apply();
        if (newCount > 0) {
            show(context, newCount == 1 ? "Hai un nuovo aggiornamento" : "Hai nuovi aggiornamenti");
        }
    }

    static void showPushMessage(Context context, String title) {
        show(context, title == null || title.isEmpty() ? "Nuovo aggiornamento disponibile" : title);
    }

    static boolean notificationsEnabled(Context context) {
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        return manager != null && manager.areNotificationsEnabled();
    }

    private static int collectNewTasks(JSONArray items, Set<String> announced) {
        if (items == null) {
            return 0;
        }
        int count = 0;
        for (int index = 0; index < items.length(); index++) {
            JSONObject task = items.optJSONObject(index);
            if (task == null || "completed".equals(task.optString("status"))
                    || "cancelled".equals(task.optString("status"))) {
                continue;
            }
            String id = "task:" + task.optString("task_id");
            if (!announced.contains(id)) {
                announced.add(id);
                count++;
            }
        }
        return count;
    }

    private static int collectNewNotifications(JSONArray items, Set<String> announced) {
        if (items == null) {
            return 0;
        }
        int count = 0;
        for (int index = 0; index < items.length(); index++) {
            JSONObject item = items.optJSONObject(index);
            if (item == null || "seen".equals(item.optString("status"))) {
                continue;
            }
            String id = "notification:" + item.optString("notification_id");
            if (!announced.contains(id)) {
                announced.add(id);
                count++;
            }
        }
        return count;
    }

    private static void show(Context context, String title) {
        createChannel(context);
        Intent intent = new Intent(context, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                context,
                20,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        Notification publicVersion = new Notification.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle("IoT Edge Companion")
                .setContentText("Nuovo aggiornamento disponibile")
                .build();
        Notification notification = new Notification.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(title)
                .setContentText("Apri l'app per visualizzare i dettagli.")
                .setContentIntent(pendingIntent)
                .setAutoCancel(true)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setPublicVersion(publicVersion)
                .build();
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.notify((int) (System.currentTimeMillis() % Integer.MAX_VALUE), notification);
        }
    }

    private static void createChannel(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    "Aggiornamenti del paziente",
                    NotificationManager.IMPORTANCE_DEFAULT
            );
            channel.setDescription("Attivita' e messaggi inviati dal personale sanitario");
            channel.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE);
            manager.createNotificationChannel(channel);
        }
    }
}
