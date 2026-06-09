# 长期记忆对话流评估体系 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 spec(`docs/superpowers/specs/2026-06-04-memory-eval-rebuild-design.md`)落地长期记忆评估体系:多 session 对话脚本喂真实写管线 + 双层断言(逐 session 查库 + 最终提问评回答),输出能力维度 × 难度档分数表。

**Architecture:** 新体系独立于旧 eval,落 `backend/eval/memory_dialogue/`。执行流分两阶段:写阶段把脚本里的每个 session 以可控时间戳写入 episode 表、触发真实批量抽取管线、逐 session 跑数据库确定性断言;读阶段对每个提问走真实检索+生成,叠加字符串硬校验、LLM 裁判、不变量开关三层判分。真实依赖(抽取/检索/裁判)全部走依赖注入,测试用假实现,CLI 接真实现——沿用旧 eval 的 wiring 模式与差分测试的逐 session 断言模式。

**Tech Stack:** Python dataclasses + PyYAML(脚本加载,风格对齐 `dashboard/derive/report.py` 的 fail-loud)、SQLAlchemy(数据库断言查真 PG)、既有 `HierarchicalMemory` / `PathBRunner` / `LLMService`(真实管线)、pytest(真 PG fixture 复用 `backend/tests/integration/memory/conftest.py`)。

**运行环境(关键):** 后端测试一律走 WSL fria-venv,不用仓库 Windows `.venv`。标准命令模板:

```bash
wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && POSTGRES_PASSWORD=postgres123 POSTGRES_USER=postgres POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 JWT_SECRET_KEY=test-jwt LLM_MODE=mock /home/administrator/fria-venv/bin/python3 -m pytest <测试路径> -q"
```

pytest 退出码 0 = 全过(warnings 可能冲掉 summary 行,看退出码最可靠)。

**写作纪律(用户明确要求):** 本计划与所有产出物禁用自创字母数字代号。脚本族叫全名(观点演化族),难度档叫直球/自然难/对抗,脚本用英文 slug 做机器标识 + 中文 title 做人读名。

---

## 文件结构

```
backend/eval/memory_dialogue/
├── __init__.py
├── script_schema.py        # 脚本数据类 + yaml 加载器(fail-loud)
├── db_assertions.py        # 数据库断言引擎(确定性,零 LLM)
├── write_phase.py          # 写阶段:episode 入库 + 触发抽取 + 逐 session 断言
├── read_phase.py           # 读阶段:检索 + 生成 + 硬校验 + 裁判 + 不变量开关
├── scoring.py              # 维度 × 难度档分数表聚合
├── live_deps.py            # 真实依赖 wiring(CLI 用;测试不碰)
├── run_eval.py             # CLI 入口
└── scripts/
    └── viewpoint-baijiu.yaml   # 首段脚本《白酒观点演化》(格式范本)
    └── ...(其余 27 段,任务八逐批合写)

backend/tests/unit/eval_memory_dialogue/
├── __init__.py
├── test_script_schema.py
├── test_read_phase.py
└── test_scoring.py

backend/tests/integration/eval_memory_dialogue/
├── __init__.py
├── conftest.py             # 转发既有 pg_memory_* fixture
├── test_db_assertions.py
└── test_write_phase.py
```

职责边界:`script_schema` 只管"yaml → 类型化对象";`db_assertions` 只管"断言描述 + PG 现状 → 红绿";`write_phase`/`read_phase` 只管编排,不自带任何真实依赖;`live_deps` 是唯一 import 真实管线的地方。

---

### 任务一:脚本 schema 与加载器

**Files:**
- Create: `backend/eval/memory_dialogue/__init__.py`(空)
- Create: `backend/eval/memory_dialogue/script_schema.py`
- Create: `backend/tests/unit/eval_memory_dialogue/__init__.py`(空)
- Test: `backend/tests/unit/eval_memory_dialogue/test_script_schema.py`

- [ ] **Step 1: 写失败测试**

```python
"""脚本 schema 加载器测试:合法脚本全字段类型化,非法脚本 fail loud。"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.memory_dialogue.script_schema import load_script

FIXTURE = Path(__file__).parent / "fixture_minimal_script.yaml"


def _write_minimal(tmp_path: Path) -> Path:
    p = tmp_path / "s.yaml"
    p.write_text(
        """
script_id: viewpoint-minimal
title: "最小观点脚本"
family: 观点演化族
substrate: 观点演化
sessions:
  - n: 1
    date: 2025-01-06
    length: 中
    turns:
      - u: "白酒我研究完了,结论是看多,逻辑是提价权"
      - a: "(回应)"
  - n: 2
    date: 2025-02-03
    length: 短
    turns:
      - u: "美联储议息怎么看"
      - a: "(简要分析)"
db_assertions:
  - after: 1
    assert:
      - {type: fact_active, rel_type: HOLDS_VIEW, target_label: 白酒, value_contains: ["看多"]}
probes:
  - tier: 直球
    dimension: 知识更新
    q: "我对白酒什么看法?"
    expect_contain: ["看多"]
    expect_not: []
    judge_rubric: "答案应包含看多观点与提价权逻辑"
""",
        encoding="utf-8",
    )
    return p


def test_load_minimal_script(tmp_path: Path) -> None:
    s = load_script(_write_minimal(tmp_path))
    assert s.script_id == "viewpoint-minimal"
    assert s.family == "观点演化族"
    assert len(s.sessions) == 2
    assert s.sessions[0].date.isoformat() == "2025-01-06"
    assert s.sessions[0].turns[0].role == "u"
    assert s.db_assertions[0].after_session == 1
    assert s.db_assertions[0].checks[0].type == "fact_active"
    assert s.probes[0].tier == "直球"
    assert s.probes[0].dimension == "知识更新"
    assert s.probes[0].swap_order_invariant is False  # 默认关
    assert s.probes[0].answerable is True  # 默认可答


def test_missing_required_field_fails_loud(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("script_id: x\ntitle: t\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sessions"):
        load_script(p)


def test_invalid_tier_fails_loud(tmp_path: Path) -> None:
    good = _write_minimal(tmp_path).read_text(encoding="utf-8")
    p = tmp_path / "bad_tier.yaml"
    p.write_text(good.replace("tier: 直球", "tier: 入门"), encoding="utf-8")
    with pytest.raises(ValueError, match="tier"):
        load_script(p)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && /home/administrator/fria-venv/bin/python3 -m pytest tests/unit/eval_memory_dialogue/test_script_schema.py -q"
```
Expected: FAIL,`ModuleNotFoundError: No module named 'eval.memory_dialogue'`

- [ ] **Step 3: 实现 script_schema.py**

