from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from edge_deploy import cli as deploy
from edge_deploy import lan_certificate
from edge_stack import cli as stack


@pytest.mark.parametrize("host", ["192.168.5.227", "iot-pc.local", "pc-medico"])
def test_pc_host(host):
    assert deploy.valid_host(host) == host


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "0.0.0.0", "mqtt", "::1", "224.0.0.1",
                                  "http://192.168.1.10:8080", "host\n[Service]", "999.1.1.1"])
def test_reject_wrong_host(host):
    with pytest.raises(ValueError):
        deploy.valid_host(host)


def test_secret_round_trip_and_private_file(tmp_path, monkeypatch, capsys):
    secret = 'test # space $ and "quote" \\ character'
    path = tmp_path / "service.env"
    deploy.write_private(path, deploy.secret_text(secret))
    monkeypatch.delenv("MQTT_EDGE_PASSWORD", raising=False)
    deploy.load_service_environment(path)
    assert deploy.os.environ["MQTT_EDGE_PASSWORD"] == secret
    assert not capsys.readouterr().out
    assert not list(tmp_path.glob(".iot-setup-*"))


@pytest.mark.parametrize("secret", ["", "one\ntwo", "one\rtwo", "\0", 42])
def test_invalid_secret(secret):
    with pytest.raises(ValueError):
        deploy.secret_text(secret)


def test_unit_is_unprivileged_and_boot_enabled():
    template = (deploy.EDGE_DIR / "deploy/iot-edge.service.in").read_text(encoding="utf-8")
    unit = deploy.render_unit(PurePosixPath("/home/pi/My Project/edge_node"), "pi", template)
    assert "User=pi" in unit
    assert 'WorkingDirectory="/home/pi/My Project/edge_node"' in unit
    assert "Restart=on-failure" in unit
    assert "KillMode=control-group" in unit
    assert "WantedBy=multi-user.target" in unit
    assert "network-online.target" in unit
    assert "EnvironmentFile=" in unit
    assert "--config config/edge.rpi.yml" in unit
    assert "@PYTHON@" not in unit
    assert "sudo" not in unit
    assert "MQTT_EDGE_PASSWORD=" not in unit


def test_unit_rejects_privileged_or_injected_user():
    for user in ("root", "pi\nExecStart=/bin/sh"):
        with pytest.raises(ValueError):
            deploy.render_unit(Path("/home/pi/repo/edge_node"), user, "@USER@")
    assert deploy.unit_quote("/home/pi/100% project") == '"/home/pi/100%% project"'
    with pytest.raises(ValueError):
        deploy.unit_quote("/home/pi/$HOME")


def prepare_stack_test(monkeypatch):
    args = stack.build_parser().parse_args([])
    monkeypatch.setattr(stack, "build_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    monkeypatch.setattr(stack, "_print_startup_summary", lambda args: None)
    monkeypatch.setattr(stack, "_warn_about_config", lambda path: None)
    cleaned = []
    monkeypatch.setattr(stack, "_terminate_processes", lambda processes: cleaned.extend(processes))
    return cleaned


def test_second_spawn_failure_cleans_first_child(monkeypatch):
    cleaned = prepare_stack_test(monkeypatch)
    receiver = object()

    def start(name, command):
        if name == "receiver":
            return receiver
        raise OSError("spawn failed")

    monkeypatch.setattr(stack, "_start_process", start)
    assert stack.main() == 1
    assert cleaned == [receiver]


def test_child_exit_is_failure_for_systemd(monkeypatch):
    cleaned = prepare_stack_test(monkeypatch)
    monkeypatch.setattr(stack, "_start_process", lambda name, command: name)

    def failed(processes):
        raise RuntimeError("child exited with code 0")

    monkeypatch.setattr(stack, "_watch_processes", failed)
    assert stack.main() == 1
    assert cleaned == ["runtime", "receiver"]


def test_requested_stop_cleans_children_and_succeeds(monkeypatch):
    cleaned = prepare_stack_test(monkeypatch)
    old_handler = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(stack, "_start_process", lambda name, command: name)

    def stopped(processes):
        stack._stop_requested(signal.SIGTERM, None)

    monkeypatch.setattr(stack, "_watch_processes", stopped)
    assert stack.main() == 0
    assert cleaned == ["runtime", "receiver"]
    assert signal.getsignal(signal.SIGTERM) == old_handler


def test_stuck_child_is_killed_and_reaped():
    calls = []

    def wait(timeout=None):
        calls.append("wait")
        if timeout is not None:
            raise subprocess.TimeoutExpired("child", timeout)

    child = SimpleNamespace(poll=lambda: None, terminate=lambda: calls.append("terminate"),
                            wait=wait, kill=lambda: calls.append("kill"))
    stack._terminate_processes([child])
    assert calls == ["terminate", "wait", "kill", "wait"]


def test_diagnostics_reads_real_mqtt_summary_without_errors_or_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs/last-cycle.json").write_text(json.dumps({
        "mqtt_publish": {"status": "published", "published": 3, "queue_depth": 0, "errors": ["SECRET"]},
    }), encoding="utf-8")
    ble = tmp_path / "ble.csv"
    ble.write_text("timestamp,room\n", encoding="utf-8")
    config = SimpleNamespace(ble=SimpleNamespace(raw_csv=ble), mqtt=SimpleNamespace(queue_dir=tmp_path / "queue"))
    import edge_ingest.config
    monkeypatch.setattr(edge_ingest.config, "load_config", lambda path: config)
    monkeypatch.setattr(deploy, "preflight", lambda **kwargs: 0)
    assert deploy.diagnose(SimpleNamespace(models=False, network=False)) == 0
    output = capsys.readouterr().out
    assert '"published": 3' in output
    assert "SECRET" not in output


