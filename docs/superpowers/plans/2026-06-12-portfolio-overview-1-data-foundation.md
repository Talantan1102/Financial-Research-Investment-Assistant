# 持仓总览 ①底子层:多资产持仓 + 取数工具 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给持仓加"资产类型"一栏,并补上三个一直缺的取数工具(指数当日 / 基金净值与类型 / 板块当日与个股行业),让"算账引擎"有料可用,也让聊天能直接问大盘/板块/基金。

**Architecture:** 沿用现有 `TushareService` Protocol + RealTushareService + LegacyMockTushareAdapter 三层,每个新取数方法走"Protocol 签名 → Real `_call_cached` → Mock deterministic fixture → Tool 类 → MCP 适配器 → tool_docs → 4 处测试"的既定 7 步。Position 加字段走 `create_all() + reconcile_columns()` 幂等机制(无 alembic)。

**Tech Stack:** Python / FastAPI / SQLAlchemy(PG)/ pandas / tushare / MCP(模型上下文协议工具层)/ pytest。

> 配套设计稿:`docs/superpowers/specs/2026-06-12-portfolio-overview-design.md`(§3 多资产、§6 取数工具)。
> 关键约定(来自现有代码,务必遵守):**Mock 适配器必须 deterministic(硬编码 DataFrame,绝不 fallback 到 LLM 生成)**,否则 L0 测试在 `LLM_MODE=none` 下不确定。

---

### Task 1: Position 加 `asset_class` 字段(股票/场内基金/场外基金/债/黄金/现金)

**Files:**
- Modify: `backend/app/models/position.py:31-63`(加列)
- Modify: `backend/app/schemas/portfolio.py`(PositionRead 加字段、onboarding 入参加可选 asset_class)
- Modify: `backend/app/router/portfolio_router.py:134-180`(onboarding 透传 asset_class)
- Test: `backend/tests/unit/services/test_position_asset_class.py`(新建)
- Test(集成): `backend/tests/integration/test_portfolio_onboarding_asset_class.py`(新建)

- [ ] **Step 1: 写失败的单元测试 —— 默认资产类型为 stock**

`backend/tests/unit/services/test_position_asset_class.py`:

```python
from app.models.position import Position


def test_position_asset_class_defaults_to_stock() -> None:
    p = Position(id="x", user_id=None, ts_code="600519.SH", name="贵州茅台", quantity=100)
    # 未显式赋值时,Python 侧默认应为 "stock"
    assert p.asset_class == "stock"


def test_position_asset_class_accepts_fund() -> None:
    p = Position(id="y", user_id=None, ts_code="110011.OF", name="某基金", quantity=0, asset_class="fund_otc")
    assert p.asset_class == "fund_otc"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/unit/services/test_position_asset_class.py -v`
Expected: FAIL — `AttributeError: 'Position' object has no attribute 'asset_class'`

- [ ] **Step 3: 给 Position 加列**

`backend/app/models/position.py`,在 `is_silenced` 列之后加(保持 `nullable` + `default`,reconcile 才能自动补列):

```python
    # 资产类型:stock / fund_etf(场内ETF) / fund_otc(场外基金) / bond / gold / cash
    asset_class = Column(String(32), nullable=False, default="stock", server_default="stock")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/unit/services/test_position_asset_class.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: PositionRead schema 加字段 + onboarding 入参可选 asset_class**

`backend/app/schemas/portfolio.py`,在 `PositionRead` 加 `asset_class: str`;在 onboarding 单条持仓入参模型(现有用于 `/portfolio/onboarding` 的那个,如 `OnboardingPosition`)加 `asset_class: str = "stock"`。

`backend/app/router/portfolio_router.py:134-180` 的 `onboarding()` 里,创建 Position/Trade 时把 `asset_class` 透传(默认 "stock",保持老调用零变化)。

- [ ] **Step 6: 写集成测试 —— onboarding 能带 asset_class 落库**

`backend/tests/integration/test_portfolio_onboarding_asset_class.py`(用 `db_session` fixture,模仿 `backend/tests/unit/services/test_portfolio_recompute.py` 的建数据方式):

```python
def test_onboarding_persists_asset_class(db_session):
    from app.services.position_service import PositionService
    from app.models.position import Position

    db_session.add(Position(id="p1", user_id=None, ts_code="159915.SZ",
                            name="创业板ETF", quantity=1000, asset_class="fund_etf"))
    db_session.flush()

    got = db_session.query(Position).filter_by(ts_code="159915.SZ").one()
    assert got.asset_class == "fund_etf"
