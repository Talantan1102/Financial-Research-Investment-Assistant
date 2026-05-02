"""__main__ 薄壳:`python -m app.scripts.ingest_kb ...`"""

from __future__ import annotations

import sys

from app.kb.ingest.cli import main

if __name__ == "__main__":
    sys.exit(main())
