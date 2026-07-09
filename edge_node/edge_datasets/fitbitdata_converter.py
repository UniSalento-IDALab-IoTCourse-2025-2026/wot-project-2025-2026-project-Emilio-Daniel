from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite, nan
from pathlib import Path
from typing import Any

import pandas as pd

from edge_ai.schema import DATASET_COLUMNS, FEATURE_COLUMNS


@dataclass(frozen=True)
class FitbitDataConversionSummary:
    """Riepilogo della conversione dei dataset wearable stile Fitbit."""

    input_files: int
    output_rows: int
    hrv_rows: int
    health_rows: int
    oxi_rows: int
    activity_rows: int
    sleep_rows: int
    hrv_condition: str
    output_csv: str

    def to_dict(self) -> dict[str, Any]:
        """Converte il riepilogo in un dizionario serializzabile come JSON."""
        return {
            "input_files": self.input_files,
            "output_rows": self.output_rows,
            "hrv_rows": self.hrv_rows,
            "health_rows": self.health_rows,
            "oxi_rows": self.oxi_rows,
            "activity_rows": self.activity_rows,
            "sleep_rows": self.sleep_rows,
            "hrv_condition": self.hrv_condition,
            "output_csv": self.output_csv,
        }


def convert_fitbitdata_dataset(
    input_dir: str | Path,
    output_csv: str | Path,
    window_minutes: int = 4,
    hrv_condition: str = "no stress",
    health_status: str = "0",
    include_oxi: bool = True,
    oxi_label: int = 0,
    oxi_min_spo2: float = 92.0,
    max_output_rows: int | None = None,
    hrv_chunksize: int = 100_000,
) -> FitbitDataConversionSummary:
    """Converte i dataset in `data/external/fitbitdata` nello schema edge.

    La cartella contiene sorgenti diverse: feature HRV gia' calcolate, riepiloghi
    daily activity e un piccolo dataset sleep/lifestyle. Il converter le unifica
    in un solo CSV compatibile con `edge_ai train-generic`, riempiendo solo le
    feature disponibili e lasciando `nan` dove la sorgente non offre quel dato.
    """
    source_dir = Path(input_dir)
    if not source_dir.exists():
        raise FileNotFoundError(f"Fitbit-style input directory not found: {source_dir}")

    target = Path(output_csv)
    target.parent.mkdir(parents=True, exist_ok=True)
    base_time = datetime(2020, 1, 1, tzinfo=timezone.utc)

    hrv_rows = 0
    health_rows = 0
    oxi_rows = 0
    activity_rows = 0
    sleep_rows = 0
    input_files = 0
    written = 0

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
        writer.writeheader()

        hrv_count, used_files = _write_hrv_archive_rows(
            source_dir=source_dir,
            writer=writer,
            base_time=base_time,
            window_minutes=window_minutes,
            hrv_condition=hrv_condition,
            max_rows=_remaining(max_output_rows, written),
            chunksize=hrv_chunksize,
        )
        hrv_rows += hrv_count
        written += hrv_count
        input_files += used_files

        health_count, used_files = _write_health_data_rows(
            source_dir=source_dir,
            writer=writer,
            base_time=base_time + timedelta(days=2500),
            window_minutes=window_minutes,
            health_status=health_status,
            max_rows=_remaining(max_output_rows, written),
        )
        health_rows += health_count
        written += health_count
        input_files += used_files

        if include_oxi:
            oxi_count, used_files = _write_hugcdn_oxi_rows(
                source_dir=source_dir,
                writer=writer,
                base_time=base_time + timedelta(days=3000),
                window_minutes=window_minutes,
                oxi_label=oxi_label,
                min_spo2=oxi_min_spo2,
                max_rows=_remaining(max_output_rows, written),
            )
            oxi_rows += oxi_count
            written += oxi_count
            input_files += used_files

        activity_count, used_files = _write_activity_rows(
            source_dir=source_dir,
            writer=writer,
            window_minutes=window_minutes,
            max_rows=_remaining(max_output_rows, written),
        )
        activity_rows += activity_count
        written += activity_count
        input_files += used_files

        sleep_count, used_files = _write_sleep_health_rows(
            source_dir=source_dir,
            writer=writer,
            base_time=base_time + timedelta(days=5000),
            window_minutes=window_minutes,
            max_rows=_remaining(max_output_rows, written),
        )
        sleep_rows += sleep_count
        written += sleep_count
        input_files += used_files

    return FitbitDataConversionSummary(
        input_files=input_files,
        output_rows=written,
        hrv_rows=hrv_rows,
        health_rows=health_rows,
        oxi_rows=oxi_rows,
        activity_rows=activity_rows,
        sleep_rows=sleep_rows,
        hrv_condition=hrv_condition,
        output_csv=str(target),
    )


