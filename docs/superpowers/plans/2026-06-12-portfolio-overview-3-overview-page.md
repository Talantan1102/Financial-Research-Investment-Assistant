# 持仓总览 ③脸面层:整盘总览页(前端 + 聚合 endpoint)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把②引擎层的拆账/看结构/复盘端到前端,做成"我的持仓·总览"页(合进持仓相关入口当总览层):头条(总身家+今天+今年)、算账卡、看结构(饼图+集中度)、复盘曲线(带区间选择器),红涨绿跌、看不穿基金诚实标注。

**Architecture:** 后端加聚合 endpoint `/portfolio/overview` + `/portfolio/overview/trend`(包 ②层的 build_overview/narrate/compute_twr);前端新增 `/portfolio-overview` 页,沿用现有 axios `request` wrapper + Ant Design + ECharts(`frontend/src/components/chart`);主题直接用现有 `tokens-retail.ts`(本就 iOS 风),涨跌色用 `tokens-base.ts` 的 `semantic.up/down` 常量(红涨绿跌,已正确)。

**Tech Stack:** React 18 / React Router v6 / valtio(本页可不用)/ Ant Design 5 / ECharts / TypeScript / FastAPI(聚合 endpoint)。

> 依赖:②引擎层已落地。设计稿:`docs/superpowers/specs/2026-06-12-portfolio-overview-design.md` §4.3/§5。
> 复用:页面套路参考 `frontend/src/pages/portfolio/index.tsx`;图表用 `frontend/src/components/chart/index.tsx` 的 `Chart`;API 模式参考 `frontend/src/api/portfolio.ts` 的 `listPositions`。

---

### Task 1: 后端聚合 endpoint `/portfolio/overview` 与 `/portfolio/overview/trend`

**Files:**
- Modify: `backend/app/router/portfolio_router.py`(加两个 GET)
- Modify: `backend/app/schemas/portfolio.py`(加 `OverviewRead` / `TrendRead`)
- Test: `backend/tests/integration/test_portfolio_overview_endpoint.py`

- [ ] **Step 1: 写失败的集成测试(TestClient + mock tushare)**

`backend/tests/integration/test_portfolio_overview_endpoint.py`(模仿现有 router 集成测试,带 auth 依赖覆盖):

```python
import pytest


@pytest.mark.asyncio
async def test_overview_endpoint_shape(async_client, seed_anon_positions, monkeypatch):
    monkeypatch.setenv("TUSHARE_MODE", "mock")
    monkeypatch.setenv("LLM_MODE", "mock")
    r = await async_client.get("/portfolio/overview")
    assert r.status_code == 200
    body = r.json()
    assert "attribution" in body and "structure" in body and "narrative" in body
    assert "total_value" in body


@pytest.mark.asyncio
async def test_trend_endpoint_accepts_range(async_client, seed_anon_positions):
    r = await async_client.get("/portfolio/overview/trend", params={"range": "3m"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"dates", "portfolio", "benchmark", "cumulative", "range"}
```

- [ ] **Step 2: 跑确认失败** — `pytest backend/tests/integration/test_portfolio_overview_endpoint.py -v` → FAIL

- [ ] **Step 3: 实现两个 endpoint**

`backend/app/router/portfolio_router.py` 追加:

