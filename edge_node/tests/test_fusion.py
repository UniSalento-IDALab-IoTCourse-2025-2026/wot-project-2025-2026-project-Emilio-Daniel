from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from edge_ai.fusion import FusionConfig, fuse_model_results
from edge_ai.schema import InferenceResult

WS = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)
WE = WS + timedelta(minutes=4)


def result(
    score: float,
    label: str = "anomaly",
    patient: str = "patient-001",
    context: dict | None = None,
) -> InferenceResult:
    return InferenceResult(
        patient_id=patient,
        window_start=WS,
        window_end=WE,
        anomaly_score=score,
        model_decision_value=score,
        model_label=label,
        feature_values={"heart_rate_mean": 70.0},
        context=context or {},
    )


def test_fusion_requires_at_least_one_model() -> None:
    with pytest.raises(ValueError):
        fuse_model_results()


def test_fusion_single_personal_result_is_kept() -> None:
    fused = fuse_model_results(personal_result=result(80.0))
    assert fused.anomaly_score == pytest.approx(80.0)
    assert fused.model_label == "personal_anomaly_only"
    assert fused.patient_id == "patient-001"


def test_fusion_renormalizes_weights_with_two_models() -> None:
    spatial = result(100.0, label="anomaly")
    personal = result(10.0, label="normal")
    fused = fuse_model_results(generic_spatial_result=spatial, personal_result=personal)
    assert fused.model_label == "generic_spatial_anomaly_only"
    assert fused.anomaly_score == pytest.approx(79.9, abs=0.01)
    weights = fused.context["fusion"]["weights"]
    assert weights["personal"] == pytest.approx(0.30 / 0.65, abs=0.001)
    assert weights["generic_spatial"] == pytest.approx(0.35 / 0.65, abs=0.001)


def test_fusion_personal_model_has_thirty_percent_weight() -> None:
    fused = fuse_model_results(
        generic_spatial_result=result(40.0),
        generic_wearable_result=result(40.0),
        personal_result=result(40.0),
    )

    weights = fused.context["fusion"]["weights"]
    assert weights == {
        "generic_spatial": pytest.approx(0.35),
        "generic_wearable": pytest.approx(0.35),
        "personal": pytest.approx(0.30),
    }


def test_fusion_agreement_bonus_two_yellow_models() -> None:
    spatial = result(60.0, label="anomaly")
    wearable = result(62.0, label="anomaly")
    fused = fuse_model_results(generic_spatial_result=spatial, generic_wearable_result=wearable)
    assert fused.model_label == "multi_model_agreement_yellow"
    assert fused.anomaly_score == pytest.approx(67.0, abs=0.01)


def test_fusion_all_normal_is_clipped() -> None:
    spatial = result(30.0, label="normal")
    wearable = result(32.0, label="normal")
    personal = result(34.0, label="normal")
    fused = fuse_model_results(
        generic_spatial_result=spatial,
        generic_wearable_result=wearable,
        personal_result=personal,
    )
    assert fused.model_label == "agreement_normal"
    assert fused.anomaly_score <= 34.9


def test_fusion_context_exposes_models_and_mode() -> None:
    fused = fuse_model_results(personal_result=result(77.0))
    fusion = fused.context["fusion"]
    assert fusion["mode"] == "personal"
    assert fusion["models"]["personal"]["score"] == pytest.approx(77.0)
    assert fusion["reasons"]

def test_fusion_prefers_personal_as_base_result() -> None:
    spatial = result(35.0, label="normal", patient="patient-A")
    personal = result(84.0, label="anomaly", patient="patient-B")
    fused = fuse_model_results(generic_spatial_result=spatial, personal_result=personal)
    assert fused.patient_id == "patient-B"
    assert fused.window_start == WS


def test_fusion_single_generic_is_capped_before_red() -> None:
    spatial = result(95.0, label="anomaly")
    wearable = result(20.0, label="normal")
    fused = fuse_model_results(generic_spatial_result=spatial, generic_wearable_result=wearable)
    assert fused.model_label == "generic_spatial_anomaly_only"
    assert fused.anomaly_score <= 79.9


def test_fusion_config_can_be_customized() -> None:
    custom = FusionConfig(personal_weight=1.0, single_model_penalty=0.0)
    fused = fuse_model_results(personal_result=result(60.0), config=custom)
    assert fused.anomaly_score == pytest.approx(60.0)
