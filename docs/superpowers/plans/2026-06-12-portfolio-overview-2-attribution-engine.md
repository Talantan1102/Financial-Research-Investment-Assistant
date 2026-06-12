# 持仓总览 ②引擎层:算账(组合归因)+ 复盘快照 + AI 叙事 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现"账户为什么涨跌"的确定性拆账计算、支撑复盘的每日持仓快照与剔除加减仓的链式收益、以及把算好的数翻成人话的 AI 叙事(AI 只讲不算)。

**Architecture:** 拆账 = **后端纯函数确定性计算**(`portfolio_analytics.py`),输入持仓+行情、输出三层拆解,加总闭合可单测;复盘 = 每日 `PositionSnapshot` 表(模仿 `trace_models.py` 时序表)+ 时间加权链式收益纯函数;叙事 = 复用 monitoring 详情卡同款 LLM 调用,把拆好的数字作为输入,产出短文,**断言数字来自输入而非 LLM 杜撰、且不含买卖建议**。

**Tech Stack:** Python / SQLAlchemy(PG)/ Celery / pytest(`db_session` savepoint 隔离)/ 现有 LLM 客户端。

> 依赖:①底子层(`asset_class` 字段 + 取数工具)已落地。设计稿:`docs/superpowers/specs/2026-06-12-portfolio-overview-design.md` §3a(无现金流→只算市场赚赔;复盘剔除加减仓)、§4.1(取数/算账/讲人话三分界)。
> 复用(别重造):单只市值/浮盈 `backend/app/chatloop/portfolio_tool.py:56-71`;持仓重算 `backend/app/services/portfolio_recompute.py:36-76`;读持仓 `backend/app/services/position_service.py:17-48`。

---

### Task 1: 拆账纯函数 `compute_daily_attribution`(确定性,可单测闭合)

**Files:**
- Create: `backend/app/services/portfolio_analytics.py`
- Test: `backend/tests/unit/services/test_portfolio_attribution.py`(模仿 `backend/tests/unit/agents/valuation_helpers/test_pe.py` 的纯计算断言)

- [ ] **Step 1: 写失败的单元测试(数值闭合 + 三层拆解)**

`backend/tests/unit/services/test_portfolio_attribution.py`:

```python
import pytest
from app.services.portfolio_analytics import HoldingDaily, compute_daily_attribution


def _holdings():
    return [
        # 茅台:仓位3万、当日-3.5%、白酒板块-3.0%、大盘-0.8%
        HoldingDaily(ts_code="600519.SH", asset_class="stock", market_value=30000,
                     today_pct=-3.5, sector="白酒", sector_pct=-3.0, market_pct=-0.8),
        # 招行:仓位2万、当日+0.5%、银行板块+0.2%、大盘-0.8%
        HoldingDaily(ts_code="600036.SH", asset_class="stock", market_value=20000,
                     today_pct=0.5, sector="银行", sector_pct=0.2, market_pct=-0.8),
        # 基金:仓位5万、当日-0.2%(不拆板块)
        HoldingDaily(ts_code="110011.OF", asset_class="fund_otc", market_value=50000,
                     today_pct=-0.2),
    ]


def test_total_pct_is_weighted_sum() -> None:
    r = compute_daily_attribution(_holdings())
    # 0.3*-3.5 + 0.2*0.5 + 0.5*-0.2 = -1.05
    assert r.total_pct == pytest.approx(-1.05, abs=1e-9)


def test_by_class_sums_to_total() -> None:
    r = compute_daily_attribution(_holdings())
    assert r.by_class["stock"] == pytest.approx(-0.95, abs=1e-9)
    assert r.by_class["fund_otc"] == pytest.approx(-0.10, abs=1e-9)
    assert sum(r.by_class.values()) == pytest.approx(r.total_pct, abs=1e-9)


def test_stock_three_layer_closure() -> None:
    r = compute_daily_attribution(_holdings())
    s = r.stock_breakdown
    assert s["market"] == pytest.approx(-0.40, abs=1e-9)          # 0.5 * -0.8
    assert s["sector_excess"] == pytest.approx(-0.46, abs=1e-9)   # 0.3*(-2.2)+0.2*(1.0)
    assert s["idiosyncratic"] == pytest.approx(-0.09, abs=1e-9)   # 0.3*(-0.5)+0.2*(0.3)
    # 三层加总必须严丝合缝等于股票部分贡献
    assert s["market"] + s["sector_excess"] + s["idiosyncratic"] == pytest.approx(r.by_class["stock"], abs=1e-9)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/unit/services/test_portfolio_attribution.py -v`