```python
from app.services.portfolio_overview_service import build_overview
from app.services.portfolio_narrator import narrate_today
from app.services.portfolio_analytics import compute_twr, DailySnap
from app.services.position_snapshot_repo import PositionSnapshotRepo

_RANGE_DAYS = {"1m": 30, "3m": 90, "6m": 182, "1y": 365, "3y": 1095}


def _uid(user) -> object:
    return None if str(user.id) == "anonymous" else user.id


@router.get("/overview")
async def get_overview(db: Annotated[Session, Depends(get_db)],
                       user: Annotated[User, Depends(get_current_user_required)]):
    ov = await build_overview(db, user_id=_uid(user))
    ov["narrative"] = await narrate_today(ov["attribution"], persona_note=None)
    return ov


@router.get("/overview/trend")
async def get_trend(range: str = "1m",
                    db: Annotated[Session, Depends(get_db)] = None,
                    user: Annotated[User, Depends(get_current_user_required)] = None):
    import datetime as dt
    days = _RANGE_DAYS.get(range, 30)
    end = dt.date.today(); start = end - dt.timedelta(days=days)
    rows = PositionSnapshotRepo(db).list_range(user_id=_uid(user), start_date=start, end_date=end)
    by_date: dict[str, dict] = {}
    for r in rows:
        by_date.setdefault(str(r.snapshot_date), {})[r.ts_code] = (int(r.quantity), float(r.market_price))
    snaps = [DailySnap(date=d, holdings=h) for d, h in sorted(by_date.items())]
    twr = compute_twr(snaps) if len(snaps) >= 2 else {"daily": [], "cumulative": 0.0}
    # 基准:沪深300 同窗口(get_index_daily,留给实现:取 pct 串成累计)
    return {"dates": [s.date for s in snaps], "portfolio": twr["daily"],
            "cumulative": twr["cumulative"], "benchmark": [], "range": range}
```

> `Annotated`/`Session`/`get_db`/`get_current_user_required`/`User` 均已在该文件 import(参考文件顶部与现有端点)。基准 benchmark 的填充(沪深300 同窗口累计)在本 step 用 `get_index_daily` 补全,不留 TODO。

- [ ] **Step 4: 跑测试确认通过 + 提交**
```bash
git add backend/app/router/portfolio_router.py backend/app/schemas/portfolio.py backend/tests/integration/test_portfolio_overview_endpoint.py
git commit -m "feat(portfolio): /portfolio/overview + /overview/trend 聚合 endpoint"
```

---

### Task 2: 前端 API client + 类型

**Files:**
- Modify: `frontend/src/api/portfolio.ts`(加 `getOverview` / `getTrend` + 类型)
- Test: `frontend/src/api/__tests__/portfolio.test.ts`(模仿现有 api 测试)

- [ ] **Step 1: 写失败的测试(mock request)**

`frontend/src/api/__tests__/portfolio.test.ts`:

```typescript
import { describe, it, expect, vi } from 'vitest'
import * as api from '../portfolio'

describe('portfolio overview api', () => {
  it('getOverview hits /portfolio/overview', async () => {
    const spy = vi.spyOn(api, 'getOverview')
    expect(typeof api.getOverview).toBe('function')
    spy.mockRestore()
  })
})
```

- [ ] **Step 2: 跑确认失败** — `pnpm --dir frontend test portfolio` → FAIL(getOverview 未定义)

- [ ] **Step 3: 实现**

`frontend/src/api/portfolio.ts` 末尾追加(沿用文件顶部已有的 `request`):

```typescript
export type TimeRange = '1m' | '3m' | '6m' | '1y' | '3y'

export interface AttributionBreakdown {
  total_pct: number
  by_class: Record<string, number>
  stock_breakdown: { market: number; sector_excess: number; idiosyncratic: number }
  contributions: { ts_code: string; asset_class: string; contrib_pct: number }[]
}
export interface OverviewRead {
  total_value: number
  today_pct: number
  ytd_pct: number
  attribution: AttributionBreakdown
  structure: { by_class: Record<string, number>; by_sector: Record<string, number>; as_of: string | null }
  narrative: string
}
export interface TrendRead {
  dates: string[]; portfolio: number[]; benchmark: number[]; cumulative: number; range: TimeRange
}

export function getOverview() { return request.get<OverviewRead>('/portfolio/overview') }
export function getTrend(range: TimeRange) { return request.get<TrendRead>('/portfolio/overview/trend', { params: { range } }) }
```

- [ ] **Step 4: 跑测试 + 提交**
```bash
git add frontend/src/api/portfolio.ts frontend/src/api/__tests__/portfolio.test.ts
git commit -m "feat(frontend): portfolio overview/trend API client"
```