```python
"""对话流评估脚本 — yaml 加载 + 校验 + 类型化。

设计与 dashboard/derive/report.py 一脉相承:必填缺失即 fail loud,
全部冻结 dataclass。脚本是评估的数据 SSOT,本模块只读不写。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

VALID_TIERS = ("直球", "自然难", "对抗")
VALID_LENGTHS = ("短", "中", "长")
VALID_DIMENSIONS = (
    "知识更新", "单跳召回", "多跳推理", "时间推理", "克制弃答", "偏好一致", "持仓仲裁",
)


def _req(value: object, ctx: str) -> object:
    if value is None or value == "" or value == []:
        raise ValueError(f"script yaml 缺失必填字段: {ctx}")
    return value


@dataclass(frozen=True)
class Turn:
    role: str  # "u" 用户 / "a" 助手
    text: str


@dataclass(frozen=True)
class ScriptSession:
    n: int
    date: date
    length: str  # 短/中/长
    turns: tuple[Turn, ...]


@dataclass(frozen=True)
class DbCheck:
    """单条数据库断言描述。type 决定 params 里要什么键,由断言引擎解释。"""

    type: str
    params: dict[str, object]


@dataclass(frozen=True)
class DbAssertionGroup:
    after_session: int
    checks: tuple[DbCheck, ...]


@dataclass(frozen=True)
class Probe:
    tier: str
    dimension: str
    q: str
    expect_contain: tuple[str, ...]
    expect_not: tuple[str, ...]
    judge_rubric: str
    swap_order_invariant: bool = False
    answerable: bool = True  # False = 弃答题(正确行为是指出无法回答)


@dataclass(frozen=True)
class Script:
    script_id: str
    title: str
    family: str
    substrate: str
    sessions: tuple[ScriptSession, ...]
    db_assertions: tuple[DbAssertionGroup, ...]
    probes: tuple[Probe, ...]


def _parse_turns(raw: object, ctx: str) -> tuple[Turn, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"script yaml: {ctx}.turns 必须是非空 list")
    out: list[Turn] = []
    for i, t in enumerate(raw):
        if not isinstance(t, dict) or len(t) != 1:
            raise ValueError(f"script yaml: {ctx}.turns[{i}] 必须是单键 mapping(u: / a:)")
        role, text = next(iter(t.items()))
        if role not in ("u", "a"):
            raise ValueError(f"script yaml: {ctx}.turns[{i}] 角色必须是 u 或 a,实得 {role}")
        out.append(Turn(role=str(role), text=str(_req(text, f"{ctx}.turns[{i}]"))))
    return tuple(out)


def _parse_sessions(raw: object) -> tuple[ScriptSession, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("script yaml: sessions 必须是非空 list")
    out: list[ScriptSession] = []
    for i, s in enumerate(raw):
        ctx = f"sessions[{i}]"
        if not isinstance(s, dict):
            raise ValueError(f"script yaml: {ctx} 必须是 mapping")
        length = str(_req(s.get("length"), f"{ctx}.length"))
        if length not in VALID_LENGTHS:
            raise ValueError(f"script yaml: {ctx}.length 必须是 {VALID_LENGTHS},实得 {length}")
        d = s.get("date")
        if not isinstance(d, date):
            raise ValueError(f"script yaml: {ctx}.date 必须是 ISO 日期")
        out.append(
            ScriptSession(
                n=int(_req(s.get("n"), f"{ctx}.n")),  # type: ignore[arg-type]
                date=d,
                length=length,
                turns=_parse_turns(s.get("turns"), ctx),
            )
        )
    return tuple(out)


def _parse_db_assertions(raw: object) -> tuple[DbAssertionGroup, ...]:
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ValueError("script yaml: db_assertions 必须是 list")
    out: list[DbAssertionGroup] = []
    for i, g in enumerate(raw):
        ctx = f"db_assertions[{i}]"
        if not isinstance(g, dict):
            raise ValueError(f"script yaml: {ctx} 必须是 mapping")
        checks_raw = g.get("assert")
        if not isinstance(checks_raw, list) or not checks_raw:
            raise ValueError(f"script yaml: {ctx}.assert 必须是非空 list")
        checks: list[DbCheck] = []
        for j, c in enumerate(checks_raw):
            if not isinstance(c, dict):
                raise ValueError(f"script yaml: {ctx}.assert[{j}] 必须是 mapping")
            ctype = str(_req(c.get("type"), f"{ctx}.assert[{j}].type"))
            params = {k: v for k, v in c.items() if k != "type"}
            checks.append(DbCheck(type=ctype, params=params))
        out.append(
            DbAssertionGroup(
                after_session=int(_req(g.get("after"), f"{ctx}.after")),  # type: ignore[arg-type]
                checks=tuple(checks),
            )
        )
    return tuple(out)


def _parse_probes(raw: object) -> tuple[Probe, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("script yaml: probes 必须是非空 list")
    out: list[Probe] = []
    for i, p in enumerate(raw):
        ctx = f"probes[{i}]"
        if not isinstance(p, dict):
            raise ValueError(f"script yaml: {ctx} 必须是 mapping")
        tier = str(_req(p.get("tier"), f"{ctx}.tier"))
        if tier not in VALID_TIERS:
            raise ValueError(f"script yaml: {ctx}.tier 必须是 {VALID_TIERS},实得 {tier}")
        dimension = str(_req(p.get("dimension"), f"{ctx}.dimension"))
        if dimension not in VALID_DIMENSIONS:
            raise ValueError(f"script yaml: {ctx}.dimension 必须是 {VALID_DIMENSIONS},实得 {dimension}")
        out.append(
            Probe(
                tier=tier,
                dimension=dimension,
                q=str(_req(p.get("q"), f"{ctx}.q")),
                expect_contain=tuple(str(x) for x in (p.get("expect_contain") or [])),
                expect_not=tuple(str(x) for x in (p.get("expect_not") or [])),
                judge_rubric=str(_req(p.get("judge_rubric"), f"{ctx}.judge_rubric")),
                swap_order_invariant=bool(p.get("swap_order_invariant", False)),
                answerable=bool(p.get("answerable", True)),
            )
        )
    return tuple(out)


def load_script(path: Path) -> Script:
    """加载 + 校验脚本 yaml → 类型化 Script。非法即抛 ValueError 带上下文。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"script yaml 顶层必须是 mapping,实得 {type(data).__name__}")
    return Script(
        script_id=str(_req(data.get("script_id"), "script_id")),
        title=str(_req(data.get("title"), "title")),
        family=str(_req(data.get("family"), "family")),
        substrate=str(_req(data.get("substrate"), "substrate")),
        sessions=_parse_sessions(data.get("sessions")),
        db_assertions=_parse_db_assertions(data.get("db_assertions")),
        probes=_parse_probes(data.get("probes")),
    )
```

- [ ] **Step 4: 跑测试确认通过**

同 Step 2 命令。Expected: 3 passed(退出码 0)。

- [ ] **Step 5: ruff + mypy + commit**

```bash
wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && /home/administrator/fria-venv/bin/python3 -m ruff check eval/memory_dialogue/ tests/unit/eval_memory_dialogue/ && /home/administrator/fria-venv/bin/python3 -m mypy eval/memory_dialogue/script_schema.py"
git add backend/eval/memory_dialogue/ backend/tests/unit/eval_memory_dialogue/
git commit -m "feat(eval): 对话流记忆评估 — 脚本 schema 与 fail-loud 加载器"
```

---

### 任务二:首段脚本《白酒观点演化》定稿(协作任务)

**Files:**
- Create: `backend/eval/memory_dialogue/scripts/viewpoint-baijiu.yaml`
- Modify: `backend/tests/unit/eval_memory_dialogue/test_script_schema.py`(追加真脚本加载测试)

这是**合写任务**:执行者先按 brainstorm 已定的草稿(9 个 session,压"直接推翻+部分更新"梯子,重复去重、事件时间搭车)产出完整多轮版,**然后停下来交用户审台词真实感与刁钻度,审定前不进入任务三**。

- [ ] **Step 1: 写出完整 yaml 初稿**

要求(spec 已定,此处只列硬约束):
- 9 个 session:3 个有效(看多三年→改两年→转中性)+ 6 个干扰;长度分布含至少 1 短 1 中 1 长
- 有效 session 信息埋中后段,不放第一轮;其中一处有效信息以"助手要点式台词带出、用户确认"的形态出现
- 重复提及 session("我记得我跟你聊过白酒的看法吧")配 fact_count_no_increase 断言
- 数据库断言至少覆盖:fact_active(value_contains)/old_invalidated/fact_count_no_increase/invalidated_chain_intact/valid_from_is_event_time 五种
- probes 覆盖三档:直球(现在什么看法)、自然难(当初逻辑+为何放弃,挂 swap_order_invariant;改过几次)、对抗(假前提"我是不是一直看空")
- rel_type 用写管线白名单里的真实值(实施时查 `backend/app/memory/registry.py` 的 11 类白名单,观点类事实用白名单中对应观点/关注语义的那一类,不得编造新 rel_type)

- [ ] **Step 2: 追加加载测试**

```python
def test_real_script_viewpoint_baijiu_loads() -> None:
    """首段真脚本:结构合法 + 关键设计点在位。"""
    p = (
        Path(__file__).parent.parent.parent.parent
        / "eval" / "memory_dialogue" / "scripts" / "viewpoint-baijiu.yaml"
    )
    s = load_script(p)
    assert s.family == "观点演化族"
    assert len(s.sessions) == 9
    lengths = {sess.length for sess in s.sessions}
    assert {"短", "中", "长"} <= lengths
    tiers = {pr.tier for pr in s.probes}
    assert tiers == {"直球", "自然难", "对抗"}
    check_types = {c.type for g in s.db_assertions for c in g.checks}
    assert "fact_active" in check_types and "old_invalidated" in check_types
    assert any(pr.swap_order_invariant for pr in s.probes)
```

- [ ] **Step 3: 跑测试确认通过**(同任务一命令)

- [ ] **Step 4: ⏸ 用户审稿门(不可跳过)**

把 yaml 全文呈给用户审:台词像不像真人、刁钻点够不够。修改直至用户确认。

- [ ] **Step 5: Commit**

```bash
git add backend/eval/memory_dialogue/scripts/ backend/tests/unit/eval_memory_dialogue/
git commit -m "feat(eval): 首段对话流脚本《白酒观点演化》定稿(用户已审)"
```

---

### 任务三:数据库断言引擎

**Files:**
- Create: `backend/eval/memory_dialogue/db_assertions.py`
- Create: `backend/tests/integration/eval_memory_dialogue/__init__.py`(空)
- Create: `backend/tests/integration/eval_memory_dialogue/conftest.py`
- Test: `backend/tests/integration/eval_memory_dialogue/test_db_assertions.py`

断言引擎只依赖 SQLAlchemy session 和 ORM 模型,逐条返回红绿+解释,绝不抛断言异常(收集所有失败再报,fail loud 但不 fail fast)。

- [ ] **Step 1: conftest 转发既有 PG fixture**

```python
"""转发 backend/tests/integration/memory/conftest.py 的真 PG fixture。"""

from __future__ import annotations

pytest_plugins = ["tests.integration.memory.conftest"]
```

(若该 conftest 的 fixture 因包路径无法直接 plugin 化,改为 `from tests.integration.memory.conftest import *`;以实际能让 `pg_memory_fixture` / `pg_memory_session_factory` 在本目录可见为准。)

- [ ] **Step 2: 写失败测试**

