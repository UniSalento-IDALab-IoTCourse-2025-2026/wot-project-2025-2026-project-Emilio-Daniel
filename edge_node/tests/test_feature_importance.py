from __future__ import annotations

import json
import math
from dataclasses import replace

import pandas as pd
import pytest

from edge_ai.feature_importance import (
    FEATURE_CATEGORIES,
    FEATURE_LABELS,
    compute_feature_importance,
    feature_category,
    feature_label,
)
from edge_ai.model import EdgeAnomalyDetector
from edge_ai.schema import FEATURE_COLUMNS

from test_validation import _make_synthetic_dataset


def _train_personal(n: int = 220, seed: int = 42) -> EdgeAnomalyDetector:
    frame = _make_synthetic_dataset(n_normal=n, n_anomalous=0, seed=seed)
    detector = EdgeAnomalyDetector.train(
        frame=frame,
        patient_id="test-patient",
        contamination=0.05,
        random_state=seed,
    )
    assert detector.metadata.feature_medians
    return detector


def _base_record(detector: EdgeAnomalyDetector) -> dict:
    frame = _make_synthetic_dataset(n_normal=1, n_anomalous=0, seed=99)
    row = frame.iloc[0].to_dict()
    record = {column: float(row[column]) for column in FEATURE_COLUMNS}
    record["patient_id"] = "test-patient"
    record["window_start"] = "2026-01-05T00:00:00+00:00"
    record["window_end"] = "2026-01-05T00:04:00+00:00"
    record["wearable_present"] = "true"
    return record


def _importance_for(detector: EdgeAnomalyDetector, record: dict) -> dict:
    result = compute_feature_importance(detector, record, top_k=6)
    assert result.get("available") is True
    assert result["items"], f"No importance items for record: {record}"
    return result


def _top_feature(result: dict) -> str:
    return str(result["items"][0]["feature"])


class TestControlledScenarios:
    def test_high_heart_rate_ranks_heart_rate_mean(self) -> None:
        detector = _train_personal()
        record = _base_record(detector)
        record["heart_rate_mean"] = 155.0
        result = _importance_for(detector, record)
        item = next(x for x in result["items"] if x["feature"] == "heart_rate_mean")
        assert item["impact"] == "aumenta_indice"
        assert item["weight"] >= 0.15
        assert 100 < item["value"] < 200
        assert abs(item["reference"] - 72.0) < 6.0

    def test_low_spo2_ranks_spo2_mean(self) -> None:
        detector = _train_personal()
        record = _base_record(detector)
        record["spo2_mean"] = 85.0
        result = _importance_for(detector, record)
        item = next(x for x in result["items"] if x["feature"] == "spo2_mean")
        assert item["impact"] == "aumenta_indice"
        assert item["weight"] >= 0.15

    def test_room_isolation_ranks_spatial_feature(self) -> None:
        detector = _train_personal()
        record = _base_record(detector)
        record["longest_single_room_minutes"] = 55.0
        record["bedroom_minutes"] = 40.0
        record["room_changes"] = 0.0
        result = _importance_for(detector, record)
        spatial_top = any(
            item["category"] == "spaziale" and item["weight"] >= 0.2
            for item in result["items"]
        )
        assert spatial_top
        item = next(x for x in result["items"] if x["feature"] == "longest_single_room_minutes")
        assert item["impact"] == "aumenta_indice"

    def test_absence_of_movement_ranks_steps(self) -> None:
        detector = _train_personal()
        record = _base_record(detector)
        record["steps"] = 0.0
        record["sedentary_minutes"] = 4.0
        result = _importance_for(detector, record)
        item = next(x for x in result["items"] if x["feature"] == "steps")
        assert item["impact"] == "aumenta_indice"
        assert item["weight"] >= 0.15


class TestImportanceFormat:
    def test_item_shape_matches_d23_contract(self) -> None:
        detector = _train_personal()
        record = _base_record(detector)
        record["heart_rate_mean"] = 150.0
        result = _importance_for(detector, record)
        item = result["items"][0]
        required = {"feature", "label", "impact", "weight", "value", "reference"}
        assert required <= set(item)
        assert item["impact"] in {"aumenta_indice", "riduce_indice"}
        assert 0.0 <= item["weight"] <= 1.0

    def test_ranking_sorted_by_weight(self) -> None:
        detector = _train_personal()
        record = _base_record(detector)
        record["heart_rate_mean"] = 160.0
        record["spo2_mean"] = 84.0
        result = _importance_for(detector, record)
        weights = [item["weight"] for item in result["items"]]
        assert weights == sorted(weights, reverse=True)

    def test_categories_assigned(self) -> None:
        detector = _train_personal()
        record = _base_record(detector)
        record["heart_rate_mean"] = 150.0
        result = _importance_for(detector, record)
        for item in result["items"]:
            assert item["category"] in {"wearable", "spaziale", "nilm", "personale", "altro"}

    def test_result_is_json_serializable(self) -> None:
        detector = _train_personal()
        record = _base_record(detector)
        record["heart_rate_mean"] = 150.0
        result = _importance_for(detector, record)
        json.dumps(result)

    def test_baseline_score_present(self) -> None:
        detector = _train_personal()
        record = _base_record(detector)
        record["heart_rate_mean"] = 150.0
        result = _importance_for(detector, record)
        assert isinstance(result.get("baseline_score"), (int, float))


class TestMissingMedians:
    def test_unavailable_when_no_medians(self) -> None:
        detector = _train_personal()
        detector.metadata = replace(detector.metadata, feature_medians={})
        result = compute_feature_importance(detector, _base_record(detector))
        assert result["available"] is False

    def test_accepts_pandas_series_record(self) -> None:
        detector = _train_personal()
        frame = _make_synthetic_dataset(n_normal=2, n_anomalous=0, seed=5)
        row = frame.iloc[0].copy()
        row["heart_rate_mean"] = 155.0
        result = _importance_for(detector, row)
        assert any(x["feature"] == "heart_rate_mean" for x in result["items"])


class TestLabelHelpers:
    def test_known_label(self) -> None:
        assert feature_label("heart_rate_mean") == FEATURE_LABELS["heart_rate_mean"]
        assert feature_label("spo2_mean") == "Saturazione ossigeno (SpO2)"

    def test_fallback_label(self) -> None:
        assert feature_label("unknown_feature") == "Unknown feature"

    def test_known_category(self) -> None:
        assert feature_category("nilm_tv_minutes") == "nilm"
        assert feature_category("room_changes") == "spaziale"
        assert feature_category("heart_rate_mean") == "wearable"
        assert feature_category("fall_events") == "personale"