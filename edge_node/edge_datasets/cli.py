from __future__ import annotations

import argparse
import json

from edge_datasets.casas_converter import (
    convert_casas_dataset,
    parse_include_patterns as parse_casas_include_patterns,
)
from edge_datasets.merge import merge_feature_datasets, parse_input_paths
from edge_datasets.pamap2_converter import (
    convert_pamap2_dataset,
    parse_include_patterns as parse_pamap2_include_patterns,
)
from edge_datasets.wesad_converter import (
    convert_wesad_dataset,
    parse_include_patterns as parse_wesad_include_patterns,
    parse_label_ids,
)


def build_parser() -> argparse.ArgumentParser:
    """Costruisce la CLI per convertire dataset pubblici nello schema edge.

    La CLI tiene separata la fase dataset dalla fase runtime del Raspberry:
    qui trasformiamo CASAS/WESAD/PAMAP2 in CSV compatibili, mentre `edge_runtime`
    resta dedicato ai dati reali raccolti in casa.
    """
    parser = argparse.ArgumentParser(
        prog="edge-datasets",
        description="Convert public datasets into the edge AI feature schema.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    casas = subparsers.add_parser(
        "casas",
        help="Convert CASAS smart-home CSV files into generic spatial windows.",
    )
    casas.add_argument(
        "--input-dir",
        default="data/external/casas",
        help="Directory containing CASAS CSV files.",
    )
    casas.add_argument(
        "--output",
        default="data/processed/generic_spatial_dataset.csv",
        help="Output CSV compatible with edge_ai train-generic.",
    )
    casas.add_argument(
        "--window-minutes",
        type=int,
        default=4,
        help="Aggregation window size in minutes.",
    )
    casas.add_argument(
        "--include",
        default="*.csv",
        help="Comma-separated glob patterns, for example aruba.csv,milan.csv.",
    )
    casas.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional cap on number of input files, useful for quick tests.",
    )
    casas.add_argument(
        "--limit-rows-per-file",
        type=int,
        default=None,
        help="Optional cap on read rows per file, useful for smoke tests.",
    )
    casas.add_argument(
        "--max-output-rows",
        type=int,
        default=None,
        help="Optional cap on output rows, useful for smoke tests.",
    )

    pamap2 = subparsers.add_parser(
        "pamap2",
        help="Convert PAMAP2 .dat files into generic wearable windows.",
    )
    pamap2.add_argument(
        "--input-dir",
        default="data/external/pamap2/Protocol",
        help="Directory containing PAMAP2 subject .dat files.",
    )
    pamap2.add_argument(
        "--output",
        default="data/processed/generic_wearable_dataset_pamap2.csv",
        help="Output CSV compatible with edge_ai train-generic.",
    )
    pamap2.add_argument(
        "--window-minutes",
        type=int,
        default=4,
        help="Aggregation window size in minutes.",
    )
    pamap2.add_argument(
        "--include",
        default="*.dat",
        help="Comma-separated glob patterns, for example subject101.dat,subject102.dat.",
    )
    pamap2.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional cap on number of input files, useful for quick tests.",
    )
    pamap2.add_argument(
        "--limit-rows-per-file",
        type=int,
        default=None,
        help="Optional cap on read rows per file, useful for smoke tests.",
    )
    pamap2.add_argument(
        "--max-output-rows",
        type=int,
        default=None,
        help="Optional cap on output rows, useful for smoke tests.",
    )
    pamap2.add_argument(
        "--sampling-hz",
        type=float,
        default=100.0,
        help="PAMAP2 sampling frequency used to estimate minutes and steps.",
    )
    pamap2.add_argument(
        "--chunksize",
        type=int,
        default=250_000,
        help="Number of rows read per pandas chunk.",
    )

    wesad = subparsers.add_parser(
        "wesad",
        help="Convert WESAD subject .pkl files into generic wearable windows.",
    )
    wesad.add_argument(
        "--input-dir",
        default="data/external/wesad",
        help="Directory containing WESAD S*/S*.pkl files.",
    )
    wesad.add_argument(
        "--output",
        default="data/processed/generic_wearable_dataset_wesad.csv",
        help="Output CSV compatible with edge_ai train-generic.",
    )
    wesad.add_argument(
        "--window-minutes",
        type=int,
        default=4,
        help="Aggregation window size in minutes.",
    )
    wesad.add_argument(
        "--include",
        default="S*/S*.pkl",
        help="Comma-separated glob patterns, for example S2/S2.pkl,S3/S3.pkl.",
    )
    wesad.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional cap on number of subjects, useful for quick tests.",
    )
    wesad.add_argument(
        "--max-output-rows",
        type=int,
        default=None,
        help="Optional cap on output rows, useful for smoke tests.",
    )
    wesad.add_argument(
        "--accepted-labels",
        default="1,3,4",
        help="WESAD label ids used as normal training data. Default: baseline, amusement, meditation.",
    )
    wesad.add_argument(
        "--min-label-ratio",
        type=float,
        default=0.8,
        help="Minimum fraction of a window covered by one accepted label.",
    )
    wesad.add_argument(
        "--bvp-sampling-hz",
        type=float,
        default=64.0,
        help="WESAD wrist BVP sampling frequency.",
    )
    wesad.add_argument(
        "--label-sampling-hz",
        type=float,
        default=700.0,
        help="WESAD label sampling frequency.",
    )

    merge = subparsers.add_parser(
        "merge",
        help="Merge already converted feature CSV files.",
    )
    merge.add_argument(
        "--inputs",
        required=True,
        help="Comma-separated CSV paths to merge.",
    )
    merge.add_argument(
        "--output",
        required=True,
        help="Output CSV path.",
    )
    return parser