def _write_hrv_archive_rows(
    source_dir: Path,
    writer: csv.DictWriter,
    base_time: datetime,
    window_minutes: int,
    hrv_condition: str,
    max_rows: int | None,
    chunksize: int,
) -> tuple[int, int]:
    """Scrive righe HR/HRV partendo dai file `archive2`.

    Supportiamo due formati: quello con `time_domain_features_train.csv` e label
    in `heart_rate_non_linear_features_train.csv`, e quello piu' compatto con
    `train.csv`/`test.csv`, dove `condition` e' gia' nella stessa riga. Di
    default usiamo solo `no stress`, cosi' il modello generico impara una
    normalita fisiologica piu' pulita.
    """
    archive_dir = source_dir / "archive2"
    time_path = archive_dir / "time_domain_features_train.csv"
    nonlinear_path = archive_dir / "heart_rate_non_linear_features_train.csv"
    output_rows = 0
    used_files = 0

    if time_path.exists():
        accepted_uuids = _load_accepted_hrv_uuids(nonlinear_path, hrv_condition)
        used_files += 1 + (1 if nonlinear_path.exists() else 0)

        usecols = ["uuid", "MEAN_RR", "SDRR", "RMSSD", "HR"]
        for chunk in pd.read_csv(  # type: ignore[call-overload]
            time_path,
            usecols=usecols,  # type: ignore[reportArgumentType]
            chunksize=chunksize,
        ):
            if accepted_uuids is not None:
                chunk = chunk[chunk["uuid"].astype(str).isin(accepted_uuids)]
            if chunk.empty:
                continue

            for _, record in chunk.iterrows():
                if max_rows is not None and output_rows >= max_rows:
                    return output_rows, used_files
                row = _row_from_hrv_record(
                    record=record,
                    patient_id="fitbitdata-hrv",
                    window_start=base_time + timedelta(minutes=output_rows * window_minutes),
                    window_minutes=window_minutes,
                )
                if row is None:
                    continue
                writer.writerow(row)
                output_rows += 1

    for labeled_path in _iter_labeled_hrv_paths(source_dir):
        if max_rows is not None and output_rows >= max_rows:
            break
        count = _write_labeled_hrv_file(
            path=labeled_path,
            writer=writer,
            base_time=base_time,
            window_minutes=window_minutes,
            hrv_condition=hrv_condition,
            row_offset=output_rows,
            max_rows=_remaining(max_rows, output_rows),
            chunksize=chunksize,
        )
        output_rows += count
        used_files += 1

    return output_rows, used_files


def _iter_labeled_hrv_paths(source_dir: Path) -> list[Path]:
    """Restituisce file HRV dove `condition` e' gia' nel CSV sorgente."""
    candidates = [
        source_dir / "archive2" / "train.csv",
        source_dir / "archive2" / "test.csv",
        source_dir / "train.csv",
        source_dir / "test.csv",
    ]
    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in candidates:
        if candidate.exists() and candidate.resolve() not in seen:
            seen.add(candidate.resolve())
            result.append(candidate)
    return result


