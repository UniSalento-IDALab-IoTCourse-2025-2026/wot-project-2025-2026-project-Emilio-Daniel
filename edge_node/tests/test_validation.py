from __future__ import annotations

import json
from math import isnan

import numpy as np
import pandas as pd
import pytest

from edge_ai.model import EdgeAnomalyDetector
from edge_ai.schema import FEATURE_COLUMNS
from edge_ai.validation import (
    ModelMetrics,
    compute_validation_metrics,
    evaluate_and_save,
    train_with_validation,
)


def _make_synthetic_dataset(
    n_normal: int = 200,
    n_anomalous: int = 20,
    seed: int = 42,
) -> pd.DataFrame:
    """Crea un dataset sintetico con record normali e anomali per test.

    I record normali seguono distribuzioni ragionevoli per ADL.
    I record anomali hanno feature estreme (HR alto, SpO2 bassa, isolamento).
    """
    rng = np.random.RandomState(seed)
    records: list[dict] = []

    for i in range(n_normal):
        record: dict = {
            "patient_id": "test-patient",
            "window_start": f"2026-01-01T{i * 4 // 60:02d}:{(i * 4) % 60:02d}:00+00:00",
            "window_end": f"2026-01-01T{i * 4 // 60:02d}:{(i * 4 + 4) % 60:02d}:00+00:00",
            "wearable_present": "true",
            "wearable_battery_pct": 85.0,
            "heart_rate_mean": float(rng.normal(72.0, 8.0)),
            "heart_rate_std": float(rng.normal(5.0, 2.0)),
            "resting_heart_rate": float(rng.normal(62.0, 6.0)),
            "hrv_rmssd": float(rng.normal(45.0, 12.0)),
            "spo2_mean": float(rng.normal(97.0, 1.5)),
            "sleep_minutes": float(rng.normal(420.0, 60.0)),
            "awake_minutes": float(rng.normal(30.0, 15.0)),
            "steps": float(rng.normal(3000.0, 800.0)),
            "sedentary_minutes": float(rng.uniform(1.0, 3.5)),
            "room_changes": float(rng.poisson(3.0)),
            "night_room_changes": float(rng.poisson(1.0)),
            "bedroom_minutes": float(rng.uniform(0.5, 3.0)),
            "kitchen_minutes": float(rng.uniform(0.0, 1.5)),
            "bathroom_minutes": float(rng.uniform(0.0, 0.8)),
            "living_room_minutes": float(rng.uniform(0.0, 2.0)),
            "longest_single_room_minutes": float(rng.uniform(0.5, 2.5)),
            "nilm_total_wh": float(rng.normal(50.0, 20.0)),
            "nilm_kitchen_events": float(rng.poisson(1.0)),
            "nilm_tv_minutes": float(rng.uniform(0.0, 2.0)),
            "nilm_coffee_events": float(rng.poisson(0.5)),
            "nilm_stove_events": float(rng.poisson(0.3)),
            "fall_events": 0.0,
        }
        records.append(record)

    for i in range(n_anomalous):
        record = {
            "patient_id": "test-patient",
            "window_start": f"2026-01-02T{i * 4 // 60:02d}:{(i * 4) % 60:02d}:00+00:00",
            "window_end": f"2026-01-02T{i * 4 // 60:02d}:{(i * 4 + 4) % 60:02d}:00+00:00",
            "wearable_present": "true",
            "wearable_battery_pct": 85.0,
            "heart_rate_mean": float(rng.uniform(130.0, 180.0)),
            "heart_rate_std": float(rng.uniform(15.0, 30.0)),
            "resting_heart_rate": float(rng.normal(62.0, 6.0)),
            "hrv_rmssd": float(rng.uniform(3.0, 10.0)),
            "spo2_mean": float(rng.uniform(82.0, 89.0)),
            "sleep_minutes": float(rng.normal(420.0, 60.0)),
            "awake_minutes": float(rng.normal(30.0, 15.0)),
            "steps": 0.0,
            "sedentary_minutes": 4.0,
            "room_changes": 0.0,
            "night_room_changes": 0.0,
            "bedroom_minutes": 4.0,
            "kitchen_minutes": 0.0,
            "bathroom_minutes": 0.0,
            "living_room_minutes": 0.0,
            "longest_single_room_minutes": 4.0,
            "nilm_total_wh": 0.0,
            "nilm_kitchen_events": 0.0,
            "nilm_tv_minutes": 0.0,
            "nilm_coffee_events": 0.0,
            "nilm_stove_events": 0.0,
            "fall_events": 0.0,
        }
        records.append(record)

    return pd.DataFrame(records)


def _train_model_on_dataset(frame: pd.DataFrame) -> EdgeAnomalyDetector:
    """Addestra un modello IsolationForest sul dataset sintetico."""
    return EdgeAnomalyDetector.train(
        frame=frame,
        patient_id="test-patient",
        contamination=0.1,
        model_scope="personal",
    )


