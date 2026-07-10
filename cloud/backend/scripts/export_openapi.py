from __future__ import annotations

import json
from pathlib import Path

from app.main import app


def main() -> None:
    """Export the FastAPI OpenAPI document used by frontend/app contracts."""
    project_root = Path(__file__).resolve().parents[3]
    output_path = project_root / "Documenti" / "contracts" / "openapi.json"
    output_path.write_text(
        json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI exported to {output_path}")


if __name__ == "__main__":
    main()
