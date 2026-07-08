from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from edge_ingest.config import load_config


def build_parser() -> argparse.ArgumentParser:
    """Costruisce il comando unico dell'edge node.

    Questo launcher e' pensato per i test e per il futuro Raspberry: avvia il
    receiver HTTP per l'app Android e, nello stesso terminale, il runtime che
    ogni 4 minuti aggrega BLE, Google Health e le altre sorgenti abilitate.
    """
    parser = argparse.ArgumentParser(
        prog="edge-stack",
        description="Start BLE receiver and edge runtime loop together.",
    )
    parser.add_argument("--config", default="config/edge.yml")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=240,
        help="Runtime interval in seconds. Defaults to 240 seconds.",
    )
    parser.add_argument(
        "--append-baseline",
        action="store_true",
        help="Run runtime loop in baseline collection mode.",
    )
    return parser


def main() -> None:
    """Avvia receiver e runtime loop come due processi coordinati."""
    args = build_parser().parse_args()
    config_path = Path(args.config)
    _print_startup_summary(args)
    _warn_about_config(config_path)

    receiver = _start_process(
        "receiver",
        [
            sys.executable,
            "-m",
            "edge_receiver.cli",
            "--config",
            str(config_path),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
    )
    runtime_command = [
        sys.executable,
        "-m",
        "edge_runtime.cli",
        "--config",
        str(config_path),
        "--loop",
        "--interval-seconds",
        str(max(1, args.interval_seconds)),
    ]
    if args.append_baseline:
        runtime_command.append("--append-baseline")
    runtime = _start_process("runtime", runtime_command)

    try:
        _watch_processes({"receiver": receiver, "runtime": runtime})
    except KeyboardInterrupt:
        _log("CTRL+C ricevuto: arresto receiver e runtime")
    except RuntimeError as exc:
        _log(f"Errore stack: {exc}")
    finally:
        _terminate_processes([runtime, receiver])


def _print_startup_summary(args: argparse.Namespace) -> None:
    """Mostra in modo chiaro cosa verra' avviato."""
    _log("Avvio stack IoT edge")
    _log(f"Config: {args.config}")
    _log(f"Receiver: http://{args.host}:{args.port}")
    _log(f"Runtime loop: ogni {max(1, args.interval_seconds)} secondi")
    if args.append_baseline:
        _log("Modalita baseline: attiva")
    _log("Premi CTRL+C per fermare tutto")


def _warn_about_config(config_path: Path) -> None:
    """Controlla che il file YAML abiliti le sorgenti attese."""
    try:
        config = load_config(config_path)
    except Exception as exc:
        _log(f"ATTENZIONE: configurazione non leggibile: {exc}")
        return

    if not config.ble.enabled:
        _log(
            "ATTENZIONE: ble.enabled=false. Il receiver partira', ma "
            "edge_runtime non usera' i campioni beacon in latest_window.csv."
        )
    if not config.google_health.enabled:
        _log(
            "ATTENZIONE: google_health.enabled=false. Il runtime non leggera' "
            "i dati Google Health / Pixel Watch 2."
        )
    elif config.google_health.data_delay_minutes > 0:
        _log(
            "ATTENZIONE: google_health.data_delay_minutes="
            f"{config.google_health.data_delay_minutes}. Il Watch verra' letto "
            "su una finestra passata, non sulla finestra corrente da 4 minuti."
        )
    else:
        _log("Google Health senza delay: Watch e BLE sulla stessa finestra da 4 minuti")


def _start_process(name: str, command: list[str]) -> subprocess.Popen:
    """Avvia un processo figlio ereditando stdout/stderr del terminale."""
    _log(f"Avvio {name}: {' '.join(command)}")
    return subprocess.Popen(command)


def _watch_processes(processes: dict[str, subprocess.Popen]) -> None:
    """Resta vivo finche' receiver e runtime sono entrambi attivi."""
    while True:
        for name, process in processes.items():
            return_code = process.poll()
            if return_code is not None:
                raise RuntimeError(f"Processo {name} terminato con codice {return_code}")
        time.sleep(1)


def _terminate_processes(processes: list[subprocess.Popen]) -> None:
    """Ferma ordinatamente i processi ancora attivi."""
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.time() + 8
    for process in processes:
        while process.poll() is None and time.time() < deadline:
            time.sleep(0.2)
        if process.poll() is None:
            process.kill()


def _log(message: str) -> None:
    """Stampa un log compatto e immediatamente visibile nel terminale."""
    print(f"EDGE-STACK: {message}", flush=True)


if __name__ == "__main__":
    main()