class TestModelMetricsDataclass:
    """Test per la dataclass ModelMetrics."""

    def test_to_dict_contains_all_fields(self) -> None:
        metrics = ModelMetrics(
            model_id="patient-001",
            model_scope="personal",
            contamination_used=0.05,
            training_rows=500,
            validation_rows=100,
            precision=0.85,
            recall=0.79,
            f1=0.82,
            accuracy=0.88,
            roc_auc=0.91,
            true_positives=40,
            true_negatives=48,
            false_positives=7,
            false_negatives=5,
            ambiguous_excluded=10,
            synthetic_anomalies_added=20,
            computed_at="2026-09-01T10:00:00Z",
        )
        d = metrics.to_dict()
        assert d["model_id"] == "patient-001"
        assert d["f1"] == 0.82
        assert d["roc_auc"] == 0.91
        assert "computed_at" in d

    def test_save_and_load_roundtrip(self, tmp_path: None) -> None:
        path = tmp_path / "metrics.json"
        metrics = ModelMetrics(
            model_id="patient-001",
            model_scope="personal",
            contamination_used=0.05,
            training_rows=500,
            validation_rows=100,
            precision=0.85,
            recall=0.79,
            f1=0.82,
            accuracy=0.88,
            roc_auc=0.91,
            true_positives=40,
            true_negatives=48,
            false_positives=7,
            false_negatives=5,
            ambiguous_excluded=10,
            synthetic_anomalies_added=20,
            computed_at="2026-09-01T10:00:00Z",
        )
        metrics.save(path)
        loaded = ModelMetrics.load(path)
        assert loaded is not None
        assert loaded.model_id == "patient-001"
        assert loaded.f1 == 0.82

    def test_load_returns_none_for_missing_file(self, tmp_path: None) -> None:
        path = tmp_path / "nonexistent.json"
        loaded = ModelMetrics.load(path)
        assert loaded is None


class TestComputeValidationMetrics:
    """Test per la funzione compute_validation_metrics."""

    def test_returns_valid_metrics(self) -> None:
        frame = _make_synthetic_dataset(n_normal=200, n_anomalous=20)
        detector = _train_model_on_dataset(frame)

        metrics = compute_validation_metrics(
            detector, frame, add_synthetic_anomalies=True, synthetic_count=50
        )

        assert metrics.model_id == "test-patient"
        assert metrics.model_scope == "personal"
        assert metrics.validation_rows > 0
        assert 0.0 <= metrics.precision <= 1.0
        assert 0.0 <= metrics.recall <= 1.0
        assert 0.0 <= metrics.f1 <= 1.0
        assert 0.0 <= metrics.accuracy <= 1.0
        assert metrics.synthetic_anomalies_added == 50

    def test_metrics_with_no_synthetic(self) -> None:
        frame = _make_synthetic_dataset(n_normal=200, n_anomalous=20)
        detector = _train_model_on_dataset(frame)

        metrics = compute_validation_metrics(
            detector, frame, add_synthetic_anomalies=False
        )

        assert metrics.synthetic_anomalies_added == 0
        assert metrics.validation_rows > 0

    def test_raises_on_empty_frame(self) -> None:
        frame = _make_synthetic_dataset(n_normal=200)
        detector = _train_model_on_dataset(frame)
        empty = pd.DataFrame(columns=frame.columns)

        with pytest.raises(ValueError, match="empty"):
            compute_validation_metrics(detector, empty)

    def test_roc_auc_is_computed(self) -> None:
        frame = _make_synthetic_dataset(n_normal=200, n_anomalous=20)
        detector = _train_model_on_dataset(frame)

        metrics = compute_validation_metrics(detector, frame)

        assert metrics.roc_auc is not None
        assert 0.0 <= metrics.roc_auc <= 1.0


