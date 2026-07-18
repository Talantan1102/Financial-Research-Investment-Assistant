# Paper Trading Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立单用户默认模拟账户、版本化 A 股规则、真实交易时钟、五档实时行情协议和可审计资金/持股底座。

**Architecture:** 新增独立 `app.services.paper_trading` 包，所有金额使用 `Decimal`，所有市场判断通过可注入的 `TradingClock`、`RealtimeQuoteProvider` 和 `RuleBook` 完成。账户、流水、持股批次和重置审计进入 PostgreSQL；本计划不创建订单，也不接 Chat Agent。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2.x、PostgreSQL、Pydantic v2、Tushare SDK、pytest、Hypothesis、ruff、mypy

---

## 文件边界

- Create: `backend/app/models/paper_account.py` — 账户、资金流水、持股批次、重置审计 ORM。
- Modify: `backend/app/models/__init__.py` — 注册新 ORM，确保 `create_all()` 与测试元数据能发现表。
- Create: `backend/app/services/paper_trading/types.py` — 行情、时钟、规则与费用的不可变值对象。
- Create: `backend/app/services/paper_trading/clock.py` — 生产/测试市场时钟。
- Create: `backend/app/services/paper_trading/quote_provider.py` — 五档行情协议、Tushare 实现和测试实现。
- Create: `backend/app/services/paper_trading/rulebook.py` — 按市场、板块、风险警示和生效日选择规则。
- Create: `backend/app/services/paper_trading/rules/a_share_20260706.json` — 已核验的版本化规则和来源。
- Create: `backend/app/services/paper_trading/account_service.py` — 默认账户、账本、批次与内部重置事务。
- Create: `backend/app/schemas/paper_trading.py` — 账户读取 schema。
- Create: `backend/app/router/paper_trading_router.py` — `GET /api/v0/paper-trading/account`。
- Modify: `backend/app/app_main.py` — 注册 router。
- Create: `backend/tests/unit/services/paper_trading/*` — 纯规则、时钟、行情映射测试。
- Create: `backend/tests/integration/paper_trading/test_account_foundation.py` — PostgreSQL 账户与账本测试。

### Task 1: 建立领域值对象和稳定错误码

**Files:**
- Create: `backend/app/services/paper_trading/__init__.py`
- Create: `backend/app/services/paper_trading/types.py`
- Create: `backend/app/services/paper_trading/errors.py`
- Test: `backend/tests/unit/services/paper_trading/test_types.py`

- [ ] **Step 1: 写失败测试，锁定 Decimal、五档和错误码契约**

```python
from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote


def test_quote_rejects_float_and_requires_five_levels() -> None:
    with pytest.raises(ValidationError):
        RealtimeQuote(
            ts_code="600519.SH",
            name="贵州茅台",
            quoted_at=datetime(2026, 7, 20, 10, 0),
            previous_close=1500.0,
            last_price=Decimal("1501.00"),
            bids=[],
            asks=[],
            source="fixture",
            suspended=False,
        )


def test_error_exposes_stable_code() -> None:
    exc = PaperTradingError("stale_quote", "行情已过期")
    assert exc.code == "stale_quote"
    assert str(exc) == "行情已过期"
```

- [ ] **Step 2: 运行测试并确认因模块不存在失败**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_types.py -q`

Expected: FAIL，错误包含 `ModuleNotFoundError: No module named 'app.services.paper_trading'`。

- [ ] **Step 3: 实现严格值对象和错误类型**

```python
# backend/app/services/paper_trading/types.py
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarketPhase(StrEnum):
    CLOSED = "closed"
    OPENING_AUCTION = "opening_auction"
    MORNING = "morning"
    LUNCH = "lunch"
    AFTERNOON = "afternoon"
    CLOSING_AUCTION = "closing_auction"


class QuoteLevel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    price: Decimal = Field(gt=0)
    quantity: int = Field(ge=0)