Expected: FAIL — ModuleNotFoundError: app.services.portfolio_analytics

- [ ] **Step 3: 实现纯函数**

`backend/app/services/portfolio_analytics.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class HoldingDaily:
    ts_code: str
    asset_class: str            # stock / fund_etf / fund_otc / bond / gold / cash
    market_value: float         # 当前市值(权重分母)
    today_pct: float            # 该持仓当日涨跌 %
    sector: str | None = None
    sector_pct: float | None = None     # 所属板块当日 %(仅 stock 用)
    market_pct: float | None = None     # 大盘(沪深300)当日 %(仅 stock 用)


@dataclass
class AttributionResult:
    total_pct: float
    by_class: dict[str, float]
    stock_breakdown: dict[str, float]   # market / sector_excess / idiosyncratic
    contributions: list[dict] = field(default_factory=list)  # 每只票对总盘的贡献,供"哪几只拖累最大"


def compute_daily_attribution(holdings: list[HoldingDaily]) -> AttributionResult:
    """确定性拆账。无现金流口径:只拆'市场赚赔'。MVP 取 beta≈1。"""
    total_mv = sum(h.market_value for h in holdings)
    if total_mv <= 0:
        return AttributionResult(0.0, {}, {"market": 0.0, "sector_excess": 0.0, "idiosyncratic": 0.0})

    by_class: dict[str, float] = {}
    contributions: list[dict] = []
    market = sector_excess = idio = 0.0

    for h in holdings:
        w = h.market_value / total_mv
        contrib = w * h.today_pct                 # 该持仓对总盘的贡献(百分点)
        by_class[h.asset_class] = by_class.get(h.asset_class, 0.0) + contrib
        contributions.append({"ts_code": h.ts_code, "asset_class": h.asset_class, "contrib_pct": contrib})

        if h.asset_class == "stock" and h.market_pct is not None and h.sector_pct is not None:
            market += w * h.market_pct
            sector_excess += w * (h.sector_pct - h.market_pct)
            idio += w * (h.today_pct - h.sector_pct)

    total = sum(by_class.values())
    contributions.sort(key=lambda c: c["contrib_pct"])  # 最拖累的在前
    return AttributionResult(
        total_pct=round(total, 6),
        by_class={k: round(v, 6) for k, v in by_class.items()},
        stock_breakdown={"market": round(market, 6), "sector_excess": round(sector_excess, 6), "idiosyncratic": round(idio, 6)},
        contributions=contributions,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/unit/services/test_portfolio_attribution.py -v`
Expected: PASS(4 passed)

- [ ] **Step 5: 提交**
```bash
git add backend/app/services/portfolio_analytics.py backend/tests/unit/services/test_portfolio_attribution.py
git commit -m "feat(portfolio): 拆账纯函数 compute_daily_attribution(三层闭合,确定性)"
```

---

### Task 2: 每日持仓快照表 + 仓库层(支撑复盘)

**Files:**
- Create: `backend/app/models/position_snapshot.py`
- Modify: `backend/app/models/__init__.py`(barrel 导入 + `__all__`)
- Create: `backend/app/services/position_snapshot_repo.py`
- Test: `backend/tests/integration/test_position_snapshot_repo.py`(用 `db_session`)

- [ ] **Step 1: 写失败的集成测试**

`backend/tests/integration/test_position_snapshot_repo.py`(模仿 `backend/tests/unit/services/test_monitoring_repositories.py:27-50`):

```python
import datetime as dt
from app.services.position_snapshot_repo import PositionSnapshotRepo


def test_upsert_and_read_by_user(db_session):
    repo = PositionSnapshotRepo(db_session)
    d = dt.date(2026, 11, 14)
    repo.upsert(user_id=None, ts_code="600519.SH", snapshot_date=d,
                quantity=100, market_price=1650.0, market_value=165000.0, asset_class="stock")
    db_session.flush()
    rows = repo.list_for_user_date(user_id=None, snapshot_date=d)
    assert len(rows) == 1
    assert rows[0].ts_code == "600519.SH"
    assert float(rows[0].market_value) == 165000.0
```