def test_diagnostics_missing_cycle_is_not_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = SimpleNamespace(ble=SimpleNamespace(raw_csv=tmp_path / "ble.csv"), mqtt=SimpleNamespace(queue_dir=tmp_path / "queue"))
    import edge_ingest.config
    monkeypatch.setattr(edge_ingest.config, "load_config", lambda path: config)
    monkeypatch.setattr(deploy, "preflight", lambda **kwargs: 0)
    assert deploy.diagnose(SimpleNamespace(models=False, network=False)) == 1


def test_certificate_existing_files_not_overwritten_without_consent(tmp_path, monkeypatch):
    certs = tmp_path / "certs"
    certs.mkdir()
    old = certs / "server.crt"
    old.write_text("old certificate", encoding="utf-8")
    monkeypatch.setattr(lan_certificate, "openssl_binary", lambda: "openssl")
    monkeypatch.setattr(lan_certificate, "certificate_matches", lambda *args: False)
    with pytest.raises(ValueError, match="--replace"):
        lan_certificate.prepare_certificate(tmp_path, "192.168.1.10")
    assert old.read_text(encoding="utf-8") == "old certificate"


def test_real_certificate_generation_and_reuse(tmp_path):
    try:
        binary = lan_certificate.openssl_binary()
    except ValueError:
        pytest.skip("OpenSSL not installed")
    lan_certificate.prepare_certificate(tmp_path, "192.168.1.10")
    assert lan_certificate.certificate_matches(tmp_path / "certs", "192.168.1.10", binary)
    assert not lan_certificate.certificate_matches(tmp_path / "certs", "192.168.1.11", binary)
    before = (tmp_path / "certs/server.key").read_bytes()
    lan_certificate.prepare_certificate(tmp_path, "192.168.1.10")
    assert (tmp_path / "certs/server.key").read_bytes() == before
    lan_certificate.prepare_certificate(tmp_path, "192.168.1.11", replace=True)
    assert len(list((tmp_path / "cert-backups").glob("*/server.key"))) == 1
    assert lan_certificate.certificate_matches(tmp_path / "certs", "192.168.1.11", binary)


def test_prepare_profile_keeps_local_config_and_reuses_secret(tmp_path, monkeypatch):
    import yaml

    edge = tmp_path / "edge_node"
    (edge / "config").mkdir(parents=True)
    (edge / "deploy").mkdir()
    (edge / "config/edge.example.yml").write_text(
        (deploy.EDGE_DIR / "config/edge.example.yml").read_text(encoding="utf-8"), encoding="utf-8")
    (edge / "deploy/iot-edge.service.in").write_text(
        (deploy.EDGE_DIR / "deploy/iot-edge.service.in").read_text(encoding="utf-8"), encoding="utf-8")
    (edge / "config/edge.yml").write_text("original PC profile", encoding="utf-8")
    ca = tmp_path / "public-ca.crt"
    ca.write_text("public test fixture", encoding="utf-8")
    monkeypatch.chdir(edge)
    monkeypatch.setattr(deploy, "EDGE_DIR", edge)
    proxy = dict(vars(os))
    proxy.update(name="posix", getuid=lambda: 1000)
    monkeypatch.setattr(deploy, "os", SimpleNamespace(**proxy))
    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwuid=lambda uid: SimpleNamespace(pw_name="pi")))
    monkeypatch.setattr(deploy.socket, "create_server", lambda address: nullcontext())
    monkeypatch.setattr(deploy.ssl, "create_default_context", lambda **kwargs: None)
    monkeypatch.setattr(deploy, "preflight", lambda **kwargs: 0)
    prompts = []
    monkeypatch.setattr(deploy.getpass, "getpass", lambda prompt: prompts.append(prompt) or "test-mqtt-secret")
    monkeypatch.delenv("MQTT_EDGE_PASSWORD", raising=False)
    args = SimpleNamespace(pc_host="192.168.1.10", ca_file=str(ca), patient_id="patient-001",
                           mqtt_user="edge_patient_001", rotate_secret=False)
    assert deploy.prepare(args) == 0
    profile = yaml.safe_load((edge / deploy.CONFIG).read_text(encoding="utf-8"))
    assert profile["mqtt"]["host"] == "192.168.1.10"
    assert profile["mqtt"]["password"] == ""
    assert profile["mqtt"]["use_tls"] is True
    assert (edge / "config/edge.yml").read_text(encoding="utf-8") == "original PC profile"
    assert "test-mqtt-secret" not in (edge / "deploy/generated/iot-edge.service").read_text(encoding="utf-8")
    assert deploy.prepare(args) == 0
    assert len(prompts) == 1


def test_setup_refuses_root_or_non_linux():
    if os.name == "posix" and os.getuid() != 0:
        pytest.skip("Guard exercised on Windows/root environments")
    with pytest.raises(ValueError, match="utente ordinario"):
        deploy.prepare(SimpleNamespace())