```python
"""数据库断言引擎:直接往真 PG 种节点/边,验证各断言类型的红绿判定。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

import pytest

from app.memory.models import ChatMemoryEdge, ChatMemoryNode
from eval.memory_dialogue.db_assertions import DbAssertionEngine
from eval.memory_dialogue.script_schema import DbCheck


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


@pytest.fixture
def seeded_user(pg_memory_session_factory: Callable[[], Any]):
    """种一个用户 + '白酒'目标节点 + 一条看多观点边(active)+ 一条已作废旧边。"""
    session = pg_memory_session_factory()
    user_id = uuid4()
    # users 表由 memory conftest 内联建表;直接裸 INSERT
    from sqlalchemy import text

    session.execute(
        text("INSERT INTO users (id, email) VALUES (:i, :e)"),
        {"i": str(user_id), "e": f"eval-{user_id.hex[:8]}@test.local"},
    )
    src = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label="User")
    tgt = ChatMemoryNode(user_id=user_id, entity_type="Industry", entity_label="白酒")
    session.add_all([src, tgt])
    session.flush()
    old = ChatMemoryEdge(
        user_id=user_id, source_node_id=src.node_id, target_node_id=tgt.node_id,
        rel_type="HOLDS_VIEW", valid_from=_utc("2025-01-06"), valid_to=_utc("2025-02-03"),
        importance=0.9, properties={"stance": "看多", "horizon": "三年", "logic": "提价权"},
    )
    new = ChatMemoryEdge(
        user_id=user_id, source_node_id=src.node_id, target_node_id=tgt.node_id,
        rel_type="HOLDS_VIEW", valid_from=_utc("2025-02-03"), valid_to=None,
        importance=0.9, properties={"stance": "看多", "horizon": "两年", "logic": "提价权"},
    )
    session.add_all([old, new])
    session.commit()
    try:
        yield user_id, session
    finally:
        session.close()


def test_fact_active_green(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    r = engine.run_check(DbCheck(
        type="fact_active",
        params={"rel_type": "HOLDS_VIEW", "target_label": "白酒", "value_contains": ["看多", "两年"]},
    ))
    assert r.passed, r.detail


def test_fact_active_red_when_value_missing(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    r = engine.run_check(DbCheck(
        type="fact_active",
        params={"rel_type": "HOLDS_VIEW", "target_label": "白酒", "value_contains": ["中性"]},
    ))
    assert not r.passed
    assert "中性" in r.detail


def test_old_invalidated_green(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    r = engine.run_check(DbCheck(
        type="old_invalidated",
        params={"rel_type": "HOLDS_VIEW", "target_label": "白酒", "min_count": 1},
    ))
    assert r.passed, r.detail


def test_fact_count_snapshot_no_increase(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    engine.snapshot_counts(rel_type="HOLDS_VIEW", target_label="白酒")
    r = engine.run_check(DbCheck(
        type="fact_count_no_increase",
        params={"rel_type": "HOLDS_VIEW", "target_label": "白酒"},
    ))
    assert r.passed, r.detail


def test_no_holdings_fact_written(seeded_user) -> None:
    """持仓仲裁:不得出现 HOLDS 持仓边(种的是观点边,应绿)。"""
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    r = engine.run_check(DbCheck(type="no_fact_written", params={"rel_type": "HOLDS"}))
    assert r.passed, r.detail
```

- [ ] **Step 3: 跑测试确认失败**

```bash
wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && POSTGRES_PASSWORD=postgres123 POSTGRES_USER=postgres POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 JWT_SECRET_KEY=test-jwt LLM_MODE=mock /home/administrator/fria-venv/bin/python3 -m pytest tests/integration/eval_memory_dialogue/test_db_assertions.py -q"
```
Expected: FAIL,`No module named 'eval.memory_dialogue.db_assertions'`

- [ ] **Step 4: 实现 db_assertions.py**

```python
"""数据库断言引擎 — 对话流评估的写管线层判分。确定性,零 LLM。

每种断言类型一个私有方法;run_check 收集红绿不抛异常,失败带可读 detail
(差分思想:红灯要能直接指出库里实际长什么样)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.models import ChatMemoryEdge, ChatMemoryNode
from eval.memory_dialogue.script_schema import DbCheck


@dataclass(frozen=True)
class CheckResult:
    check_type: str
    passed: bool
    detail: str


class DbAssertionEngine:
    """绑定一个 user 的断言执行器。snapshot_counts 供'数量不得增加'类断言记基线。"""

    def __init__(self, session: Session, user_id: UUID) -> None:
        self._s = session
        self._user_id = user_id
        self._count_snapshots: dict[tuple[str, str | None], int] = {}

    # ---- 查询基元 ----------------------------------------------------------

    def _edges(
        self, rel_type: str | None = None, target_label: str | None = None
    ) -> list[ChatMemoryEdge]:
        stmt = select(ChatMemoryEdge).where(ChatMemoryEdge.user_id == self._user_id)
        if rel_type:
            stmt = stmt.where(ChatMemoryEdge.rel_type == rel_type)
        if target_label:
            stmt = stmt.join(
                ChatMemoryNode, ChatMemoryEdge.target_node_id == ChatMemoryNode.node_id
            ).where(ChatMemoryNode.entity_label == target_label)
        return list(self._s.execute(stmt).scalars())

    @staticmethod
    def _is_active(e: ChatMemoryEdge) -> bool:
        return e.valid_to is None and e.invalidated_at is None

    @staticmethod
    def _props_text(e: ChatMemoryEdge) -> str:
        return " ".join(str(v) for v in (e.properties or {}).values())

    # ---- 断言类型 ----------------------------------------------------------

    def run_check(self, check: DbCheck) -> CheckResult:
        handler = getattr(self, f"_check_{check.type}", None)
        if handler is None:
            return CheckResult(check.type, False, f"未知断言类型: {check.type}")
        return handler(**check.params)  # type: ignore[no-any-return]

    def _check_fact_active(
        self, rel_type: str, target_label: str, value_contains: list[str] | None = None
    ) -> CheckResult:
        active = [e for e in self._edges(rel_type, target_label) if self._is_active(e)]
        if not active:
            return CheckResult("fact_active", False, f"无 active 的 {rel_type}→{target_label} 边")
        if value_contains:
            texts = [self._props_text(e) for e in active]
            missing = [v for v in value_contains if not any(v in t for t in texts)]
            if missing:
                return CheckResult(
                    "fact_active", False,
                    f"active 边存在但缺关键值 {missing};实际 properties: {texts}",
                )
        return CheckResult("fact_active", True, f"{len(active)} 条 active")

    def _check_old_invalidated(
        self, rel_type: str, target_label: str, min_count: int = 1
    ) -> CheckResult:
        ended = [
            e for e in self._edges(rel_type, target_label)
            if e.valid_to is not None or e.invalidated_at is not None
        ]
        ok = len(ended) >= min_count
        return CheckResult(
            "old_invalidated", ok,
            f"已作废 {len(ended)} 条(要求 ≥{min_count})",
        )

    def snapshot_counts(self, rel_type: str, target_label: str | None = None) -> None:
        self._count_snapshots[(rel_type, target_label)] = len(self._edges(rel_type, target_label))

    def _check_fact_count_no_increase(
        self, rel_type: str, target_label: str | None = None
    ) -> CheckResult:
        key = (rel_type, target_label)
        if key not in self._count_snapshots:
            return CheckResult("fact_count_no_increase", False, "未先 snapshot_counts,无基线")
        before = self._count_snapshots[key]
        now = len(self._edges(rel_type, target_label))
        return CheckResult(
            "fact_count_no_increase", now <= before,
            f"基线 {before} 条 → 现在 {now} 条",
        )

    def _check_invalidated_chain_intact(
        self, rel_type: str, target_label: str, expected_versions: int
    ) -> CheckResult:
        all_edges = self._edges(rel_type, target_label)
        ok = len(all_edges) >= expected_versions
        return CheckResult(
            "invalidated_chain_intact", ok,
            f"链上共 {len(all_edges)} 个版本(要求 ≥{expected_versions};作废≠删除,历史必须可溯)",
        )

    def _check_valid_from_is_event_time(
        self, rel_type: str, target_label: str, expected_date: str, tolerance_days: int = 14
    ) -> CheckResult:
        active = [e for e in self._edges(rel_type, target_label) if self._is_active(e)]
        if not active:
            return CheckResult("valid_from_is_event_time", False, "无 active 边可校验")
        expected = datetime.fromisoformat(expected_date)
        tol = timedelta(days=tolerance_days)
        for e in active:
            vf = e.valid_from.replace(tzinfo=None)
            if abs(vf - expected) <= tol:
                return CheckResult(
                    "valid_from_is_event_time", True, f"valid_from={vf.date()} ≈ {expected_date}"
                )
        actual = [e.valid_from.date().isoformat() for e in active]
        return CheckResult(
            "valid_from_is_event_time", False,
            f"valid_from 实为 {actual},期望 ≈{expected_date}(±{tolerance_days}天)——疑似打成录入时间",
        )

    def _check_no_fact_written(self, rel_type: str) -> CheckResult:
        edges = self._edges(rel_type)
        return CheckResult(
            "no_fact_written", not edges,
            f"{rel_type} 边 {len(edges)} 条(要求 0——该信息不归记忆管)",
        )
```