- [ ] **Step 2: 跑确认失败** — `pytest backend/tests/integration/test_position_snapshot_repo.py -v` → FAIL(ModuleNotFoundError)

- [ ] **Step 3: ORM 模型**(模仿 `backend/app/services/trace_models.py:142-162` 时序表 + `position.py` 精度)

`backend/app/models/position_snapshot.py`:

```python
import datetime
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"

    id = Column(String(36), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    ts_code = Column(String(10), nullable=False, index=True)
    asset_class = Column(String(32), nullable=False, default="stock")
    snapshot_date = Column(Date, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    market_price = Column(Numeric(12, 4), nullable=False)
    market_value = Column(Numeric(14, 2), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "ts_code", "snapshot_date", name="uq_snapshot_user_code_date"),
        Index("idx_snapshot_user_date", "user_id", "snapshot_date"),
    )
```

`backend/app/models/__init__.py`:加 `from app.models.position_snapshot import PositionSnapshot` 并加入 `__all__`。

- [ ] **Step 4: 仓库层**

`backend/app/services/position_snapshot_repo.py`:

```python
import uuid, datetime
from sqlalchemy.orm import Session
from app.models.position_snapshot import PositionSnapshot


class PositionSnapshotRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def upsert(self, *, user_id, ts_code, snapshot_date, quantity, market_price, market_value, asset_class="stock") -> None:
        row = (self._s.query(PositionSnapshot)
               .filter_by(user_id=user_id, ts_code=ts_code, snapshot_date=snapshot_date).one_or_none())
        if row is None:
            row = PositionSnapshot(id=str(uuid.uuid4()), user_id=user_id, ts_code=ts_code, snapshot_date=snapshot_date)
            self._s.add(row)
        row.quantity = quantity
        row.market_price = market_price
        row.market_value = market_value
        row.asset_class = asset_class

    def list_for_user_date(self, *, user_id, snapshot_date):
        return (self._s.query(PositionSnapshot)
                .filter_by(user_id=user_id, snapshot_date=snapshot_date).all())

    def list_range(self, *, user_id, start_date, end_date):
        return (self._s.query(PositionSnapshot)
                .filter(PositionSnapshot.user_id == user_id,
                        PositionSnapshot.snapshot_date >= start_date,
                        PositionSnapshot.snapshot_date <= end_date)
                .order_by(PositionSnapshot.snapshot_date).all())
```

- [ ] **Step 5: 跑测试确认通过** — `pytest backend/tests/integration/test_position_snapshot_repo.py -v` → PASS

- [ ] **Step 6: 提交**
```bash
git add backend/app/models/position_snapshot.py backend/app/models/__init__.py backend/app/services/position_snapshot_repo.py backend/tests/integration/test_position_snapshot_repo.py
git commit -m "feat(portfolio): 每日持仓快照表 + 仓库层(支撑复盘)"
```

---

### Task 3: 复盘时间加权链式收益纯函数(剔除加减仓)

**Files:**
- Modify: `backend/app/services/portfolio_analytics.py`(加 `compute_twr`)
- Test: `backend/tests/unit/services/test_portfolio_twr.py`

- [ ] **Step 1: 写失败的单元测试 —— 中途加仓不污染收益**

`backend/tests/unit/services/test_portfolio_twr.py`:

```python
import pytest
from app.services.portfolio_analytics import DailySnap, compute_twr


def test_twr_excludes_position_changes() -> None:
    # 第1天→第2天:持仓不变,价从100→110,日收益+10%
    # 第2天→第3天:期初(第2天)持仓在第3天估值得日收益;即便第3天加了仓也不算进收益
    snaps = [
        DailySnap(date="20261112", holdings={"A": (100, 100.0)}),   # (qty, price)
        DailySnap(date="20261113", holdings={"A": (100, 110.0)}),
        DailySnap(date="20261114", holdings={"A": (200, 99.0)}),    # 加了100股 + 价跌到99
    ]
    twr = compute_twr(snaps)
    # day1 收益 = 110/100-1 = +0.10
    # day2 收益:用第2天持仓(100股)在 day3 价 99 vs day2 价 110 = 99/110-1 = -0.10
    #   注意:第3天多出的100股是"加仓",不计入收益
    # 链式:(1.10)*(0.90)-1 = -0.01
    assert twr["cumulative"] == pytest.approx(-0.01, abs=1e-9)
    assert twr["daily"][0] == pytest.approx(0.10, abs=1e-9)
    assert twr["daily"][1] == pytest.approx(-0.0909090909, abs=1e-6)
```