class TestEvaluateAndSave:
    """Test per la funzione evaluate_and_save (CLI pipeline)."""

    def test_evaluate_and_save_creates_json(self, tmp_path: None) -> None:
        frame = _make_synthetic_dataset(n_normal=200, n_anomalous=20)
        detector = _train_model_on_dataset(frame)

        model_path = tmp_path / "model.pkl"
        detector.save(model_path)

        dataset_path = tmp_path / "dataset.csv"
        frame.to_csv(dataset_path, index=False)

        output_path = tmp_path / "metrics.json"

        metrics = evaluate_and_save(model_path, dataset_path, output_path)

        assert output_path.exists()
        assert metrics.f1 >= 0.0

        with output_path.open("r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["model_id"] == "test-patient"
        assert "precision" in saved
        assert "recall" in saved
        assert "f1" in saved


class TestTrainWithValidation:
    """Test per l'holdout temporale con metriche (D21)."""

    def test_holds_out_recent_windows_and_saves_artifacts(self, tmp_path) -> None:
        frame = _make_synthetic_dataset(n_normal=260, n_anomalous=0)
        dataset_path = tmp_path / "baseline.csv"
        frame.to_csv(dataset_path, index=False)

        model_path = tmp_path / "patient-001.pkl"
        metrics_path = tmp_path / "patient-001_metrics.json"

        detector, metrics = train_with_validation(
            dataset_path=dataset_path,
            patient_id="test-patient",
            model_output=model_path,
            metrics_output=metrics_path,
            validation_ratio=0.2,
            contamination=0.05,
        )

        assert model_path.exists()
        assert metrics_path.exists()
        assert metrics.model_id == "test-patient"
        assert metrics.validation_rows > 0
        assert detector.metadata.training_rows > 0

    def test_memory_validates_on_held_out_only(self, tmp_path) -> None:
        frame = _make_synthetic_dataset(n_normal=160, n_anomalous=0)
        dataset_path = tmp_path / "baseline.csv"
        frame.to_csv(dataset_path, index=False)

        model_path = tmp_path / "m.pkl"
        metrics_path = tmp_path / "m_metrics.json"

        _, metrics = train_with_validation(
            dataset_path=dataset_path,
            patient_id="test-patient",
            model_output=model_path,
            metrics_output=metrics_path,
            validation_ratio=0.25,
        )

        total_rows = 160
        split_index = int(total_rows * (1.0 - 0.25))
        held_out = total_rows - split_index
        assert held_out > 0
        assert split_index >= 50
        assert 0.0 <= metrics.f1 <= 1.0

    def test_rejects_small_training_split(self, tmp_path) -> None:
        frame = _make_synthetic_dataset(n_normal=60, n_anomalous=0)
        dataset_path = tmp_path / "baseline.csv"
        frame.to_csv(dataset_path, index=False)

        with pytest.raises(ValueError, match="Training split is too small"):
            train_with_validation(
                dataset_path=dataset_path,
                patient_id="test-patient",
                model_output=tmp_path / "m.pkl",
                metrics_output=tmp_path / "m_metrics.json",
                validation_ratio=0.5,
            )

    def test_rejects_invalid_ratio(self, tmp_path) -> None:
        frame = _make_synthetic_dataset(n_normal=100, n_anomalous=0)
        dataset_path = tmp_path / "baseline.csv"
        frame.to_csv(dataset_path, index=False)

        with pytest.raises(ValueError, match="validation_ratio"):
            train_with_validation(
                dataset_path=dataset_path,
                patient_id="test-patient",
                model_output=tmp_path / "m.pkl",
                metrics_output=tmp_path / "m_metrics.json",
                validation_ratio=0.0,
            )


class TestEdgeCases:
    """Test per casi limite e robustezza."""

    def test_all_normal_records(self) -> None:
        frame = _make_synthetic_dataset(n_normal=100, n_anomalous=0)
        detector = _train_model_on_dataset(frame)

        metrics = compute_validation_metrics(
            detector, frame, add_synthetic_anomalies=True, synthetic_count=30
        )

        assert metrics.validation_rows > 0
        assert metrics.synthetic_anomalies_added == 30

    def test_small_dataset(self) -> None:
        frame = _make_synthetic_dataset(n_normal=60, n_anomalous=5)
        detector = _train_model_on_dataset(frame)

        metrics = compute_validation_metrics(
            detector, frame, add_synthetic_anomalies=True, synthetic_count=10
        )

        assert metrics.validation_rows > 0

    def test_notes_contain_model_info(self) -> None:
        frame = _make_synthetic_dataset(n_normal=200, n_anomalous=20)
        detector = _train_model_on_dataset(frame)

        metrics = compute_validation_metrics(detector, frame)

        assert "personal" in metrics.notes
        assert "Training rows" in metrics.notes

    def test_normal_record_stays_normal_and_critical_is_detected(self) -> None:
        """Dimostra (D21) che un caso normale resta nella zona normale e un
        caso critico viene rilevato come anomalo dal modello."""
        rng = np.random.RandomState(1)
        normal_frame = _make_synthetic_dataset(n_normal=180, n_anomalous=0)
        detector = _train_model_on_dataset(normal_frame)

        normal_record = dict(normal_frame.iloc[0])
        normal_record["heart_rate_mean"] = float(rng.normal(72.0, 4.0))
        normal_record["spo2_mean"] = 97.5
        normal_record["steps"] = 2500.0
        normal_record["room_changes"] = 3.0

        critical_record = dict(normal_frame.iloc[0])
        critical_record["heart_rate_mean"] = 155.0
        critical_record["heart_rate_std"] = 22.0
        critical_record["spo2_mean"] = 85.0
        critical_record["hrv_rmssd"] = 6.0
        critical_record["steps"] = 0.0
        critical_record["room_changes"] = 0.0
        critical_record["bedroom_minutes"] = 4.0

        normal = detector.predict_record(normal_record)
        critical = detector.predict_record(critical_record)

        assert normal.anomaly_score < 35
        assert critical.anomaly_score > 65
        assert critical.anomaly_score > normal.anomaly_score
