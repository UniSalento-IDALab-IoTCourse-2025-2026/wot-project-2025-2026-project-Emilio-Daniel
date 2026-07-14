package it.unisalento.iotedgecompanion;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.util.AttributeSet;
import android.view.MotionEvent;
import android.view.View;

import java.util.Locale;

/** Grafico leggero e interattivo per le serie temporali mostrate al paziente. */
public class HealthTrendView extends View {
    private final Paint gridPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint linePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint fillPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint tooltipPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path linePath = new Path();
    private final Path fillPath = new Path();
    private float[] values = new float[0];
    private String[] labels = new String[0];
    private String unit = "";
    private int accentColor = Color.rgb(15, 118, 110);
    private int selectedIndex = -1;
    private Float forcedMinimum;
    private Float forcedMaximum;

    public HealthTrendView(Context context) {
        super(context);
        initialize();
    }

    public HealthTrendView(Context context, AttributeSet attrs) {
        super(context, attrs);
        initialize();
    }

    public HealthTrendView(Context context, AttributeSet attrs, int defStyleAttr) {
        super(context, attrs, defStyleAttr);
        initialize();
    }

    private void initialize() {
        setMinimumHeight(dp(190));
        setClickable(true);
        setFocusable(true);
        gridPaint.setColor(Color.rgb(225, 233, 237));
        gridPaint.setStrokeWidth(dp(1));
        linePaint.setStyle(Paint.Style.STROKE);
        linePaint.setStrokeWidth(dp(3));
        linePaint.setStrokeCap(Paint.Cap.ROUND);
        linePaint.setStrokeJoin(Paint.Join.ROUND);
        fillPaint.setStyle(Paint.Style.FILL);
        textPaint.setColor(Color.rgb(86, 101, 115));
        textPaint.setTextSize(sp(11));
        tooltipPaint.setColor(Color.rgb(31, 41, 51));
        tooltipPaint.setStyle(Paint.Style.FILL);
    }

    public void setSeries(String unit, int color, float[] values, String[] labels) {
        setSeries(unit, color, values, labels, null, null);
    }

    public void setSeries(
            String unit,
            int color,
            float[] values,
            String[] labels,
            Float forcedMinimum,
            Float forcedMaximum
    ) {
        this.unit = unit == null ? "" : unit;
        this.accentColor = color;
        this.values = values == null ? new float[0] : values.clone();
        this.labels = labels == null ? new String[0] : labels.clone();
        this.forcedMinimum = forcedMinimum;
        this.forcedMaximum = forcedMaximum;
        this.selectedIndex = -1;
        linePaint.setColor(accentColor);
        fillPaint.setColor(withAlpha(accentColor, 28));
        setContentDescription(buildContentDescription());
        invalidate();
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int desiredHeight = dp(190);
        int height = resolveSize(desiredHeight, heightMeasureSpec);
        setMeasuredDimension(MeasureSpec.getSize(widthMeasureSpec), height);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float left = dp(42);
        float right = getWidth() - dp(12);
        float top = dp(18);
        float bottom = getHeight() - dp(30);
        if (right <= left || bottom <= top) {
            return;
        }

        float[] range = valueRange();
        if (range == null) {
            textPaint.setTextSize(sp(13));
            canvas.drawText("Dati non ancora disponibili", left, (top + bottom) / 2f, textPaint);
            return;
        }
        float minimum = range[0];
        float maximum = range[1];
        drawGrid(canvas, left, right, top, bottom, minimum, maximum);
        drawSeries(canvas, left, right, top, bottom, minimum, maximum);
        drawAxisLabels(canvas, left, right, bottom);
        if (selectedIndex >= 0 && selectedIndex < values.length && !Float.isNaN(values[selectedIndex])) {
            drawTooltip(canvas, selectedIndex, left, right, top, bottom, minimum, maximum);
        }
    }

