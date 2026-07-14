package it.unisalento.iotedgecompanion;

import android.content.Context;

import com.google.firebase.FirebaseApp;
import com.google.firebase.messaging.FirebaseMessaging;

/** Recupera il token FCM solo quando Firebase e' configurato nel progetto. */
final class FcmRegistration {
    private FcmRegistration() {
    }

    static void ensureToken(Context sourceContext) {
        Context context = sourceContext.getApplicationContext();
        if (FirebaseApp.getApps(context).isEmpty()) {
            return;
        }
        FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task -> {
            if (!task.isSuccessful() || task.getResult() == null || task.getResult().isEmpty()) {
                return;
            }
            AppPreferences.get(context).saveFcmToken(task.getResult());
            new Thread(() -> PatientSyncManager.synchronize(context), "patient-fcm-register").start();
        });
    }
}
