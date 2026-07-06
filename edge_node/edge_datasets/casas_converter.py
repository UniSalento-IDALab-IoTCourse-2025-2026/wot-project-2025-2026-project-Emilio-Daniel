from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import nan
from pathlib import Path
from typing import Any, Iterable

from edge_ai.schema import DATASET_COLUMNS, FEATURE_COLUMNS


POSITIVE_STATES = {"ON", "OPEN", "PRESENT", "MOTION"}
ROOM_TO_FEATURE = {
    "bedroom": "bedroom_minutes",
    "kitchen": "kitchen_minutes",
    "bathroom": "bathroom_minutes",
    "living_room": "living_room_minutes",
}


@dataclass
class CasasWindowAggregate:
    """Mantiene gli eventi stanza osservati dentro una singola finestra.

    CASAS non fornisce direttamente "minuti in stanza", ma eventi ambientali
    generati dai sensori. Per trasformarli nello schema del nostro modello, il
    convertitore conta gli eventi per stanza e usa la proporzione degli eventi
    come stima dei minuti di permanenza nella finestra.
    """

    room_counts: dict[str, int] = field(default_factory=dict)
    event_count: int = 0
    room_changes: int = 0
    last_room: str | None = None

    def add_room_event(self, room: str) -> None:
        """Aggiunge un evento stanza aggiornando conteggi e cambi stanza."""
        if self.last_room is not None and self.last_room != room:
            self.room_changes += 1
        self.last_room = room
        self.event_count += 1
        self.room_counts[room] = self.room_counts.get(room, 0) + 1


@dataclass(frozen=True)
class CasasConversionSummary:
    input_files: int
    input_rows: int
    accepted_events: int
    output_rows: int
    output_csv: str

    def to_dict(self) -> dict[str, Any]:
        """Converte il riepilogo finale in un dizionario stampabile come JSON."""
        return {
            "input_files": self.input_files,
            "input_rows": self.input_rows,
            "accepted_events": self.accepted_events,
            "output_rows": self.output_rows,
            "output_csv": self.output_csv,
        }


def convert_casas_dataset(
    input_dir: str | Path,
    output_csv: str | Path,
    window_minutes: int = 4,
    include: tuple[str, ...] = ("*.csv",),
    max_files: int | None = None,
    limit_rows_per_file: int | None = None,
    max_output_rows: int | None = None,
) -> CasasConversionSummary:
    """Converte i CSV CASAS nello schema feature usato dai modelli edge.

    Ogni file CASAS viene trattato come una casa/soggetto distinto e diventa un
    `patient_id` sintetico, ad esempio `casas-aruba`. Il converter produce solo
    finestre con almeno un evento stanza utile, lasciando a `nan` le feature non
    disponibili in CASAS, come heart rate o dati NILM.
    """
    source_dir = Path(input_dir)
    target = Path(output_csv)
    files = _select_input_files(source_dir, include, max_files)
    target.parent.mkdir(parents=True, exist_ok=True)

    total_input_rows = 0
    total_accepted_events = 0
    total_output_rows = 0

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
        writer.writeheader()

        for source in files:
            aggregates, input_rows, accepted_events = _aggregate_file(
                source,
                window_minutes=window_minutes,
                limit_rows=limit_rows_per_file,
            )
            total_input_rows += input_rows
            total_accepted_events += accepted_events
            patient_id = f"casas-{source.stem}"

            for window_start in sorted(aggregates):
                row = _row_from_aggregate(
                    patient_id=patient_id,
                    window_start=window_start,
                    aggregate=aggregates[window_start],
                    window_minutes=window_minutes,
                )
                writer.writerow(row)
                total_output_rows += 1
                if max_output_rows is not None and total_output_rows >= max_output_rows:
                    return CasasConversionSummary(
                        input_files=len(files),
                        input_rows=total_input_rows,
                        accepted_events=total_accepted_events,
                        output_rows=total_output_rows,
                        output_csv=str(target),
                    )

    return CasasConversionSummary(
        input_files=len(files),
        input_rows=total_input_rows,
        accepted_events=total_accepted_events,
        output_rows=total_output_rows,
        output_csv=str(target),
    )


def _select_input_files(
    source_dir: Path,
    include: tuple[str, ...],
    max_files: int | None,
) -> list[Path]:
    """Seleziona i file CASAS da convertire usando pattern glob ordinati.

    La cartella CASAS contiene molti ambienti. I pattern permettono di lavorare
    prima su pochi file, ad esempio `aruba.csv` e `milan.csv`, e poi estendere
    la conversione all'intero dataset quando la pipeline e' stabile.
    """
    if not source_dir.exists():
        raise FileNotFoundError(f"CASAS input directory not found: {source_dir}")

    selected: list[Path] = []
    for pattern in include:
        selected.extend(source_dir.glob(pattern))

    files = sorted({path for path in selected if path.is_file() and path.suffix.lower() == ".csv"})
    if max_files is not None:
        files = files[:max_files]
    if not files:
        raise FileNotFoundError(f"No CASAS CSV files found in {source_dir}")
    return files


