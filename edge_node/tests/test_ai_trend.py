from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from edge_ai.trend import (
    feature_trend,
    linear_slope,
    score_trend_from_timestamps,
    trend_direction,
    trend_dict,
)

REFERENCE = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def _points_from_scores(scores, *, start_days_ago=14):
    start = REFERENCE - timedelta(days=start_days_ago)
    return [(start + timedelta(days=i), float(score)) for i, score in enumerate(scores)]


def test_linear_slope_increasing():
    slope, n = linear_slope([(0.0, 0.0), (1.0, 2.0), (2.0, 4.0), (3.0, 6.0)])
    assert n == 4
    assert slope == pytest.approx(2.0)


def test_linear_slope_needs_two_points():
    slope, n = linear_slope([(0.0, 1.0)])
    assert slope is None
    assert n == 1


def test_trend_direction_mapping():
    assert trend_direction(3.0) == "in_aumento"
    assert trend_direction(-3.0) == "in_diminuzione"
    assert trend_direction(0.5) == "stabile"
    assert trend_direction(None) == "unknown"
    assert trend_direction(float("nan")) == "unknown"


def test_trend_dict_shape():
    result = trend_dict(4.8, 12, 7)
    assert result["score_slope_per_day"] == 4.8
    assert result["direction"] == "in_aumento"
    assert result["window_days"] == 7
    assert result["n_points"] == 12


def test_score_trend_from_increasing_scores():
    scores = [30.0 + i * 3.0 for i in range(15)]
    result = score_trend_from_timestamps(_points_from_scores(scores), reference=REFERENCE)
    best = result["best"]
    assert best["direction"] == "in_aumento"
    assert best["score_slope_per_day"] > 2.0
    assert "3" in result["windows"] and "7" in result["windows"] and "14" in result["windows"]


def test_score_trend_from_flat_scores():
    scores = [50.0] * 15
    result = score_trend_from_timestamps(_points_from_scores(scores), reference=REFERENCE)
    assert result["best"]["direction"] == "stabile"
    assert abs(result["best"]["score_slope_per_day"]) < 2.0


def test_score_trend_unknown_without_data():
    result = score_trend_from_timestamps([], reference=REFERENCE)
    assert result["best"]["direction"] == "unknown"
    assert result["best"]["score_slope_per_day"] is None


def test_feature_trend_decreasing():
    values = [(0.0, 900.0), (1.0, 800.0), (2.0, 700.0), (3.0, 600.0)]
    result = feature_trend(values, window_days=7)
    assert result["direction"] == "in_diminuzione"
    assert result["slope_per_day"] == pytest.approx(-100.0)
    assert result["window_days"] == 7