"""技能 L1 元数据清单 → 稳定前缀文本(spec § 3.4)。

清单生成抽成独立函数,是为写死**两层化逃生口**:当前(7 个技能)全部 L1
元数据常驻稳定前缀;当技能数 ≥15 或离线评测显示选错率抬头时,切两层化——
高频技能常驻 + 长尾技能改 search_tools 按需检索(与工具渐进披露同构)。

把清单产出收口到一个函数,意味着切两层只改这里(常驻名单 + 长尾走检索),
context.py 的稳定前缀拼接、ContextDeps.skill_listing 注入点都不动。
"""
from __future__ import annotations

from typing import Protocol

from app.skills.types import SkillManifest


class _SupportsLoadL1(Protocol):
    """build_skill_listing 只依赖 loader.load_l1() —— 最小接口,便于 Fake 替身。"""

    def load_l1(self) -> list[SkillManifest]: ...


_HEADER = "## 可用技能"


def build_skill_listing(loader: _SupportsLoadL1) -> str:
    """遍历 loader 的 L1 元数据,产出技能清单文本(进稳定前缀区)。

    格式(每行第三人称触发判据,技能间边界互斥):
        ## 可用技能
        - {name}: {description}

    空清单仍产出标题行 —— 稳定前缀逐字节恒定是 KV-cache 折扣的前提,
    清单为空(技能目录还没建)时也给固定标题,不让前缀因 0/1 技能而抖动。
    """
    manifests = loader.load_l1()
    lines = [_HEADER]
    for m in manifests:
        lines.append(f"- {m.name}: {m.description}")
    return "\n".join(lines)


__all__ = ["build_skill_listing"]
