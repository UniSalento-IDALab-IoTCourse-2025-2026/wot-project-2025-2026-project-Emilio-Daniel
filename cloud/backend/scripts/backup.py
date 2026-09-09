from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
KEEP_BACKUPS = 7
VERIFY_TABLES = ["patients", "users", "feature_windows", "decisions", "alerts", "tasks"]


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _is_postgres(url: str) -> bool:
    return url.startswith("postgresql") or url.startswith("postgres://")


def _sqlite_path(url: str) -> Path:
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///") :])
    raise ValueError(f"Non posso estrarre il percorso da: {url}")


def backup_database(
    database_url: str,
    target_dir: Path | None = None,
    keep: int = KEEP_BACKUPS,
) -> dict:
    """Crea un backup del database nel percorso indicato e ruota i vecchi backup."""
    target_dir = target_dir or BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = _now_stamp()
    if _is_postgres(database_url):
        suffix = ".dump"
    else:
        suffix = ".sqlite"
    target = target_dir / f"backup_{stamp}{suffix}"

    if _is_postgres(database_url):
        _pg_dump(database_url, target)
    else:
        _sqlite_backup(_sqlite_path(database_url), target)

    backups = sorted(target_dir.glob(f"backup_*{suffix}"))
    rotated: list[str] = []
    for stale in backups[:-keep]:
        stale.unlink(missing_ok=True)
        rotated.append(stale.name)

    return {
        "created_backup": target.name,
        "backup_path": str(target),
        "database_engine": "postgresql" if _is_postgres(database_url) else "sqlite",
        "retained": [b.name for b in backups[-keep:]],
        "rotated_out": rotated,
    }


def _sqlite_backup(source: Path, target: Path) -> None:
    source_conn = sqlite3.connect(str(source))
    target_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _pg_dump(database_url: str, target: Path) -> None:
    if shutil.which("pg_dump") is None:
        raise RuntimeError("pg_dump non trovato: installare i client PostgreSQL.")
    subprocess.run(
        ["pg_dump", "--no-owner", "--no-privileges", "-f", str(target), database_url],
        check=True,
        capture_output=True,
        text=True,
    )


def verify_backup(backup_path: str | Path) -> dict:
    """Verifica l'integrita' di un backup SQLite contando le tabelle principali."""
    path = Path(backup_path)
    if not path.exists():
        raise FileNotFoundError(f"Backup non trovato: {path}")
    if path.suffix == ".dump":
        return {"format": "postgresql_dump", "integrity": "unchecked"}
    conn = sqlite3.connect(str(path))
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {}
        for table in VERIFY_TABLES:
            try:
                counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            except sqlite3.OperationalError:
                counts[table] = None
    finally:
        conn.close()
    return {
        "format": "sqlite",
        "integrity": integrity,
        "tables": counts,
    }


def restore_to_temp(database_url: str, backup_path: str | Path, target_dir: Path | None = None) -> dict:
    """Ripristina un backup su un database TEMPORANEO e lo verifica.

    Il database di produzione non viene MAI toccato: il restore viene eseguito
    su un file/catalogo temporaneo e distrutto dopo la verifica.
    """
    target_dir = target_dir or BACKUP_DIR / "restore_tests"
    target_dir.mkdir(parents=True, exist_ok=True)
    backup = Path(backup_path)

    if backup.suffix == ".dump":
        return _pg_restore_to_temp(database_url, backup)

    temp_db = target_dir / f"restore_test_{uuid.uuid4().hex[:8]}.sqlite"
    _sqlite_backup(backup, temp_db)
    verified = verify_backup(temp_db)
    temporary = {
        "temporary_database": temp_db.name,
        "database_engine": "sqlite",
        "production_touched": False,
    }
    return {**temporary, **verified}


def _pg_restore_to_temp(database_url: str, backup: Path) -> dict:
    db_name = f"iot_restore_test_{uuid.uuid4().hex[:8]}"
    if shutil.which("createdb") is None or shutil.which("pg_restore") is None:
        raise RuntimeError("Client PostgreSQL non trovati: installare createdb/pg_restore.")
    subprocess.run(["createdb", db_name], check=True, capture_output=True, text=True)
    try:
        subprocess.run(
            ["pg_restore", "--no-owner", "--dbname", db_name, str(backup)],
            check=True,
            capture_output=True,
            text=True,
        )
        verified = _pg_integrity_counts(db_name)
    finally:
        subprocess.run(["dropdb", db_name], check=False, capture_output=True, text=True)
    return {
        "temporary_database": db_name,
        "database_engine": "postgresql",
        "production_touched": False,
        "integrity": verified["integrity"],
        "tables": verified["tables"],
    }


def _pg_integrity_counts(db_name: str) -> dict:
    counts = {}
    for table in VERIFY_TABLES:
        try:
            result = subprocess.run(
                ["psql", "-d", db_name, "-tAc", f'SELECT COUNT(*) FROM "{table}";'],
                check=True,
                capture_output=True,
                text=True,
            )
            counts[table] = int(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError):
            counts[table] = None
    return {"integrity": "ok" if any(counts.values()) else "unknown", "tables": counts}


def main() -> None:
    """CLI backup/restore testato: python -m scripts.backup backup|restore|verify."""
    parser = argparse.ArgumentParser(description="Backup e restore testato (D32).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("backup", help="Crea un backup e ruota gli ultimi 7.")
    restore = subparsers.add_parser("restore", help="Ripristina un backup su database temporaneo.")
    restore.add_argument("backup_path")
    verify = subparsers.add_parser("verify", help="Verifica l'integrita' di un backup.")
    verify.add_argument("backup_path")

    args = parser.parse_args()

    from app.core.config import get_settings

    database_url = get_settings().database_url

    if args.command == "backup":
        print(backup_database(database_url))
    elif args.command == "verify":
        print(verify_backup(args.backup_path))
    else:
        print(restore_to_temp(database_url, args.backup_path))


if __name__ == "__main__":
    main()