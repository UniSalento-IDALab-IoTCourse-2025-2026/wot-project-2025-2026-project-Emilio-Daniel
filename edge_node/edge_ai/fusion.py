from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from edge_ai.schema import InferenceResult


@dataclass(frozen=True)
class FusionConfig:
    generic_spatial_weight: float = 0.30
    generic_wearable_weight: float = 0.30
    personal_weight: float = 0.40
    yellow_score: float = 35.0
    orange_score: float = 65.0
    red_score: float = 80.0
    agreement_bonus: float = 5.0
    single_model_penalty: float = 10.0
    unconfirmed_generic_max_score: float = 79.9
    disagreement_margin: float = 25.0


def fuse_model_results(
    generic_spatial_result: InferenceResult | None = None,
    generic_wearable_result: InferenceResult | None = None,
    personal_result: InferenceResult | None = None,
    config: FusionConfig | None = None,
) -> InferenceResult:
    """Fonde tre modelli AI in un unico risultato operativo.

    Il progetto distingue tre prospettive: routine domestica/spaziale, segnali
    wearable/fisiologici e baseline personale del paziente. Questa funzione
    mantiene separati i tre punteggi, li pesa in base ai modelli disponibili e
    produce uno score finale compatibile con il debounce clinico.
    """
    active_config = config or FusionConfig()
    results = _available_results(
        generic_spatial_result=generic_spatial_result,
        generic_wearable_result=generic_wearable_result,
        personal_result=personal_result,
    )
    if not results:
        raise ValueError("At least one model result is required for fusion")

    normalized_weights = _normalized_weights(results, active_config)
    weighted_score = _weighted_metric(results, normalized_weights, "anomaly_score")
    weighted_decision_value = _weighted_metric(
        results,
        normalized_weights,
        "model_decision_value",
    )
    score, label, reasons = _fuse_scores(
        results=results,
        weighted_score=weighted_score,
        config=active_config,
    )

    base_result = _base_result(results)
    mode = "_plus_".join(name for name, _result in results)
    context = dict(base_result.context)
    context["fusion"] = {
        "mode": mode,
        "score": round(float(score), 3),
        "label": label,
        "reasons": reasons,
        "weights": {
            name: round(float(weight), 3)
            for name, weight in normalized_weights.items()
        },
        "models": {
            "generic_spatial": _result_summary(generic_spatial_result),
            "generic_wearable": _result_summary(generic_wearable_result),
            "personal": _result_summary(personal_result),
        },
    }

    return InferenceResult(
        patient_id=base_result.patient_id,
        window_start=base_result.window_start,
        window_end=base_result.window_end,
        anomaly_score=float(score),
        model_decision_value=float(weighted_decision_value),
        model_label=label,
        feature_values=base_result.feature_values,
        context=context,
    )


def _available_results(
    generic_spatial_result: InferenceResult | None,
    generic_wearable_result: InferenceResult | None,
    personal_result: InferenceResult | None,
) -> list[tuple[str, InferenceResult]]:
    """Restituisce i risultati presenti preservando l'ordine logico."""
    items: list[tuple[str, InferenceResult]] = []
    if generic_spatial_result is not None:
        items.append(("generic_spatial", generic_spatial_result))
    if generic_wearable_result is not None:
        items.append(("generic_wearable", generic_wearable_result))
    if personal_result is not None:
        items.append(("personal", personal_result))
    return items


def _normalized_weights(
    results: list[tuple[str, InferenceResult]],
    config: FusionConfig,
) -> dict[str, float]:
    """Calcola pesi normalizzati solo sui modelli realmente disponibili.

    Se, ad esempio, durante la baseline manca ancora il modello personale, i
    pesi dei due generici vengono riscalati senza cambiare codice o soglie.
    """
    raw_weights = {
        "generic_spatial": config.generic_spatial_weight,
        "generic_wearable": config.generic_wearable_weight,
        "personal": config.personal_weight,
    }
    active = {name: raw_weights[name] for name, _result in results}
    total = sum(active.values())
    if total <= 0:
        equal_weight = 1.0 / len(active)
        return {name: equal_weight for name in active}
    return {name: weight / total for name, weight in active.items()}