```

- [ ] **Step 7: 跑测试 + 提交**

Run: `pytest backend/tests/unit/services/test_position_asset_class.py backend/tests/integration/test_portfolio_onboarding_asset_class.py -v`
Expected: PASS

```bash
git add backend/app/models/position.py backend/app/schemas/portfolio.py backend/app/router/portfolio_router.py backend/tests/unit/services/test_position_asset_class.py backend/tests/integration/test_portfolio_onboarding_asset_class.py
git commit -m "feat(portfolio): Position 加 asset_class 字段(多资产基础)"
```

---

### Task 2: 取数工具「指数当日」`get_index_daily`(算账"跟大盘"那刀要用)

> 这是新增取数工具的**完整模板**,Task 3/4 照此结构。务必同步改 §末尾"4 处测试"。

**Files:**
- Modify: `backend/app/services/tushare_service.py`(Protocol 签名 + RealTushareService 实现)
- Modify: `backend/app/services/tushare_mock_adapter.py`(deterministic mock)
- Create: `backend/app/tools/get_index_daily.py`(Tool 类 + 纯格式化函数)
- Create: `backend/app/mcp_server/tools/get_index_daily.py`(TOOL_DEF + handle)
- Modify: `backend/app/mcp_server/server.py:34-44`(`_CHAT_TOOL_MODULES` 加模块)
- Modify: `backend/app/chatloop/tool_docs.py`(加 ToolDoc)
- Test: `backend/tests/unit/mcp_server/test_get_index_daily_tool.py`(新建)
- Test(4 处): 见 Step 8

- [ ] **Step 1: 写失败的单元测试(纯格式化函数,不碰网络)**

`backend/tests/unit/mcp_server/test_get_index_daily_tool.py`(模仿 `backend/tests/unit/mcp_server/test_get_daily_tool.py`):

```python
import pandas as pd
from app.tools.get_index_daily import _format_index_daily, IndexDailyArgs
from app.mcp_server.tools.get_index_daily import TOOL_DEF


def test_format_index_daily_computes_pct_change() -> None:
    df = pd.DataFrame({
        "trade_date": ["20261113", "20261114"],
        "close": [4000.0, 3968.0],
        "pre_close": [4010.0, 4000.0],
        "pct_chg": [-0.25, -0.80],
    })
    out = _format_index_daily(df, "000300.SH")
    assert out["ts_code"] == "000300.SH"
    assert out["latest"]["trade_date"] == "20261114"
    assert out["latest"]["pct_chg"] == -0.80   # 当日涨跌幅(%)