def _write_labeled_hrv_file(
    path: Path,
    writer: csv.DictWriter,
    base_time: datetime,
    window_minutes: int,
    hrv_condition: str,
    row_offset: int,
    max_rows: int | None,
    chunksize: int,
) -> int:
    """Scrive righe HRV da CSV con colonna `condition` incorporata."""
    output_rows = 0
    usecols = ["MEAN_RR", "SDRR", "RMSSD", "HR", "condition"]
    condition = hrv_condition.strip().lower()

    for chunk in pd.read_csv(  # type: ignore[call-overload]
        path,
        usecols=usecols,  # type: ignore[reportArgumentType]
        chunksize=chunksize,
    ):
        if condition not in {"", "all", "*"}:
            mask = chunk["condition"].astype(str).str.strip().str.lower() == condition
            chunk = chunk[mask]
        if chunk.empty:
            continue

        for _, record in chunk.iterrows():
            if max_rows is not None and output_rows >= max_rows:
                return output_rows
            row = _row_from_hrv_record(
                record=record,
                patient_id=f"fitbitdata-hrv-{path.stem}",
                window_start=base_time
                + timedelta(minutes=(row_offset + output_rows) * window_minutes),
                window_minutes=window_minutes,
            )
            if row is None:
                continue
            writer.writerow(row)
            output_rows += 1

    return output_rows


def _load_accepted_hrv_uuids(
    nonlinear_path: Path,
    hrv_condition: str,
) -> set[str] | None:
    """Restituisce gli UUID con condizione desiderata, oppure `None` per tutti."""
    condition = hrv_condition.strip().lower()
    if condition in {"", "all", "*"} or not nonlinear_path.exists():
        return None

    accepted: set[str] = set()
    for chunk in pd.read_csv(  # type: ignore[call-overload]
        nonlinear_path,
        usecols=["uuid", "condition"],  # type: ignore[reportArgumentType]
        chunksize=200_000,
    ):
        mask = chunk["condition"].astype(str).str.strip().str.lower() == condition
        accepted.update(chunk.loc[mask, "uuid"].astype(str))
    return accepted


def _row_from_hrv_record(
    record: pd.Series,
    patient_id: str,
    window_start: datetime,
    window_minutes: int,
) -> dict[str, Any] | None:
    """Mappa una riga HRV nello schema ufficiale del progetto."""
    heart_rate = _number(record.get("HR"))
    rmssd = _number(record.get("RMSSD"))
    mean_rr = _number(record.get("MEAN_RR"))
    sdrr = _number(record.get("SDRR"))

    if not _in_range(heart_rate, 35.0, 220.0):
        return None
    if not _in_range(rmssd, 0.0, 500.0):
        rmssd = nan

    row = _empty_row(
        patient_id=patient_id,
        window_start=window_start,
        window_minutes=window_minutes,
    )
    row["heart_rate_mean"] = float(heart_rate)
    row["heart_rate_std"] = _estimate_hr_std_from_rr(mean_rr, sdrr)
    if isfinite(rmssd):
        row["hrv_rmssd"] = float(rmssd)
    row["fall_events"] = 0.0
    return _ordered(row)