- [ ] **Step 5: 跑测试确认通过**(同 Step 3 命令)Expected: 5 passed

- [ ] **Step 6: ruff + mypy + commit**

```bash
git add backend/eval/memory_dialogue/db_assertions.py backend/tests/integration/eval_memory_dialogue/
git commit -m "feat(eval): 对话流记忆评估 — 数据库断言引擎(六种断言类型,确定性零 LLM)"
```

---

### 任务四:写阶段执行器

**Files:**
- Create: `backend/eval/memory_dialogue/write_phase.py`
- Test: `backend/tests/integration/eval_memory_dialogue/test_write_phase.py`

职责:把脚本的 session 流灌进库并触发抽取,逐 session 跑断言组。**抽取器走依赖注入**:`extract_session(user_id, session_id, script_session)` 是一个可调用——live_deps 接真 PathBRunner,测试给假实现(直接写边)。episode 用裸 INSERT 写入并**显式给 created_at=脚本日期**(绕过 server default,这是时间可控的关键,沿用差分测试的模式)。

- [ ] **Step 1: 写失败测试**

```python
"""写阶段:episodes 按脚本日期入库 → 假抽取器写边 → 逐 session 断言红绿。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.memory.models import ChatMemoryEdge, ChatMemoryNode
from eval.memory_dialogue.script_schema import ScriptSession, load_script
from eval.memory_dialogue.write_phase import WritePhaseRunner

MINIMAL = Path(__file__).parent / "fixture_write_minimal.yaml"


@pytest.fixture
def fresh_user(pg_memory_session_factory: Callable[[], Any]):
    session = pg_memory_session_factory()
    user_id, chat_session_id = uuid4(), uuid4()
    session.execute(
        text("INSERT INTO users (id, email) VALUES (:i, :e)"),
        {"i": str(user_id), "e": f"wp-{user_id.hex[:8]}@test.local"},
    )
    session.execute(
        text("INSERT INTO chat_sessions (id, user_id) VALUES (:s, :u)"),
        {"s": str(chat_session_id), "u": str(user_id)},
    )
    session.commit()
    try:
        yield user_id, chat_session_id, session
    finally:
        session.close()


def _fake_extractor(session_handle: Any):
    """假抽取器:第 1 个 session 写一条看多边;第 2 个 session 把它作废并写中性边。"""

    async def extract(user_id: UUID, chat_session_id: UUID, ss: ScriptSession) -> None:
        s = session_handle
        if ss.n == 1:
            src = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label="User")
            tgt = ChatMemoryNode(user_id=user_id, entity_type="Industry", entity_label="白酒")
            s.add_all([src, tgt])
            s.flush()
            s.add(ChatMemoryEdge(
                user_id=user_id, source_node_id=src.node_id, target_node_id=tgt.node_id,
                rel_type="HOLDS_VIEW",
                valid_from=datetime.combine(ss.date, datetime.min.time(), tzinfo=UTC),
                valid_to=None, importance=0.9, properties={"stance": "看多"},
            ))
        else:
            for e in s.query(ChatMemoryEdge).filter_by(user_id=user_id, valid_to=None):
                e.valid_to = datetime.combine(ss.date, datetime.min.time(), tzinfo=UTC)
        s.commit()

    return extract


async def test_write_phase_runs_assertions_per_session(fresh_user, tmp_path: Path) -> None:
    user_id, chat_session_id, session = fresh_user
    p = tmp_path / "s.yaml"
    p.write_text(
        """
script_id: write-minimal
title: "写阶段最小脚本"
family: 观点演化族
substrate: 观点演化
sessions:
  - n: 1
    date: 2025-01-06
    length: 短
    turns: [{u: "白酒看多"}, {a: "(回应)"}]
  - n: 2
    date: 2025-04-01
    length: 短
    turns: [{u: "白酒观点收回"}, {a: "(回应)"}]
db_assertions:
  - after: 1
    assert:
      - {type: fact_active, rel_type: HOLDS_VIEW, target_label: 白酒, value_contains: ["看多"]}
  - after: 2
    assert:
      - {type: old_invalidated, rel_type: HOLDS_VIEW, target_label: 白酒, min_count: 1}
probes:
  - {tier: 直球, dimension: 知识更新, q: "占位", expect_contain: [], expect_not: [], judge_rubric: "占位"}
""",
        encoding="utf-8",
    )
    script = load_script(p)
    runner = WritePhaseRunner(
        session=session, user_id=user_id, chat_session_id=chat_session_id,
        extract_session=_fake_extractor(session),
    )
    report = await runner.run(script)
    assert report.all_passed, [r.detail for r in report.results if not r.passed]
    # episode created_at 必须等于脚本日期,不是今天
    row = session.execute(
        text("SELECT created_at FROM chat_memory_episodes WHERE user_id=:u ORDER BY episode_index LIMIT 1"),
        {"u": str(user_id)},
    ).first()
    assert row is not None and str(row[0]).startswith("2025-01-06")


async def test_write_phase_collects_red_not_raises(fresh_user, tmp_path: Path) -> None:
    """断言失败收集成红灯报告,不抛异常中断后续 session。"""
    user_id, chat_session_id, session = fresh_user
    p = tmp_path / "s.yaml"
    p.write_text(
        """
script_id: write-red
title: "红灯脚本"
family: 观点演化族
substrate: 观点演化
sessions:
  - n: 1
    date: 2025-01-06
    length: 短
    turns: [{u: "白酒看多"}, {a: "(回应)"}]
db_assertions:
  - after: 1
    assert:
      - {type: fact_active, rel_type: HOLDS_VIEW, target_label: 白酒, value_contains: ["中性"]}
probes:
  - {tier: 直球, dimension: 知识更新, q: "占位", expect_contain: [], expect_not: [], judge_rubric: "占位"}
""",
        encoding="utf-8",
    )
    runner = WritePhaseRunner(
        session=session, user_id=user_id, chat_session_id=chat_session_id,
        extract_session=_fake_extractor(session),
    )
    report = await runner.run(load_script(p))
    assert not report.all_passed
    assert any("中性" in r.detail for r in report.results)
```

- [ ] **Step 2: 跑测试确认失败**(命令同任务三;Expected: import 失败)

- [ ] **Step 3: 实现 write_phase.py**

```python
"""写阶段执行器 — 把脚本 session 流灌进库、触发抽取、逐 session 跑断言。

时间可控的关键:episode 用裸 INSERT 显式给 created_at=脚本 session 日期,
绕过 server default(沿用 bi_temporal_differential 测试的模式)。
抽取器依赖注入:live_deps 接真实批量抽取,测试给假实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from eval.memory_dialogue.db_assertions import CheckResult, DbAssertionEngine
from eval.memory_dialogue.script_schema import Script, ScriptSession


class ExtractSessionFn(Protocol):
    def __call__(
        self, user_id: UUID, chat_session_id: UUID, ss: ScriptSession
    ) -> Awaitable[None]: ...


@dataclass(frozen=True)
class SessionCheckResult:
    after_session: int
    check_type: str
    passed: bool
    detail: str


@dataclass
class WritePhaseReport:
    results: list[SessionCheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)


class WritePhaseRunner:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        chat_session_id: UUID,
        extract_session: ExtractSessionFn,
    ) -> None:
        self._s = session
        self._user_id = user_id
        self._chat_session_id = chat_session_id
        self._extract = extract_session
        self._engine = DbAssertionEngine(session=session, user_id=user_id)

    def _insert_episodes(self, ss: ScriptSession) -> None:
        """把一个 session 的轮次按 (用户消息, 助手回复) 对写成 episode,created_at=脚本日期。"""
        created = datetime.combine(ss.date, datetime.min.time(), tzinfo=UTC)
        pairs: list[tuple[str, str]] = []
        pending_user: str | None = None
        for t in ss.turns:
            if t.role == "u":
                if pending_user is not None:
                    pairs.append((pending_user, ""))
                pending_user = t.text
            else:
                pairs.append((pending_user or "", t.text))
                pending_user = None
        if pending_user is not None:
            pairs.append((pending_user, ""))
        for idx, (u_msg, a_msg) in enumerate(pairs):
            self._s.execute(
                text(
                    "INSERT INTO chat_memory_episodes "
                    "(episode_id, user_id, session_id, episode_index, "
                    " user_message_text, agent_response_text, source_kind, created_at) "
                    "VALUES (:eid, :uid, :sid, :idx, :u, :a, 'chat_turn', :created)"
                ),
                {
                    "eid": str(uuid4()), "uid": str(self._user_id),
                    "sid": str(self._chat_session_id),
                    "idx": ss.n * 1000 + idx,  # session 内有序且全局不撞
                    "u": u_msg, "a": a_msg, "created": created,
                },
            )
        self._s.commit()

    async def run(self, script: Script) -> WritePhaseReport:
        report = WritePhaseReport()
        groups_by_after = {g.after_session: g for g in script.db_assertions}
        # 重复去重类断言需要基线:在每个带断言的 session 之前快照
        for ss in script.sessions:
            group = groups_by_after.get(ss.n)
            if group:
                for c in group.checks:
                    if c.type == "fact_count_no_increase":
                        self._engine.snapshot_counts(
                            rel_type=str(c.params["rel_type"]),
                            target_label=c.params.get("target_label"),  # type: ignore[arg-type]
                        )
            self._insert_episodes(ss)
            await self._extract(self._user_id, self._chat_session_id, ss)
            if group:
                for c in group.checks:
                    r: CheckResult = self._engine.run_check(c)
                    report.results.append(
                        SessionCheckResult(
                            after_session=ss.n, check_type=r.check_type,
                            passed=r.passed, detail=r.detail,
                        )
                    )
        return report
```

