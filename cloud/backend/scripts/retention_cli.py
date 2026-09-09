from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.retention import retention_summary, run_full_purge


def main() -> None:
    """Mostra lo stato della retention o esegue il purge (comando manuale D31)."""
    parser = argparse.ArgumentParser(description="Database retention (D31).")
    parser.add_argument("command", choices=["status", "purge"])
    args = parser.parse_args()
    if get_settings().environment == "production" and args.command == "purge":
        raise SystemExit("Il purge e' bloccato in production: usare la procedura di archiviazione.")
    with SessionLocal() as db:
        if args.command == "status":
            print(retention_summary(db))
        else:
            print(run_full_purge(db))


if __name__ == "__main__":
    main()