    private void drawGrid(
            Canvas canvas,
            float left,
            float right,
            float top,
            float bottom,
            float minimum,
            float maximum
    ) {
        textPaint.setTextSize(sp(10));
        for (int index = 0; index < 4; index++) {
            float ratio = index / 3f;
            float y = top + ratio * (bottom - top);
            canvas.drawLine(left, y, right, y, gridPaint);
            float value = maximum - ratio * (maximum - minimum);
            canvas.drawText(formatValue(value), dp(2), y + dp(4), textPaint);
        }
    }

    private void drawSeries(
            Canvas canvas,
            float left,
            float right,
            float top,
            float bottom,
            float minimum,
            float maximum
    ) {
        linePath.reset();
        fillPath.reset();
        boolean segmentStarted = false;
        int firstValid = -1;
        int lastValid = -1;
        for (int index = 0; index < values.length; index++) {
            float value = values[index];
            if (Float.isNaN(value)) {
                segmentStarted = false;
                continue;
            }
            float x = xForIndex(index, left, right);
            float y = yForValue(value, top, bottom, minimum, maximum);
            if (!segmentStarted) {
                linePath.moveTo(x, y);
                segmentStarted = true;
            } else {
                linePath.lineTo(x, y);
            }
            if (firstValid < 0) {
                firstValid = index;
            }
            lastValid = index;
        }
        if (firstValid < 0) {
            return;
        }
        if (allValuesContiguous(firstValid, lastValid)) {
            float firstX = xForIndex(firstValid, left, right);
            float firstY = yForValue(values[firstValid], top, bottom, minimum, maximum);
            fillPath.moveTo(firstX, bottom);
            fillPath.lineTo(firstX, firstY);
            for (int index = firstValid + 1; index <= lastValid; index++) {
                fillPath.lineTo(
                        xForIndex(index, left, right),
                        yForValue(values[index], top, bottom, minimum, maximum)
                );
            }
            fillPath.lineTo(xForIndex(lastValid, left, right), bottom);
            fillPath.close();
            canvas.drawPath(fillPath, fillPaint);
        }
        canvas.drawPath(linePath, linePaint);

        float lastX = xForIndex(lastValid, left, right);
        float lastY = yForValue(values[lastValid], top, bottom, minimum, maximum);
        Paint dot = new Paint(Paint.ANTI_ALIAS_FLAG);
        dot.setColor(Color.WHITE);
        canvas.drawCircle(lastX, lastY, dp(5), dot);
        dot.setColor(accentColor);
        canvas.drawCircle(lastX, lastY, dp(3), dot);
    }

    private void drawAxisLabels(Canvas canvas, float left, float right, float bottom) {
        textPaint.setTextSize(sp(10));
        textPaint.setTextAlign(Paint.Align.LEFT);
        if (labels.length > 0) {
            canvas.drawText(labels[0], left, bottom + dp(20), textPaint);
            String last = labels[labels.length - 1];
            textPaint.setTextAlign(Paint.Align.RIGHT);
            canvas.drawText(last, right, bottom + dp(20), textPaint);
            textPaint.setTextAlign(Paint.Align.LEFT);
        }
    }

