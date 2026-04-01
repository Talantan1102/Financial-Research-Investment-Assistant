"""
Ground truth cache for verifiable rewards.

Reduces API cost and latency by caching Tushare/API responses.
"""

import json
import hashlib
from pathlib import Path
from typing import Any, Optional, Dict, Callable, List
from datetime import datetime, timedelta


class GroundTruthCache:
    """Ground Truth cache manager with memory + disk caching."""

    def __init__(self, cache_dir: str = ".cache/ground_truth"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: Dict[str, Dict[str, Any]] = {}

        # TTL in minutes per field type
        self.ttl_config = {
            "current_price": 60,
            "pe_ratio": 1440,
            "pb_ratio": 1440,
            "roe": 10080,
            "default": 60,
        }

    def _get_cache_key(self, stock_code: str, field: str) -> str:
        content = f"{stock_code}_{field}_{datetime.now().strftime('%Y%m%d')}"
        return hashlib.md5(content.encode()).hexdigest()

    def _get_cache_file(self, cache_key: str) -> Path:
        return self.cache_dir / f"{cache_key}.json"

    def get(self, stock_code: str, field: str) -> Optional[Any]:
        cache_key = self._get_cache_key(stock_code, field)

        # Memory cache
        if cache_key in self._memory_cache:
            entry = self._memory_cache[cache_key]
            if not self._is_expired(entry, field):
                return entry["value"]

        # Disk cache
        cache_file = self._get_cache_file(cache_key)
        if cache_file.exists():
            try:
                entry = json.loads(cache_file.read_text(encoding="utf-8"))
                if not self._is_expired(entry, field):
                    self._memory_cache[cache_key] = entry
                    return entry["value"]
            except (json.JSONDecodeError, KeyError):
                pass

        return None

    def set(self, stock_code: str, field: str, value: Any) -> None:
        cache_key = self._get_cache_key(stock_code, field)
        entry = {
            "stock_code": stock_code,
            "field": field,
            "value": value,
            "cached_at": datetime.now().isoformat(),
        }
        self._memory_cache[cache_key] = entry
        cache_file = self._get_cache_file(cache_key)
        try:
            cache_file.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _is_expired(self, entry: Dict[str, Any], field: str) -> bool:
        cached_at_str = entry.get("cached_at")
        if not cached_at_str:
            return True
        try:
            cached_at = datetime.fromisoformat(cached_at_str)
        except ValueError:
            return True
        ttl_minutes = self.ttl_config.get(field, self.ttl_config["default"])
        expired_at = cached_at + timedelta(minutes=ttl_minutes)
        return datetime.now() > expired_at

    def batch_cache(
        self,
        stock_codes: List[str],
        fields: List[str],
        fetch_func: Callable[[List[tuple[str, str]]], List[Any]],
    ) -> None:
        """Batch fetch and cache missing entries."""
        missing: List[tuple[str, str]] = []
        for code in stock_codes:
            for field in fields:
                if self.get(code, field) is None:
                    missing.append((code, field))

        if missing:
            results = fetch_func(missing)
            for (code, field), value in zip(missing, results):
                self.set(code, field, value)