- [ ] **Step 4: 跑测试确认通过**;**Step 5: ruff + mypy + commit**

```bash
git commit -m "feat(eval): 对话流记忆评估 — 写阶段执行器(可控时间戳 + 逐 session 断言)"
```

---

### 任务五:读阶段执行器(检索 + 生成 + 三层判分)

**Files:**
- Create: `backend/eval/memory_dialogue/read_phase.py`
- Test: `backend/tests/unit/eval_memory_dialogue/test_read_phase.py`

三层判分次序:字符串硬校验(必过)→ 弃答纪律(answerable 与拒答形态互斥)→ 裁判 rubric(0/1)。不变量开关:同一 probe 把检索结果倒序再生成一遍,两次都得过硬校验且裁判一致。检索/生成/裁判全部 Protocol 注入。

- [ ] **Step 1: 写失败测试**

```python
"""读阶段:三层判分 + 不变量开关,全假依赖。"""

from __future__ import annotations

import pytest

from eval.memory_dialogue.read_phase import ReadPhaseRunner
from eval.memory_dialogue.script_schema import Probe


class FakeRetriever:
    def __init__(self, facts: list[dict]) -> None:
        self._facts = facts
        self.search_calls: int = 0

    async def search(self, query: str, k: int = 5) -> list[dict]:
        self.search_calls += 1
        return list(self._facts)


class FakeGenerator:
    """按检索结果第一条的 stance 作答 —— 用来模拟'答案随顺序漂移'。"""

    def __init__(self, order_sensitive: bool = False, fixed: str | None = None) -> None:
        self._order_sensitive = order_sensitive
        self._fixed = fixed

    async def generate(self, query: str, facts: list[dict]) -> str:
        if self._fixed is not None:
            return self._fixed
        if self._order_sensitive and facts:
            return f"你的观点是{facts[0]['stance']}"
        actives = [f for f in facts if f.get("active")]
        return f"你的观点是{actives[0]['stance']}" if actives else "没有相关记录"


class FakeJudge:
    def __init__(self, verdict: bool = True) -> None:
        self._verdict = verdict

    async def judge(self, question: str, answer: str, rubric: str) -> bool:
        return self._verdict


FACTS = [
    {"stance": "中性", "active": True},
    {"stance": "看多", "active": False},
]

PROBE = Probe(
    tier="直球", dimension="知识更新", q="我对白酒什么看法?",
    expect_contain=("中性",), expect_not=("看多",),
    judge_rubric="应答中性", swap_order_invariant=False, answerable=True,
)


async def test_hard_check_pass_and_judge_pass() -> None:
    runner = ReadPhaseRunner(
        retriever=FakeRetriever(FACTS), generator=FakeGenerator(), judge=FakeJudge(True)
    )
    r = await runner.run_probe(PROBE)
    assert r.hard_passed and r.judge_passed and r.final_passed


async def test_expect_not_violation_fails_hard() -> None:
    runner = ReadPhaseRunner(
        retriever=FakeRetriever(FACTS),
        generator=FakeGenerator(fixed="你的观点是看多"),
        judge=FakeJudge(True),
    )
    r = await runner.run_probe(PROBE)
    assert not r.hard_passed and not r.final_passed
    assert "看多" in r.detail


async def test_unanswerable_probe_rewards_abstention() -> None:
    probe = Probe(
        tier="对抗", dimension="克制弃答", q="我比特币成本多少?",
        expect_contain=(), expect_not=("成本",),
        judge_rubric="必须指出从未聊过比特币", answerable=False,
    )
    runner = ReadPhaseRunner(
        retriever=FakeRetriever([]),
        generator=FakeGenerator(fixed="你没有跟我聊过比特币,我没有这个信息"),
        judge=FakeJudge(True),
    )
    r = await runner.run_probe(probe)
    assert r.final_passed


async def test_answerable_probe_zero_on_refusal() -> None:
    """反蹭分守卫:可答题输出拒答形态 → 直接 0,裁判说什么都没用。"""
    runner = ReadPhaseRunner(
        retriever=FakeRetriever(FACTS),
        generator=FakeGenerator(fixed="我不知道,没有相关信息"),
        judge=FakeJudge(True),
    )
    r = await runner.run_probe(PROBE)
    assert not r.final_passed
    assert "拒答" in r.detail


async def test_swap_order_invariance_catches_drift() -> None:
    probe = Probe(
        tier="自然难", dimension="知识更新", q="我对白酒什么看法?",
        expect_contain=("中性",), expect_not=(),
        judge_rubric="应答中性", swap_order_invariant=True,
    )
    runner = ReadPhaseRunner(
        retriever=FakeRetriever(FACTS),
        generator=FakeGenerator(order_sensitive=True),  # 第一条是中性,倒序后变看多
        judge=FakeJudge(True),
    )
    r = await runner.run_probe(probe)
    assert not r.final_passed
    assert "不变量" in r.detail
```

- [ ] **Step 2: 跑测试确认失败**

```bash
wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && /home/administrator/fria-venv/bin/python3 -m pytest tests/unit/eval_memory_dialogue/test_read_phase.py -q"
```

- [ ] **Step 3: 实现 read_phase.py**

```python
"""读阶段执行器 — 检索 + 生成 + 三层判分 + 不变量开关。

判分次序(spec 判分纪律):
1. 字符串硬校验(expect_contain / expect_not)——确定性,必过
2. 弃答纪律:可答题输出拒答形态直接 0(反蹭分);弃答题要求拒答形态在场
3. LLM 裁判按 rubric 判 0/1
不变量开关:检索结果倒序重生成,两轨都必须过硬校验,否则判'答案随顺序漂移'。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from eval.memory_dialogue.script_schema import Probe

# 拒答形态:出现任一即视为'这次回答是在拒答/弃答'
REFUSAL_MARKERS = ("不知道", "没有相关", "没有这个信息", "无法回答", "没聊过", "没有跟我聊过", "没提过")


class RetrieverProtocol(Protocol):
    async def search(self, query: str, k: int = 5) -> list[Any]: ...


class GeneratorProtocol(Protocol):
    async def generate(self, query: str, facts: list[Any]) -> str: ...


class JudgeProtocol(Protocol):
    async def judge(self, question: str, answer: str, rubric: str) -> bool: ...


@dataclass(frozen=True)
class ProbeResult:
    probe: Probe
    answer: str
    hard_passed: bool
    judge_passed: bool
    invariance_passed: bool
    final_passed: bool
    detail: str


def _hard_check(answer: str, probe: Probe) -> tuple[bool, str]:
    missing = [c for c in probe.expect_contain if c not in answer]
    leaked = [c for c in probe.expect_not if c in answer]
    if missing or leaked:
        return False, f"硬校验失败: 缺 {missing} / 不该出现 {leaked}"
    return True, "硬校验通过"


def _is_refusal(answer: str) -> bool:
    return any(m in answer for m in REFUSAL_MARKERS)


class ReadPhaseRunner:
    def __init__(
        self,
        retriever: RetrieverProtocol,
        generator: GeneratorProtocol,
        judge: JudgeProtocol,
        k: int = 5,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._judge = judge
        self._k = k

    async def run_probe(self, probe: Probe) -> ProbeResult:
        facts = await self._retriever.search(probe.q, k=self._k)
        answer = await self._generator.generate(probe.q, facts)

        hard_ok, hard_detail = _hard_check(answer, probe)
        refusal = _is_refusal(answer)

        # 弃答纪律
        if probe.answerable and refusal:
            return ProbeResult(
                probe, answer, hard_passed=False, judge_passed=False,
                invariance_passed=True, final_passed=False,
                detail=f"可答题输出拒答形态(反蹭分判 0): {answer!r}",
            )
        if not probe.answerable and not refusal:
            return ProbeResult(
                probe, answer, hard_passed=hard_ok, judge_passed=False,
                invariance_passed=True, final_passed=False,
                detail=f"弃答题未拒答(疑似顺着假前提编): {answer!r}",
            )

        judge_ok = await self._judge.judge(probe.q, answer, probe.judge_rubric)

        invariance_ok, inv_detail = True, ""
        if probe.swap_order_invariant and facts:
            answer_swapped = await self._generator.generate(probe.q, list(reversed(facts)))
            swapped_ok, _ = _hard_check(answer_swapped, probe)
            if not swapped_ok:
                invariance_ok = False
                inv_detail = f";不变量失败: 倒序后答 {answer_swapped!r}(答案随检索顺序漂移)"

        final = hard_ok and judge_ok and invariance_ok
        return ProbeResult(
            probe, answer, hard_passed=hard_ok, judge_passed=judge_ok,
            invariance_passed=invariance_ok, final_passed=final,
            detail=hard_detail + inv_detail,
        )
```

