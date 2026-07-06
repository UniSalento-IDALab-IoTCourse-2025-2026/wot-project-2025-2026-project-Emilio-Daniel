from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from edge_ai.schema import DATASET_COLUMNS


@dataclass(frozen=True)
class MergeSummary:
    """Riepilogo dell'unione di piu' CSV nello schema del progetto."""

    input_files: int
    output_rows: int
    output_csv: str

    def to_dict(self) -> dict[str, Any]:
        """Converte il riepilogo in un dizionario serializzabile."""
        return {
            "input_files": self.input_files,
            "output_rows": self.output_rows,
            "output_csv": self.output_csv,
        }


def merge_feature_datasets(
    inputs: Iterable[str | Path],
    output_csv: str | Path,
) -> MergeSummary:
    """Unisce CSV gia' convertiti nello schema feature ufficiale.

    Il modello generico wearable puo' nascere da piu' dataset pubblici. Questa
    funzione mantiene l'ordine delle colonne stabile e rifiuta file con schema
    incompatibile, evitando di creare un training set difficile da interpretare.
    """
    sources = [Path(source) for source in inputs]
    if not sources:
        raise ValueError("At least one input CSV is required")

    target = Path(output_csv)
    target.parent.mkdir(parents=True, exist_ok=True)
    output_rows = 0

    with target.open("w", newline="", encoding="utf-8") as output_handle:
        writer = csv.DictWriter(output_handle, fieldnames=DATASET_COLUMNS)
        writer.writeheader()

        for source in sources:
            if not source.exists():
                raise FileNotFoundError(f"Input CSV not found: {source}")
            with source.open("r", newline="", encoding="utf-8") as input_handle:
                reader = csv.DictReader(input_handle)
                missing = [column for column in DATASET_COLUMNS if column not in (reader.fieldnames or [])]
                if missing:
                    raise ValueError(
                        f"{source} has missing columns: {', '.join(missing)}"
                    )
                for row in reader:
                    writer.writerow({column: row.get(column, "") for column in DATASET_COLUMNS})
                    output_rows += 1

    return MergeSummary(
        input_files=len(sources),
        output_rows=output_rows,
        output_csv=str(target),
    )


def parse_input_paths(value: str | Iterable[str]) -> tuple[str, ...]:
    """Normalizza percorsi CLI separati da virgola."""
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)
    paths = tuple(item.strip() for item in items if str(item).strip())
    if not paths:
        raise ValueError("At least one input path is required")
    return paths
