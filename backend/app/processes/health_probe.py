"""Pure-stdlib file freshness probe for container healthchecks."""

from __future__ import annotations

import json
import os
import time


def main() -> None:
    path = os.getenv("RUN_HEALTH_FILE", "/tmp/run-control-health.json")
    maximum_age = float(os.getenv("RUN_HEALTH_MAX_AGE_SECONDS", "3"))
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        fresh = time.time() - os.stat(path).st_mtime <= maximum_age
    except (OSError, ValueError, TypeError):
        fresh = False
        payload = {}
    raise SystemExit(0 if payload.get("healthy") is True and fresh else 1)


if __name__ == "__main__":
    main()