def _aggregate_file(
    source: Path,
    window_minutes: int,
    limit_rows: int | None,
) -> tuple[dict[datetime, CasasWindowAggregate], int, int]:
    """Legge un file CASAS e aggrega gli eventi positivi per finestra.

    Vengono considerati solo stati come `ON` e `OPEN`, perche' rappresentano una
    osservazione attiva del sensore. Stati come `OFF` o `CLOSE` descrivono la
    fine dell'impulso e non sono usati come nuova posizione del paziente.
    """
    aggregates: dict[datetime, CasasWindowAggregate] = {}
    input_rows = 0
    accepted_events = 0

    with source.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            input_rows += 1
            if limit_rows is not None and input_rows > limit_rows:
                break
            event = _parse_casas_row(row)
            if event is None:
                continue
            timestamp, room = event
            window_start = _floor_timestamp(timestamp, window_minutes)
            aggregate = aggregates.setdefault(window_start, CasasWindowAggregate())
            aggregate.add_room_event(room)
            accepted_events += 1

    return aggregates, input_rows, accepted_events


def _parse_casas_row(row: list[str]) -> tuple[datetime, str] | None:
    """Estrae timestamp e stanza canonica da una riga CASAS.

    Il formato osservato e' `date,time,sensor,state`. Il sensore viene tradotto
    nelle quattro stanze del nostro progetto: bedroom, kitchen, bathroom e
    living_room. Sensori esterni o non interpretabili vengono ignorati.
    """
    if len(row) < 4:
        return None
    state = row[3].strip().upper()
    if state not in POSITIVE_STATES:
        return None

    room = _canonical_room(row[2])
    if room is None:
        return None

    try:
        timestamp = datetime.fromisoformat(f"{row[0].strip()}T{row[1].strip()}")
    except ValueError:
        return None
    return timestamp.replace(tzinfo=timezone.utc), room


def _canonical_room(sensor_name: str) -> str | None:
    """Mappa il nome sensore CASAS in una stanza del nostro schema.

    Molti dataset CASAS usano nomi piu' specifici, come `LoungeChair` o
    `DiningRoom`. Per il nostro modello questi ambienti vengono trattati come
    `living_room`, cioe' area giorno. Sensori esterni come `OutsideDoor` vengono
    esclusi per non confondere presenza domestica e aperture porte.
    """
    normalized = sensor_name.strip().lower().replace(" ", "").replace("_", "")
    if not normalized or "outside" in normalized or "door" in normalized:
        return None
    if "bed" in normalized:
        return "bedroom"
    if "kitchen" in normalized:
        return "kitchen"
    if "bath" in normalized or "toilet" in normalized or "shower" in normalized:
        return "bathroom"
    if any(
        token in normalized
        for token in (
            "living",
            "lounge",
            "dining",
            "work",
            "guest",
            "hall",
            "other",
            "office",
            "room",
            "chair",
        )
    ):
        return "living_room"
    return None


def _floor_timestamp(timestamp: datetime, window_minutes: int) -> datetime:
    """Porta un timestamp al confine inferiore della finestra configurata."""
    minute = (timestamp.minute // window_minutes) * window_minutes
    return timestamp.replace(minute=minute, second=0, microsecond=0)


def _row_from_aggregate(
    patient_id: str,
    window_start: datetime,
    aggregate: CasasWindowAggregate,
    window_minutes: int,
) -> dict[str, Any]:
    """Crea una riga CSV finale a partire dagli eventi aggregati CASAS."""
    row: dict[str, Any] = {
        "patient_id": patient_id,
        "window_start": window_start.isoformat(),
        "window_end": (window_start + timedelta(minutes=window_minutes)).isoformat(),
        "wearable_present": "",
        "wearable_battery_pct": "",
    }
    row.update({column: nan for column in FEATURE_COLUMNS})

    room_minutes = _estimated_room_minutes(aggregate, window_minutes)
    row.update(room_minutes)
    row["room_changes"] = float(aggregate.room_changes)
    row["night_room_changes"] = (
        float(aggregate.room_changes) if 0 <= window_start.hour < 6 else 0.0
    )
    row["longest_single_room_minutes"] = max(room_minutes.values()) if room_minutes else 0.0
    return {column: row.get(column, "") for column in DATASET_COLUMNS}


def _estimated_room_minutes(
    aggregate: CasasWindowAggregate,
    window_minutes: int,
) -> dict[str, float]:
    """Stima i minuti stanza dividendo la finestra in base agli eventi."""
    minutes = {
        "bedroom_minutes": 0.0,
        "kitchen_minutes": 0.0,
        "bathroom_minutes": 0.0,
        "living_room_minutes": 0.0,
    }
    if aggregate.event_count <= 0:
        return minutes

    for room, count in aggregate.room_counts.items():
        feature = ROOM_TO_FEATURE.get(room)
        if feature is None:
            continue
        minutes[feature] += float(window_minutes) * float(count) / float(aggregate.event_count)
    return minutes


def parse_include_patterns(value: str | Iterable[str]) -> tuple[str, ...]:
    """Normalizza pattern CLI separati da virgola in una tupla pulita."""
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)
    patterns = tuple(item.strip() for item in items if str(item).strip())
    return patterns or ("*.csv",)
