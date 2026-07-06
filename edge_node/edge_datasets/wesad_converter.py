from __future__ import annotations

import csv
import pickle
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite, nan
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from edge_ai.schema import DATASET_COLUMNS, FEATURE_COLUMNS


DEFAULT_ACCEPTED_LABELS = (1, 3, 4)
LABEL_DESCRIPTION = {
    0: "not_defined",
    1: "baseline",
    2: "stress",
    3: "amusement",
    4: "meditation",
    5: "transient_1",
    6: "transient_2",
    7: "transient_3",
}


@dataclass(frozen=True)
class WesadConversionSummary:
    """Riepilogo della conversione WESAD.

    Il riepilogo permette di capire subito quanti soggetti sono stati letti e
    quante finestre finali sono entrate nel CSV wearable generico.
    """

    input_files: int
    total_windows: int
    output_rows: int
    skipped_windows: int
    accepted_labels: tuple[int, ...]
    output_csv: str

    def to_dict(self) -> dict[str, Any]:
        """Converte il riepilogo in un dizionario stampabile come JSON."""
        return {
            "input_files": self.input_files,
            "total_windows": self.total_windows,
            "output_rows": self.output_rows,
            "skipped_windows": self.skipped_windows,
            "accepted_labels": list(self.accepted_labels),
            "accepted_label_names": [
                LABEL_DESCRIPTION.get(label, str(label))
                for label in self.accepted_labels
            ],
            "output_csv": self.output_csv,
        }


def convert_wesad_dataset(
    input_dir: str | Path,
    output_csv: str | Path,
    window_minutes: int = 4,
    include: tuple[str, ...] = ("S*/S*.pkl",),
    max_files: int | None = None,
    max_output_rows: int | None = None,
    accepted_labels: tuple[int, ...] = DEFAULT_ACCEPTED_LABELS,
    min_label_ratio: float = 0.8,
    bvp_sampling_hz: float = 64.0,
    label_sampling_hz: float = 700.0,
) -> WesadConversionSummary:
    """Converte WESAD nello schema wearable generico del progetto.

    WESAD contiene segnali fisiologici sincronizzati e label sperimentali. Per
    addestrare un modello generico di normalita usiamo, di default, baseline,
    amusement e meditation, mentre scartiamo stress e transitori. La frequenza
    cardiaca e l'HRV vengono stimate dal BVP del polso, che e' il segnale piu'
    vicino al wearable commerciale previsto nel progetto.
    """
    source_dir = Path(input_dir)
    target = Path(output_csv)
    files = _select_input_files(source_dir, include, max_files)
    target.parent.mkdir(parents=True, exist_ok=True)

    accepted = tuple(sorted(set(int(label) for label in accepted_labels)))
    total_windows = 0
    output_rows = 0
    skipped_windows = 0

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
        writer.writeheader()

        for file_index, source in enumerate(files):
            subject_rows, subject_total, subject_skipped = _convert_subject(
                source=source,
                file_index=file_index,
                window_minutes=window_minutes,
                accepted_labels=accepted,
                min_label_ratio=min_label_ratio,
                bvp_sampling_hz=bvp_sampling_hz,
                label_sampling_hz=label_sampling_hz,
            )
            total_windows += subject_total
            skipped_windows += subject_skipped

            for row in subject_rows:
                writer.writerow(row)
                output_rows += 1
                if max_output_rows is not None and output_rows >= max_output_rows:
                    return WesadConversionSummary(
                        input_files=len(files),
                        total_windows=total_windows,
                        output_rows=output_rows,
                        skipped_windows=skipped_windows,
                        accepted_labels=accepted,
                        output_csv=str(target),
                    )

    return WesadConversionSummary(
        input_files=len(files),
        total_windows=total_windows,
        output_rows=output_rows,
        skipped_windows=skipped_windows,
        accepted_labels=accepted,
        output_csv=str(target),
    )


