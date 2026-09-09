from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from edge_ai.confidence import (
    HIGH_CONFIDENCE,
    MEDIUM_CONFIDENCE,
    SOURCE_FEATURES,
    SourceCompleteness,
    compute_confidence,
    confidence_level_from_score,
)


def _full_record() -> dict:
    return {
        "patient_id": "test-patient",
        "window_start": "2026-01-01T00:00:00+00:00",
        "window_end": "2026-01-01T00:04:00+00:00",
        "wearable_present": "true",
        "wearable_battery_pct": 85.0,
        "heart_rate_mean": 72.5,
        "heart_rate_std": 5.2,
        "resting_heart_rate": 61.0,
        "hrv_rmssd": 46.0,
        "spo2_mean": 97.5,
        "sleep_minutes": 420.0,
        "awake_minutes": 30.0,
        "steps": 3000.0,
        "sedentary_minutes": 2.0,
        "room_changes": 3.0,
        "night_room_changes": 0.0,
        "bedroom_minutes": 8.0,
        "kitchen_minutes": 4.0,
        "bathroom_minutes": 2.0,
        "living_room_minutes": 6.0,
        "longest_single_room_minutes": 9.0,
        "nilm_total_wh": 250.0,
        "nilm_kitchen_events": 3.0,
        "nilm_tv_minutes": 18.0,
        "nilm_coffee_events": 1.0,
        "nilm_stove_events": 1.0,
        "fall_events": 0.0,
    }


def _sparse_record() -> dict:
    record = _full_record()
    for feature in SOURCE_FEATURES["google_health"]:
        record[feature] = math.nan
    for feature in SOURCE_FEATURES["shelly"][2:]:
        record[feature] = math.nan
    record["fall_events"] = None
    record["wearable_present"] = ""
    return record


class TestComputeConfidenceLevels:
    def test_full_record_is_alta(self) -> None:
        result = compute_confidence(_full_record(), personal_model_available=True)
        assert result.score >= HIGH_CONFIDENCE
        assert result.level == "alta"
        assert "modello personale disponibile" in result.reasons

    def test_sparse_record_is_bassa(self) -> None:
        result = compute_confidence(_sparse_record(), personal_model_available=False)
        assert result.score < MEDIUM_CONFIDENCE
        assert result.level == "bassa"
        assert result.score > 0

    def test_partial_record_is_media(self) -> None:
        record = _full_record()
        for feature in ["spo2_mean", "steps", "nilm_total_wh", "nilm_tv_minutes", "living_room_minutes", "bedroom_minutes"]:
            record[feature] = math.nan
        result = compute_confidence(record, personal_model_available=True)
        assert MEDIUM_CONFIDENCE <= result.score < HIGH_CONFIDENCE
        assert result.level == "media"

    def test_penalties_bring_score_down(self) -> None:
        full = compute_confidence(_full_record(), personal_model_available=True)
        penalized = compute_confidence(
            dict(_full_record(), wearable_present="false"),
            personal_model_available=False,
            ble_samples=1,
            mqtt_queue_depth=30,
        )
        assert penalized.score < full.score
        assert any("wearable assente" in reason for reason in penalized.reasons)
        assert any("BLE scarsi" in reason for reason in penalized.reasons)
        assert any("MQTT" in reason for reason in penalized.reasons)

    def test_score_never_exceeds_bounds(self) -> None:
        result = compute_confidence(_full_record(), personal_model_available=True)
        assert 0 <= result.score <= 100


class TestSourceCompleteness:
    def test_reports_presence_by_source(self) -> None:
        result = compute_confidence(_full_record())
        by_source = {source.source: source for source in result.sources}
        assert by_source["google_health"].available
        assert by_source["google_health"].completeness == 1.0
        assert by_source["ble"].completeness == 1.0
        assert by_source["shelly"].completeness == 1.0
        assert by_source["patient_app"].available

    def test_reports_missing_features(self) -> None:
        result = compute_confidence(_sparse_record())
        assert "heart_rate_mean" in result.missing_features
        assert "fall_events" in result.missing_features

    def test_partial_source_is_parziale(self) -> None:
        record = _full_record()
        record["hrv_rmssd"] = math.nan
        record["resting_heart_rate"] = math.nan
        result = compute_confidence(record)
        assert any("Google Health parziale" in reason for reason in result.reasons)

    def test_to_dict_is_serializable(self) -> None:
        result = compute_confidence(_full_record(), personal_model_available=True)
        payload = result.to_dict()
        assert {"score", "level", "reasons", "sources", "missing_features", "penalties"} <= set(payload)
        assert isinstance(payload["score"], int)
        assert payload["level"] in {"alta", "media", "bassa"}


class TestLevelMapping:
    def test_high(self) -> None:
        assert confidence_level_from_score(80) == "alta"
        assert confidence_level_from_score(HIGH_CONFIDENCE) == "alta"

    def test_medium(self) -> None:
        assert confidence_level_from_score(60) == "media"
        assert confidence_level_from_score(MEDIUM_CONFIDENCE) == "media"

    def test_low(self) -> None:
        assert confidence_level_from_score(20) == "bassa"

    def test_non_finite_defaults_media(self) -> None:
        assert confidence_level_from_score(float("nan")) == "media"
        assert confidence_level_from_score(float("inf")) == "media"


class TestRecordShapes:
    def test_accepts_pandas_series(self) -> None:
        result = compute_confidence(pd.Series(_full_record()), personal_model_available=True)
        assert result.score > 0

    def test_empty_record_scores_zero_low(self) -> None:
        result = compute_confidence({}, personal_model_available=False)
        assert result.score == 0
        assert result.level == "bassa"

    def test_nan_as_missing(self) -> None:
        record = _full_record()
        record["heart_rate_mean"] = float("nan")
        result = compute_confidence(record)
        assert "heart_rate_mean" in result.missing_features

    def test_null_and_string_missing(self) -> None:
        record = _full_record()
        record["steps"] = None
        record["room_changes"] = ""
        result = compute_confidence(record)
        assert "steps" in result.missing_features
        assert "room_changes" in result.missing_features