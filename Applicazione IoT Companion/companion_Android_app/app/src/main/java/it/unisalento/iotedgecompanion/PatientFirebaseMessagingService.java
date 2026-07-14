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
        String title = message.getNotification() == null
                ? "Nuovo aggiornamento disponibile"
                : message.getNotification().getTitle();
        PatientNotificationHelper.showPushMessage(this, title);
        executor.execute(() -> PatientSyncManager.synchronize(this));
    }

    @Override
    public void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }
}
