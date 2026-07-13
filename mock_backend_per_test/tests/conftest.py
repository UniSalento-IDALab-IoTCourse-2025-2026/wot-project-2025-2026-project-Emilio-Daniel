from __future__ import annotations

import sys
from pathlib import Path


MOCK_BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(MOCK_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(MOCK_BACKEND_DIR))