class RealtimeQuote(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    ts_code: str
    name: str
    quoted_at: datetime
    previous_close: Decimal = Field(gt=0)
    last_price: Decimal = Field(gt=0)
    bids: tuple[QuoteLevel, ...]
    asks: tuple[QuoteLevel, ...]
    source: str
    suspended: bool

    @field_validator("bids", "asks")
    @classmethod
    def five_levels(cls, value: tuple[QuoteLevel, ...]) -> tuple[QuoteLevel, ...]:
        if len(value) != 5:
            raise ValueError("exactly five quote levels required")
        return value


class RuleSet(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    version: str
    effective_from: date
    board: str
    risk_warning: bool
    side: str
    buy_lot_size: int
    price_tick: Decimal
    price_limit_ratio: Decimal
    quote_freshness_seconds: int


class FeeBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.stamp_duty + self.transfer_fee
```

```python
# backend/app/services/paper_trading/errors.py
class PaperTradingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_types.py -q`

Expected: `2 passed`。

- [ ] **Step 5: 提交领域类型**

```bash
git add backend/app/services/paper_trading backend/tests/unit/services/paper_trading/test_types.py
git commit -m "feat(paper): add strict trading domain types"
```

### Task 2: 实现可注入市场时钟

**Files:**
- Create: `backend/app/services/paper_trading/clock.py`
- Test: `backend/tests/unit/services/paper_trading/test_clock.py`

- [ ] **Step 1: 写开市、午休、收盘和下一交易日失败测试**

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.paper_trading.clock import FixedTradingCalendar, TradingClock
from app.services.paper_trading.types import MarketPhase

SH = ZoneInfo("Asia/Shanghai")


def test_market_phases_and_next_open_day() -> None:
    calendar = FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)})
    assert TradingClock(calendar).phase(datetime(2026, 7, 20, 10, 0, tzinfo=SH)) == MarketPhase.MORNING
    assert TradingClock(calendar).phase(datetime(2026, 7, 20, 9, 20, tzinfo=SH)) == MarketPhase.OPENING_AUCTION
    assert TradingClock(calendar).phase(datetime(2026, 7, 20, 12, 0, tzinfo=SH)) == MarketPhase.LUNCH
    assert TradingClock(calendar).phase(datetime(2026, 7, 20, 14, 58, tzinfo=SH)) == MarketPhase.CLOSING_AUCTION
    assert TradingClock(calendar).phase(datetime(2026, 7, 20, 15, 1, tzinfo=SH)) == MarketPhase.CLOSED
    assert calendar.next_open_date(date(2026, 7, 20)) == date(2026, 7, 21)
```

- [ ] **Step 2: 运行并确认失败**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_clock.py -q`

Expected: FAIL，缺少 `clock` 模块。

- [ ] **Step 3: 实现时区明确的时钟**

```python
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from app.services.paper_trading.types import MarketPhase

SHANGHAI = ZoneInfo("Asia/Shanghai")


class TradingCalendar(Protocol):
    def is_open_date(self, value: date) -> bool:
        raise NotImplementedError
    def next_open_date(self, value: date) -> date:
        raise NotImplementedError


class FixedTradingCalendar:
    def __init__(self, open_dates: set[date]) -> None:
        self._open_dates = open_dates

    def is_open_date(self, value: date) -> bool:
        return value in self._open_dates

    def next_open_date(self, value: date) -> date:
        probe = value + timedelta(days=1)
        while probe not in self._open_dates:
            probe += timedelta(days=1)
        return probe


class TradingClock:
    def __init__(self, calendar: TradingCalendar) -> None:
        self.calendar = calendar

    def phase(self, now: datetime) -> MarketPhase:
        local = now.astimezone(SHANGHAI)
        if not self.calendar.is_open_date(local.date()):
            return MarketPhase.CLOSED
        t = local.time().replace(tzinfo=None)
        if time(9, 15) <= t < time(9, 25):
            return MarketPhase.OPENING_AUCTION
        if time(9, 30) <= t < time(11, 30):
            return MarketPhase.MORNING
        if time(11, 30) <= t < time(13, 0):
            return MarketPhase.LUNCH
        if time(13, 0) <= t < time(14, 57):
            return MarketPhase.AFTERNOON
        if time(14, 57) <= t < time(15, 0):
            return MarketPhase.CLOSING_AUCTION
        return MarketPhase.CLOSED
```

首版撮合只支持连续竞价的 `MORNING/AFTERNOON`。集合竞价阶段的限价单进入 `queued`，市价单返回 `market_closed_for_market_order`；不使用五档深度伪造集合竞价成交。

- [ ] **Step 4: 运行测试**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_clock.py -q`

Expected: `1 passed`。

- [ ] **Step 5: 提交时钟**

```bash
git add backend/app/services/paper_trading/clock.py backend/tests/unit/services/paper_trading/test_clock.py
git commit -m "feat(paper): add deterministic market clock"
```

### Task 3: 固化 2026-07-06 生效的 A 股规则

**Files:**
- Create: `backend/app/services/paper_trading/rules/a_share_20260706.json`
- Create: `backend/app/services/paper_trading/rulebook.py`
- Test: `backend/tests/unit/services/paper_trading/test_rulebook.py`

- [ ] **Step 1: 写规则选择与 fail-closed 测试**

```python
from datetime import date
from decimal import Decimal

import pytest

from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.rulebook import RuleBook


def test_rulebook_selects_board_and_risk_warning() -> None:
    rules = RuleBook.from_builtin_fixture()
    main = rules.resolve(ts_code="600519.SH", board="main", risk_warning=False, on=date(2026, 7, 20))
    star = rules.resolve(ts_code="688001.SH", board="star", risk_warning=False, on=date(2026, 7, 20))
    assert main.buy_lot_size == 100
    assert main.price_limit_ratio == Decimal("0.10")
    assert star.price_limit_ratio == Decimal("0.20")


def test_unknown_regime_fails_closed() -> None:
    with pytest.raises(PaperTradingError, match="特殊交易阶段") as caught:
        RuleBook.from_builtin_fixture().resolve(
            ts_code="600000.SH", board="main", risk_warning=False,
            on=date(2026, 7, 20), special_regime="ipo_unlimited",
        )
    assert caught.value.code == "unsupported_trading_regime"
```

- [ ] **Step 2: 运行并确认失败**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_rulebook.py -q`

Expected: FAIL，缺少 `RuleBook`。

- [ ] **Step 3: 写版本化 fixture，保留官方来源和核验日期**

```json
{
  "version": "cn-a-2026-07-06-v1",
  "effective_from": "2026-07-06",
  "verified_on": "2026-07-18",
  "sources": [
    "https://www.sse.com.cn/lawandrules/sselawsrules2025/fund/trading/c/c_20260424_10817739.shtml",
    "https://www.szse.cn/lawrules/rule/allrules/bussiness/t20260424_620190.html"
  ],
  "defaults": {"buy_lot_size": 100, "price_tick": "0.01", "quote_freshness_seconds": 15},
  "boards": {
    "main": {"normal_limit_ratio": "0.10", "risk_warning_limit_ratio": "0.05"},
    "star": {"normal_limit_ratio": "0.20", "risk_warning_limit_ratio": "0.20"},
    "chinext": {"normal_limit_ratio": "0.20", "risk_warning_limit_ratio": "0.20"}
  }
}
```

- [ ] **Step 4: 实现 RuleBook 的加载、日期选择、价格范围和手数校验**

`RuleBook` 必须提供四个 public 方法：`from_builtin_fixture() -> RuleBook`、`resolve(ts_code, board, risk_warning, side, on, special_regime=None) -> RuleSet`、`validate_quantity(rules, quantity, current_holding=0) -> None`、`price_bounds(rules, previous_close) -> tuple[Decimal, Decimal]`。加载时把 JSON 字符串显式转为 `Decimal`；价格上下限按 `price_tick` 量化。买入必须是 100 股整数倍；卖出允许把不足 100 股的剩余零股一次性全部卖出，但禁止拆卖零股。`special_regime` 非空立即抛 `PaperTradingError("unsupported_trading_regime", "首版不支持该特殊交易阶段")`。

- [ ] **Step 5: 运行规则测试**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_rulebook.py -q`

Expected: `2 passed`。

- [ ] **Step 6: 提交规则引擎**

```bash
git add backend/app/services/paper_trading/rulebook.py backend/app/services/paper_trading/rules backend/tests/unit/services/paper_trading/test_rulebook.py
git commit -m "feat(paper): add versioned A-share rulebook"
```

### Task 3A: 建立按生效日版本化的费用表

**Files:**
- Create: `backend/app/services/paper_trading/rules/fees_cn_a_20230828.json`
- Create: `backend/app/services/paper_trading/fee_schedule.py`
- Test: `backend/tests/unit/services/paper_trading/test_fee_schedule.py`

- [ ] **Step 1: 写买卖方向、最低佣金和 Decimal 舍入测试**

```python
def test_fee_schedule_applies_sell_only_stamp_duty_and_minimum_commission() -> None:
    fees = FeeSchedule.from_builtin_fixture()
    buy = fees.calculate(side="buy", gross=Decimal("1000"))
    sell = fees.calculate(side="sell", gross=Decimal("1000"))
    assert buy.commission == Decimal("5.00")
    assert buy.stamp_duty == Decimal("0.00")
    assert sell.stamp_duty == Decimal("0.50")
    assert sell.total > buy.total
```

- [ ] **Step 2: 运行并确认缺少费用模块**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_fee_schedule.py -q`

Expected: FAIL，缺少 `FeeSchedule`。

- [ ] **Step 3: 写清来源、费率口径和可配置佣金**

fixture 保存 `version/effective_from/verified_on/sources`，以及卖方印花税 `0.0005`、双向过户费 `0.00001`。官方来源必须指向财政部/税务总局证券交易印花税公告、中国结算股票交易过户费公告和沪深交易所收费项目页面。券商佣金不冒充法定费率：由账户的 `commission_rate` 和 `minimum_commission` 传入，首版默认分别为 `0.0003` 和 `5.00`。

- [ ] **Step 4: 实现费用计算器**

```python
class FeeSchedule:
    @classmethod
    def from_builtin_fixture(cls) -> "FeeSchedule":
        path = Path(__file__).parent / "rules" / "fees_cn_a_20230828.json"
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def calculate(self, *, side: str, gross: Decimal, commission_rate: Decimal = Decimal("0.0003"), minimum_commission: Decimal = Decimal("5.00")) -> FeeBreakdown:
        commission = max(minimum_commission, gross * commission_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        stamp = (gross * Decimal("0.0005") if side == "sell" else Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        transfer = (gross * Decimal("0.00001")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return FeeBreakdown(commission=commission, stamp_duty=stamp, transfer_fee=transfer)
```

- [ ] **Step 5: 运行测试并提交**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_fee_schedule.py -q`

Expected: PASS。

```bash
git add backend/app/services/paper_trading/fee_schedule.py backend/app/services/paper_trading/rules/fees_cn_a_20230828.json backend/tests/unit/services/paper_trading/test_fee_schedule.py
git commit -m "feat(paper): add versioned trading fee schedule"
```

### Task 4: 实现五档实时行情 Provider

**Files:**
- Create: `backend/app/services/paper_trading/quote_provider.py`
- Test: `backend/tests/unit/services/paper_trading/test_quote_provider.py`

- [ ] **Step 1: 写字段映射、新鲜度和失败关闭测试**

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.quote_provider import TushareRealtimeQuoteProvider


@pytest.mark.asyncio
async def test_maps_five_levels_and_rejects_stale_quote() -> None:
    row = {"TS_CODE": "600519.SH", "NAME": "贵州茅台", "DATE": "20260720", "TIME": "10:00:00", "PRE_CLOSE": "1500", "PRICE": "1501"}
    for n in range(1, 6):
        row[f"BID{n}"] = str(1501 - n)
        row[f"BID_VOL{n}"] = str(n * 100)
        row[f"ASK{n}"] = str(1501 + n)
        row[f"ASK_VOL{n}"] = str(n * 200)
    provider = TushareRealtimeQuoteProvider(fetch=lambda _: pd.DataFrame([row]))
    quote = await provider.get("600519.SH")
    assert len(quote.bids) == len(quote.asks) == 5
    with pytest.raises(PaperTradingError) as caught:
        provider.assert_fresh(quote, datetime(2026, 7, 20, 10, 1, tzinfo=ZoneInfo("Asia/Shanghai")), 15)
    assert caught.value.code == "stale_quote"
```

- [ ] **Step 2: 运行并确认失败**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_quote_provider.py -q`

Expected: FAIL，缺少 provider。

- [ ] **Step 3: 实现协议、SDK 适配器和测试注入缝**

```python
class RealtimeQuoteProvider(Protocol):
    async def get(self, ts_code: str) -> RealtimeQuote:
        raise NotImplementedError


class TushareRealtimeQuoteProvider:
    def __init__(self, fetch: Callable[[str], pd.DataFrame] | None = None) -> None:
        self._fetch = fetch or self._sdk_fetch

    async def get(self, ts_code: str) -> RealtimeQuote:
        frame = await asyncio.to_thread(self._fetch, ts_code)
        if frame.empty:
            raise PaperTradingError("quote_unavailable", "实时行情不可用")
        return self._map_row(frame.iloc[0])

    def assert_fresh(self, quote: RealtimeQuote, now: datetime, max_age_seconds: int) -> None:
        if now.astimezone(SHANGHAI) - quote.quoted_at > timedelta(seconds=max_age_seconds):
            raise PaperTradingError("stale_quote", "实时行情已过期")
```

`_sdk_fetch()` 使用已安装 `tushare.realtime_quote(ts_code=ts_code)`；不得调用现有日线 `get_stock_quote` 作为成交回退。

- [ ] **Step 4: 运行测试**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_quote_provider.py -q`

Expected: `1 passed`。

- [ ] **Step 5: 提交行情适配器**

```bash
git add backend/app/services/paper_trading/quote_provider.py backend/tests/unit/services/paper_trading/test_quote_provider.py
git commit -m "feat(paper): add fail-closed realtime quote provider"
```

### Task 5: 建立账户、流水、持股批次和重置审计表

**Files:**
- Create: `backend/app/models/paper_account.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/integration/paper_trading/test_account_models.py`

- [ ] **Step 1: 写 PostgreSQL 约束失败测试**

```python
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.paper_account import PaperAccount


def test_only_one_active_account_per_user(db_session, user) -> None:
    db_session.add(PaperAccount.new(user_id=user.id, generation=1, initial_cash=Decimal("1000000")))
    db_session.flush()
    db_session.add(PaperAccount.new(user_id=user.id, generation=2, initial_cash=Decimal("1000000")))
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: 运行并确认失败**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_account_models.py -q`

Expected: FAIL，缺少 `PaperAccount`。

- [ ] **Step 3: 实现 ORM 和数据库约束**

`PaperAccount` 字段必须为 `id UUID`、`user_id UUID`、`generation int`、`initial_cash Numeric(18,2)`、`available_cash Numeric(18,2)`、`frozen_cash Numeric(18,2)`、`commission_rate Numeric(10,8)`、`minimum_commission Numeric(10,2)`、`status enum`、`version int` 和时间戳；添加 `(user_id, generation)` 唯一约束以及 PostgreSQL 条件唯一索引 `user_id WHERE status='active'`。

`PaperCashLedger` 必须包含 `account_id`、`generation`、`kind`、`amount`、变更前后 available/frozen、`business_key` 唯一、`order_id/fill_id` 可空和 `created_at`。

`PaperHoldingLot` 必须包含 `account_id`、`generation`、`ts_code`、`name`、`source_fill_id`、`original_quantity`、`remaining_quantity`、`frozen_quantity`、`unit_cost`、`available_on`，并用 `CHECK` 保证三种数量非负且冻结不超过剩余。

`PaperAccountResetAudit` 必须保存旧/新 account id、旧/新 generation、确认来源、重置前摘要 JSONB 和时间戳。

- [ ] **Step 4: 在模型 barrel 中显式导出四个模型**

```python
from .paper_account import (
    PaperAccount,
    PaperAccountResetAudit,
    PaperCashLedger,
    PaperHoldingLot,
)
```

- [ ] **Step 5: 运行模型测试**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_account_models.py -q`

Expected: PASS，重复 active account 命中 `IntegrityError`，负余额和非法批次命中 check constraint。

- [ ] **Step 6: 提交模型**

```bash
git add backend/app/models/paper_account.py backend/app/models/__init__.py backend/tests/integration/paper_trading/test_account_models.py
git commit -m "feat(paper): add account ledger and holding lot models"
```

### Task 6: 实现默认账户和内部重置事务

**Files:**
- Create: `backend/app/services/paper_trading/account_service.py`
- Test: `backend/tests/integration/paper_trading/test_account_service.py`

- [ ] **Step 1: 写首次开户、并发开户和重置审计测试**

```python
def test_get_or_create_defaults_to_one_million(db_session, user) -> None:
    account = PaperAccountService(db_session).get_or_create(user_id=user.id)
    assert account.generation == 1
    assert account.available_cash == Decimal("1000000.00")
    assert account.frozen_cash == Decimal("0.00")
    assert db_session.query(PaperCashLedger).filter_by(kind="initial_deposit").count() == 1


def test_reset_archives_old_generation_and_keeps_history(db_session, user) -> None:
    service = PaperAccountService(db_session)
    old = service.get_or_create(user_id=user.id)
    new = service.reset_confirmed(
        user_id=user.id,
        initial_cash=Decimal("800000"),
        source_session_id="session-1",
        confirmation_id="confirm-1",
    )
    assert old.status.value == "archived"
    assert new.generation == 2
    assert db_session.query(PaperAccountResetAudit).count() == 1
```

- [ ] **Step 2: 运行并确认失败**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_account_service.py -q`

Expected: FAIL，缺少 service。

- [ ] **Step 3: 实现带账户行锁和 ledger 的服务**

`PaperAccountService` 保存 `DEFAULT_INITIAL_CASH = Decimal("1000000.00")` 和传入的 `Session`，并提供以下精确接口：

- `get_or_create(*, user_id: UUID, initial_cash: Decimal | None = None) -> PaperAccount`
- `get_active(*, user_id: UUID, for_update: bool = False) -> PaperAccount`
- `append_ledger(*, account: PaperAccount, kind: str, amount: Decimal, available_after: Decimal, frozen_after: Decimal, business_key: str) -> PaperCashLedger`
- `reset_confirmed(*, user_id: UUID, initial_cash: Decimal, source_session_id: str, confirmation_id: str) -> PaperAccount`

`get_or_create()` 捕获条件唯一索引竞争，rollback savepoint 后读取胜出的 active 行；`reset_confirmed()` 使用 `SELECT ... FOR UPDATE`、归档旧行、新建 generation、追加初始入金和 reset audit，方法只 `flush()`，commit 由调用方负责。

- [ ] **Step 4: 运行账户服务测试**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_account_service.py -q`

Expected: PASS。

- [ ] **Step 5: 提交账户服务**

```bash
git add backend/app/services/paper_trading/account_service.py backend/tests/integration/paper_trading/test_account_service.py
git commit -m "feat(paper): add default account and audited reset service"
```

### Task 7: 暴露账户 API 和首次资金编辑

**Files:**
- Create: `backend/app/schemas/paper_trading.py`
- Create: `backend/app/router/paper_trading_router.py`
- Modify: `backend/app/app_main.py`
- Test: `backend/tests/integration/paper_trading/test_account_endpoint.py`

- [ ] **Step 1: 写认证、默认开户和跨用户隔离测试**

```python
def test_get_account_creates_default_account(client, db_session, user) -> None:
    response = client.get("/api/v0/paper-trading/account")
    assert response.status_code == 200
    assert response.json()["available_cash"] == "1000000.00"
    assert response.json()["generation"] == 1

def test_initial_cash_can_change_once_before_activity(client) -> None:
    assert client.patch("/api/v0/paper-trading/account/initial-cash", json={"initial_cash": "800000.00"}).status_code == 200
    assert client.patch("/api/v0/paper-trading/account/initial-cash", json={"initial_cash": "900000.00"}).status_code == 409
```

- [ ] **Step 2: 运行并确认 404 失败**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_account_endpoint.py -q`

Expected: FAIL，endpoint 不存在。

- [ ] **Step 3: 实现 schema 与 router**

```python
class PaperAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    generation: int
    initial_cash: Decimal
    available_cash: Decimal
    frozen_cash: Decimal
    status: str
```

```python
router = APIRouter(prefix="/api/v0/paper-trading", tags=["paper-trading"])

@router.get("/account", response_model=PaperAccountRead)
async def get_account(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user_required)]) -> PaperAccountRead:
    account = PaperAccountService(db).get_or_create(user_id=user.id)
    db.commit()
    db.refresh(account)
    return PaperAccountRead.model_validate(account)
```

新增 `PATCH /account/initial-cash`：只允许 generation 1、除 initial_deposit 外没有流水、没有订单/成交且 `initial_cash_edited_at IS NULL` 的账户调用一次；同一事务更新 initial/available cash、冲正旧 initial_deposit、追加新 initial_deposit，并写 `initial_cash_edited_at`。之后任何修改必须走带确认的 reset。

- [ ] **Step 4: 在 `app_main.py` import 并 include router**

```python
from app.router.paper_trading_router import router as paper_trading_router
# 在 app_main.py 现有 router 注册区域增加下一行：
app.include_router(paper_trading_router)
```

- [ ] **Step 5: 运行 endpoint 测试**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_account_endpoint.py -q`

Expected: PASS。

- [ ] **Step 6: 提交 API**

```bash
git add backend/app/schemas/paper_trading.py backend/app/router/paper_trading_router.py backend/app/app_main.py backend/tests/integration/paper_trading/test_account_endpoint.py
git commit -m "feat(paper): expose default paper account"
```

### Task 8: 完成本计划验证

**Files:**
- Modify: `docs/Codex-context/` 中新增本阶段完成卡片，仅在实现确实落地后执行。

- [ ] **Step 1: 运行本计划测试集**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading backend/tests/integration/paper_trading/test_account_models.py backend/tests/integration/paper_trading/test_account_service.py backend/tests/integration/paper_trading/test_account_endpoint.py -q`

Expected: 全部 PASS，无 xfail。

- [ ] **Step 2: 运行静态检查**

Run: `uv run --frozen --extra dev ruff format --check backend/app/services/paper_trading backend/app/models/paper_account.py backend/app/router/paper_trading_router.py backend/app/schemas/paper_trading.py backend/tests/unit/services/paper_trading backend/tests/integration/paper_trading`

Expected: exit 0。

Run: `uv run --frozen --extra dev ruff check backend/app/services/paper_trading backend/app/models/paper_account.py backend/app/router/paper_trading_router.py backend/app/schemas/paper_trading.py backend/tests/unit/services/paper_trading backend/tests/integration/paper_trading`

Expected: exit 0。

Run: `uv run --frozen --extra dev mypy backend/app/services/paper_trading backend/app/router/paper_trading_router.py backend/app/schemas/paper_trading.py`

Expected: `Success: no issues found`。

- [ ] **Step 3: 运行既有持仓回归**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/test_trade_service.py backend/tests/unit/services/test_position_service.py backend/tests/unit/services/test_monitoring_scope.py -q`

Expected: 全部 PASS。

- [ ] **Step 4: 提交阶段完成卡片**

```bash
git add docs/Codex-context
git commit -m "docs(context): record paper trading foundation"
```