def _weighted_metric(
    results: list[tuple[str, InferenceResult]],
    weights: dict[str, float],
    attribute: str,
) -> float:
    """Calcola la media pesata di uno score tecnico dei modelli."""
    return float(
        sum(float(getattr(result, attribute)) * weights[name] for name, result in results)
    )


def _fuse_scores(
    results: list[tuple[str, InferenceResult]],
    weighted_score: float,
    config: FusionConfig,
) -> tuple[float, str, list[str]]:
    """Applica regole conservative quando i modelli concordano o divergono.

    Due o piu' modelli concordi su una soglia alta pesano piu' di un singolo
    outlier. Un singolo modello alto non viene ignorato, ma viene leggermente
    attenuato per ridurre falsi positivi nella fase iniziale.
    """
    scores = {name: float(result.anomaly_score) for name, result in results}
    yellow_models = [
        name for name, score in scores.items() if score >= config.yellow_score
    ]
    orange_models = [
        name for name, score in scores.items() if score >= config.orange_score
    ]
    red_models = [
        name for name, score in scores.items() if score >= config.red_score
    ]

    if len(red_models) >= 2:
        return (
            min(100.0, max(scores.values()) + config.agreement_bonus),
            "multi_model_agreement_red",
            [f"Severe anomaly confirmed by {', '.join(red_models)}"],
        )

    if len(orange_models) >= 2:
        return (
            min(100.0, max(scores.values()) + config.agreement_bonus),
            "multi_model_agreement_orange",
            [f"Important anomaly confirmed by {', '.join(orange_models)}"],
        )

    if len(yellow_models) >= 2:
        return (
            min(100.0, max(scores.values()) + config.agreement_bonus),
            "multi_model_agreement_yellow",
            [f"Attention signal confirmed by {', '.join(yellow_models)}"],
        )

    if len(yellow_models) == 1:
        model_name = yellow_models[0]
        high_score = scores[model_name]
        score = max(weighted_score, high_score - config.single_model_penalty)
        if model_name.startswith("generic_"):
            # Un solo modello generico puo' essere utile per triage iniziale,
            # ma prima della baseline personale non deve generare da solo un
            # rosso clinico quando gli altri modelli disponibili non confermano.
            score = min(score, config.unconfirmed_generic_max_score)
        return (
            float(np.clip(score, 0.0, 100.0)),
            f"{model_name}_anomaly_only",
            [
                f"{model_name} reports an anomaly",
                "Other available models do not confirm the anomaly at alert level",
            ],
        )

    if len(scores) >= 2 and max(scores.values()) - min(scores.values()) >= config.disagreement_margin:
        return (
            float(np.clip(weighted_score, 0.0, 100.0)),
            "mixed_low_risk",
            ["Model scores differ, but all remain below alert threshold"],
        )

    return (
        float(np.clip(weighted_score, 0.0, 100.0)),
        "agreement_normal",
        ["Available models report routine-compatible behavior"],
    )


def _base_result(results: list[tuple[str, InferenceResult]]) -> InferenceResult:
    """Sceglie il risultato base da cui copiare paziente, finestre e feature.

    Il modello personale e' preferito quando esiste, perche' rappresenta il
    paziente osservato. In assenza del personale, si usa il primo generico
    disponibile.
    """
    for name, result in results:
        if name == "personal":
            return result
    return results[0][1]


def _result_summary(result: InferenceResult | None) -> dict[str, Any]:
    """Crea un riepilogo JSON-safe di un risultato modello.

    L'output finale deve essere leggibile anche senza aprire il file `.pkl`.
    Per questo salviamo solo score, label e valore decisionale, evitando di
    duplicare tutte le feature biometriche o spaziali.
    """
    if result is None:
        return {"available": False}
    summary = {
        "available": True,
        "score": round(float(result.anomaly_score), 3),
        "label": result.model_label,
        "decision_value": round(float(result.model_decision_value), 6),
    }
    explanation = result.context.get("feature_explanation")
    if isinstance(explanation, dict):
        summary["feature_explanation"] = explanation
    return summary
