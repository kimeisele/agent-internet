from __future__ import annotations

import sys
from pathlib import Path


_repo_root = Path(__file__).resolve().parent.parent
_steward_root = _repo_root.parent / "steward-protocol"

if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

if _steward_root.exists() and str(_steward_root) not in sys.path:
    sys.path.insert(0, str(_steward_root))
