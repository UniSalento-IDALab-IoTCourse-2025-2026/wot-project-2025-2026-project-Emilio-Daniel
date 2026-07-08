from __future__ import annotations

from pathlib import Path

import pandas as pd

from edge_ai.schema import FEATURE_COLUMNS, REQUIRED_COLUMNS


def load_feature_frame(path: str | Path) -> pd.DataFrame:
    """Carica da CSV o JSON un dataset di finestre ADL gia' aggregate.

    Il modello non lavora sui campioni grezzi, ma su righe feature prodotte
    dall'edge node. Questa funzione rappresenta quindi il punto di ingresso
    comune sia per la baseline sia per l'inferenza.
    """
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Input dataset not found: {source}")

    if source.suffix.lower() == ".json":
        frame = pd.read_json(source)
    else:
        frame = pd.read_csv(source)

    return validate_feature_frame(frame)


def validate_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Verifica e normalizza lo schema delle feature richieste dal modello.

    La validazione controlla la presenza delle colonne obbligatorie, converte
    timestamp e identificativo paziente e forza le feature numeriche a valori
    compatibili con scikit-learn. Cosi' eventuali errori di formato vengono
    intercettati prima del training o dell'inferenza.
    """
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(
            "Missing required columns: " + ", ".join(missing)
        )

    cleaned = frame.copy()
    cleaned["patient_id"] = cleaned["patient_id"].astype(str)
    cleaned["window_start"] = pd.to_datetime(cleaned["window_start"], utc=True)
    cleaned["window_end"] = pd.to_datetime(cleaned["window_end"], utc=True)

    for column in FEATURE_COLUMNS:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    return cleaned


def select_features(
    frame: pd.DataFrame,
    columns: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Seleziona solo le colonne numeriche usate dall'Isolation Forest.

    Le colonne di contesto, come paziente e timestamp, sono importanti per
    tracciare la finestra ma non devono entrare direttamente nel modello.
    """
    selected = list(columns) if columns is not None else FEATURE_COLUMNS
    return frame[selected].copy()


def latest_record(frame: pd.DataFrame) -> pd.Series:
    """Restituisce la finestra piu' recente del dataset.

    In inferenza il file puo' contenere piu' righe, ma il ciclo edge deve
    valutare l'ultima finestra temporale disponibile. L'ordinamento per
    `window_end` evita di dipendere dall'ordine fisico del CSV.
    """
    if frame.empty:
        raise ValueError("Input dataset contains no records")
    ordered = frame.sort_values("window_end")
    return ordered.iloc[-1]