---

### Task 3: 涨跌色常量收敛(红涨绿跌,去 hardcode)

**Files:**
- Create: `frontend/src/utils/pnl-color.ts`
- Test: `frontend/src/utils/__tests__/pnl-color.test.ts`

- [ ] **Step 1: 失败测试**

```typescript
import { describe, it, expect } from 'vitest'
import { pnlColor } from '../pnl-color'

describe('pnlColor 红涨绿跌', () => {
  it('涨为红', () => expect(pnlColor(1.2)).toBe('#ff3b30'))
  it('跌为绿', () => expect(pnlColor(-0.8)).toBe('#34c759'))
  it('平为中性', () => expect(pnlColor(0)).toBe('inherit'))
})
```

- [ ] **Step 2: 跑确认失败** — FAIL

- [ ] **Step 3: 实现**(引用 `tokens-base.ts:29-30` 的 `semantic.up/down`)

`frontend/src/utils/pnl-color.ts`:

```typescript
import { baseTokens } from '@/themes/tokens-base'

export function pnlColor(n: number): string {
  if (n > 0) return baseTokens.semantic.up      // #ff3b30 红=涨
  if (n < 0) return baseTokens.semantic.down    // #34c759 绿=跌
  return 'inherit'
}
```

- [ ] **Step 4: 跑测试 + 提交**
```bash
git add frontend/src/utils/pnl-color.ts frontend/src/utils/__tests__/pnl-color.test.ts
git commit -m "feat(frontend): pnlColor 红涨绿跌常量(去 hardcode)"
```

---

### Task 4: 总览页组件 + 四块卡(头条/算账/看结构/复盘)

**Files:**
- Create: `frontend/src/pages/portfolio-overview/index.tsx`
- Create: `frontend/src/pages/portfolio-overview/charts.ts`(ECharts option builders)
- Modify: `frontend/src/router/routes.tsx`(加路由)
- Modify: `frontend/src/components/sidebar/nav-links.ts`(加导航)
- Test: `frontend/src/pages/portfolio-overview/__tests__/index.test.tsx`

- [ ] **Step 1: 写失败的页面测试(RTL,mock api)**

`frontend/src/pages/portfolio-overview/__tests__/index.test.tsx`:

```typescript
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import PortfolioOverviewPage from '../index'

vi.mock('@/api/portfolio', () => ({
  getOverview: () => Promise.resolve({ data: {
    total_value: 319000, today_pct: -2.1, ytd_pct: 12.4,
    attribution: { total_pct: -2.1, by_class: { stock: -2.0, fund_otc: -0.1 },
      stock_breakdown: { market: -0.9, sector_excess: -0.8, idiosyncratic: -0.3 }, contributions: [] },
    structure: { by_class: { stock: 0.58, fund_otc: 0.22 }, by_sector: { 白酒: 0.46 }, as_of: '2026-09-30' },
    narrative: '今天主要是白酒砸的。' } }),
  getTrend: () => Promise.resolve({ data: { dates: ['1','2'], portfolio: [0.01], benchmark: [0.005], cumulative: 0.032, range: '1m' } }),
}))

describe('PortfolioOverviewPage', () => {
  it('渲染头条总身家与今天涨跌', async () => {
    render(<PortfolioOverviewPage />)
    await waitFor(() => expect(screen.getByText(/总身家/)).toBeInTheDocument())
    expect(screen.getByText(/319,?000|31.9/)).toBeInTheDocument()
  })
  it('渲染 AI 叙事文案', async () => {
    render(<PortfolioOverviewPage />)
    await waitFor(() => expect(screen.getByText(/白酒砸的/)).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: 跑确认失败** — `pnpm --dir frontend test portfolio-overview` → FAIL

- [ ] **Step 3: ECharts option builders**

`frontend/src/pages/portfolio-overview/charts.ts`:

```typescript
import type { EChartsOption } from 'echarts'
import { pnlColor } from '@/utils/pnl-color'

