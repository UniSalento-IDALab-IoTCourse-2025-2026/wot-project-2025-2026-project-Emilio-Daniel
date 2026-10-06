from __future__ import annotations

import argparse
import json

from app.db.session import SessionLocal
from app.services.patient_reset import (
    patient_data_summary,
    patient_telemetry_summary,
    reset_patient_data,
    reset_patient_telemetry,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or reset historical data for one patient.",
    )
    parser.add_argument("--patient-id", required=True)
    parser.add_argument("--include-audit", action="store_true")
    parser.add_argument(
        "--telemetry-only",
        action="store_true",
        help="Delete Edge telemetry and derived alerts, preserving tasks and messages.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--confirm",
        default="",
        help="Must exactly match --patient-id when --execute is used.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.execute and args.confirm != args.patient_id:
        raise SystemExit("Reset refused: --confirm must exactly match --patient-id.")

    with SessionLocal() as db:
        try:
            if args.execute:
                if args.telemetry_only:
                    payload = reset_patient_telemetry(db, args.patient_id)
                else:
                    payload = reset_patient_data(
                        db,
                        args.patient_id,
                        include_audit=args.include_audit,
                    )
                db.commit()
            else:
                if args.telemetry_only:
                    payload = patient_telemetry_summary(db, args.patient_id)
                else:
                    payload = patient_data_summary(
                        db,
                        args.patient_id,
                        include_audit=args.include_audit,
                    )
                payload["status"] = "dry_run"
        except Exception:
            db.rollback()
            raise

    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
