from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from edge_ai.features import select_features
from edge_ai.schema import FEATURE_COLUMNS, InferenceResult, parse_timestamp


@dataclass(frozen=True)
class ModelMetadata:
    patient_id: str
    feature_columns: list[str]
    contamination: float
    normal_anchor: float
    severe_anchor: float
    training_rows: int


class EdgeAnomalyDetector:
    def __init__(self, pipeline: Pipeline, metadata: ModelMetadata):
        self.pipeline = pipeline
        self.metadata = metadata

    @classmethod
    def train(
        cls,
        frame: pd.DataFrame,
        patient_id: str,
        contamination: float = 0.05,
        random_state: int = 42,
    ) -> "EdgeAnomalyDetector":
        if len(frame) < 50:
            raise ValueError(
                "At least 50 baseline records are required. "
                "For this project, collect about 5-6 days of real windows; "
                "longer baselines are better for production."
            )

        patient_frame = frame[frame["patient_id"].astype(str) == str(patient_id)]
        if patient_frame.empty:
            raise ValueError(f"No rows found for patient_id={patient_id}")

        pipeline = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "model",
                    IsolationForest(
                        n_estimators=200,
                        contamination=contamination,
                        random_state=random_state,
                        n_jobs=-1,
                    ),
                ),
            ]
        )

        features = select_features(patient_frame)
        pipeline.fit(features)
        decision_values = pipeline.decision_function(features)
        normal_anchor = float(np.percentile(decision_values, 50))
        severe_anchor = float(np.percentile(decision_values, 1))
        if normal_anchor <= severe_anchor:
            severe_anchor = float(np.min(decision_values))

        metadata = ModelMetadata(
            patient_id=str(patient_id),
            feature_columns=FEATURE_COLUMNS,
            contamination=contamination,
            normal_anchor=normal_anchor,
            severe_anchor=severe_anchor,
            training_rows=len(patient_frame),
        )
        return cls(pipeline=pipeline, metadata=metadata)

    def predict_record(self, record: Union[pd.Series, dict[str, Any]]) -> InferenceResult:
        row = pd.DataFrame([dict(record)])
        features = row[self.metadata.feature_columns]
        decision_value = float(self.pipeline.decision_function(features)[0])
        label = "outlier" if int(self.pipeline.predict(features)[0]) == -1 else "normal"
        anomaly_score = self._decision_to_score(decision_value)

        patient_id = str(row.iloc[0].get("patient_id", self.metadata.patient_id))
        return InferenceResult(
            patient_id=patient_id,
            window_start=parse_timestamp(row.iloc[0]["window_start"]),
            window_end=parse_timestamp(row.iloc[0]["window_end"]),
            anomaly_score=anomaly_score,
            model_decision_value=decision_value,
            model_label=label,
            feature_values={
                column: float(row.iloc[0][column])
                for column in self.metadata.feature_columns
            },
            context={
                "wearable_present": row.iloc[0].get("wearable_present"),
                "wearable_battery_pct": row.iloc[0].get("wearable_battery_pct"),
            },
        )

    def save(self, path: Union[str, Path]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pipeline": self.pipeline,
            "metadata": self.metadata,
        }
        with target.open("wb") as handle:
            pickle.dump(payload, handle)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "EdgeAnomalyDetector":
        source = Path(path)
        with source.open("rb") as handle:
            payload = pickle.load(handle)
        return cls(
            pipeline=payload["pipeline"],
            metadata=payload["metadata"],
        )

    def _decision_to_score(self, decision_value: float) -> float:
        span = self.metadata.normal_anchor - self.metadata.severe_anchor
        if span <= 0:
            return 0.0
        score = (self.metadata.normal_anchor - decision_value) / span * 100.0
        return float(np.clip(score, 0.0, 100.0))