const CLASS_LABEL: Record<string, string> = {
  stock: '股票', fund_etf: '场内ETF', fund_otc: '场外基金', bond: '债基', gold: '黄金', cash: '现金',
}

export function structurePie(byClass: Record<string, number>): EChartsOption {
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {d}%' },
    series: [{ type: 'pie', radius: ['45%', '70%'],
      data: Object.entries(byClass).map(([k, v]) => ({ name: CLASS_LABEL[k] ?? k, value: Math.round(v * 1000) / 10 })) }],
  }
}

export function trendLine(dates: string[], portfolio: number[], benchmark: number[], cumulative: number): EChartsOption {
  return {
    color: [pnlColor(cumulative), '#c7c7cc'],
    tooltip: { trigger: 'axis' },
    legend: { data: ['我的整盘', '沪深300'] },
    xAxis: { type: 'category', data: dates, show: false },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [
      { name: '我的整盘', type: 'line', smooth: true, showSymbol: false, data: portfolio.map(x => +(x * 100).toFixed(2)) },
      { name: '沪深300', type: 'line', smooth: true, showSymbol: false, lineStyle: { type: 'dashed' }, data: benchmark.map(x => +(x * 100).toFixed(2)) },
    ],
  }
}
```

- [ ] **Step 4: 页面组件**

`frontend/src/pages/portfolio-overview/index.tsx`(头条 + 算账 + 看结构饼图 + 复盘 Segmented 区间;复用 `Chart`):

```tsx
import { useEffect, useState } from 'react'
import { Card, Row, Col, Spin, Alert, Statistic, Segmented } from 'antd'
import Chart from '@/components/chart'
import { getOverview, getTrend, type OverviewRead, type TrendRead, type TimeRange } from '@/api/portfolio'
import { pnlColor } from '@/utils/pnl-color'
import { structurePie, trendLine } from './charts'

const RANGES: TimeRange[] = ['1m', '3m', '6m', '1y', '3y']
const RANGE_LABEL: Record<TimeRange, string> = { '1m': '近1月', '3m': '近3月', '6m': '近半年', '1y': '近1年', '3y': '近3年' }

