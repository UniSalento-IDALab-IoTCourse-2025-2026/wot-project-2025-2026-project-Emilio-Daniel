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
    model_scope: str = "personal"
    training_source: str = "patient_baseline"


class EdgeAnomalyDetector:
    def __init__(self, pipeline: Pipeline, metadata: ModelMetadata):
        """Memorizza pipeline scikit-learn e metadati del modello edge.

        La pipeline contiene preprocessing e Isolation Forest, mentre i metadati
        descrivono paziente, feature e soglie di normalizzazione dello score. La
        separazione e' utile per salvare un artefatto leggibile e riutilizzabile.
        """
        self.pipeline = pipeline
        self.metadata = metadata

    @classmethod
    def train(
        cls,
        frame: pd.DataFrame,
        patient_id: str,
        contamination: float = 0.05,
        random_state: int = 42,
        include_all_patients: bool = False,
        model_scope: str = "personal",
        training_source: str = "patient_baseline",
    ) -> "EdgeAnomalyDetector":
        """Addestra un modello di anomaly detection sulla baseline del paziente.

        Di default il training usa solo le righe del paziente indicato, perche'
        l'obiettivo del modello personale e' imparare la routine individuale.
        Quando `include_all_patients` e' attivo, invece, la stessa pipeline viene
        usata per costruire un modello generico da dataset esterni o multiutente.
        """
        if include_all_patients:
            training_frame = frame.copy()
        else:
            training_frame = frame[frame["patient_id"].astype(str) == str(patient_id)]

        if training_frame.empty:
            raise ValueError(f"No rows found for patient_id={patient_id}")
        if len(training_frame) < 50:
            raise ValueError(
                "At least 50 training records are required for the selected model. "
                "For this project, collect about 5-6 days of real windows; "
                "longer baselines are better for production."
            )

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

        features = select_features(training_frame)
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
            training_rows=len(training_frame),
            model_scope=model_scope,
            training_source=training_source,
        )
        return cls(pipeline=pipeline, metadata=metadata)

    @classmethod
    def train_generic(
        cls,
        frame: pd.DataFrame,
        model_id: str = "generic",
        model_scope: str = "generic",
        training_source: str = "external_or_multi_patient_dataset",
        contamination: float = 0.05,
        random_state: int = 42,
    ) -> "EdgeAnomalyDetector":
        """Addestra il modello generico su un dataset multiutente o clinico.

        Questo modello non rappresenta un singolo paziente: serve come base
        iniziale installabile sul Raspberry prima della baseline personale.
        Per questo motivo usa tutte le righe disponibili e salva nei metadati
        uno scope diverso dal modello paziente-specifico.
        """
        return cls.train(
            frame=frame,
            patient_id=model_id,
            contamination=contamination,
            random_state=random_state,
            include_all_patients=True,
            model_scope=model_scope,
            training_source=training_source,
        )

    def predict_record(self, record: Union[pd.Series, dict[str, Any]]) -> InferenceResult:
        """Calcola lo score di anomalia per una singola finestra aggregata.

        La funzione applica la stessa pipeline usata in training e converte il
        valore decisionale dell'Isolation Forest in uno score 0-100 piu'
        comprensibile per la parte di triage. Restituisce anche contesto tecnico
        come presenza e batteria del wearable.
        """
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
        """Salva modello e metadati in un file `.pkl`.

        L'artefatto prodotto e' quello che verra' copiato o mantenuto sul
        Raspberry Pi per l'inferenza continua. Si usa `pickle` standard per
        evitare dipendenze aggiuntive come joblib.
        """
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
        """Carica da disco un modello precedentemente addestrato.

        Questa funzione viene usata dal runtime ogni volta che esiste il file
        `models/<patient_id>.pkl`. Se il file non c'e', il ciclo edge puo'
        comunque produrre la finestra ma salta l'inferenza.
        """
        source = Path(path)
        with source.open("rb") as handle:
            payload = pickle.load(handle)
        pipeline = payload["pipeline"]
        _patch_loaded_pipeline_compatibility(pipeline)
        return cls(
            pipeline=pipeline,
            metadata=payload["metadata"],
        )

    def _decision_to_score(self, decision_value: float) -> float:
        """Converte il valore interno del modello in uno score di anomalia 0-100.

        Isolation Forest restituisce valori meno intuitivi: piu' il valore e'
        distante dalla routine, piu' la finestra e' sospetta. Questa conversione
        usa ancore calcolate sulla baseline per ottenere uno score leggibile.
        """
        span = self.metadata.normal_anchor - self.metadata.severe_anchor
        if span <= 0:
            return 0.0
        score = (self.metadata.normal_anchor - decision_value) / span * 100.0
        return float(np.clip(score, 0.0, 100.0))


def _patch_loaded_pipeline_compatibility(pipeline: Pipeline) -> None:
    """Ripara piccoli mismatch di compatibilita nei modelli pickle.

    Gli artefatti `.pkl` di scikit-learn non sono completamente stabili tra
    versioni diverse. In particolare, modelli salvati con una versione precedente
    possono caricare un `SimpleImputer` senza attributi interni introdotti dopo.
    Questo fix mantiene il ciclo edge robusto, ma la soluzione migliore resta
    rigenerare i modelli con la stessa versione installata sul Raspberry.
    """
    try:
        imputer = pipeline.named_steps.get("imputer")
    except AttributeError:
        return
    if imputer is None:
        return
    if hasattr(imputer, "_fill_dtype"):
        return
    fit_dtype = getattr(imputer, "_fit_dtype", None)
    if fit_dtype is not None:
        setattr(imputer, "_fill_dtype", fit_dtype)
