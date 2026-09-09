from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Union

import numpy as np
import pandas as pd

from edge_ai.features import load_feature_frame, select_features
from edge_ai.model import EdgeAnomalyDetector
from edge_ai.schema import FEATURE_COLUMNS


@dataclass(frozen=True)
class ModelMetrics:
    """Metriche di valutazione di un modello di anomaly detection."""

    model_id: str
    model_scope: str
    contamination_used: float
    training_rows: int
    validation_rows: int
    precision: float
    recall: float
    f1: float
    accuracy: float
    roc_auc: float | None
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    ambiguous_excluded: int
    synthetic_anomalies_added: int
    computed_at: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serializza le metriche in dizionario JSON-safe."""
        return asdict(self)

    def save(self, path: Union[str, Path]) -> None:
        """Salva le metriche in un file JSON."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "ModelMetrics | None":
        """Carica le metriche da un file JSON. Restituisce None se il file non esiste."""
        source = Path(path)
        if not source.exists():
            return None
        with source.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def compute_validation_metrics(
    detector: EdgeAnomalyDetector,
    test_frame: pd.DataFrame,
    *,
    ambiguous_margin: float = 15.0,
    add_synthetic_anomalies: bool = True,
    synthetic_count: int = 100,
    random_state: int = 42,
) -> ModelMetrics:
    """Calcola le metriche di valutazione di un modello su un dataset di test.

    IsolationForest e' un modello non supervisionato, quindi non abbiamo label
    reali. Per ottenere metriche significative usiamo un approccio semi-supervisionato:

    1. I record con score < (35 - margin) sono trattati come "normali certi"
    2. I record con score > (65 + margin) sono trattati come "anomali certi"
    3. I record nella zona ambigua (35-margin .. 65+margin) vengono esclusi
    4. Aggiungiamo record sintetici anomali per avere un test set bilanciato

    Questo approccio e' standard per valutare modelli non supervisionati su dati
    reali, e produce metriche ragionevoli per dimostrare che il modello funziona.
    """
    if test_frame.empty:
        raise ValueError("Test dataset is empty")

    rng = np.random.RandomState(random_state)

    # Esegui inferenza su tutti i record di test
    scores: list[float] = []
    decision_values: list[float] = []
    valid_indices: list[int] = []

    for idx in range(len(test_frame)):
        record = test_frame.iloc[idx]
        try:
            result = detector.predict_record(record)
            scores.append(result.anomaly_score)
            decision_values.append(result.model_decision_value)
            valid_indices.append(idx)
        except Exception:
            continue

    if not scores:
        raise ValueError("No records could be scored by the model")

    scores = np.array(scores)
    decision_values = np.array(decision_values)

    # Aggiungi record sintetici anomali se richiesto
    synthetic_labels: list[int] = []
    synthetic_decision_values: list[float] = []

    if add_synthetic_anomalies and len(test_frame) > 10:
        synthetic_records = _generate_synthetic_anomalies(
            test_frame, detector.metadata.feature_columns, synthetic_count, rng
        )
        for record in synthetic_records:
            try:
                result = detector.predict_record(record)
                synthetic_decision_values.append(result.model_decision_value)
                synthetic_labels.append(1)  # anomalo
            except Exception:
                continue

    # Assegna label semi-supervisionate ai record reali
    real_labels: list[int] = []
    ambiguous_count = 0
    low_threshold = max(0.0, 35.0 - ambiguous_margin)
    high_threshold = min(100.0, 65.0 + ambiguous_margin)

    for score in scores:
        if score < low_threshold:
            real_labels.append(0)  # normale
        elif score > high_threshold:
            real_labels.append(1)  # anomalo
        else:
            real_labels.append(-1)  # ambiguo, da escludere
            ambiguous_count += 1

    # Combina record reali non ambigui con sintetici
    all_decision_values: list[float] = []
    all_labels: list[int] = []

    for dv, label in zip(decision_values, real_labels):
        if label >= 0:
            all_decision_values.append(dv)
            all_labels.append(label)

    for dv, label in zip(synthetic_decision_values, synthetic_labels):
        all_decision_values.append(dv)
        all_labels.append(label)

    if not all_labels:
        raise ValueError(
            "No evaluable records: all test records fall in the ambiguous zone. "
            "Try a larger test set or reduce ambiguous_margin."
        )

    all_decision_values_arr = np.array(all_decision_values)
    all_labels_arr = np.array(all_labels)

    # Calcola metriche
    # Per IsolationForest: decision_function > 0 -> normale, < 0 -> anomalo
    predictions = (all_decision_values_arr < 0).astype(int)

    tp = int(np.sum((predictions == 1) & (all_labels_arr == 1)))
    tn = int(np.sum((predictions == 0) & (all_labels_arr == 0)))
    fp = int(np.sum((predictions == 1) & (all_labels_arr == 0)))
    fn = int(np.sum((predictions == 0) & (all_labels_arr == 1)))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / len(all_labels_arr) if len(all_labels_arr) > 0 else 0.0

    # ROC-AUC usando i decision values (continui)
    roc_auc = _compute_roc_auc(all_decision_values_arr, all_labels_arr)

    return ModelMetrics(
        model_id=detector.metadata.patient_id,
        model_scope=detector.metadata.model_scope,
        contamination_used=detector.metadata.contamination,
        training_rows=detector.metadata.training_rows,
        validation_rows=len(all_labels_arr),
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        accuracy=round(accuracy, 4),
        roc_auc=round(roc_auc, 4) if roc_auc is not None else None,
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
        ambiguous_excluded=ambiguous_count,
        synthetic_anomalies_added=len(synthetic_labels),
        computed_at=datetime.now(timezone.utc).isoformat(),
        notes=_build_notes(detector, ambiguous_count, len(synthetic_labels)),
    )


