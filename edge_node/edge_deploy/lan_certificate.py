from __future__ import annotations

import ipaddress
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def openssl_binary() -> str:
    found = shutil.which("openssl")
    if found:
        return found
    candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/usr/bin/openssl.exe"
    if candidate.is_file():
        return str(candidate)
    raise ValueError("OpenSSL non trovato: installare Git for Windows con OpenSSL oppure OpenSSL nel PATH.")


def run_ssl(binary: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([binary, *args], capture_output=True, text=True, timeout=30)


def host_option(host: str) -> tuple[str, str]:
    try:
        ipaddress.ip_address(host)
        return "-checkip", f"IP:{host}"
    except ValueError:
        return "-checkhost", f"DNS:{host}"


def certificate_matches(directory: Path, host: str, binary: str) -> bool:
    cert, key, ca = (directory / name for name in ("server.crt", "server.key", "ca.crt"))
    if not all(path.is_file() for path in (cert, key, ca)):
        return False
    for option, value in (("-checkhost", "mqtt"), ("-checkhost", "localhost"),
                          ("-checkip", "127.0.0.1"), (host_option(host)[0], host),
                          ("-checkend", "86400")):
        if run_ssl(binary, "x509", "-in", str(cert), "-noout", option, value).returncode:
            return False
    if run_ssl(binary, "verify", "-CAfile", str(ca), str(cert)).returncode:
        return False
    cert_key = run_ssl(binary, "x509", "-in", str(cert), "-pubkey", "-noout")
    private_key = run_ssl(binary, "pkey", "-in", str(key), "-pubout", "-passin", "pass:")
    return not cert_key.returncode and not private_key.returncode and cert_key.stdout == private_key.stdout


def prepare_certificate(mqtt_dir: Path, host: str, *, replace: bool = False) -> None:
    binary = openssl_binary()
    target = mqtt_dir / "certs"
    if certificate_matches(target, host, binary):
        print("OK certificati MQTT gia' validi per PC, localhost e mqtt; nessuna modifica.")
        return
    existing = [target / name for name in ("server.crt", "server.key", "ca.crt") if (target / name).exists()]
    if existing and not replace:
        raise ValueError("Certificati esistenti non adatti alla LAN. Fermare broker/worker e rieseguire con --replace; sara' creata una copia di backup.")
    mqtt_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=mqtt_dir) as temporary:
        work = Path(temporary)
        san = "DNS:localhost,DNS:mqtt,IP:127.0.0.1," + host_option(host)[1]
        result = run_ssl(binary, "req", "-x509", "-newkey", "rsa:3072", "-nodes",
                         "-keyout", str(work / "server.key"), "-out", str(work / "server.crt"),
                         "-days", "365", "-subj", "/CN=IoT-LAN-Broker",
                         "-addext", f"subjectAltName={san}",
                         "-addext", "basicConstraints=critical,CA:TRUE",
                         "-addext", "extendedKeyUsage=serverAuth")
        if result.returncode:
            raise ValueError("Generazione certificato fallita; verificare OpenSSL (richiesto supporto -addext).")
        shutil.copyfile(work / "server.crt", work / "ca.crt")
        if not certificate_matches(work, host, binary):
            raise ValueError("Il certificato generato non supera la verifica; file esistenti lasciati invariati.")
        if existing:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = mqtt_dir / "cert-backups" / stamp
            backup.mkdir(parents=True, mode=0o700)
            for path in existing:
                shutil.copy2(path, backup / path.name)
            print(f"Backup dei certificati precedenti: {backup}")
        target.mkdir(parents=True, exist_ok=True)
        for name in ("server.key", "server.crt", "ca.crt"):
            shutil.copyfile(work / name, target / name)
            (target / name).chmod(0o600 if name.endswith(".key") else 0o644)
    print("OK certificato LAN creato (365 giorni). Riavviare broker/worker e ricopiare solo ca.crt sul Raspberry.")
