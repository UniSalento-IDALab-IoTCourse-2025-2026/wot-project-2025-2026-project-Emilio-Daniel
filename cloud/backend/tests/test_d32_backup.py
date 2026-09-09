from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.backup import (
    KEEP_BACKUPS,
    backup_database,
    restore_to_temp,
    verify_backup,
)


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS patients (id INTEGER PRIMARY KEY, patient_id TEXT);
            CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT);
            CREATE TABLE IF NOT EXISTS feature_windows (id INTEGER PRIMARY KEY, message_id TEXT);
            CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, message_id TEXT);
            CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, message_id TEXT);
            CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, task_id TEXT);
            INSERT INTO patients (patient_id) VALUES ('patient-001');
            INSERT INTO users (email) VALUES ('demo@example.invalid');
            INSERT INTO feature_windows (message_id) VALUES ('fw-0001');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_backup_creates_file_and_verifies(tmp_path: Path) -> None:
    db_file = tmp_path / "source.sqlite"
    _make_db(db_file)
    result = backup_database(f"sqlite:///{db_file}", target_dir=tmp_path / "backups")
    assert result["database_engine"] == "sqlite"
    backup_path = tmp_path / "backups" / result["created_backup"]
    assert backup_path.exists()
    assert helper_verify(backup_path)


def helper_verify(path: Path) -> bool:
    conn = sqlite3.connect(str(path))
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    return integrity == "ok"


def test_backup_rotation_keeps_last_seven(tmp_path: Path) -> None:
    db_file = tmp_path / "source.sqlite"
    _make_db(db_file)
    target = tmp_path / "rot"
    for _ in range(10):
        backup_database(f"sqlite:///{db_file}", target_dir=target)
    backups = sorted(target.glob("backup_*.sqlite"))
    assert len(backups) == KEEP_BACKUPS


def test_verify_backup_counts_tables(tmp_path: Path) -> None:
    db_file = tmp_path / "source.sqlite"
    _make_db(db_file)
    result = backup_database(f"sqlite:///{db_file}", target_dir=tmp_path / "backups")
    verified = verify_backup(Path(result["backup_path"]))
    assert verified["integrity"] == "ok"
    assert verified["tables"]["patients"] == 1
    assert verified["tables"]["feature_windows"] == 1


def test_restore_to_temp_keeps_production_untouched(tmp_path: Path) -> None:
    db_file = tmp_path / "source.sqlite"
    _make_db(db_file)
    source_conn = sqlite3.connect(str(db_file))
    try:
        before = source_conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    finally:
        source_conn.close()

    result = backup_database(f"sqlite:///{db_file}", target_dir=tmp_path / "backups")
    restored = restore_to_temp(
        f"sqlite:///{db_file}",
        result["backup_path"],
        target_dir=tmp_path / "restore_tests",
    )
    assert restored["format"] == "sqlite"
    assert restored["integrity"] == "ok"
    assert restored["production_touched"] is False
    assert restored["tables"]["patients"] == before
    assert restored["tables"]["alerts"] == 0

    source_conn = sqlite3.connect(str(db_file))
    try:
        after = source_conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    finally:
        source_conn.close()
    assert after == before


def test_backup_from_sqlite_file_roundtrip(tmp_path: Path) -> None:
    db_file = tmp_path / "source.sqlite"
    _make_db(db_file)
    result = backup_database(f"sqlite:///{db_file}", target_dir=tmp_path / "backups")
    restored = restore_to_temp(
        f"sqlite:///{db_file}",
        result["backup_path"],
        target_dir=tmp_path / "restore_tests",
    )
    temp_db = tmp_path / "restore_tests" / restored["temporary_database"]
    conn = sqlite3.connect(str(temp_db))
    try:
        emails = conn.execute("SELECT email FROM users").fetchall()
    finally:
        conn.close()
    assert emails == [("demo@example.invalid",)]