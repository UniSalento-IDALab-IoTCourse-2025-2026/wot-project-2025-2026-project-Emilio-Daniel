package it.unisalento.iotedgecompanion;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Renderer generico dei test concordati e dei check-in paziente. */
public class TaskActivity extends Activity {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final List<AnswerField> answerFields = new ArrayList<>();
    private JSONObject task;
    private Instant startedAt;
    private LinearLayout questionsContainer;
    private EditText noteInput;
    private TextView statusText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_task);
        try {
            task = new JSONObject(getIntent().getStringExtra("task_json"));
        } catch (Exception exception) {
            finish();
            return;
        }
        startedAt = Instant.now();
        questionsContainer = findViewById(R.id.questionsContainer);
        noteInput = findViewById(R.id.taskNoteInput);
        statusText = findViewById(R.id.taskStatusText);
        findViewById(R.id.backButton).setOnClickListener(view -> finish());
        findViewById(R.id.submitTaskButton).setOnClickListener(view -> submit());
        renderTask();
        markStarted();
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private void renderTask() {
        ((TextView) findViewById(R.id.taskTypeText)).setText(prettyTaskType(task.optString("type")));
        ((TextView) findViewById(R.id.taskTitleText)).setText(task.optString("title", "Attivita'"));
        ((TextView) findViewById(R.id.taskInstructionsText)).setText(
                task.optString("instructions", "Completa i campi e invia le risposte.")
        );
        JSONObject payload = task.optJSONObject("payload");
        JSONArray questions = payload == null ? null : payload.optJSONArray("questions");
        if (questions == null || questions.length() == 0) {
            addInformativePanel("Questa attivita' non richiede domande strutturate. Puoi aggiungere una nota e confermare.");
            return;
        }
        for (int index = 0; index < questions.length(); index++) {
            JSONObject question = questions.optJSONObject(index);
            if (question != null) {
                addQuestion(question, index + 1);
            }
        }
    }

    private void addQuestion(JSONObject question, int number) {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setBackgroundResource(R.drawable.bg_panel);
        panel.setPadding(dp(16), dp(16), dp(16), dp(16));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        params.bottomMargin = dp(10);
        panel.setLayoutParams(params);

        String questionText = question.optString("text", "Domanda " + number);
        TextView label = new TextView(this);
        label.setText(number + ". " + questionText);
        label.setTextColor(getColor(R.color.text_primary));
        label.setTextSize(15);
        label.setTypeface(null, android.graphics.Typeface.BOLD);
        panel.addView(label);

        String type = question.optString("type", "text");
        JSONArray options = question.optJSONArray("options");
        if (options != null && options.length() > 0) {
            RadioGroup group = new RadioGroup(this);
            group.setOrientation(RadioGroup.VERTICAL);
            group.setPadding(0, dp(8), 0, 0);
            for (int index = 0; index < options.length(); index++) {
                RadioButton option = new RadioButton(this);
                option.setText(options.optString(index));
                option.setTextColor(getColor(R.color.text_primary));
                option.setTextSize(14);
                option.setPadding(0, dp(4), 0, dp(4));
                group.addView(option);
            }
            panel.addView(group);
            answerFields.add(AnswerField.choice(question.optString("id", "q" + number), questionText, group));
        } else {
            EditText input = new EditText(this);
            input.setBackgroundResource(R.drawable.bg_input);
            input.setPadding(dp(12), dp(10), dp(12), dp(10));
            input.setTextColor(getColor(R.color.text_primary));
            input.setHint("Inserisci la risposta");
            input.setSingleLine(!"text_area".equals(type));
            if ("number".equals(type)) {
                input.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
            } else {
                input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
            }
            LinearLayout.LayoutParams inputParams = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    dp("text_area".equals(type) ? 92 : 48)
            );
            inputParams.topMargin = dp(10);
            input.setLayoutParams(inputParams);
            panel.addView(input);
            answerFields.add(AnswerField.text(question.optString("id", "q" + number), questionText, input));
        }
        questionsContainer.addView(panel);
    }

    private void addInformativePanel(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(getColor(R.color.text_secondary));
        view.setTextSize(14);
        view.setBackgroundResource(R.drawable.bg_panel);
        view.setPadding(dp(16), dp(16), dp(16), dp(16));
        questionsContainer.addView(view);
    }

    private void markStarted() {
        executor.execute(() -> {
            try {
                new BackendApiClient(this).updateTaskState(
                        task.getString("task_id"),
                        "started",
                        startedAt.toString()
                );
            } catch (Exception ignored) {
                // L'utente puo' lavorare offline; il risultato restera' nella coda locale.
            }
        });
    }

    private void submit() {
        JSONArray answers = new JSONArray();
        JSONObject payload;
        try {
            for (AnswerField field : answerFields) {
                String value = field.value();
                if (value == null || value.trim().isEmpty()) {
                    statusText.setText("Completa tutte le risposte prima di inviare.");
                    field.focus();
                    return;
                }
                answers.put(new JSONObject()
                        .put("question_id", field.id)
                        .put("question_text", field.questionText)
                        .put("value", value));
            }
            Instant completedAt = Instant.now();
            long durationSeconds = Math.max(1L, completedAt.getEpochSecond() - startedAt.getEpochSecond());
            AppPreferences preferences = AppPreferences.get(this);
            payload = new JSONObject()
                    .put("patient_id", preferences.patientId())
                    .put("message_id", "task-result-" + UUID.randomUUID())
                    .put("started_at", startedAt.toString())
                    .put("completed_at", completedAt.toString())
                    .put("duration_seconds", durationSeconds)
                    .put("answers", answers)
                    .put("note", noteInput.getText().toString().trim())
                    .put("test_metadata", new JSONObject().put("app_version", BuildConfig.VERSION_NAME))
                    .put("device_info", new JSONObject()
                            .put("device_id", preferences.deviceId())
                            .put("platform", "android")
                            .put("model", android.os.Build.MODEL));
        } catch (Exception exception) {
            statusText.setText("Impossibile preparare il risultato.");
            return;
        }

        statusText.setText("Salvataggio sicuro del risultato...");
        findViewById(R.id.submitTaskButton).setEnabled(false);
        executor.execute(() -> {
            try {
                OfflineResultQueue queue = new OfflineResultQueue(this);
                queue.enqueue(task.getString("task_id"), payload);
                boolean sent = true;
                try {
                    queue.flush(new BackendApiClient(this));
                } catch (Exception exception) {
                    sent = false;
                }
                boolean delivered = sent;
                runOnUiThread(() -> showCompletion(delivered));
            } catch (Exception exception) {
                runOnUiThread(() -> {
                    findViewById(R.id.submitTaskButton).setEnabled(true);
                    statusText.setText("Impossibile salvare il risultato sul dispositivo.");
                });
            }
        });
    }

    private void showCompletion(boolean delivered) {
        new AlertDialog.Builder(this)
                .setTitle(delivered ? "Risultato inviato" : "Risultato salvato")
                .setMessage(delivered
                        ? "Il team di cura ricevera' il risultato."
                        : "La rete non e' disponibile. Il risultato e' protetto sul telefono e verra' inviato automaticamente.")
                .setCancelable(false)
                .setPositiveButton("Chiudi", (dialog, which) -> finish())
                .show();
    }

    private String prettyTaskType(String type) {
        if ("cognitive_test".equals(type)) {
            return "TEST COGNITIVO ASSISTITO";
        }
        if ("check_in".equals(type)) {
            return "CHECK-IN BENESSERE";
        }
        if ("medication_reminder".equals(type)) {
            return "PROMEMORIA TERAPEUTICO";
        }
        return "ATTIVITA'";
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static final class AnswerField {
        final String id;
        final String questionText;
        final EditText input;
        final RadioGroup choices;

        private AnswerField(String id, String questionText, EditText input, RadioGroup choices) {
            this.id = id;
            this.questionText = questionText;
            this.input = input;
            this.choices = choices;
        }

        static AnswerField text(String id, String questionText, EditText input) {
            return new AnswerField(id, questionText, input, null);
        }

        static AnswerField choice(String id, String questionText, RadioGroup choices) {
            return new AnswerField(id, questionText, null, choices);
        }

        String value() {
            if (input != null) {
                return input.getText().toString().trim();
            }
            int checked = choices.getCheckedRadioButtonId();
            if (checked == View.NO_ID) {
                return null;
            }
            RadioButton button = choices.findViewById(checked);
            return button == null ? null : button.getText().toString();
        }

        void focus() {
            if (input != null) {
                input.requestFocus();
            } else if (choices != null) {
                choices.requestFocus();
            }
        }
    }
}