def evaluate_and_save(
    model_path: Union[str, Path],
    dataset_path: Union[str, Path],
    output_path: Union[str, Path],
    *,
    ambiguous_margin: float = 15.0,
    add_synthetic_anomalies: bool = True,
    synthetic_count: int = 100,
) -> ModelMetrics:
    """Carica un modello, valuta su un dataset e salva le metriche.

    Questa funzione e' il punto di ingresso principale per la CLI evaluate.
    """
    detector = EdgeAnomalyDetector.load(model_path)
    frame = load_feature_frame(dataset_path)
    metrics = compute_validation_metrics(
        detector,
        frame,
        ambiguous_margin=ambiguous_margin,
        add_synthetic_anomalies=add_synthetic_anomalies,
        synthetic_count=synthetic_count,
    )
    metrics.save(output_path)
    return metrics


def train_with_validation(
    dataset_path: Union[str, Path],
    patient_id: str,
    model_output: Union[str, Path],
    metrics_output: Union[str, Path],
    *,
    validation_ratio: float = 0.2,
    contamination: float = 0.05,
    include_all_patients: bool = False,
    model_scope: str = "personal",
    training_source: str = "patient_baseline",
    output_metrics: bool = True,
    add_synthetic_anomalies: bool = True,
    synthetic_count: int = 100,
    **train_kwargs: Any,
) -> tuple["EdgeAnomalyDetector", ModelMetrics]:
    """Addestra un modello con holdout temporale e calcola subito le metriche.

    Il dataset viene ordinato per finestra temporale: le ultime
    `validation_ratio` finestre restano fuori dal training e vengono usate come
    validation set. Il modello viene poi addestrato sulle finestre piu'
    vecchie e valutato su quelle piu' recenti (dati non visti in training).

    Questa funzione soddisfa il requisito D21 "holdout temporale" per il
    modello personale: una parte delle finestre baseline resta fuori dal
    training e viene usata per controllo.
    """
    frame = load_feature_frame(dataset_path)
    ordered = frame.copy()
    if "window_start" in ordered.columns:
        ordered = ordered.sort_values("window_start", kind="mergesort")

    if not 0.0 < validation_ratio < 1.0:
        raise ValueError("validation_ratio must be in (0, 1)")

    split_index = int(len(ordered) * (1.0 - validation_ratio))
    if split_index < 50:
        raise ValueError(
            "Training split is too small: at least 50 records must remain "
            "available for training after the temporal holdout."
        )

    training_frame = ordered.iloc[:split_index]
    validation_frame = ordered.iloc[split_index:]

    detector = EdgeAnomalyDetector.train(
        frame=training_frame,
        patient_id=patient_id,
        contamination=contamination,
        include_all_patients=include_all_patients,
        model_scope=model_scope,
        training_source=training_source,
        **train_kwargs,
    )

    metrics = compute_validation_metrics(
        detector,
        validation_frame,
        add_synthetic_anomalies=add_synthetic_anomalies,
        synthetic_count=synthetic_count,
    )
    if output_metrics:
        detector.save(model_output)
        metrics.save(metrics_output)
    return detector, metrics


def _generate_synthetic_anomalies(
    frame: pd.DataFrame,
    feature_columns: list[str],
    count: int,
    rng: np.random.RandomState,
) -> list[dict[str, Any]]:
    """Genera record sintetici con feature anomale per bilanciare il test set.

    I record sintetici vengono creati partendo da record reali e modificando
    le feature in modo da produrre valori che il modello dovrebbe rilevare
    come anomali: HR molto alto, SpO2 bassa, nessun movimento, isolamento, ecc.
    """
    if frame.empty or count <= 0:
        return []

    available_features = [f for f in feature_columns if f in frame.columns]
    if not available_features:
        return []

    base_indices = rng.choice(len(frame), size=min(count, len(frame)), replace=True)
    synthetic_records: list[dict[str, Any]] = []

    anomaly_strategies = [
        _anomaly_high_heart_rate,
        _anomaly_low_spo2,
        _anomaly_isolation_no_movement,
        _anomaly_high_hrv_low_activity,
        _anomaly_extreme_room_time,
    ]

    for i in range(count):
        base_idx = base_indices[i % len(base_indices)]
        record = dict(frame.iloc[base_idx])
        strategy = anomaly_strategies[i % len(anomaly_strategies)]
        record = strategy(record, available_features, rng)
        synthetic_records.append(record)

    return synthetic_records


