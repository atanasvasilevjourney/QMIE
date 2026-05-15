"""Ensure python/ is on sys.path for backtest test imports."""
from __future__ import annotations

import sys
from pathlib import Path

_PY_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))
