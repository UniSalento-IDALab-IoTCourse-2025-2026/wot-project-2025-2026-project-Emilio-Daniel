from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import nan, sqrt
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from edge_ai.schema import DATASET_COLUMNS, FEATURE_COLUMNS


SEDENTARY_ACTIVITY_IDS = {1, 2, 9, 10, 11}
STEP_CADENCE_BY_ACTIVITY = {
    4: 100.0,   # walking
    5: 160.0,   # running
    7: 110.0,   # Nordic walking
    12: 80.0,   # ascending stairs
    13: 80.0,   # descending stairs
    16: 70.0,   # vacuum cleaning
    17: 35.0,   # ironing
    18: 45.0,   # folding laundry
    19: 70.0,   # house cleaning
    20: 120.0,  # playing soccer
    24: 120.0,  # rope jumping
}


@dataclass
class Pamap2WindowAggregate:
    """Accumula le statistiche wearable di una finestra PAMAP2.

    PAMAP2 fornisce campioni ad alta frequenza con activity id, heart rate e
    IMU. Per il nostro primo modello wearable generico usiamo heart rate e
    activity id, che sono sufficienti a produrre feature simili a quelle del
    Google Watch 2: media battito, variabilita battito, passi stimati e minuti
    sedentari.
    """

    row_count: int = 0
    hr_count: int = 0
    hr_sum: float = 0.0
    hr_sum_sq: float = 0.0
    activity_counts: dict[int, int] = field(default_factory=dict)

    def add_chunk_stats(
        self,
        row_count: int,
        heart_rates: pd.Series,
        activity_counts: dict[int, int],
    ) -> None:
        """Aggiunge al totale finestra le statistiche calcolate su un chunk."""
        self.row_count += int(row_count)
        valid_hr = pd.Series(
            pd.to_numeric(heart_rates, errors="coerce"),
            dtype="float64",
        ).dropna()
        if not valid_hr.empty:
            self.hr_count += int(valid_hr.shape[0])
            self.hr_sum += float(valid_hr.sum())
            self.hr_sum_sq += float((valid_hr * valid_hr).sum())
        for activity_id, count in activity_counts.items():
            self.activity_counts[activity_id] = self.activity_counts.get(activity_id, 0) + int(count)


@dataclass(frozen=True)
class Pamap2ConversionSummary:
    input_files: int
    input_rows: int
    output_rows: int
    output_csv: str

    def to_dict(self) -> dict[str, Any]:
        """Converte il riepilogo finale in un dizionario serializzabile."""
        return {
            "input_files": self.input_files,
            "input_rows": self.input_rows,
            "output_rows": self.output_rows,
            "output_csv": self.output_csv,
        }


def convert_pamap2_dataset(
    input_dir: str | Path,
    output_csv: str | Path,
    window_minutes: int = 4,
    include: tuple[str, ...] = ("*.dat",),
    max_files: int | None = None,
    limit_rows_per_file: int | None = None,
    max_output_rows: int | None = None,
    sampling_hz: float = 100.0,
    chunksize: int = 250_000,
) -> Pamap2ConversionSummary:
    """Converte PAMAP2 nello schema wearable generico del progetto.

    Ogni soggetto PAMAP2 diventa un `patient_id` sintetico, ad esempio
    `pamap2-subject101`. Le date sono sintetiche perche' il dataset usa secondi
    relativi, ma le durate e le finestre restano coerenti per il training.
    """
    source_dir = Path(input_dir)
    target = Path(output_csv)
    files = _select_input_files(source_dir, include, max_files)
    target.parent.mkdir(parents=True, exist_ok=True)

    total_input_rows = 0
    total_output_rows = 0

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
        writer.writeheader()

        for file_index, source in enumerate(files):
            aggregates, input_rows = _aggregate_file(
                source=source,
                window_minutes=window_minutes,
                limit_rows=limit_rows_per_file,
                sampling_hz=sampling_hz,
                chunksize=chunksize,
            )
            total_input_rows += input_rows
            patient_id = f"pamap2-{source.stem}"
            base_time = datetime(2012, 1, 1, tzinfo=timezone.utc) + timedelta(days=file_index)

            for window_index in sorted(aggregates):
                row = _row_from_aggregate(
                    patient_id=patient_id,
                    base_time=base_time,
                    window_index=window_index,
                    aggregate=aggregates[window_index],
                    window_minutes=window_minutes,
                    sampling_hz=sampling_hz,
                )
                writer.writerow(row)
                total_output_rows += 1
                if max_output_rows is not None and total_output_rows >= max_output_rows:
                    return Pamap2ConversionSummary(
                        input_files=len(files),
                        input_rows=total_input_rows,
                        output_rows=total_output_rows,
                        output_csv=str(target),
                    )

    return Pamap2ConversionSummary(
        input_files=len(files),
        input_rows=total_input_rows,
        output_rows=total_output_rows,
        output_csv=str(target),
    )


