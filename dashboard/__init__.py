# dashboard/__init__.py
"""Harness Board · 独立轻量 web 工具,8 维 LLM Harness Capability Matrix。"""

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).parent.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