def _select_input_files(
    source_dir: Path,
    include: tuple[str, ...],
    max_files: int | None,
) -> list[Path]:
    """Seleziona i file `.pkl` WESAD da convertire."""
    if not source_dir.exists():
        raise FileNotFoundError(f"WESAD input directory not found: {source_dir}")

    selected: list[Path] = []
    for pattern in include:
        selected.extend(source_dir.glob(pattern))

    files = sorted({path for path in selected if path.is_file() and path.suffix.lower() == ".pkl"})
    if max_files is not None:
        files = files[:max_files]
    if not files:
        raise FileNotFoundError(f"No WESAD .pkl files found in {source_dir}")
    return files


def _convert_subject(
    source: Path,
    file_index: int,
    window_minutes: int,
    accepted_labels: tuple[int, ...],
    min_label_ratio: float,
    bvp_sampling_hz: float,
    label_sampling_hz: float,
) -> tuple[list[dict[str, Any]], int, int]:
    """Converte un singolo soggetto WESAD in finestre wearable.

    Carichiamo un soggetto alla volta per non tenere in memoria tutto il dataset.
    Il file contiene label a 700 Hz e BVP da polso a 64 Hz: per ogni finestra
    controlliamo prima la label prevalente e poi stimiamo HR/HRV dal BVP.
    """
    with source.open("rb") as handle:
        payload = pickle.load(handle, encoding="latin1")

    subject = str(payload.get("subject") or source.stem)
    labels = np.asarray(payload["label"]).reshape(-1)
    bvp = np.asarray(payload["signal"]["wrist"]["BVP"], dtype=float).reshape(-1)

    window_seconds = window_minutes * 60.0
    duration_seconds = min(
        labels.shape[0] / label_sampling_hz,
        bvp.shape[0] / bvp_sampling_hz,
    )
    total_windows = int(duration_seconds // window_seconds)
    base_time = datetime(2017, 1, 1, tzinfo=timezone.utc) + timedelta(days=file_index)

    rows: list[dict[str, Any]] = []
    skipped = 0
    accepted_set = set(accepted_labels)

    for window_index in range(total_windows):
        start_s = window_index * window_seconds
        end_s = start_s + window_seconds

        label_start = int(start_s * label_sampling_hz)
        label_end = int(end_s * label_sampling_hz)
        dominant_label, label_ratio = _dominant_label(labels[label_start:label_end])

        if dominant_label not in accepted_set or label_ratio < min_label_ratio:
            skipped += 1
            continue

        bvp_start = int(start_s * bvp_sampling_hz)
        bvp_end = int(end_s * bvp_sampling_hz)
        hr_mean, hr_std, hrv_rmssd = _estimate_bvp_features(
            bvp[bvp_start:bvp_end],
            sampling_hz=bvp_sampling_hz,
        )
        if not isfinite(hr_mean):
            skipped += 1
            continue

        rows.append(
            _row_from_features(
                patient_id=f"wesad-{subject}",
                base_time=base_time,
                window_index=window_index,
                window_minutes=window_minutes,
                heart_rate_mean=hr_mean,
                heart_rate_std=hr_std,
                hrv_rmssd=hrv_rmssd,
            )
        )

    return rows, total_windows, skipped


def _dominant_label(labels: np.ndarray) -> tuple[int, float]:
    """Restituisce label prevalente e percentuale nella finestra.

    Il controllo serve a scartare finestre che attraversano due fasi diverse del
    protocollo, perche' non rappresenterebbero una condizione fisiologica pulita.
    """
    if labels.size == 0:
        return -1, 0.0
    values, counts = np.unique(labels.astype(int), return_counts=True)
    best_index = int(np.argmax(counts))
    return int(values[best_index]), float(counts[best_index]) / float(labels.size)


def _estimate_bvp_features(
    bvp_segment: np.ndarray,
    sampling_hz: float,
) -> tuple[float, float, float]:
    """Stima HR medio, variabilita HR e HRV RMSSD dal BVP da polso.

    WESAD non salva nel `.pkl` la frequenza cardiaca gia' aggregata. Questa
    funzione usa quindi un peak detector semplice e conservativo: normalizza il
    BVP, cerca massimi locali sopra soglia e filtra intervalli battito-battito
    fisiologicamente plausibili.
    """
    values = np.asarray(bvp_segment, dtype=float).reshape(-1)
    values = values[np.isfinite(values)]
    if values.size < int(sampling_hz * 20):
        return nan, nan, nan

    centered = values - float(np.median(values))
    spread = float(np.std(centered))
    if spread <= 1e-9:
        return nan, nan, nan

    threshold = float(np.mean(centered) + 0.35 * spread)
    local_maxima = np.where(
        (centered[1:-1] > centered[:-2])
        & (centered[1:-1] >= centered[2:])
        & (centered[1:-1] > threshold)
    )[0] + 1

    peak_indices = _enforce_min_peak_distance(
        local_maxima,
        centered,
        min_distance=int(0.35 * sampling_hz),
    )
    if peak_indices.size < 3:
        return nan, nan, nan

    ibi_seconds = np.diff(peak_indices.astype(float)) / sampling_hz
    valid_ibi = ibi_seconds[(ibi_seconds >= 0.35) & (ibi_seconds <= 1.8)]
    if valid_ibi.size < 2:
        return nan, nan, nan

    beats_per_minute = 60.0 / valid_ibi
    valid_bpm_mask = (beats_per_minute >= 40.0) & (beats_per_minute <= 180.0)
    beats_per_minute = beats_per_minute[valid_bpm_mask]
    valid_ibi = valid_ibi[valid_bpm_mask]
    if beats_per_minute.size < 2:
        return nan, nan, nan

    hrv_rmssd = nan
    if valid_ibi.size >= 3:
        ibi_diff = np.diff(valid_ibi)
        hrv_rmssd = float(np.sqrt(np.mean(ibi_diff * ibi_diff)) * 1000.0)

    return (
        float(np.mean(beats_per_minute)),
        float(np.std(beats_per_minute)),
        hrv_rmssd,
    )


def _enforce_min_peak_distance(
    candidates: np.ndarray,
    values: np.ndarray,
    min_distance: int,
) -> np.ndarray:
    """Filtra picchi BVP troppo vicini tenendo quello con ampiezza maggiore."""
    selected: list[int] = []
    for candidate in candidates.astype(int):
        if not selected or candidate - selected[-1] >= min_distance:
            selected.append(int(candidate))
            continue
        if values[candidate] > values[selected[-1]]:
            selected[-1] = int(candidate)
    return np.asarray(selected, dtype=int)


def _row_from_features(
    patient_id: str,
    base_time: datetime,
    window_index: int,
    window_minutes: int,
    heart_rate_mean: float,
    heart_rate_std: float,
    hrv_rmssd: float,
) -> dict[str, Any]:
    """Crea una riga CSV finale nello schema ufficiale del progetto."""
    window_start = base_time + timedelta(minutes=window_index * window_minutes)
    row: dict[str, Any] = {
        "patient_id": patient_id,
        "window_start": window_start.isoformat(),
        "window_end": (window_start + timedelta(minutes=window_minutes)).isoformat(),
        "wearable_present": 1,
        "wearable_battery_pct": "",
    }
    row.update({column: nan for column in FEATURE_COLUMNS})
    row["heart_rate_mean"] = heart_rate_mean
    row["heart_rate_std"] = heart_rate_std
    if isfinite(hrv_rmssd):
        row["hrv_rmssd"] = hrv_rmssd
    row["fall_events"] = 0.0
    return {column: row.get(column, "") for column in DATASET_COLUMNS}


def parse_include_patterns(value: str | Iterable[str]) -> tuple[str, ...]:
    """Normalizza pattern CLI separati da virgola in una tupla pulita."""
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)
    patterns = tuple(item.strip() for item in items if str(item).strip())
    return patterns or ("S*/S*.pkl",)


def parse_label_ids(value: str | Iterable[int]) -> tuple[int, ...]:
    """Converte le label accettate da stringa CLI a tuple di interi."""
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)
    labels = tuple(int(item) for item in items if str(item).strip())
    return labels or DEFAULT_ACCEPTED_LABELS