- [ ] **Step 2: 跑确认失败** — `pytest backend/tests/unit/services/test_portfolio_twr.py -v` → FAIL

- [ ] **Step 3: 实现 `DailySnap` + `compute_twr`**

`backend/app/services/portfolio_analytics.py` 追加:

```python
@dataclass
class DailySnap:
    date: str
    holdings: dict[str, tuple[int, float]]   # ts_code -> (qty, price)


def compute_twr(snaps: list[DailySnap]) -> dict:
    """时间加权链式收益:用每日'期初持仓'估值算当日纯市场收益,剔除加减仓。"""
    snaps = sorted(snaps, key=lambda s: s.date)
    daily: list[float] = []
    cum = 1.0
    for prev, cur in zip(snaps, snaps[1:]):
        # 用 prev(期初)的持仓数量,分别按 prev、cur 当日价估值
        base = sum(qty * prev.holdings[c][1] for c, (qty, _) in prev.holdings.items())
        nowv = sum(qty * cur.holdings.get(c, (0, prev.holdings[c][1]))[1]
                   for c, (qty, _) in prev.holdings.items())
        r = (nowv / base - 1.0) if base else 0.0
        daily.append(round(r, 10))
        cum *= (1.0 + r)
    return {"daily": daily, "cumulative": round(cum - 1.0, 10)}
```

- [ ] **Step 4: 跑测试确认通过** — `pytest backend/tests/unit/services/test_portfolio_twr.py -v` → PASS

- [ ] **Step 5: 提交**
```bash
git add backend/app/services/portfolio_analytics.py backend/tests/unit/services/test_portfolio_twr.py
git commit -m "feat(portfolio): 复盘时间加权链式收益(剔除加减仓,确定性)"
```

---

### Task 4: 聚合服务 `build_overview` —— 串起取数 + 拆账(给后端 endpoint 用)

**Files:**
- Create: `backend/app/services/portfolio_overview_service.py`
- Test: `backend/tests/integration/test_portfolio_overview_service.py`(用 `db_session` + mock tushare via `build_tushare_service`(TUSHARE_MODE=mock 确定性))

- [ ] **Step 1: 写失败的集成测试**

```python
import pytest
from app.services.portfolio_overview_service import build_overview


@pytest.mark.asyncio
async def test_build_overview_returns_attribution_and_structure(db_session, monkeypatch):
    monkeypatch.setenv("TUSHARE_MODE", "mock")
    from app.models.position import Position
    db_session.add_all([
        Position(id="a", user_id=None, ts_code="600519.SH", name="茅台", quantity=100,
                 avg_cost=1500, total_cost=150000, last_quote_price=1650, asset_class="stock"),
        Position(id="f", user_id=None, ts_code="110011.OF", name="基金", quantity=10000,
                 avg_cost=2.5, total_cost=25000, last_quote_price=2.475, asset_class="fund_otc"),
    ])
    db_session.flush()

    ov = await build_overview(db_session, user_id=None)
    assert "attribution" in ov and "structure" in ov
    assert ov["structure"]["by_class"]["stock"] > 0    # 占比 > 0
    assert isinstance(ov["attribution"]["total_pct"], float)
```

- [ ] **Step 2: 跑确认失败** — FAIL(ModuleNotFoundError)

- [ ] **Step 3: 实现聚合服务**

`backend/app/services/portfolio_overview_service.py`:读持仓(`PositionService.list_for_user`)→ 对每只票按 `asset_class` 取当日涨跌(stock 用 `get_daily` 最近两日算 pct + `get_sector_daily` + `get_index_daily`;fund 用 `get_fund_nav`)→ 组装 `HoldingDaily` 列表 → `compute_daily_attribution` → 同时算"看结构"(按 `asset_class` 聚合市值占比 + 股票内按 sector 聚合 + 跨品种主题合并)→ 返回 dict `{attribution, structure, as_of}`。所有取数走 `build_tushare_service()`(测试时 mock 确定性)。

> 注意:基金大类拆解要带 `as_of` 季报日提示(设计稿 §4.2);跨品种暴露合并(白酒股+白酒主题基金)用基金名/类型关键词匹配,匹配不到就不合并、不硬猜。

