from __future__ import annotations

import argparse
import os

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    """Costruisce la CLI per avviare il receiver FastAPI locale.

    Gli argomenti permettono di scegliere configurazione, host e porta. Sul
    Raspberry questi valori verranno usati da un servizio automatico, non dal
    paziente manualmente.
    """
    parser = argparse.ArgumentParser(
        prog="edge-receiver",
        description="Run the Raspberry Pi local receiver for Android BLE samples.",
    )
    parser.add_argument("--config", default="config/edge.example.yml")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    return parser


def main() -> None:
    """Avvia il server Uvicorn che espone gli endpoint del receiver.

    La configurazione viene passata all'app tramite variabile ambiente
    `EDGE_CONFIG`, cosi' FastAPI puo' caricarla anche quando viene istanziata da
    Uvicorn.
    """
    args = build_parser().parse_args()
    os.environ["EDGE_CONFIG"] = args.config
    uvicorn.run("edge_receiver.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
