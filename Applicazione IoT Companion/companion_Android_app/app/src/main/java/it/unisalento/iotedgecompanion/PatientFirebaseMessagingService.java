package it.unisalento.iotedgecompanion;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Riceve push FCM e aggiorna subito i dati reali tramite REST autenticato. */
public class PatientFirebaseMessagingService extends FirebaseMessagingService {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    @Override
    public void onNewToken(String token) {
        super.onNewToken(token);
        AppPreferences.get(this).saveFcmToken(token);
        executor.execute(() -> PatientSyncManager.synchronize(this));
    }

    @Override
    public void onMessageReceived(RemoteMessage message) {
        super.onMessageReceived(message);
        PatientNotificationHelper.markPushAnnounced(this, message.getData());
        String title = message.getNotification() == null
                ? "Nuovo aggiornamento disponibile"
                : message.getNotification().getTitle();
        String body = message.getNotification() == null
                ? "Apri l'app per visualizzare i dettagli."
                : message.getNotification().getBody();
        String type = message.getData().get("type");
        PatientNotificationHelper.showPushMessage(this, title, body, type);
        executor.execute(() -> PatientSyncManager.synchronize(this));
    }

    @Override
    public void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }
}