- [ ] **Step 4: 跑测试确认通过 + 提交**
```bash
git add backend/app/services/portfolio_overview_service.py backend/tests/integration/test_portfolio_overview_service.py
git commit -m "feat(portfolio): build_overview 聚合(取数+拆账+看结构)"
```

---

### Task 5: AI 叙事 —— 把算好的数翻成人话(AI 只讲不算)

**Files:**
- Create: `backend/app/services/portfolio_narrator.py`
- Test: `backend/tests/integration/test_portfolio_narrator.py`(LLM_MODE=mock / cassette,模仿 monitoring 详情卡 `backend/app/tasks/monitoring.py:266-276` 的 LLM 调用方式)

- [ ] **Step 1: 写失败的测试 —— 叙事不算数、不荐股**

```python
import pytest
from app.services.portfolio_narrator import narrate_today


@pytest.mark.asyncio
async def test_narrate_uses_given_numbers_no_advice(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    attribution = {"total_pct": -1.05,
                   "stock_breakdown": {"market": -0.40, "sector_excess": -0.46, "idiosyncratic": -0.09},
                   "contributions": [{"ts_code": "600519.SH", "contrib_pct": -1.05}]}
    text = await narrate_today(attribution, persona_note="用户在意白酒仓位")
    assert isinstance(text, str) and len(text) > 0
    # 红线:不得出现买卖建议词
    for banned in ("建议买", "建议卖", "应该减仓", "应该加仓", "清仓"):
        assert banned not in text
```

- [ ] **Step 2: 跑确认失败** — FAIL

- [ ] **Step 3: 实现叙事**

`backend/app/services/portfolio_narrator.py`:构造 prompt(系统提示明确"你只负责把给定数字讲成人话,**禁止给买卖建议、禁止自己编造或重算数字、禁止预测涨跌**;挑最该说的一两件;可结合用户在意点")→ 复用现有 LLM 客户端(与 `generate_detail_card` 同款)→ 返回短文。`LLM_MODE=mock` 时返回结构化占位短文(确定性,供 L1 测试)。

- [ ] **Step 4: 跑测试确认通过 + 提交**
```bash
git add backend/app/services/portfolio_narrator.py backend/tests/integration/test_portfolio_narrator.py
git commit -m "feat(portfolio): AI 叙事(只讲不算,禁买卖建议)"
```

---

### Task 6: 每日快照 Celery 任务(收盘后存一张)

**Files:**
- Modify: `backend/app/tasks/monitoring.py`(加 `snapshot_portfolios` task,或新文件 `backend/app/tasks/portfolio_snapshot.py`)
- Modify: Celery beat 配置(与 `daily_full_scan` 16:30 同侧,加 16:35 快照)
- Test: `backend/tests/e2e/test_portfolio_snapshot_task.py`(eager 模式)

- [ ] **Step 1-5:** 写失败的 eager 测试(模仿现有 monitoring task 测试)→ 实现 task:遍历有持仓的 user → 对每只持仓取当日价 → `PositionSnapshotRepo.upsert` → 跑通 → 提交。

```bash
git commit -m "feat(portfolio): 每日持仓快照 Celery 任务(收盘后)"
```

---

## Self-Review

- **Spec 覆盖**:§4.1 拆账三分界(Task1 算账纯函数 + Task5 叙事只讲不算)、§3a 复盘剔除加减仓(Task3 TWR)、§4.2/4.3 看结构与复盘数据(Task4 聚合 + Task2/6 快照)。✅
- **占位扫描**:Task4/Task5/Task6 的 Step 3 用文字描述了实现逻辑而非贴全码——因这些是"编排/IO"类、依赖①层工具签名与现有 LLM 客户端;核心**确定性计算**(Task1/Task3)给了完整真码与闭合断言。可接受,但执行 Task4-6 时须按描述补全,不得留 TODO。⚠️(执行者注意)
- **类型一致**:`HoldingDaily` / `AttributionResult` / `DailySnap` / `compute_twr` 字段名在 Task1/3/4 间一致;`PositionSnapshotRepo.upsert` 签名在 Task2 定义、Task6 调用一致。✅
- **数值闭合**:Task1 测试用手算值(总 -1.05;股票三层 -0.40/-0.46/-0.09 和为 -0.95)硬断言,杜绝"算错也过"。