def _write_health_data_rows(
    source_dir: Path,
    writer: csv.DictWriter,
    base_time: datetime,
    window_minutes: int,
    health_status: str,
    max_rows: int | None,
) -> tuple[int, int]:
    """Scrive righe da `Health data.csv`, usando pulse e SpO2.

    Il file contiene anche una colonna `Status`. Per il modello generico di
    normalita usiamo di default solo `Status = 0`; valori diversi possono essere
    usati in futuro per test/validazione, ma non per insegnare la routine.
    """
    health_path = source_dir / "Health data.csv"
    if not health_path.exists() or max_rows == 0:
        return 0, 0

    frame = pd.read_csv(health_path)
    status_filter = str(health_status).strip().lower()
    if status_filter not in {"", "all", "*"} and "Status" in frame.columns:
        frame = frame[frame["Status"].astype(str).str.strip().str.lower() == status_filter]

    output_rows = 0
    for window_index, (_, record) in enumerate(frame.iterrows()):
        if max_rows is not None and output_rows >= max_rows:
            break
        pulse = _number(record.get("pulse"))
        spo2 = _number(record.get("SpO2"))
        if not _in_range(pulse, 35.0, 220.0) or not _in_range(spo2, 70.0, 100.0):
            continue

        row = _empty_row(
            patient_id="fitbitdata-health",
            window_start=base_time + timedelta(minutes=window_index * window_minutes),
            window_minutes=window_minutes,
        )
        row["heart_rate_mean"] = float(pulse)
        row["heart_rate_std"] = 0.0
        row["spo2_mean"] = float(spo2)
        row["fall_events"] = 0.0
        writer.writerow(_ordered(row))
        output_rows += 1

    return output_rows, 1


def _write_hugcdn_oxi_rows(
    source_dir: Path,
    writer: csv.DictWriter,
    base_time: datetime,
    window_minutes: int,
    oxi_label: int,
    min_spo2: float,
    max_rows: int | None,
) -> tuple[int, int]:
    """Scrive righe da HuGCDN2014-OXI usando RR, SpO2 e label non-apnea.

    Il dataset contiene segmenti ECG/SpO2 e label minuto per minuto. Per il
    modello generico usiamo solo segmenti con label `0` e SpO2 media sopra
    soglia, evitando di addestrare la normalita su eventi respiratori patologici.
    """
    oxi_root = source_dir / "HuGCDN2014-OXI"
    rr_dir = oxi_root / "RR"
    sat_dir = oxi_root / "SAT"
    labels_dir = oxi_root / "LABELS"
    if not rr_dir.exists() or not sat_dir.exists() or not labels_dir.exists() or max_rows == 0:
        return 0, 0

    try:
        from scipy.io import loadmat
    except Exception as exc:  # pragma: no cover - depends on optional local setup.
        raise RuntimeError(
            "HuGCDN2014-OXI conversion requires scipy. "
            "Install requirements.txt before converting .mat datasets."
        ) from exc

    output_rows = 0
    used_files = 0
    for subject_index, rr_path in enumerate(sorted(rr_dir.glob("*.mat"))):
        sat_path = sat_dir / rr_path.name
        label_path = labels_dir / rr_path.name
        if not sat_path.exists() or not label_path.exists():
            continue

        rr_cells = _mat_cells(loadmat(rr_path), preferred_key="RR_notch_abs_pr_ada")
        sat_cells = _mat_cells(loadmat(sat_path), preferred_key="SAT")
        labels = _mat_labels(loadmat(label_path))
        used_files += 3

        cell_count = min(len(rr_cells), len(sat_cells), len(labels))
        for cell_index in range(cell_count):
            if max_rows is not None and output_rows >= max_rows:
                return output_rows, used_files
            if int(labels[cell_index]) != int(oxi_label):
                continue
            row = _row_from_oxi_segment(
                rr_values=rr_cells[cell_index],
                spo2_values=sat_cells[cell_index],
                patient_id=f"hugcdn-oxi-{rr_path.stem}",
                window_start=base_time
                + timedelta(days=subject_index, minutes=cell_index * window_minutes),
                window_minutes=window_minutes,
                min_spo2=min_spo2,
            )
            if row is None:
                continue
            writer.writerow(row)
            output_rows += 1

    return output_rows, used_files