    private void drawTooltip(
            Canvas canvas,
            int index,
            float left,
            float right,
            float top,
            float bottom,
            float minimum,
            float maximum
    ) {
        float x = xForIndex(index, left, right);
        float y = yForValue(values[index], top, bottom, minimum, maximum);
        Paint marker = new Paint(Paint.ANTI_ALIAS_FLAG);
        marker.setColor(withAlpha(accentColor, 80));
        marker.setStrokeWidth(dp(1));
        canvas.drawLine(x, top, x, bottom, marker);
        marker.setColor(Color.WHITE);
        canvas.drawCircle(x, y, dp(6), marker);
        marker.setColor(accentColor);
        canvas.drawCircle(x, y, dp(4), marker);

        String label = index < labels.length ? labels[index] : "";
        String value = formatValue(values[index]) + (unit.isEmpty() ? "" : " " + unit);
        String content = label.isEmpty() ? value : label + "  " + value;
        textPaint.setTextSize(sp(11));
        textPaint.setColor(Color.WHITE);
        float width = textPaint.measureText(content) + dp(18);
        float tooltipLeft = Math.max(dp(4), Math.min(x - width / 2f, getWidth() - width - dp(4)));
        float tooltipTop = Math.max(dp(2), y - dp(42));
        RectF bounds = new RectF(tooltipLeft, tooltipTop, tooltipLeft + width, tooltipTop + dp(28));
        canvas.drawRoundRect(bounds, dp(6), dp(6), tooltipPaint);
        canvas.drawText(content, tooltipLeft + dp(9), tooltipTop + dp(18), textPaint);
        textPaint.setColor(Color.rgb(86, 101, 115));
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        if (values.length == 0) {
            return super.onTouchEvent(event);
        }
        if (event.getAction() == MotionEvent.ACTION_DOWN
                || event.getAction() == MotionEvent.ACTION_MOVE
                || event.getAction() == MotionEvent.ACTION_UP) {
            float left = dp(42);
            float right = getWidth() - dp(12);
            float normalized = Math.max(0f, Math.min(1f, (event.getX() - left) / Math.max(1f, right - left)));
            selectedIndex = Math.round(normalized * Math.max(0, values.length - 1));
            selectedIndex = nearestValidIndex(selectedIndex);
            invalidate();
            if (event.getAction() == MotionEvent.ACTION_UP) {
                performClick();
            }
            return true;
        }
        return super.onTouchEvent(event);
    }

    @Override
    public boolean performClick() {
        super.performClick();
        return true;
    }

    private float[] valueRange() {
        float minimum = Float.POSITIVE_INFINITY;
        float maximum = Float.NEGATIVE_INFINITY;
        for (float value : values) {
            if (!Float.isNaN(value)) {
                minimum = Math.min(minimum, value);
                maximum = Math.max(maximum, value);
            }
        }
        if (!Float.isFinite(minimum) || !Float.isFinite(maximum)) {
            return null;
        }
        float padding = Math.max(1f, (maximum - minimum) * 0.18f);
        if (maximum == minimum) {
            padding = Math.max(1f, Math.abs(maximum) * 0.05f);
        }
        float lower = forcedMinimum == null ? Math.max(0f, minimum - padding) : forcedMinimum;
        float upper = forcedMaximum == null ? maximum + padding : forcedMaximum;
        if (upper <= lower) {
            upper = lower + 1f;
        }
        return new float[]{lower, upper};
    }

    private boolean allValuesContiguous(int first, int last) {
        for (int index = first; index <= last; index++) {
            if (Float.isNaN(values[index])) {
                return false;
            }
        }
        return true;
    }

    private int nearestValidIndex(int start) {
        if (start < 0 || start >= values.length || !Float.isNaN(values[start])) {
            return start;
        }
        for (int distance = 1; distance < values.length; distance++) {
            int left = start - distance;
            int right = start + distance;
            if (left >= 0 && !Float.isNaN(values[left])) {
                return left;
            }
            if (right < values.length && !Float.isNaN(values[right])) {
                return right;
            }
        }
        return -1;
    }

    private float xForIndex(int index, float left, float right) {
        if (values.length <= 1) {
            return (left + right) / 2f;
        }
        return left + index * (right - left) / (values.length - 1f);
    }

    private float yForValue(float value, float top, float bottom, float minimum, float maximum) {
        float ratio = (value - minimum) / Math.max(0.0001f, maximum - minimum);
        return bottom - ratio * (bottom - top);
    }

    private String formatValue(float value) {
        if (Math.abs(value - Math.round(value)) < 0.05f) {
            return String.valueOf(Math.round(value));
        }
        return String.format(Locale.ITALY, "%.1f", value);
    }

    private String buildContentDescription() {
        int valid = 0;
        for (float value : values) {
            if (!Float.isNaN(value)) {
                valid++;
            }
        }
        return valid == 0
                ? "Grafico senza dati disponibili"
                : "Grafico con " + valid + " rilevazioni. Tocca il grafico per leggere i valori.";
    }

    private int withAlpha(int color, int alpha) {
        return Color.argb(alpha, Color.red(color), Color.green(color), Color.blue(color));
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private float sp(int value) {
        return value * getResources().getDisplayMetrics().scaledDensity;
    }
}
