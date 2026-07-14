package it.unisalento.iotedgecompanion;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

/** Coda locale persistente per risultati prodotti senza connessione. */
final class OfflineResultQueue {
    private static final String KEY = "pendingTaskResults";
    private final SharedPreferences preferences;

    OfflineResultQueue(Context context) {
        preferences = AppPreferences.get(context).raw();
    }

    synchronized void enqueue(String taskId, JSONObject payload) throws Exception {
        JSONArray queue = readQueue();
        String messageId = payload.optString("message_id");
        for (int index = 0; index < queue.length(); index++) {
            JSONObject item = queue.getJSONObject(index);
            JSONObject queuedPayload = item.optJSONObject("payload");
            if (queuedPayload != null && messageId.equals(queuedPayload.optString("message_id"))) {
                return;
            }
        }
        queue.put(new JSONObject().put("task_id", taskId).put("payload", payload));
        saveQueue(queue);
    }

    synchronized int flush(BackendApiClient client) throws Exception {
        JSONArray queue = readQueue();
        JSONArray remaining = new JSONArray();
        for (int index = 0; index < queue.length(); index++) {
            JSONObject item = queue.getJSONObject(index);
            try {
                client.submitTaskResult(item.getString("task_id"), item.getJSONObject("payload"));
            } catch (ApiException exception) {
                if (exception.statusCode() != 409) {
                    copyRemaining(queue, remaining, index);
                    saveQueue(remaining);
                    throw exception;
                }
            } catch (Exception exception) {
                copyRemaining(queue, remaining, index);
                saveQueue(remaining);
                throw exception;
            }
        }
        saveQueue(remaining);
        return remaining.length();
    }

    synchronized int size() {
        return readQueue().length();
    }

    private JSONArray readQueue() {
        try {
            return new JSONArray(preferences.getString(KEY, "[]"));
        } catch (Exception exception) {
            return new JSONArray();
        }
    }

    private void saveQueue(JSONArray queue) {
        preferences.edit().putString(KEY, queue.toString()).apply();
    }

    private void copyRemaining(JSONArray source, JSONArray target, int start) throws Exception {
        for (int index = start; index < source.length(); index++) {
            target.put(source.getJSONObject(index));
        }
    }
}