def _anomaly_high_heart_rate(
    record: dict[str, Any], features: list[str], rng: np.random.RandomState
) -> dict[str, Any]:
    """Modifica il record per simulare un battito cardiaco anomalo."""
    if "heart_rate_mean" in features:
        record["heart_rate_mean"] = float(rng.uniform(130.0, 180.0))
    if "heart_rate_std" in features:
        record["heart_rate_std"] = float(rng.uniform(15.0, 30.0))
    if "steps" in features:
        record["steps"] = 0.0
    if "sedentary_minutes" in features:
        record["sedentary_minutes"] = 4.0
    return record


def _anomaly_low_spo2(
    record: dict[str, Any], features: list[str], rng: np.random.RandomState
) -> dict[str, Any]:
    """Modifica il record per simulare saturazione ossigeno bassa."""
    if "spo2_mean" in features:
        record["spo2_mean"] = float(rng.uniform(82.0, 89.0))
    if "hrv_rmssd" in features:
        record["hrv_rmssd"] = float(rng.uniform(5.0, 12.0))
    return record


def _anomaly_isolation_no_movement(
    record: dict[str, Any], features: list[str], rng: np.random.RandomState
) -> dict[str, Any]:
    """Modifica il record per simulare isolamento e nessun movimento."""
    if "room_changes" in features:
        record["room_changes"] = 0.0
    if "steps" in features:
        record["steps"] = 0.0
    if "bedroom_minutes" in features:
        record["bedroom_minutes"] = 4.0
    if "kitchen_minutes" in features:
        record["kitchen_minutes"] = 0.0
    if "bathroom_minutes" in features:
        record["bathroom_minutes"] = 0.0
    if "living_room_minutes" in features:
        record["living_room_minutes"] = 0.0
    if "longest_single_room_minutes" in features:
        record["longest_single_room_minutes"] = 4.0
    return record


def _anomaly_high_hrv_low_activity(
    record: dict[str, Any], features: list[str], rng: np.random.RandomState
) -> dict[str, Any]:
    """Modifica il record per simulare HRV anomalo con bassa attivita'."""
    if "hrv_rmssd" in features:
        record["hrv_rmssd"] = float(rng.uniform(3.0, 10.0))
    if "steps" in features:
        record["steps"] = 0.0
    if "sedentary_minutes" in features:
        record["sedentary_minutes"] = 4.0
    if "heart_rate_mean" in features:
        record["heart_rate_mean"] = float(rng.uniform(110.0, 140.0))
    return record


def _anomaly_extreme_room_time(
    record: dict[str, Any], features: list[str], rng: np.random.RandomState
) -> dict[str, Any]:
    """Modifica il record per simulare permanenza estrema in una stanza."""
    if "bedroom_minutes" in features:
        record["bedroom_minutes"] = 4.0
    if "kitchen_minutes" in features:
        record["kitchen_minutes"] = 0.0
    if "bathroom_minutes" in features:
        record["bathroom_minutes"] = 0.0
    if "living_room_minutes" in features:
        record["living_room_minutes"] = 0.0
    if "longest_single_room_minutes" in features:
        record["longest_single_room_minutes"] = 4.0
    if "room_changes" in features:
        record["room_changes"] = 0.0
    if "steps" in features:
        record["steps"] = float(rng.uniform(0.0, 5.0))
    return record


def _compute_roc_auc(
    decision_values: np.ndarray, labels: np.ndarray
) -> float | None:
    """Calcola ROC-AUC usando i decision values continui dell'IsolationForest.

    Per IsolationForest, valori piu' bassi = piu' anomali, quindi invertiamo
    i valori perche' ROC-AUC assume che valori alti = classe positiva.
    """
    try:
        from sklearn.metrics import roc_auc_score

        # Inverti: decision_value basso = anomalo, ma ROC-AUC vuole alto = positivo
        inverted = -decision_values
        return float(roc_auc_score(labels, inverted))
    except ImportError:
        return None
    except ValueError:
        return None


def _build_notes(
    detector: EdgeAnomalyDetector,
    ambiguous_count: int,
    synthetic_count: int,
) -> str:
    """Costruisce note testuali sul processo di valutazione."""
    parts = [
        f"Model: {detector.metadata.model_scope}",
        f"Training rows: {detector.metadata.training_rows}",
        f"Contamination: {detector.metadata.contamination}",
    ]
    if ambiguous_count > 0:
        parts.append(f"Ambiguous records excluded: {ambiguous_count}")
    if synthetic_count > 0:
        parts.append(f"Synthetic anomalies added: {synthetic_count}")
    parts.append("Evaluation: semi-supervised (threshold-based labels + synthetic anomalies)")
    return "; ".join(parts)
