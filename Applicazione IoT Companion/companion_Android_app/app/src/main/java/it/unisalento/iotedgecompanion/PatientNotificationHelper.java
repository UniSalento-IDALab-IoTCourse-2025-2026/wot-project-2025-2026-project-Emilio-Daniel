package it.unisalento.iotedgecompanion;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
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
            show(
                    context,
                    newCount == 1 ? "Hai un nuovo aggiornamento" : "Hai nuovi aggiornamenti",
                    "Apri l'app per visualizzare i dettagli.",
                    "notification"
            );
        }
    }

    static void showPushMessage(Context context, String title) {
        showPushMessage(context, title, "Apri l'app per visualizzare i dettagli.", "notification");
    }

    static void showPushMessage(Context context, String title, String body, String type) {
        String safeTitle = title == null || title.isEmpty() ? titleForType(type) : title;
        String safeBody = body == null || body.isEmpty() ? bodyForType(type) : body;
        show(context, safeTitle, safeBody, type);
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

    private static void show(Context context, String title, String body, String type) {
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
        Notification.BigTextStyle style = new Notification.BigTextStyle()
                .setBigContentTitle(titleForExpandedView(title, type))
                .bigText(body);
        Notification notification = new Notification.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(title)
                .setContentText(body)
                .setSubText(labelForType(type))
                .setColor(colorForType(context, type))
                .setStyle(style)
                .setContentIntent(pendingIntent)
                .setAutoCancel(true)
                .setCategory(Notification.CATEGORY_MESSAGE)
                .setPriority(Notification.PRIORITY_HIGH)
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
            channel.enableLights(true);
            channel.setLightColor(context.getColor(R.color.primary));
            channel.enableVibration(true);
            manager.createNotificationChannel(channel);
        }
    }

    private static String titleForType(String type) {
        if ("patient_message".equals(type)) {
            return "Messaggio dal medico";
        }
        if ("alert_created".equals(type)) {
            return "Aggiornamento importante";
        }
        if ("task_created".equals(type)) {
            return "Nuova attivita'";
        }
        return "Nuovo aggiornamento disponibile";
    }

    private static String bodyForType(String type) {
        if ("patient_message".equals(type)) {
            return "Apri l'app per leggere il messaggio.";
        }
        if ("task_created".equals(type)) {
            return "Apri l'app per vedere l'attivita'.";
        }
        return "Apri l'app per visualizzare i dettagli.";
    }

    private static String labelForType(String type) {
        if ("patient_message".equals(type)) {
            return "Messaggio";
        }
        if ("alert_created".equals(type)) {
            return "Avviso";
        }
        if ("task_created".equals(type)) {
            return "Attivita'";
        }
        return "Aggiornamento";
    }

    private static String titleForExpandedView(String title, String type) {
        String label = labelForType(type);
        return label + " - " + title;
    }

    private static int colorForType(Context context, String type) {
        if ("alert_created".equals(type)) {
            return context.getColor(R.color.coral);
        }
        if ("task_created".equals(type)) {
            return context.getColor(R.color.sky);
        }
        if ("patient_message".equals(type)) {
            return context.getColor(R.color.primary);
        }
        return Color.rgb(8, 127, 120);
    }
}