def main() -> None:
    """Esegue il comando richiesto e stampa un riepilogo JSON.

    Stampare JSON rende immediato controllare quante righe sono state lette,
    quanti eventi sono entrati nel dataset e dove e' stato scritto l'output.
    """
    args = build_parser().parse_args()
    if args.command == "casas":
        summary = convert_casas_dataset(
            input_dir=args.input_dir,
            output_csv=args.output,
            window_minutes=args.window_minutes,
            include=parse_casas_include_patterns(args.include),
            max_files=args.max_files,
            limit_rows_per_file=args.limit_rows_per_file,
            max_output_rows=args.max_output_rows,
        )
        print(json.dumps(summary.to_dict(), indent=2))
        return
    if args.command == "pamap2":
        summary = convert_pamap2_dataset(
            input_dir=args.input_dir,
            output_csv=args.output,
            window_minutes=args.window_minutes,
            include=parse_pamap2_include_patterns(args.include),
            max_files=args.max_files,
            limit_rows_per_file=args.limit_rows_per_file,
            max_output_rows=args.max_output_rows,
            sampling_hz=args.sampling_hz,
            chunksize=args.chunksize,
        )
        print(json.dumps(summary.to_dict(), indent=2))
        return
    if args.command == "wesad":
        summary = convert_wesad_dataset(
            input_dir=args.input_dir,
            output_csv=args.output,
            window_minutes=args.window_minutes,
            include=parse_wesad_include_patterns(args.include),
            max_files=args.max_files,
            max_output_rows=args.max_output_rows,
            accepted_labels=parse_label_ids(args.accepted_labels),
            min_label_ratio=args.min_label_ratio,
            bvp_sampling_hz=args.bvp_sampling_hz,
            label_sampling_hz=args.label_sampling_hz,
        )
        print(json.dumps(summary.to_dict(), indent=2))
        return
    if args.command == "merge":
        summary = merge_feature_datasets(
            inputs=parse_input_paths(args.inputs),
            output_csv=args.output,
        )
        print(json.dumps(summary.to_dict(), indent=2))
        return
    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