def _select_input_files(
    source_dir: Path,
    include: tuple[str, ...],
    max_files: int | None,
) -> list[Path]:
    """Seleziona i `.dat` PAMAP2 da convertire."""
    if not source_dir.exists():
        raise FileNotFoundError(f"PAMAP2 input directory not found: {source_dir}")

    selected: list[Path] = []
    for pattern in include:
        selected.extend(source_dir.glob(pattern))

    files = sorted({path for path in selected if path.is_file() and path.suffix.lower() == ".dat"})
    if max_files is not None:
        files = files[:max_files]
    if not files:
        raise FileNotFoundError(f"No PAMAP2 .dat files found in {source_dir}")
    return files


def _aggregate_file(
    source: Path,
    window_minutes: int,
    limit_rows: int | None,
    sampling_hz: float,
    chunksize: int,
) -> tuple[dict[int, Pamap2WindowAggregate], int]:
    """Aggrega un file `.dat` PAMAP2 usando lettura a chunk.

    Usiamo solo le colonne `timestamp`, `activity_id` e `heart_rate`, perche'
    sono quelle che mappano piu' direttamente sulle feature del Google Watch 2.
    """
    aggregates: dict[int, Pamap2WindowAggregate] = {}
    input_rows = 0
    window_seconds = window_minutes * 60.0

    for chunk in pd.read_csv(  # type: ignore[call-overload]
        source,
        sep=r"\s+",
        header=None,
        usecols=[0, 1, 2],  # type: ignore[reportArgumentType]
        names=["time_s", "activity_id", "heart_rate"],
        na_values=["NaN"],
        chunksize=chunksize,
        engine="c",
    ):
        if limit_rows is not None:
            remaining = limit_rows - input_rows
            if remaining <= 0:
                break
            chunk = chunk.head(remaining)

        input_rows += int(chunk.shape[0])
        if chunk.empty:
            continue

        chunk["time_s"] = pd.to_numeric(chunk["time_s"], errors="coerce")
        chunk["activity_id"] = pd.to_numeric(chunk["activity_id"], errors="coerce")
        chunk["heart_rate"] = pd.to_numeric(chunk["heart_rate"], errors="coerce")
        chunk = chunk.dropna(subset=["time_s"])
        if chunk.empty:
            continue

        chunk["window_index"] = (chunk["time_s"] // window_seconds).astype(int)
        for window_index, group in chunk.groupby("window_index", sort=False):
            aggregate = aggregates.setdefault(int(window_index), Pamap2WindowAggregate())
            activity_counts = (
                group["activity_id"]
                .dropna()
                .astype(int)
                .value_counts()
                .to_dict()
            )
            aggregate.add_chunk_stats(
                row_count=int(group.shape[0]),
                heart_rates=group["heart_rate"],
                activity_counts=activity_counts,
            )

    return aggregates, input_rows


def _row_from_aggregate(
    patient_id: str,
    base_time: datetime,
    window_index: int,
    aggregate: Pamap2WindowAggregate,
    window_minutes: int,
    sampling_hz: float,
) -> dict[str, Any]:
    """Crea una riga feature finale a partire da una finestra PAMAP2."""
    window_start = base_time + timedelta(minutes=window_index * window_minutes)
    row: dict[str, Any] = {
        "patient_id": patient_id,
        "window_start": window_start.isoformat(),
        "window_end": (window_start + timedelta(minutes=window_minutes)).isoformat(),
        "wearable_present": 1,
        "wearable_battery_pct": "",
    }
    row.update({column: nan for column in FEATURE_COLUMNS})

    if aggregate.hr_count > 0:
        mean = aggregate.hr_sum / aggregate.hr_count
        variance = max(0.0, aggregate.hr_sum_sq / aggregate.hr_count - mean * mean)
        row["heart_rate_mean"] = float(mean)
        row["heart_rate_std"] = float(sqrt(variance))

    row["steps"] = _estimate_steps(aggregate.activity_counts, sampling_hz)
    row["sedentary_minutes"] = _estimate_sedentary_minutes(
        aggregate.activity_counts,
        sampling_hz,
    )
    row["fall_events"] = 0.0
    return {column: row.get(column, "") for column in DATASET_COLUMNS}


def _estimate_steps(activity_counts: dict[int, int], sampling_hz: float) -> float:
    """Stima i passi usando activity id e cadenze medie.

    PAMAP2 non fornisce step count. Questa stima non sostituisce i passi reali
    del Google Watch 2, ma da al modello generico wearable un segnale di
    intensita movimento prima della baseline personale.
    """
    total_steps = 0.0
    for activity_id, count in activity_counts.items():
        cadence = STEP_CADENCE_BY_ACTIVITY.get(activity_id)
        if cadence is None:
            continue
        minutes = float(count) / sampling_hz / 60.0
        total_steps += minutes * cadence
    return float(total_steps)


def _estimate_sedentary_minutes(activity_counts: dict[int, int], sampling_hz: float) -> float:
    """Calcola i minuti sedentari da activity id noti come lying/sitting/TV."""
    sedentary_samples = sum(
        count for activity_id, count in activity_counts.items()
        if activity_id in SEDENTARY_ACTIVITY_IDS
    )
    return float(sedentary_samples) / sampling_hz / 60.0


def parse_include_patterns(value: str | Iterable[str]) -> tuple[str, ...]:
    """Normalizza pattern CLI separati da virgola in una tupla pulita."""
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)
    patterns = tuple(item.strip() for item in items if str(item).strip())
    return patterns or ("*.dat",)
