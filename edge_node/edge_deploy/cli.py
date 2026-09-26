from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import socket
import ssl
import sys
import threading
import time
import tempfile
import uuid
from pathlib import Path
from urllib.request import urlopen


EDGE_DIR = Path(__file__).resolve().parents[1]
CONFIG = Path("config/edge.rpi.yml")
ENV_FILE = Path("config/edge-service.env")


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"File simbolico non consentito: {path}")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".iot-setup-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        Path(temporary).chmod(0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def secret_text(password: str) -> str:
    if not isinstance(password, str) or not password or any(ord(c) < 32 or ord(c) == 127 for c in password):
        raise ValueError("La password MQTT deve essere non vuota e su una sola riga.")
    return "MQTT_EDGE_PASSWORD=" + json.dumps(password, ensure_ascii=False) + "\n"


def load_service_environment(path: Path = ENV_FILE) -> None:
    # This is our generated one-key file, not a shell script to execute.
    text = path.read_text(encoding="utf-8").strip()
    key, value = text.split("=", 1)
    if key != "MQTT_EDGE_PASSWORD":
        raise ValueError("File ambiente non riconosciuto; rigenerarlo con setup.")
    password = json.loads(value)
    secret_text(password)
    os.environ[key] = password


def valid_host(host: str) -> str:
    import ipaddress

    host = host.strip()
    if host.lower() in {"localhost", "mqtt", "0.0.0.0", "127.0.0.1"}:
        raise ValueError("Usare l'IP LAN o il nome DNS del PC, non localhost/mqtt.")
    try:
        address = ipaddress.ip_address(host)
        if address.version != 4 or address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError("Usare un indirizzo IPv4 LAN unicast del PC.")
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host) or ":" in host:
            raise ValueError("Host PC non valido; non inserire http:// o la porta.") from None
        if re.fullmatch(r"[0-9.]+", host):
            raise ValueError("Indirizzo IPv4 non valido.") from None
    return host