- [ ] **Step 4: 跑测试确认通过**(Expected: 5 passed);**Step 5: ruff + mypy + commit**

```bash
git commit -m "feat(eval): 对话流记忆评估 — 读阶段三层判分 + 不变量开关"
```

---

### 任务六:分数表聚合 + CLI + 真实依赖 wiring

**Files:**
- Create: `backend/eval/memory_dialogue/scoring.py`
- Create: `backend/eval/memory_dialogue/live_deps.py`
- Create: `backend/eval/memory_dialogue/run_eval.py`
- Test: `backend/tests/unit/eval_memory_dialogue/test_scoring.py`

- [ ] **Step 1: 写失败测试**

```python
"""分数表:能力维度 × 难度档,无聚合总分;写管线断言通过率单列。"""

from __future__ import annotations

from eval.memory_dialogue.read_phase import ProbeResult
from eval.memory_dialogue.scoring import build_score_table, format_score_table
from eval.memory_dialogue.script_schema import Probe
from eval.memory_dialogue.write_phase import SessionCheckResult


def _pr(dim: str, tier: str, passed: bool) -> ProbeResult:
    p = Probe(tier=tier, dimension=dim, q="q", expect_contain=(), expect_not=(), judge_rubric="r")
    return ProbeResult(p, "a", passed, passed, True, passed, "")


def test_table_groups_by_dimension_and_tier() -> None:
    table = build_score_table(
        probe_results=[
            _pr("知识更新", "直球", True), _pr("知识更新", "直球", True),
            _pr("知识更新", "对抗", False), _pr("克制弃答", "自然难", True),
        ],
        write_results=[
            SessionCheckResult(1, "fact_active", True, ""),
            SessionCheckResult(3, "old_invalidated", False, "红"),
        ],
    )
    assert table.cell("知识更新", "直球") == (2, 2)
    assert table.cell("知识更新", "对抗") == (0, 1)
    assert table.cell("克制弃答", "自然难") == (1, 1)
    assert table.db_assertion_rate == (1, 2)


def test_format_contains_no_aggregate_total() -> None:
    table = build_score_table([_pr("知识更新", "直球", True)], [])
    out = format_score_table(table)
    assert "知识更新" in out and "直球" in out
    assert "总分" not in out  # 设计决策:无聚合总分
```

- [ ] **Step 2: 跑确认失败 → Step 3: 实现 scoring.py**

```python
"""分数聚合 — 能力维度 × 难度档通过率表。无门控、无聚合总分(解读交给人)。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from eval.memory_dialogue.read_phase import ProbeResult
from eval.memory_dialogue.script_schema import VALID_DIMENSIONS, VALID_TIERS
from eval.memory_dialogue.write_phase import SessionCheckResult


@dataclass
class ScoreTable:
    cells: dict[tuple[str, str], tuple[int, int]] = field(default_factory=dict)
    db_assertion_rate: tuple[int, int] = (0, 0)

    def cell(self, dimension: str, tier: str) -> tuple[int, int]:
        return self.cells.get((dimension, tier), (0, 0))


def build_score_table(
    probe_results: list[ProbeResult],
    write_results: list[SessionCheckResult],
) -> ScoreTable:
    agg: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for r in probe_results:
        agg[(r.probe.dimension, r.probe.tier)].append(r.final_passed)
    cells = {k: (sum(v), len(v)) for k, v in agg.items()}
    db_pass = sum(1 for w in write_results if w.passed)
    return ScoreTable(cells=cells, db_assertion_rate=(db_pass, len(write_results)))


def format_score_table(table: ScoreTable) -> str:
    lines = ["能力维度 × 难度档(通过/总数)", "=" * 48]
    header = f"{'维度':<10}" + "".join(f"{t:>10}" for t in VALID_TIERS)
    lines.append(header)
    for dim in VALID_DIMENSIONS:
        row_cells = [table.cell(dim, t) for t in VALID_TIERS]
        if all(total == 0 for _, total in row_cells):
            continue
        row = f"{dim:<10}" + "".join(
            f"{f'{p}/{t}' if t else '—':>10}" for p, t in row_cells
        )
        lines.append(row)
    db_p, db_t = table.db_assertion_rate
    lines.append("-" * 48)
    lines.append(f"写管线数据库断言: {db_p}/{db_t}")
    lines.append("(直球档当金丝雀:大面积红先怀疑评估 harness 自身)")
    return "\n".join(lines)
```

- [ ] **Step 4: 实现 live_deps.py(唯一接真实管线的模块)**

```python
"""真实依赖 wiring — 仅 CLI 用,测试不 import 本模块。

抽取: 写完 episode 后调批量抽取管线(PathBRunner 同款链路)。
检索: HierarchicalMemory.archival_memory_search。
生成/裁判: LLMService(生成 balanced 档,裁判 fast 档)。
具体类的构造参数以 backend/app/memory/hierarchical.py 与
backend/eval/memory/_runner_deps.py 当前签名为准——实施此任务时先读这两个文件,
按真实签名填充下面的构造(本文件是计划中唯一允许'按现场签名调整'的模块,
因为它的全部职责就是对接现场)。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.services.openai_client import build_llm_service_from_env

GENERATE_PROMPT = """\
你是用户的金融研究助手。仅基于下面检索到的记忆回答用户问题;
记忆里没有的信息明确说"你没有跟我聊过这个,我没有这个信息",不要编造。

[检索到的记忆]
{facts}

[用户问题]
{question}
"""

JUDGE_PROMPT = """\
你是评估裁判。按下面的评分标准判断回答是否合格,只输出 yes 或 no。

[问题] {question}
[回答] {answer}
[评分标准] {rubric}
"""


class LiveGenerator:
    def __init__(self) -> None:
        self._llm = build_llm_service_from_env()

    async def generate(self, query: str, facts: list[Any]) -> str:
        facts_text = "\n".join(f"- {f}" for f in facts) or "(空)"
        resp = self._llm.chat(
            prompt=GENERATE_PROMPT.format(facts=facts_text, question=query),
            tier="balanced",
        )
        return str(resp.content)


class LiveJudge:
    def __init__(self) -> None:
        self._llm = build_llm_service_from_env()

    async def judge(self, question: str, answer: str, rubric: str) -> bool:
        resp = self._llm.chat(
            prompt=JUDGE_PROMPT.format(question=question, answer=answer, rubric=rubric),
            tier="fast",
        )
        return str(resp.content).strip().lower().startswith("yes")
```

- [ ] **Step 5: 实现 run_eval.py CLI**

