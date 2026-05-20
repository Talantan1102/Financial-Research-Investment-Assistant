"""KBBacktestAdapter — backtest 模式下的 KB 检索 wrapper.

spec § 4.5 决策 5 time-travel:KB chunk 必须按 publish_date <= cut_off 过滤。
两种模式:
  - lenient (默认):publish_date is None 保留(兼容历史 chunk)
  - strict:publish_date is None 也丢(确保 100% leak-free,但召回降)

注:adapter 会先放大 k(请求 k*2)以补偿过滤损失,最后返回 k 个。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol


class KBClientProtocol(Protocol):
    """允许任意支持 search 的 KB client 注入."""

    def search(self, query: str, k: int = 10, **kwargs: Any) -> list[Any]: ...


@dataclass
class KBBacktestAdapter:
    """Wrap KB client, 按 publish_date 过滤搜索结果."""

    inner: KBClientProtocol
    cut_off: date
    strict_no_date: bool = False

    def search(self, query: str, k: int = 10, **kwargs: Any) -> list[Any]:
        """搜索 KB, 自动过滤 publish_date > cut_off 的 chunk.

        先放大 k(请求 k*2)以补偿过滤可能造成的召回损失,然后过滤,最后返回 k 个。

        Args:
            query: 检索 query。
            k: 期望返回数量(过滤后)。
            kwargs: 透传到 inner.search。

        Returns:
            过滤后的 chunk 列表, 长度 <= k。
        """
        raw = self.inner.search(query=query, k=k * 2, **kwargs)
        filtered = [c for c in raw if self._keep(c)]
        return filtered[:k]

    def _keep(self, chunk: Any) -> bool:
        """根据 publish_date + 模式决定 chunk 是否保留."""
        pd: date | None = getattr(chunk, "publish_date", None)
        if pd is None:
            return not self.strict_no_date
        return bool(pd <= self.cut_off)