def unit_quote(value: str) -> str:
    if any(c in value for c in "\n\r\0$"):
        raise ValueError("Percorso non supportato dal servizio (newline o $).")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def render_unit(edge: Path, user: str, template: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*\$?", user) or user == "root":
        raise ValueError("Il servizio deve usare un utente Linux ordinario, non root.")
    replacements = {
        "USER": user,
        "EDGE_DIR": unit_quote(str(edge)),
        "ENV_FILE": unit_quote(str(edge / ENV_FILE)),
        "PYTHON": unit_quote(str(edge.parent / ".venv/bin/python")),
        "CONFIG_DIR": unit_quote(str(edge / "config")),
        "DATA_DIR": unit_quote(str(edge / "data")),
        "MODELS_DIR": unit_quote(str(edge / "models")),
        "OUTPUTS_DIR": unit_quote(str(edge / "outputs")),
    }
    for key, value in replacements.items():
        template = template.replace(f"@{key}@", value)
    return template


def prepare(args: argparse.Namespace) -> int:
    import yaml

    if os.name != "posix" or os.getuid() == 0:
        raise ValueError("Eseguire setup sul Raspberry come utente ordinario, senza sudo.")
    if sys.maxsize <= 2**32:
        raise ValueError("Richiesti sistema operativo e Python a 64 bit sul Raspberry.")
    try:
        with socket.create_server(("0.0.0.0", 8000)):
            pass
    except OSError:
        raise ValueError("Porta 8000 occupata: fermare il vecchio receiver prima del setup.") from None
    host = valid_host(args.pc_host)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.patient_id):
        raise ValueError("Identificatore paziente non valido.")
    source = CONFIG if CONFIG.exists() else Path("config/edge.example.yml")
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    old_patient = data["patient"]["id"]
    if CONFIG.exists() and old_patient != args.patient_id:
        raise ValueError("Il nodo e' gia' associato a un altro paziente: migrazione manuale richiesta.")
    ca_source = Path(args.ca_file)
    ssl.create_default_context(cafile=str(ca_source))
    ca_target = Path("config/certs/ca.crt")
    ca_target.parent.mkdir(parents=True, exist_ok=True)
    if ca_source.resolve() != ca_target.resolve():
        shutil.copyfile(ca_source, ca_target)
    ca_target.chmod(0o644)
    if not ENV_FILE.exists() or args.rotate_secret:
        password = getpass.getpass("Password dell'utente MQTT Edge sul broker PC: ")
        write_private(ENV_FILE, secret_text(password))
    load_service_environment()
    ENV_FILE.chmod(0o600)
    data["patient"]["id"] = args.patient_id
    data["ai"]["personal_model"] = f"models/{args.patient_id}.pkl"
    data["mqtt"].update({
        "enabled": True, "host": host, "port": 8883, "use_tls": True,
        "username": args.mqtt_user, "password": "", "password_env": "MQTT_EDGE_PASSWORD",
        "ca_file": str(ca_target),
    })
    # The shipped profile is for patient-001; other patients need explicit broker ACLs.
    data["ble"]["enabled"] = True
    write_private(CONFIG, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    for directory in ("data/raw", "data/processed", "data/state", "outputs", "models"):
        Path(directory).mkdir(parents=True, exist_ok=True)
    import pwd

    user = pwd.getpwuid(os.getuid()).pw_name
    unit = render_unit(EDGE_DIR, user, Path("deploy/iot-edge.service.in").read_text(encoding="utf-8"))
    target = Path("deploy/generated/iot-edge.service")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(unit, encoding="utf-8", newline="\n")
    print("Configurazione RPi preparata; segreti non stampati. Nessun servizio ancora installato.")
    return preflight(check_models=True)


def preflight(*, check_models: bool = False) -> int:
    from edge_ingest.config import load_config

    config = load_config(CONFIG)
    load_service_environment()
    valid_host(config.mqtt.host)
    if not config.mqtt.enabled or not config.mqtt.use_tls or config.mqtt.password:
        raise ValueError("Richiesti MQTT attivo, TLS e password dal file ambiente.")
    ssl.create_default_context(cafile=str(config.mqtt.ca_file))
    errors = 0
    paths = [("modello spaziale", config.ai.generic_spatial_model),
             ("modello wearable", config.ai.generic_wearable_model)]
    for provider in (config.google_health, config.fitbit):
        if provider.enabled:
            for name in ("token_file", "client_file"):
                file = getattr(provider, name)
                try:
                    content = json.loads(file.read_text(encoding="utf-8"))
                    if not isinstance(content, dict) or not content:
                        raise ValueError("Oggetto JSON vuoto")
                    if name == "token_file" and not content.get("refresh_token"):
                        raise ValueError("refresh_token mancante")
                    if name == "client_file" and (not content.get("client_id") or not content.get("client_secret")):
                        raise ValueError("client_id/client_secret mancanti")
                    if os.name == "posix" and file.stat().st_mode & 0o077:
                        print(f"WARN permessi troppo aperti: {file}; usare chmod 600")
                    print(f"OK credenziali presenti: {file} (valori nascosti)")
                except (OSError, ValueError):
                    print(f"ERRORE credenziali mancanti/invalide: {file}; copiare i file OAuth validi")
                    errors += 1
    personal = config.ai.personal_model
    if personal and personal.exists():
        paths.append(("modello personale", personal))
    else:
        print("INFO modello personale assente: baseline automatica, nessun modello fittizio creato")
    for label, file in paths:
        if not file.is_file():
            print(f"ERRORE {label} mancante: {file}")
            errors += 1
        elif check_models:
            try:
                from edge_ai.model import EdgeAnomalyDetector
                from sklearn.exceptions import InconsistentVersionWarning
                import warnings

                with warnings.catch_warnings():
                    warnings.simplefilter("error", InconsistentVersionWarning)
                    model = EdgeAnomalyDetector.load(file)
                if not hasattr(model.pipeline, "predict"):
                    raise ValueError("Pipeline non valida")
                print(f"OK {label} caricabile")
            except Exception as exc:
                print(f"ERRORE {label} non compatibile ({type(exc).__name__}); verificare Python/scikit-learn")
                errors += 1
        else:
            print(f"OK {label} presente")
    print(f"MQTT: {config.mqtt.host}:{config.mqtt.port}; paziente: {config.patient.patient_id}")
    return 1 if errors else 0


def mqtt_probe(config) -> bool:
    import paho.mqtt.client as mqtt

    connected = threading.Event()
    accepted = []
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"edge-check-{uuid.uuid4().hex[:12]}")
    client.username_pw_set(config.username, os.environ[config.password_env])
    client.tls_set(ca_certs=str(config.ca_file), cert_reqs=ssl.CERT_REQUIRED)
    client.connect_timeout = 6

    def on_connect(client, userdata, flags, reason_code, properties):
        accepted.append(not reason_code.is_failure)
        connected.set()

    client.on_connect = on_connect
    try:
        client.connect(config.host, config.port, keepalive=20)
        client.loop_start()
        return connected.wait(8) and bool(accepted and accepted[0])
    finally:
        client.disconnect()
        client.loop_stop()