def _row_from_oxi_segment(
    rr_values: Any,
    spo2_values: Any,
    patient_id: str,
    window_start: datetime,
    window_minutes: int,
    min_spo2: float,
) -> dict[str, Any] | None:
    """Converte un segmento RR/SAT in una riga feature wearable."""
    rr = _clean_vector(rr_values, lower=300.0, upper=2000.0)
    spo2 = _clean_vector(spo2_values, lower=70.0, upper=100.0)
    if rr.size < 5 or spo2.size < 10:
        return None

    heart_rates = 60000.0 / rr
    heart_rates = heart_rates[(heart_rates >= 35.0) & (heart_rates <= 220.0)]
    if heart_rates.size < 3:
        return None

    spo2_mean = float(spo2.mean())
    if spo2_mean < float(min_spo2):
        return None

    row = _empty_row(
        patient_id=patient_id,
        window_start=window_start,
        window_minutes=window_minutes,
    )
    row["heart_rate_mean"] = float(heart_rates.mean())
    row["heart_rate_std"] = float(heart_rates.std())
    row["spo2_mean"] = spo2_mean
    if rr.size >= 3:
        rr_diff = rr[1:] - rr[:-1]
        row["hrv_rmssd"] = float((rr_diff * rr_diff).mean() ** 0.5)
    row["fall_events"] = 0.0
    return _ordered(row)


def _write_activity_rows(
    source_dir: Path,
    writer: csv.DictWriter,
    window_minutes: int,
    max_rows: int | None,
) -> tuple[int, int]:
    """Scrive righe derivate dal daily activity dataset."""
    activity_path = source_dir / "Activity.csv"
    if not activity_path.exists() or max_rows == 0:
        return 0, 0

    frame = pd.read_csv(activity_path)
    output_rows = 0
    windows_per_day = 24 * 60 / float(window_minutes)

    for _, record in frame.iterrows():
        if max_rows is not None and output_rows >= max_rows:
            break
        date = pd.to_datetime(str(record.get("Date", "")), errors="coerce")
        if pd.isna(date):
            continue
        window_start = date.to_pydatetime().replace(tzinfo=timezone.utc)
        row = _empty_row(
            patient_id=f"fitbitdata-activity-{record.get('UserID')}",
            window_start=window_start,
            window_minutes=window_minutes,
        )
        steps = _number(record.get("Steps"))
        sedentary = _number(record.get("Sedentary_Minutes"))
        if isfinite(steps):
            row["steps"] = float(steps) / windows_per_day
        if isfinite(sedentary):
            row["sedentary_minutes"] = float(sedentary) / windows_per_day
        row["fall_events"] = 0.0
        writer.writerow(_ordered(row))
        output_rows += 1

    return output_rows, 1


def _write_sleep_health_rows(
    source_dir: Path,
    writer: csv.DictWriter,
    base_time: datetime,
    window_minutes: int,
    max_rows: int | None,
) -> tuple[int, int]:
    """Scrive righe dal dataset Sleep Health and Lifestyle."""
    sleep_path = source_dir / "Sleep_health_and_lifestyle_dataset.csv"
    if not sleep_path.exists() or max_rows == 0:
        return 0, 0

    frame = pd.read_csv(sleep_path)
    output_rows = 0
    windows_per_day = 24 * 60 / float(window_minutes)

    for window_index, (_, record) in enumerate(frame.iterrows()):
        if max_rows is not None and output_rows >= max_rows:
            break
        window_start = base_time + timedelta(minutes=window_index * window_minutes)
        row = _empty_row(
            patient_id=f"sleep-health-{record.get('Person ID')}",
            window_start=window_start,
            window_minutes=window_minutes,
        )

        heart_rate = _number(record.get("Heart Rate"))
        sleep_hours = _number(record.get("Sleep Duration"))
        daily_steps = _number(record.get("Daily Steps"))

        if _in_range(heart_rate, 35.0, 220.0):
            row["heart_rate_mean"] = float(heart_rate)
            row["resting_heart_rate"] = float(heart_rate)
        if _in_range(sleep_hours, 0.0, 24.0):
            row["sleep_minutes"] = float(sleep_hours) * 60.0
        if isfinite(daily_steps):
            row["steps"] = float(daily_steps) / windows_per_day
        row["fall_events"] = 0.0
        writer.writerow(_ordered(row))
        output_rows += 1

    return output_rows, 1