def test_tool_def_shape() -> None:
    assert TOOL_DEF.name == "get_index_daily"
    assert "ts_code" in TOOL_DEF.inputSchema["required"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/unit/mcp_server/test_get_index_daily_tool.py -v`
Expected: FAIL — `ModuleNotFoundError: app.tools.get_index_daily`

- [ ] **Step 3: TushareService 加签名 + Real 实现**

`backend/app/services/tushare_service.py`,Protocol 部分加(模仿 `get_money_flow` 签名,行 49-51):

```python
    async def get_index_daily(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame: ...
```

RealTushareService 部分加(模仿行 224-228):

```python
    async def get_index_daily(self, *, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return await self._call_cached(
            "index_daily",  # tushare 真实 API
            {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        )
```

- [ ] **Step 4: Mock 适配器加 deterministic 实现(无 LLM)**

`backend/app/services/tushare_mock_adapter.py`(模仿 `get_daily_basic`/`get_money_flow` 的硬编码 fixture):

```python
    async def get_index_daily(self, *, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        # deterministic:两日,当日 -0.80%
        return pd.DataFrame({
            "ts_code": [ts_code, ts_code],
            "trade_date": ["20261113", "20261114"],
            "close": [4000.0, 3968.0],
            "pre_close": [4010.0, 4000.0],
            "pct_chg": [-0.25, -0.80],
        })
```

- [ ] **Step 5: Tool 类 + 纯格式化函数**

`backend/app/tools/get_index_daily.py`(模仿 `backend/app/tools/get_money_flow.py`):

```python
from typing import Any
import pandas as pd
from pydantic import BaseModel
from app.tools.base import Tool  # 与 get_money_flow 同一基类


class IndexDailyArgs(BaseModel):
    ts_code: str          # 如 "000300.SH"(沪深300)
    start_date: str       # YYYYMMDD
    end_date: str


def _format_index_daily(df: pd.DataFrame, ts_code: str) -> dict[str, Any]:
    if df is None or df.empty:
        return {"ts_code": ts_code, "count": 0, "latest": None}
    df = df.sort_values("trade_date")
    last = df.iloc[-1]
    return {
        "ts_code": ts_code,
        "count": int(len(df)),
        "latest": {
            "trade_date": str(last["trade_date"]),
            "close": float(last["close"]),
            "pct_chg": float(last["pct_chg"]),
        },
        "series": {
            "dates": [str(d) for d in df["trade_date"]],
            "pct_chg": [float(x) for x in df["pct_chg"]],
        },
    }


class GetIndexDailyTool(Tool):
    name = "get_index_daily"
    description = "查指数日线与当日涨跌幅(如沪深300 000300.SH)。算组合'跟大盘'贡献时用。"
    args_schema = IndexDailyArgs

    def __init__(self, tushare: Any | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service
            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = IndexDailyArgs.model_validate(args.model_dump())
        df = await self._tushare.get_index_daily(
            ts_code=a.ts_code, start_date=a.start_date, end_date=a.end_date
        )
        return _format_index_daily(df, a.ts_code)
```

- [ ] **Step 6: MCP 适配器(TOOL_DEF + handle)**

`backend/app/mcp_server/tools/get_index_daily.py`(模仿 `backend/app/mcp_server/tools/get_daily.py`):

```python
import json
from typing import Any
from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="get_index_daily",
    description="查指数日线与当日涨跌幅(沪深300=000300.SH,上证=000001.SH 等)。",
    inputSchema={
        "type": "object",
        "properties": {
            "ts_code": {"type": "string", "description": "指数代码,如 000300.SH"},
            "start_date": {"type": "string", "description": "YYYYMMDD"},
            "end_date": {"type": "string", "description": "YYYYMMDD"},
        },
        "required": ["ts_code", "start_date", "end_date"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.tools.get_index_daily import GetIndexDailyTool, IndexDailyArgs
    tool = GetIndexDailyTool()
    result = await tool.run(IndexDailyArgs.model_validate(args))
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
```

- [ ] **Step 7: 注册模块 + tool_docs**

`backend/app/mcp_server/server.py:34-44`,在 `_CHAT_TOOL_MODULES` 列表加一行:

```python
    "app.mcp_server.tools.get_index_daily",
```

`backend/app/chatloop/tool_docs.py`,加 ToolDoc(模仿现有条目):

```python
    "get_index_daily": ToolDoc(
        name="get_index_daily",
        group="deferred",
        brief="查指数当日涨跌(沪深300等)。问大盘/指数今天多少时用。",
        doc="查指数日线与当日涨跌幅。ts_code 如 000300.SH(沪深300)。",
        thin_required={"ts_code": "string", "start_date": "string", "end_date": "string"},
    ),
```

- [ ] **Step 8: 同步改 4 处工具清单测试(每加一个工具必改)**

逐处把新工具名 `get_index_daily` 加入,并把计数 +1:
1. `backend/tests/unit/test_mcp_server_profiles.py:12-27` — `names` 集合加 `"get_index_daily"`,断言函数名/计数 +1
2. `backend/tests/e2e/test_chatloop_cassette.py:93-136` — `_FAKE_RESULTS` 加占位:`"get_index_daily": {"ts_code": "000300.SH", "count": 0, "latest": None}`
3. `backend/tests/unit/mcp_server/test_mcp_tools.py:22-46` — `expected` 集合加 `"get_index_daily"`,计数 +1
4. `backend/tests/integration/test_mcp_client_e2e.py:15-25` — 工具名集合加 `"get_index_daily"`

- [ ] **Step 9: 跑全部相关测试 + 提交**

Run:
```bash
pytest backend/tests/unit/mcp_server/test_get_index_daily_tool.py \
       backend/tests/unit/test_mcp_server_profiles.py \
       backend/tests/unit/mcp_server/test_mcp_tools.py -v
```
Expected: PASS

```bash
git add backend/app/services/tushare_service.py backend/app/services/tushare_mock_adapter.py backend/app/tools/get_index_daily.py backend/app/mcp_server/tools/get_index_daily.py backend/app/mcp_server/server.py backend/app/chatloop/tool_docs.py backend/tests/
git commit -m "feat(tools): 新增 get_index_daily 取数工具(指数当日涨跌)"
```

---

### Task 3: 取数工具「基金净值+类型」`get_fund_nav`

**Files:** 同 Task 2 的七类文件,把名字换成 `get_fund_nav`;`backend/app/tools/get_fund_nav.py` / `backend/app/mcp_server/tools/get_fund_nav.py` / 测试 `backend/tests/unit/mcp_server/test_get_fund_nav_tool.py`。

- [ ] **Step 1: 写失败的单元测试**

`backend/tests/unit/mcp_server/test_get_fund_nav_tool.py`:

```python
import pandas as pd
from app.tools.get_fund_nav import _format_fund_nav


def test_format_fund_nav_latest_and_type() -> None:
    nav = pd.DataFrame({
        "ts_code": ["110011.OF", "110011.OF"],
        "nav_date": ["20261113", "20261114"],
        "unit_nav": [2.500, 2.475],
    })
    out = _format_fund_nav(nav, "110011.OF", fund_type="股票型", fund_name="某白酒主题")
    assert out["fund_type"] == "股票型"
    assert out["latest"]["unit_nav"] == 2.475
    assert out["latest"]["pct_chg"] == pytest.approx((2.475 - 2.500) / 2.500 * 100, rel=1e-6)
```
(顶部 `import pytest`)

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/unit/mcp_server/test_get_fund_nav_tool.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: TushareService 加两签名 + Real 实现**

`backend/app/services/tushare_service.py`:

```python
    async def get_fund_nav(self, *, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame: ...
    async def get_fund_basic(self, *, ts_code: str) -> pd.DataFrame: ...
```

Real:

```python
    async def get_fund_nav(self, *, ts_code, start_date, end_date) -> pd.DataFrame:
        return await self._call_cached("fund_nav", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date})

    async def get_fund_basic(self, *, ts_code) -> pd.DataFrame:
        return await self._call_cached("fund_basic", {"ts_code": ts_code})
```

- [ ] **Step 4: Mock deterministic**

`backend/app/services/tushare_mock_adapter.py`:

```python
    async def get_fund_nav(self, *, ts_code, start_date, end_date) -> pd.DataFrame:
        return pd.DataFrame({"ts_code": [ts_code, ts_code], "nav_date": ["20261113", "20261114"],
                            "unit_nav": [2.500, 2.475]})

    async def get_fund_basic(self, *, ts_code) -> pd.DataFrame:
        return pd.DataFrame({"ts_code": [ts_code], "name": ["示例基金"], "fund_type": ["股票型"], "market": ["O"]})
```

- [ ] **Step 5: Tool 类 + 格式化(净值算涨跌幅 + 带回 fund_type)**

`backend/app/tools/get_fund_nav.py`:

```python
from typing import Any
import pandas as pd
from pydantic import BaseModel
from app.tools.base import Tool


class FundNavArgs(BaseModel):
    ts_code: str       # 如 "110011.OF"
    start_date: str
    end_date: str


def _format_fund_nav(nav: pd.DataFrame, ts_code: str, fund_type: str | None, fund_name: str | None) -> dict[str, Any]:
    if nav is None or nav.empty:
        return {"ts_code": ts_code, "fund_type": fund_type, "fund_name": fund_name, "latest": None}
    nav = nav.sort_values("nav_date")
    last = float(nav.iloc[-1]["unit_nav"])
    prev = float(nav.iloc[-2]["unit_nav"]) if len(nav) >= 2 else last
    pct = round((last - prev) / prev * 100, 4) if prev else 0.0
    return {
        "ts_code": ts_code, "fund_type": fund_type, "fund_name": fund_name,
        "latest": {"nav_date": str(nav.iloc[-1]["nav_date"]), "unit_nav": last, "pct_chg": pct},
        "as_of_note": "基金底层持仓只到季报、滞后,本工具只取净值层面涨跌,不穿透底层。",
    }


class GetFundNavTool(Tool):
    name = "get_fund_nav"
    description = "查基金类型与每日净值涨跌(场内/场外基金)。组合里基金部分的涨跌用它。看不穿底层持仓。"
    args_schema = FundNavArgs

    def __init__(self, tushare: Any | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service
            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = FundNavArgs.model_validate(args.model_dump())
        basic = await self._tushare.get_fund_basic(ts_code=a.ts_code)
        ftype = str(basic.iloc[0]["fund_type"]) if basic is not None and not basic.empty else None
        fname = str(basic.iloc[0]["name"]) if basic is not None and not basic.empty else None
        nav = await self._tushare.get_fund_nav(ts_code=a.ts_code, start_date=a.start_date, end_date=a.end_date)
        return _format_fund_nav(nav, a.ts_code, ftype, fname)
```

- [ ] **Step 6: MCP 适配器** — `backend/app/mcp_server/tools/get_fund_nav.py`,结构同 Task 2 Step 6,`name="get_fund_nav"`,inputSchema 三参 `ts_code/start_date/end_date`,handle 调 `GetFundNavTool`。

- [ ] **Step 7: 注册 + tool_docs** — `_CHAT_TOOL_MODULES` 加 `"app.mcp_server.tools.get_fund_nav"`;tool_docs 加 `get_fund_nav`(group `deferred`,brief "查基金类型和净值涨跌,看不穿底层持仓")。

- [ ] **Step 8: 4 处测试** — 同 Task 2 Step 8,工具名 `get_fund_nav`,`_FAKE_RESULTS` 占位 `{"ts_code": "110011.OF", "latest": None}`,各处计数 +1。

- [ ] **Step 9: 跑测试 + 提交**

Run: `pytest backend/tests/unit/mcp_server/test_get_fund_nav_tool.py backend/tests/unit/test_mcp_server_profiles.py backend/tests/unit/mcp_server/test_mcp_tools.py -v`
Expected: PASS
```bash
git add backend/app backend/tests
git commit -m "feat(tools): 新增 get_fund_nav 取数工具(基金类型+净值涨跌,不穿透)"
```

---

### Task 4: 取数工具「板块当日 + 个股行业归属」`get_sector_daily`

**实现要点:** tushare 用 `index_classify`(申万行业分类)+ `index_daily`(行业指数当日);个股行业用 `stock_basic` 的 `industry` 字段。为减少调用,Tool 接受 `ts_code`(个股)返回其所属行业 + 该行业指数当日涨跌;或接受 `industry_index`(行业指数代码)直接返回当日涨跌。

**Files:** 同模板,文件 `backend/app/tools/get_sector_daily.py` / `backend/app/mcp_server/tools/get_sector_daily.py` / 测试 `backend/tests/unit/mcp_server/test_get_sector_daily_tool.py`。

- [ ] **Step 1: 失败单测**

```python
import pandas as pd
from app.tools.get_sector_daily import _format_sector


def test_format_sector_returns_industry_and_pct() -> None:
    out = _format_sector(industry="白酒", index_code="801120.SI", pct_chg=-3.0)
    assert out["industry"] == "白酒"
    assert out["pct_chg"] == -3.0
```

- [ ] **Step 2: 跑确认失败** — `pytest backend/tests/unit/mcp_server/test_get_sector_daily_tool.py -v` → FAIL

- [ ] **Step 3: TushareService 加签名 + Real**

```python
    async def get_stock_basic(self, *, ts_code: str) -> pd.DataFrame: ...        # 取 industry
    async def get_sw_index_daily(self, *, index_code: str, trade_date: str) -> pd.DataFrame: ...
```
Real 分别 `_call_cached("stock_basic", {"ts_code": ts_code, "fields": "ts_code,name,industry"})` 与 `_call_cached("sw_daily", {"ts_code": index_code, "trade_date": trade_date})`(若积分不够,降级用通用行业指数;在 docstring 注明)。

- [ ] **Step 4: Mock deterministic**

```python
    async def get_stock_basic(self, *, ts_code) -> pd.DataFrame:
        return pd.DataFrame({"ts_code": [ts_code], "name": ["贵州茅台"], "industry": ["白酒"]})

    async def get_sw_index_daily(self, *, index_code, trade_date) -> pd.DataFrame:
        return pd.DataFrame({"ts_code": [index_code], "trade_date": [trade_date], "pct_chg": [-3.0]})
```

- [ ] **Step 5: Tool 类** —`backend/app/tools/get_sector_daily.py`:输入 `ts_code`(个股)→ `get_stock_basic` 取 industry → 行业名映射到申万行业指数代码(内置一张小映射表 `_INDUSTRY_TO_SW`,覆盖常见:白酒、银行、新能源、半导体、医药 等;未命中返回 `industry` + `pct_chg=None` 并注明"该行业指数未配置")→ `get_sw_index_daily` 取当日涨跌。纯函数 `_format_sector(industry, index_code, pct_chg)` 返回 dict。

- [ ] **Step 6-8: MCP 适配器 + 注册 + tool_docs + 4 处测试** — 同模板,工具名 `get_sector_daily`,`_FAKE_RESULTS` 占位 `{"industry": None, "pct_chg": None}`,计数 +1。

- [ ] **Step 9: 跑测试 + 提交**

Run: `pytest backend/tests/unit/mcp_server/ backend/tests/unit/test_mcp_server_profiles.py -v`
Expected: PASS
```bash
git add backend/app backend/tests
git commit -m "feat(tools): 新增 get_sector_daily(个股行业归属+板块当日涨跌)"
```

---

### Task 5: 底子层收口 —— 跑全套确认无回归

- [ ] **Step 1: 跑工具与持仓相关测试全集**

Run(在 WSL fria-venv 环境,按项目约定):
```bash
pytest backend/tests/unit/mcp_server backend/tests/unit/services/test_position_asset_class.py \
       backend/tests/unit/test_mcp_server_profiles.py backend/tests/integration/test_mcp_client_e2e.py -v
```
Expected: 全 PASS;chat profile 工具计数 = 原值 + 3。

- [ ] **Step 2: e2e cassette 冒烟(确认 4 处占位齐全、cassette 不破)**

Run: `pytest backend/tests/e2e/test_chatloop_cassette.py -v`
Expected: PASS(或与基线一致)

- [ ] **Step 3: 提交收口**
```bash
git add -A
git commit -m "test(portfolio): 底子层取数工具回归收口(+3 工具,4 处清单同步)"
```

---

## Self-Review

- **Spec 覆盖**:本计划覆盖设计稿 §3(多资产:asset_class 字段)、§6(新增取数工具:指数当日/基金/板块+个股行业、持仓加资产类型)。§3 的"每日持仓快照"与"算账"在 ②引擎层计划。✅
- **占位扫描**:无 TODO/TBD;每个 code step 给了真实代码与文件路径。Task 4 行业→申万指数映射表标注了"未命中降级"处理,非占位。✅
- **类型一致**:`get_index_daily`/`get_fund_nav`/`get_sector_daily` 三工具的 Tool 类名、TOOL_DEF.name、tool_docs key、4 处测试集合名全用同一字符串,前后一致。✅
- **已知坑**:Mock 全部 deterministic(无 LLM);加工具必改 4 处测试(已逐处列出),否则 CI 挂(项目记忆 add-mcp-chat-tool-test-sites 教训)。
