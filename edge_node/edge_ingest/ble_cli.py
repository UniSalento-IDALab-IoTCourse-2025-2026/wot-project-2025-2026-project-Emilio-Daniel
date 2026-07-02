from __future__ import annotations

import argparse
import json

from edge_ingest.ble_collector import collect_ble_samples, discover_ble_devices
from edge_ingest.config import load_config


def build_parser() -> argparse.ArgumentParser:
    """Definisce i comandi per scansione e discovery BLE da terminale.

    La CLI permette sia di cercare dispositivi vicini sia di salvare campioni
    grezzi. E' pensata per la fase di installazione e calibrazione dei beacon o
    del tag indossato.
    """
    parser = argparse.ArgumentParser(
        prog="ble-scan",
        description="Scan the wearable BLE tag and append raw samples to CSV.",
    )
    parser.add_argument("--config", default="config/edge.example.yml")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="List nearby BLE devices without writing samples.",
    )
    return parser


def main() -> None:
    """Esegue discovery BLE oppure scansione reale in base agli argomenti.

    Con `--discover` non viene scritto alcun CSV: si visualizzano solo i device
    vicini. Senza `--discover`, i campioni vengono raccolti e appesi al file raw
    usato dall'aggregatore BLE.
    """
    args = build_parser().parse_args()
    config = load_config(args.config)

    if args.discover:
        devices = discover_ble_devices(config.ble)
        print(json.dumps({"status": "ble_discovery_completed", "devices": devices}, indent=2))
        return

    samples = collect_ble_samples(config.ble)
    print(
        json.dumps(
            {
                "status": "ble_scan_completed",
                "samples": len(samples),
                "raw_csv": str(config.ble.raw_csv),
                "scanner_room": config.ble.scanner_room,
                "scanner_id": config.ble.scanner_id,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