export default function PortfolioOverviewPage() {
  const [ov, setOv] = useState<OverviewRead | null>(null)
  const [trend, setTrend] = useState<TrendRead | null>(null)
  const [range, setRange] = useState<TimeRange>('1m')
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => { getOverview().then(r => setOv(r.data)).catch(e => setErr(String(e))) }, [])
  useEffect(() => { getTrend(range).then(r => setTrend(r.data)).catch(() => {}) }, [range])

  if (err) return <Alert type="error" message="加载失败" description={err} />
  if (!ov) return <div style={{ padding: 40, textAlign: 'center' }}><Spin /></div>

  const s = ov.attribution.stock_breakdown
  return (
    <div style={{ padding: 24, maxWidth: 980, margin: '0 auto' }}>
      <h2>我的持仓 · 总览</h2>

      {/* 头条 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={24}>
          <Col><Statistic title="总身家" value={ov.total_value} prefix="¥" /></Col>
          <Col><Statistic title="今天" value={ov.today_pct} suffix="%" valueStyle={{ color: pnlColor(ov.today_pct) }} /></Col>
          <Col><Statistic title="今年" value={ov.ytd_pct} suffix="%" valueStyle={{ color: pnlColor(ov.ytd_pct) }} /></Col>
        </Row>
        <p style={{ marginTop: 12, background: '#f2f2f7', borderRadius: 11, padding: '11px 13px' }}>{ov.narrative}</p>
      </Card>

      {/* 算账 */}
      <Card title="这账怎么来的" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={8}><Statistic title="跟着大盘" value={s.market} suffix="%" valueStyle={{ color: pnlColor(s.market) }} /></Col>
          <Col span={8}><Statistic title="板块额外" value={s.sector_excess} suffix="%" valueStyle={{ color: pnlColor(s.sector_excess) }} /></Col>
          <Col span={8}><Statistic title="个股自身" value={s.idiosyncratic} suffix="%" valueStyle={{ color: pnlColor(s.idiosyncratic) }} /></Col>
        </Row>
      </Card>

      {/* 看结构 */}
      <Card title="钱分在哪 · 按大类" style={{ marginBottom: 16 }}>
        <Chart config={structurePie(ov.structure.by_class)} />
        {ov.structure.as_of && <p style={{ fontSize: 12, color: '#8a6d1f', background: '#fff8e1', borderRadius: 9, padding: '8px 11px' }}>
          📅 基金按最新季报(截至 {ov.structure.as_of})拆,之后可能已调仓。</p>}
      </Card>

      {/* 复盘 */}
      <Card title="这阵子 vs 沪深300">
        <Segmented value={range} onChange={v => setRange(v as TimeRange)}
          options={RANGES.map(r => ({ label: RANGE_LABEL[r], value: r }))} style={{ marginBottom: 12 }} />
        {trend && <Chart config={trendLine(trend.dates, trend.portfolio, trend.benchmark, trend.cumulative)} />}
      </Card>
    </div>
  )
}
```

- [ ] **Step 5: 挂路由 + 导航**

`frontend/src/router/routes.tsx`:`import PortfolioOverviewPage from '@/pages/portfolio-overview'` + 路由 `{ path: '/portfolio-overview', Component: PortfolioOverviewPage }`。
`frontend/src/components/sidebar/nav-links.ts`:加 `{ to: '/portfolio-overview', label: '持仓总览', icon: 'chart' }`(置于 `/portfolio` 之后,形成"总览 → 逐只"层级)。

- [ ] **Step 6: 跑测试确认通过 + 提交**

Run: `pnpm --dir frontend test portfolio-overview`
Expected: PASS
```bash
git add frontend/src/pages/portfolio-overview frontend/src/router/routes.tsx frontend/src/components/sidebar/nav-links.ts
git commit -m "feat(frontend): 我的持仓·总览页(头条/算账/看结构/复盘+区间选择器)"
```

---

### Task 5: 端到端冒烟 + 收口

- [ ] **Step 1: 后端 endpoint 集成测试全过** — `pytest backend/tests/integration/test_portfolio_overview_endpoint.py -v`
- [ ] **Step 2: 前端测试全过** — `pnpm --dir frontend test portfolio`
- [ ] **Step 3:(手动)起后端 + 前端,登录后访问 `/portfolio-overview`,核对**:头条红涨绿跌、饼图、区间切换换线且涨红跌绿、基金季报 as-of 提示在、AI 叙事无买卖建议。(参考记忆 screenshots-are-ground-truth:以截图为准)
- [ ] **Step 4: 提交收口**
```bash
git add -A && git commit -m "test(portfolio): 总览页端到端冒烟收口"
```

---

## Self-Review

- **Spec 覆盖**:§5 信息架构(卡片+下钻、头条总身家+今天+今年)、§4.3 复盘(区间选择器 1m/3m/6m/1y/3y + 红涨绿跌按区间)、§4.2 看结构(饼图 + 基金 as-of 提示)、§4.1 叙事展示。下钻到逐只(点持仓→现有 /monitoring 逐只)用导航层级体现,完整下钻交互留②③之后的 polish。✅
- **占位扫描**:Task1 trend 的 benchmark 填充在 Step3 注明"用 get_index_daily 补全,不留 TODO";页面/图表给了完整真码。⚠️ 执行 Task1 时务必补全 benchmark,勿留空数组上线。
- **类型一致**:`OverviewRead`/`TrendRead`/`TimeRange` 在 api(Task2)、charts(Task4)、页面(Task4)间字段名一致;`pnlColor`(Task3)在 charts 与页面复用同签名。✅
- **跨计划衔接**:本计划 Task1 调用②层 `build_overview`/`narrate_today`/`compute_twr`/`PositionSnapshotRepo`,签名与②计划定义一致;①层取数工具(`get_index_daily` 等)为 benchmark 与基金净值供数。