def diagnose(args: argparse.Namespace) -> int:
    from edge_ingest.config import load_config

    failed = preflight(check_models=args.models)
    config = load_config(CONFIG)
    for label, path, age_limit in (
        ("ultimo ciclo", Path("outputs/last-cycle.json"), 600),
        ("campioni BLE", config.ble.raw_csv, 120),
    ):
        age = time.time() - path.stat().st_mtime if path.exists() else None
        fresh = age is not None and -60 <= age < age_limit
        print(f"{'OK' if fresh else 'WARN'} {label}: " + (f"file aggiornato {age:.0f}s fa" if age is not None else "non ancora presente"))
        failed |= int(not fresh)
    cycle_path = Path("outputs/last-cycle.json")
    if cycle_path.exists():
        try:
            cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
            mqtt = cycle.get("mqtt_publish", {})
            print("Ciclo: " + json.dumps({k: cycle.get(k) for k in
                  ("window_start_local", "window_end_local", "quality_status", "inference")}, ensure_ascii=True))
            print("MQTT ciclo: " + json.dumps({k: mqtt.get(k) for k in
                  ("status", "published", "queued", "queue_depth")}, ensure_ascii=True))
            failed |= int(mqtt.get("status") != "published")
        except (OSError, ValueError):
            print("WARN stato ciclo non leggibile, riprovare al termine della scrittura")
            failed = 1
    queue = config.mqtt.queue_dir
    print(f"Coda locale: {len(list(queue.glob('*.json')))} file")
    if args.network:
        for label, url in (
            ("receiver locale", "http://127.0.0.1:8000/health"),
            ("backend PC", f"http://{config.mqtt.host}:8080/health"),
        ):
            try:
                with urlopen(url, timeout=5) as response:
                    payload = json.load(response)
                if payload.get("status") != "ok":
                    raise ValueError("Stato health non valido")
                print(f"OK {label}")
            except Exception as exc:
                print(f"ERRORE {label}: {type(exc).__name__}; controllare servizio, IP e firewall")
                failed = 1
        try:
            if not mqtt_probe(config.mqtt):
                raise ValueError("CONNACK rifiutato o timeout")
            print("OK MQTT: TLS/nome host e autenticazione verificati (nessun dato pubblicato)")
        except Exception as exc:
            print(f"ERRORE MQTT: {type(exc).__name__}; verificare CA, SAN, password, porta 8883")
            failed = 1
    return int(bool(failed))


def main() -> int:
    parser = argparse.ArgumentParser(description="Setup e diagnostica del Raspberry; nessuna password nei log.")
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("prepare")
    setup.add_argument("--pc-host", required=True)
    setup.add_argument("--ca-file", required=True)
    setup.add_argument("--patient-id", default="patient-001", choices=["patient-001"])
    setup.add_argument("--mqtt-user", default="edge_patient_001")
    setup.add_argument("--rotate-secret", action="store_true")
    check = sub.add_parser("check")
    check.add_argument("--models", action="store_true")
    check.add_argument("--network", action="store_true")
    cert = sub.add_parser("certificate")
    cert.add_argument("--pc-host", required=True)
    cert.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        args.ca_file = str(Path(args.ca_file).resolve())
    os.chdir(EDGE_DIR)
    try:
        if args.command == "prepare":
            return prepare(args)
        if args.command == "certificate":
            from edge_deploy.lan_certificate import prepare_certificate
            prepare_certificate(EDGE_DIR.parent / "cloud/mqtt", valid_host(args.pc_host), replace=args.replace)
            return 0
        return diagnose(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERRORE setup/diagnostica: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
