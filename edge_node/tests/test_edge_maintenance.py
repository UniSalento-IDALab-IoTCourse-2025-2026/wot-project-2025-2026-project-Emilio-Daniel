from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from edge_baseline.cli import build_parser as baseline_parser
from edge_maintenance.cli import archive_and_reset


def config_for(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        patient=SimpleNamespace(patient_id="patient-001"),
        paths=SimpleNamespace(
            baseline_csv=Path("data/processed/baseline.csv"),
            latest_window_csv=Path("data/processed/latest_window.csv"),
        ),
        ai=SimpleNamespace(personal_model=Path("models/patient-001.pkl")),
        ble=SimpleNamespace(raw_csv=Path("data/raw/ble_samples.csv")),
        google_health=SimpleNamespace(raw_csv=Path("data/raw/google_health_samples.csv")),
        shelly=SimpleNamespace(raw_csv=Path("data/raw/shelly_samples.csv")),
        window=SimpleNamespace(minutes=4, timezone="Europe/Rome"),
    )


def write(path: Path, content: str = "old") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_reset_archives_generated_data_and_preserves_generic_models(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = config_for(tmp_path)
    write(Path("data/processed/baseline.csv"), "patient_id\npatient-001\n")
    write(Path("data/processed/latest_window.csv"))
    write(Path("data/raw/ble_samples.csv"))
    write(Path("data/state/patient-001-debounce.json"))
    write(Path("data/state/mqtt_queue/queued.json"))
    write(Path("outputs/patient-001-decision.json"))
    write(Path("models/patient-001.pkl"))
    write(Path("models/generic_spatial.pkl"), "generic")

    payload = archive_and_reset(config, archive_root=Path("data/archive"), days=7)

    assert payload["status"] == "reset_completed"
    archive = tmp_path / payload["archive"]
    assert (archive / "data/processed/baseline.csv").exists()
    assert (archive / "data/state/mqtt_queue/queued.json").exists()
    assert (archive / "models/patient-001.pkl").exists()
    assert (archive / "reset-manifest.json").exists()
    assert not Path("outputs/patient-001-decision.json").exists()
    assert not Path("models/patient-001.pkl").exists()
    assert Path("models/generic_spatial.pkl").read_text(encoding="utf-8") == "generic"
    assert Path("data/state/baseline-session.json").exists()


def test_provisional_training_requires_explicit_flags() -> None:
    args = baseline_parser().parse_args(
        ["train", "--allow-early", "--provisional"]
    )
    assert args.allow_early is True
    assert args.provisional is True