def _mat_cells(payload: dict[str, Any], preferred_key: str) -> list[Any]:
    """Estrae celle MATLAB da un payload `.mat`."""
    key = preferred_key if preferred_key in payload else _first_public_key(payload)
    if key is None:
        return []
    return list(payload[key].reshape(-1))


def _mat_labels(payload: dict[str, Any]) -> list[int]:
    """Estrae label minuto per minuto dai file MATLAB."""
    key = "salida_man_1m" if "salida_man_1m" in payload else "salida_man"
    if key not in payload:
        return []
    labels = _clean_vector(payload[key], lower=0.0, upper=10.0)
    return [int(value) for value in labels]


def _first_public_key(payload: dict[str, Any]) -> str | None:
    """Trova la prima chiave dati in un `.mat`, ignorando metadati MATLAB."""
    for key in payload:
        if not key.startswith("__"):
            return key
    return None


def _clean_vector(values: Any, lower: float, upper: float) -> Any:
    """Converte array/celle MATLAB in vettore `float` filtrato per range."""
    import numpy as np

    array = np.asarray(values)
    if array.dtype == object:
        parts = []
        for item in array.reshape(-1):
            item_array = np.asarray(item, dtype=float).reshape(-1)
            if item_array.size:
                parts.append(item_array)
        if not parts:
            return np.asarray([], dtype=float)
        array = np.concatenate(parts)
    else:
        array = np.asarray(array, dtype=float).reshape(-1)
    array = array[np.isfinite(array)]
    return array[(array >= lower) & (array <= upper)]


def _empty_row(
    patient_id: str,
    window_start: datetime,
    window_minutes: int,
) -> dict[str, Any]:
    """Crea una riga base con tutte le feature numeriche inizializzate a `nan`."""
    row: dict[str, Any] = {
        "patient_id": patient_id,
        "window_start": window_start.isoformat(),
        "window_end": (window_start + timedelta(minutes=window_minutes)).isoformat(),
        "wearable_present": 1,
        "wearable_battery_pct": "",
    }
    row.update({column: nan for column in FEATURE_COLUMNS})
    return row


def _ordered(row: dict[str, Any]) -> dict[str, Any]:
    """Riordina una riga secondo `DATASET_COLUMNS`."""
    return {column: row.get(column, "") for column in DATASET_COLUMNS}


def _remaining(max_output_rows: int | None, written: int) -> int | None:
    """Calcola quante righe si possono ancora scrivere con il limite CLI."""
    if max_output_rows is None:
        return None
    return max(0, int(max_output_rows) - int(written))


def _number(value: Any) -> float:
    """Converte un valore in float, restituendo `nan` se non valido."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return nan
    return result if isfinite(result) else nan


def _in_range(value: float, lower: float, upper: float) -> bool:
    """Controlla che un valore numerico sia finito e fisiologicamente plausibile."""
    return isfinite(value) and lower <= value <= upper


def _estimate_hr_std_from_rr(mean_rr: float, sdrr: float) -> float:
    """Stima la deviazione standard del battito da media e variabilita RR.

    Il dataset HRV non fornisce direttamente `heart_rate_std`. Usiamo quindi una
    approssimazione differenziale: HR = 60000 / RR, quindi la variabilita di HR
    cresce con `SDRR` e diminuisce al crescere di `MEAN_RR`.
    """
    if not _in_range(mean_rr, 250.0, 2000.0) or not _in_range(sdrr, 0.0, 1000.0):
        return nan
    estimate = 60000.0 * float(sdrr) / (float(mean_rr) ** 2)
    if not _in_range(estimate, 0.0, 80.0):
        return nan
    return float(estimate)