```python
"""CLI: 跑一段或全部脚本,输出维度 × 难度分数表。

用法(WSL fria-venv,真 PG + 真 LLM):
    python -m eval.memory_dialogue.run_eval --script eval/memory_dialogue/scripts/viewpoint-baijiu.yaml
    python -m eval.memory_dialogue.run_eval --all --report json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from eval.memory_dialogue.scoring import build_score_table, format_score_table
from eval.memory_dialogue.script_schema import load_script

SCRIPTS_DIR = Path(__file__).parent / "scripts"


async def _run_one(script_path: Path) -> tuple[list, list]:
    # live wiring:构造真实 retriever/generator/judge/extractor + 评估专用 user
    from eval.memory_dialogue.live_deps import build_live_runners  # 实施任务六时按现场签名补齐

    write_runner, read_runner = await build_live_runners()
    script = load_script(script_path)
    write_report = await write_runner.run(script)
    probe_results = [await read_runner.run_probe(p) for p in script.probes]
    return probe_results, write_report.results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="对话流记忆评估 runner")
    parser.add_argument("--script", help="单段脚本 yaml 路径")
    parser.add_argument("--all", action="store_true", help="跑 scripts/ 全部")
    parser.add_argument("--report", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    paths = sorted(SCRIPTS_DIR.glob("*.yaml")) if args.all else [Path(args.script)]
    all_probes, all_writes = [], []
    for p in paths:
        probes, writes = asyncio.run(_run_one(p))
        all_probes.extend(probes)
        all_writes.extend(writes)

    table = build_score_table(all_probes, all_writes)
    if args.report == "json":
        print(json.dumps(
            {f"{d}|{t}": v for (d, t), v in table.cells.items()}
            | {"db_assertions": table.db_assertion_rate},
            ensure_ascii=False, indent=2,
        ))
    else:
        print(format_score_table(table))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: 跑全部单测 + ruff + mypy + commit**

```bash
wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && /home/administrator/fria-venv/bin/python3 -m pytest tests/unit/eval_memory_dialogue/ -q"
git commit -m "feat(eval): 对话流记忆评估 — 分数表 + CLI + 真实依赖 wiring"
```

---

### 任务七:端到端冒烟(真 PG + 真 LLM,首段脚本)

无新文件;这是验收里程碑。前置:任务二的脚本已过用户审。

- [ ] **Step 1: 补齐 live_deps.build_live_runners**

读 `backend/app/memory/hierarchical.py`(HierarchicalMemory 构造)与 `backend/app/memory/path_b_runner.py`(批量抽取触发),把 write 阶段的真实 extract_session 接通:每个 session 的 episodes 入库后,调批量抽取链路(grouper → 抽取 → 冲突消解 → 入图)。评估用独立 user(每次跑新建 UUID,不污染真用户数据)。

- [ ] **Step 2: 真跑首段脚本**

```bash
wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && set -a && source ../.env && set +a && PYTHONPATH=. /home/administrator/fria-venv/bin/python3 -m eval.memory_dialogue.run_eval --script eval/memory_dialogue/scripts/viewpoint-baijiu.yaml"
```
Expected: 输出维度 × 难度分数表 + 写管线断言红绿明细。

- [ ] **Step 3: 红绿可解释性检查(验收核心)**

对每个红灯回答:这红灯指向写管线还是读管线?是系统真翻车(有效信号)还是 harness 问题(脚本措辞/断言过严/rel_type 对不上抽取白名单)?harness 问题修 harness,真翻车记录下来——spec 验收标准:每段脚本至少 1 个提问抓到过真实故障,或证明系统扛住,两者都是信息。

- [ ] **Step 4: 把首跑结果与解读记入 commit**

```bash
git commit -m "feat(eval): 首段脚本端到端冒烟通过 — 首跑红绿解读见 commit 正文" -m "<粘贴分数表与红灯解读>"
```

---

### 任务八:批量合写其余 27 段脚本(协作里程碑,五批)

无固定代码;每批流程相同,**每段脚本都过"草稿 → 用户审 → 加载测试 → 单段冒烟 → commit"五步**。批次顺序与素材来源(spec 已定):

| 批次 | 内容 | 段数 | 素材清单位置 |
|---|---|---|---|
| 第一批 | 观点演化族剩余(间接指代/撤回更正/多跳冲突/涟漪传播主攻段 + 机动变体) | 7 | spec 第 3 节八机制 |
| 第二批 | 持仓仲裁族(直述/暗示/混在观点里) | 3 | spec 决策"记忆不存持仓事实" |
| 第三批 | 弃答陷阱族(假前提/幻觉填空/碎片/近似冒充/过度拒答陷阱) | 5 | spec 3d 节 |
| 第四批 | 偏好画像族(过度泛化/谄媚翻转/长对话遗忘/隐式偏好 + 知行不一双轨标配) | 6 | spec 3b 节 |
| 第五批 | 时间事件族(时间窗/时序链/长程深干扰段) | 5 | spec 3c 节 |

- [ ] 第一批完成并冒烟
- [ ] 第二批完成并冒烟(注:持仓仲裁族需要 read 阶段能断言"调用了持仓模块工具而非记忆检索"——实施时给 ReadPhaseRunner 加 routing 断言钩子,模式同 no_fact_written)
- [ ] 第三批完成并冒烟
- [ ] 第四批完成并冒烟(注:知行不一双轨 = 同段脚本两个 probe:复述题 + 行为题,行为题 expect_not 填禁选标的清单)
- [ ] 第五批完成并冒烟(注:每族至少 1 段长程版 25-35 session)
- [ ] 全量跑 `--all`,产出第一份完整分数表,与用户一起解读

---

## 自检记录

- spec 覆盖:七个核心决策 → 双层断言(任务三/四/五)、持仓不入记忆(no_fact_written + 第二批)、五族 28 段(任务二/八)、三档难度无门控(schema tier 校验 + scoring 无总分测试)、双边写死(schema turns)、长短分布(任务二硬约束 + 加载测试)、合写流程(任务二/八的用户审稿门)。不变量开关(spec 3e)→ 任务五。
- 类型一致性:`DbCheck`/`CheckResult`/`SessionCheckResult`/`ProbeResult`/`ScoreTable` 在任务三/四/五/六间签名已对齐;`Probe.answerable`/`swap_order_invariant` 在 schema 与 read_phase 一致。
- 已知留白(显式声明,非占位):live_deps 的真实构造参数按现场签名填(任务七第一步),因为 HierarchicalMemory/PathBRunner 的构造依赖(Milvus client/embed service/session factory)需要实施时对照当前代码;这是该模块的全部职责所在。

---

## 执行进度(2026-06-05 会话收尾)

- [x] 任务一:脚本 schema 与加载器(4 测试)
- [x] 任务二:首段脚本《白酒观点演化》定稿——用户已审;retail-investor-voice skill(TDD 产出)加持台词
- [x] 任务三:数据库断言引擎(9 测试,真 PG)
- [x] 任务四:写阶段执行器(2 测试,可控时间戳验证)
- [x] 任务五:读阶段执行器(6 测试,三层判分+不变量开关)
- [x] 任务六:分数表 + CLI + live wiring
- [x] 任务七:端到端冒烟——六轮迭代,管线全通,红绿可解释;写侧断言 5/8 绿(知识更新全链路证明工作:中性版生效/旧版作废/四版本链可溯),抽出 18 条边、干扰 session 正确零插入
- [ ] 任务八:批量合写其余 27 段脚本(五批)——未开始

### 冒烟发现(全部 TDD 修复+测试守护,各自独立 commit)

1. skip_gate 关键词门误杀散户口语(白名单全书面语)→ 补口语词表
2. embed 批形态 vs 检索平向量接口漂移 → wiring 适配器
3. 抽取层 LLM 客户端协议不兼容(生产 Path B 在真实 LLM 下从未成功,cassette mock 掩盖)→ MemoryLLMClientAdapter,生产两处 wiring 同修
4. AGE cypher 失败毒死 PG 事务(best-effort名存实亡)→ SAVEPOINT
5. 生产库无 AGE 扩展且不可装(图镜像生产从未工作)→ 边镜像降级 best-effort(**政策变更**:原「AGE 失败→整事务回滚」契约及其测试已改写为降级语义,待用户追认)

### 任务七遗留清单(评估体系完善后回来修;用户决策:先评估体系后系统优化)

- 读侧检索层两个 bug:(甲)向量查询 struct.error 残留(collection 已 ensure 仍报,待深挖);(乙)BM25 对中文查询零召回(疑 PG 分词,候选发现六)——读侧 6 红全归因于此
- 断言措辞适配值规整:抽取把「两年」规整为「2年」,首段脚本 value_contains 需适配(或断言引擎做规整感知匹配)
- 首个 session 的边疑似写到非「白酒」实体标签(实体规整),待查证——读侧别名一致机制的现实版
- 弃答题在检索全空时躺赢,解读分数须连同检索健康度看(可考虑给弃答题加「检索非空」前置断言)
- Milvus alias 测试(test_alias_points_to_v1)pre-existing 环境失败,与本分支无关

### 检索层根因清账(2026-06-09 会话:读侧全红根因全修,TDD 守护)

读侧「全红」拆出**四层**根因,逐层 TDD 修复(失败测试→看红→最小修→看绿):

1. **建边没填 search_tokens** → `search_vector`(GENERATED)为空 → BM25 `@@` 永不匹配 → 中文零召回。
   修:`hierarchical.py` 建 search_tokens 串,`conflict_resolver.apply_action` 加 `search_tokens` 参数透传。
   守护:`test_bm25_chinese_recall.py::test_bm25_recalls_chinese_after_search_tokens`。
2. **BM25 用 `plainto_tsquery`(整句切词后全 AND)** → 真实读侧 query 是整句(「我现在对白酒整体是什么看法」),
   边的 search_tokens 不含「现在/整体/看法」→ AND 必零召回(单词「白酒」能召回是假象)。SQL 实测:整句 plainto=0,OR=5。
   修:`retriever.bm25_search` 改 `to_tsquery` + `_tokens_to_or_tsquery`(lexeme 单引号转义、滤纯标点),OR 语义靠 `ts_rank`+`LIMIT` 保精度。
   守护:`test_bm25_recalls_full_sentence_query` + `test_retriever.py` 断言 SQL 用 to_tsquery 不用 plainto。
3. **向量 embed 契约错调**:`embed` 真契约是 `embed(list[str]) -> list[list[float]]`,`vector_search`/`milvus_outbox` 过去传 **bare string**
   → 内部 `for i in range(0, len(texts), batch)` 按**字符**切片,长 query 返回多个子串向量 → `data=[多向量]` 形态错 → struct.error。
   修:两处都 `embed([query])` 收 list、取 `[0]`,兼容 legacy 扁平返回(首元素非 list 时整体当向量)。`_EmbedServiceLike` 协议改对。
   守护:`test_retriever.py::test_embed_called_with_list_and_milvus_gets_flat_vector` + `test_milvus_outbox_e2e.py::..._inserts_flat_vector`。
4. **DetachedInstanceError**:`archival_memory_search` 内 `session.commit()`(生产 SessionLocal 默认 `expire_on_commit=True`)
   先 expire 所有属性,再 `expunge` 返回失效+detached 对象,调用方一访问列属性即崩(测试 conftest 用 `expire_on_commit=False` 掩盖,只在生产/eval 暴露)。
   修:search 的 session 显式 `expire_on_commit = False`。
   守护:`test_retriever_e2e.py::test_archival_search_edges_readable_after_session_close`(用 `expire_on_commit=True` 工厂复现生产口径)。

**端到端验证**(viewpoint-baijiu,真 PG+真 LLM,Milvus collection 本环境缺失→向量路降级 BM25-only):
读侧从**全红**→ 2/7 绿(单跳召回直球 ✓「当初看多白酒核心逻辑」、克制弃答对抗 ✓「亏多少钱」正确拒答),
DetachedInstanceError 消失、召回→渲染→判分链路打通。**剩 5 红已是写侧内容保真度信号,非检索 bug**:
session 7 后 active 边仍是「看多」非「中性」(bi-temporal 机制对——3 版本链/2 作废 ✓,但抽取器没把「转中性」那轮读成中性 stance)→
归属台词精修(任务八/五批)+ 断言值校准,不再是检索层问题。memory 全套件回归仅 1 失败(Milvus alias 环境),无回归。

### 消融区分度实跑 + 裁判金标准扩样(2026-06-09 会话)

**消融区分度 runner 落地**(元评估第四步从"工具就位"→"实跑可跑"):
- `eval/memory_dialogue/ablation.py`:`separability_report`(读侧按维度×档、写侧按断言类型,逐 cell `separable()` + 方向解读)+ `format_separability_report`。5 单测守护。
- `meta_eval/run_ablation.py` CLI:完整版 vs 削弱版,各新建独立 user 跑同一批脚本;`--ablation read/write/both` + `--glob` 子集 + `--skip-read`。
- 两 knob 接在 `live_deps.build_live_runners`:写侧 `write_no_conflict_judge`(`HierarchicalMemory(llm_judge=None)`,已加 None 守卫降级 APPEND_NEW,`test_e2e_no_judge_degrades_to_append_new`)、读侧 `read_empty_retriever`(`_EmptyRetriever`)。
- **读侧 demo(viewpoint-baijiu 单脚本)**:方向全对——单跳召回/直球 完整1/1→削弱0/1、克制弃答/对抗 1/1=1/1(关键正对照:记忆关不影响弃答)、写侧 old_invalidated 完整2/2→削弱0/2;但 n=1 Wilson 全重叠→0/12 separable。结论:机器跑通+方向正确,统计"可区分"须多脚本聚合(`--glob viewpoint-* --ablation write` 8 段聚合跑见 README §四)。

**裁判金标准扩样 24→51**:multi-agent workflow(7 维度起草 + 对抗复核"标签可辩护性"防毒化金标准)产 25 条 + 手写 2 条底稿一致单跳召回。修正旧种子 #11 与底稿张冠李戴(三月新能源=阳光电源/120 非 180;180 属中际旭创/光模块/一月)。分布:单跳召回7/克制弃答10/偏好一致9/多跳6/知识更新7/时间6/持仓6,18 正 33 负(负例多=放水点边界)。**判分一致复测 51 条:agreement 1.000 / kappa 1.000 / 0 漏 0 误**,33 条放水点负例全被裁判抓出。

### 任务八 / 机动段 lead(留待"双人定稿"用户审稿门)

spec 要求 28 段脚本"双人定稿(Claude 草稿 + 用户审真实感)",**机动段 = dogfood 真实翻车案例**。本轮 dogfood 抓到的真翻车,正是机动段天然素材 + 任务八台词精修的主攻方向:
- **观点演化写侧红 — 诊断纠正了根因(2026-06-09 dump 实证)**:先前推测「转中性抽取丢失 / 助手复述旁白淹没」。`_diag_viewpoint_edges.py` dump 全部 EXPRESSED_VIEW 边后**推翻该推测**,真相是:
  1. **中性抽到了、是 active、事件时间对**(`白酒` 节点,from=2025-04-01,props.view=中性,reason="看多我收回 转中性")。抽取没漏、助手旁白没淹没。
  2. **真根因=实体规整漂移**:看多三年→两年链落在 `白酒Ⅱ` 节点(结束于 2025-03-22),中性落在 `白酒` 节点——**两个不同 target node**。中性因此没去作废早先看多(不同实体≠冲突),bi-temporal 演化链断开 → `old_invalidated`/`invalidated_chain_intact`/`fact_active(中性)` 断言据此红。registry `normalize_entity` 对 Industry 是 passthrough(申万 registry 留 v1.x 未接),白酒/白酒Ⅱ/高端白酒 不归一。
  3. **抽取非确定性**:本次 dump 中性是 active(写侧本应大面积绿),先前 eval 跑出来 active 是看多两年——**同脚本不同次抽取结果不同**,写侧红绿有 run-to-run 方差(评估可靠性问题:单跑不可靠,需多跑取多数或报方差)。
  **对任务八/系统侧的指引(修正后)**:① 系统侧治本=Industry 实体归一(白酒↔白酒Ⅱ↔高端白酒 → 一个 canonical 节点,演化链才不断;需接申万 registry 或加 alias 映射);② 抽取非确定性=eval 改多跑聚合 / 报方差,别单跑下结论;③ 台词侧助手复述旁白虽非本案 deterministic 根因,但可能加剧方差,仍值得消噪。属写管线保真度 + 评估可靠性,非检索层。诊断脚本 `_diag_viewpoint_edges.py` 留作复诊工具。

  **用户决策(2026-06-09)**:系统侧治本走**接申万 registry**(原 spec 留 v1.x,现提前)。
  这是独立新子系统,按项目纪律先定最小化设计、用户过目再实现。粗设计:① 用已有
  `app/data/tushare_client.py` + `tushare_cache.py` 调申万 `index_classify`(一/二/三级行业)
  缓存成本地层级表;② `industry_registry.normalize_industry(label)`:自由文本 label →
  申万 canonical(白酒Ⅱ 是申万二级正式名;高端白酒/白酒 等自由表述靠 alias + 模糊匹配
  /已有 qwen embedding 归到白酒Ⅱ);③ 接进 `registry.normalize_entity` 的 Industry 分支
  (当前 passthrough);④ TDD + 重跑 viewpoint 族验证演化链落同一节点、写侧红转绿。
  抽取非确定性(eval 多跑聚合/报方差)作为配套,可同期或另起。台词消噪降为可选 nice-to-have。

### 申万 registry 系统侧治本 — 已交付(2026-06-09)

- **`app/memory/industry_registry.py`**:`normalize_industry(label) -> (canonical, audit_flag)`。归一顺序:直命中申万二级正式名 → alias 精确表(高端白酒/次高端/白酒→白酒Ⅱ 等)→ contains 词根模糊 → 认不出 passthrough+audit。申万全集优先 Tushare `index_classify(SW2021,L2)` 缓存,无 token 降级内置 `_SW_L2_SEED`(14 个常用二级,够评估)。
- **接进 `registry.normalize_entity`**:Industry 分支从 passthrough 改调 `normalize_industry`(Sector 仍 passthrough,留后续)。7 单测(白酒系归一同 canonical / 申万正式名免 audit / 白酒≠医药不误并 / 生造行业 passthrough+audit)+ 既有 registry 测试改写为新行为。memory 全单测 rc=0 无回归,ruff+mypy 清。
- **诊断复跑结论(重要,如实)**:申万归一**确实生效**(白酒Ⅱ 作为 canonical 出现、中性落白酒Ⅱ),但**是必要非充分**——单脚本重跑暴露**抽取非确定性是主导残留问题**:同一句「看多高端白酒」不同次被抽成 Industry白酒Ⅱ / Stock茅台五粮液 / 甚至整句「看多高端白酒」当实体,还有 valid_to=2027 这类幻觉日期。归一治不了实体**类型**漂移(Industry vs Stock)与整体抽取抖动。
- **配套已加 `run_eval --repeat N`**:每段跑 N 次结果池化进同一分数表,通过率配 Wilson 区间——这是对**非确定系统**的唯一可信判法(单跑 1/1 不能下结论)。`--repeat 3 viewpoint-baijiu` 验证组合效果(写侧通过率稳定化)。

**`--repeat 3` 量化判定(viewpoint-baijiu,2026-06-09)**:写侧聚合 **3/24 通过,Wilson 95% [0.04-0.31]**——3 次跑结构各不同(看多落 Stock600519 / Industry白酒Ⅱ / Concept提价权 互换,PREFERS 替代 EXPRESSED_VIEW,幻觉日期 2025-04-01至4-10,链长 1/2/2 版本飘)。**这正是 --repeat 的价值**:把单跑的脆判定换成带误差棒的可信率,诚实量化出"该系统在多会话观点演化场景的写侧保真度仅 ~12%"。评估在正确做它该做的事——量化系统最弱区,而非被单跑假象骗。

**TODO⑤ 收口口径**:用户选的系统侧治本(接申万 registry)**已交付**且单测确定性证明归一正确、零回归;评估可靠性配套(--repeat 多跑取率)已落并量化出真实保真度。**真正的写侧天花板是抽取非确定性 + 实体类型/关系漂移**(看多被抽成 Stock/Industry/Concept、EXPRESSED_VIEW↔PREFERS、幻觉日期)——这属抽取器质量/prompt 工程(实体类型约束 + 输出确定性 + 日期不许编),数量级大于实体归一,是独立后续 spec。台词精修 27 段(spec「双人定稿」用户审稿门)与机动段(用此 dogfood 真翻车做素材)留用户协作。
