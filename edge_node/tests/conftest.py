from __future__ import annotations

import sys
from pathlib import Path


EDGE_NODE_DIR = Path(__file__).resolve().parents[1]

if str(EDGE_NODE_DIR) not in sys.path:
    sys.path.insert(0, str(EDGE_NODE_DIR))
