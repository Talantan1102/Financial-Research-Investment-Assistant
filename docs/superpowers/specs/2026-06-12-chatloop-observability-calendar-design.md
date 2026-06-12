# Chatloop 可观测性 · 日历热力图 + 自由范围 — 设计文档

- 日期:2026-06-12
- 主题:把可观测性页的「1d/7d/30d 固定窗口」升级为「日历热力图(按天)+ 任意起止范围」
- 前置:建在 #152(可观测性底座)+ #154(看板设计语言)之上,对 main 开 PR
- 决策记录:视图=日历热力图 / 上色指标 4 个可切 / 范围=点起点止两次选 / **纯服务端渲染、无客户端 JS**

---

## 1. 背景与动机

现有可观测性页只能看「最近 N 天」三个固定窗口的聚合,看不出**逐日**变化,也不能框定任意一段时间。用户要「像日历一样看每一天 + 自由选统计范围」:一片日历每天一个格子按指标深浅上色,点起止两天选一段,下面的卡片+最慢工具表按所选段重算。

## 2. 现状(带证据)

- 聚合服务 `ChatloopTraceAnalytics.aggregate(window)`(`backend/app/services/trace_analytics.py`)用 `started_at >= now() - (:interval)::interval` 作下界,`window` 白名单 `1d/7d/30d`。
- 只读接口 `GET /api/v0/observability/chatloop/aggregates?window=7d`(`backend/app/router/observability_router.py`)。
- 看板页 `/eval/chatloop-observability`(`dashboard/server.py` 的 `chatloop_observability_view` + `dashboard/templates/chatloop_observability.html`,#154 已套 base.html 设计语言)用 `urllib` 拉聚合 API(`dashboard/derive/observability.py`),顶部三个 `?window=` pill。
- 子循环 request_id(`%::sub::%`)已在聚合里排除。

## 3. 目标与非目标

**目标:**
- 后端能按「任意起止日期」聚合(不止固定窗口)。
- 后端能产出「逐日分桶」数据(每天 4 个指标),喂日历着色。
- 看板页:日历热力图(默认最近 ~13 周)+ 4 指标下拉切换上色 + 点起止两次选范围 + 顶部快捷;选中段驱动卡片+表。

**非目标(YAGNI):**
- 不做小时级分桶(只到天)。
- 不做拖拽框选(点起止两次选已满足;且可纯服务端实现)。
- 不引前端图表库 / 不加客户端 JS(日历与选择全用服务端渲染的链接)。
- 不新增表(继续只读 `trace_spans`)。
- 不改聚合的隐私边界(仍只出数字)。

## 4. 设计

### 4.1 后端:任意范围聚合(改 `trace_analytics.py` + 路由)

把 4 条聚合 SQL 的时间下界从 `now() - interval` 改为通用的 **`started_at >= :start AND started_at < :end`**(`:end` 取「止日 +1 天」的零点,做到「止日含当天」)。

- 新增内部解析:把请求参数解析成 `(start_ts, end_ts)`:
  - 给 `from`/`to`(ISO `YYYY-MM-DD`)→ `start = from 当天 00:00`,`end = to 当天 + 1 天 00:00`(UTC)。
  - 只给 `window`(`1d/7d/30d`)→ `end = 明天 00:00`,`start = end - N 天`(保留旧行为与白名单)。
  - 二者都缺 → 默认 `window=7d`。
  - `from > to`、非法日期 → `ValueError`(路由转 400)。
- `aggregate` 改签名为 `aggregate(*, window=None, start=None, end=None) -> ChatloopAggregates`;内部统一走 `(start_ts, end_ts)` 绑定参数(防注入照旧:日期解析成 `datetime` 再绑定,不拼串)。
- 接口:`GET /api/v0/observability/chatloop/aggregates?from=YYYY-MM-DD&to=YYYY-MM-DD`(仍兼容 `?window=`)。响应结构 `ChatloopAggregates` 不变。

### 4.2 后端:逐日分桶(新方法 + 新接口)

新方法 `ChatloopTraceAnalytics.daily(start, end) -> list[DayBucket]`:对 `[start, end)` 内非子循环 span 按 `started_at::date` 分组,每天算:

- `date`:当天(date)。
- `cost_cny`:Σ `cost_cny`(模型 span)。
- `turns`:当天去重 request_id 数(非子)= 当天「轮数/调用量」。
- `model_calls` / `tool_calls`:模型 span 数 / 工具 span 数(留作 tooltip/扩展)。
- `p95_ms`:当天**工具 span** latency 的 p95(`percentile_cont(0.95)`);当天无工具 span → `null`。
- `cache_hit_rate`:Σcached_tokens / Σprompt_tokens(模型 span;prompt=0 → null)。

只返回「当天有数据」的桶;无数据的天不返回(前端补灰)。Pydantic 模型 `DayBucket`、容器 `ChatloopDaily{days: list[DayBucket]}`。

接口:`GET /api/v0/observability/chatloop/daily?from=YYYY-MM-DD&to=YYYY-MM-DD` → `ChatloopDaily`。只出数字,不出 span 原文(隐私边界同前)。

### 4.3 前端:日历热力图 + 范围选择(改 dashboard,纯服务端渲染)

`dashboard/derive/observability.py` 加 `load_daily(backend_url, frm, to)`(urllib 拉 daily 接口,与 `load_aggregates` 同款)。`load_aggregates` 改为可带 `from`/`to`(或 `window`)。

`chatloop_observability_view`(`dashboard/server.py`)解析 query:
- `metric`(默认 `cost`,白名单 `cost / turns / p95 / cache`)。
- 选中范围 `from`/`to`(默认 `to=今天`、`from=今天-6` → 初始即「近 7 天」)。
- 日历跨度固定:`cal_to=今天`,`cal_from=今天-90` 起、对齐到周一(显示约 13 周)。
- 拉两份:`load_daily(cal_from, cal_to)`(日历)+ `load_aggregates(from, to)`(卡片+表)。任一失败 → 该块降级占位,不崩页。

模板 `chatloop_observability.html`(在 #154 版基础上加日历区,沿用 `.report-*` + 设计 token):

- **日历热力图**:周为行、周一~周日为列,~13 行。每格一天,按 `metric` 值映射到 5 档 indigo 深浅(`value / 该指标可见天最大值` 分档);无数据/该指标无值 → 灰空格。月份标签在左侧或顶部。
- **每格是一个链接**(无 JS):`href` 由「当前 from/to + 这一天 D」算出**下一步选择**:
  - 当前是单天(from==to==S)且 D≠S → 选区间 `[min(S,D), max(S,D)]`。
  - 否则(无选择 / 已是区间)→ 选单天 `[D, D]`。
  - 链接保留当前 `metric`。→ 「点起点、再点止」两次点选,纯服务端 hrefs 实现,无客户端状态。
- **指标下拉**:4 个链接 `?metric=X`(保留 from/to),切一下整片日历换配色。
- **顶部快捷**:今天 / 近7 / 近30 → `?from=&to=` 链接(替代原三个 window pill)。
- 选中区间在日历上高亮(起止之间的格子描边/底色)。
- 下方:沿用 #154 的卡片 + 最慢工具表,数据来自 `[from,to]` 聚合;范围内无数据 → 现有「暂无数据」占位。

## 5. 数据流

看板页(带 `?from&to&metric`)→ 两个 HTTP GET:
- `/daily?from=cal_from&to=今天` → 逐日分桶 → 日历着色。
- `/aggregates?from&to` → 区间聚合 → 卡片 + 表。
两接口各自跑 SQL over `trace_spans`(排除 `%::sub::%`)。点某天 = 导航到新的 `?from&to&metric`,整页服务端重渲染。

## 6. 边界 / 错误处理

- 无数据的天:daily 不返回该天 → 前端灰空格;p95 指标当天无工具 span → 该格灰。
- `from>to` / 非法日期 → 400(路由),前端降级占位。
- 除零:命中率/占比/着色归一化分母为 0 → 取 0 或灰。
- 隐私:daily 与 aggregates 都只出数字,绝不回 span inputs/outputs。
- 日历跨度上限固定(~13 周),避免任意大范围 daily 拖垮查询;`from/to` 选择段不限(但都在已有数据内)。
- 着色归一化用「可见天该指标最大值」,全 0 时不除零。

## 7. 测试

测试库沿用全 PG + `db_session` 事务回滚隔离。

- **后端 · 任意范围聚合**:seed 跨多天 span,查一个 2 天子范围,断言只算范围内;`from>to`→ ValueError;`window` 旧行为不变。
- **后端 · 逐日分桶**:seed 跨 3 天(含一条子循环 span),断言 3 个日桶、每天 cost/turns/p95/cache 正确、子循环被排除、无数据的天不出现;某天无工具 span → 该天 p95 为 null。
- **后端 · daily API**:命中接口断言 JSON 结构 + 响应不含 span 原文。
- **前端 · 渲染**:stub daily + aggregates,断言日历格子渲染、选中范围高亮、指标下拉链接带 from/to、快捷在;某天 cell 的 href 在「当前单天」与「当前区间」两种状态下分别指向「区间」与「单天」(两次点选语义)。
- **前端 · 降级**:daily 或 aggregates 拉取失败 → 对应块占位、不 500。
- **点选手感**:服务端语义用上面 href 断言覆盖;真实点击最后浏览器实拍验。

## 8. 分支

建在 `chatloop-observability-calendar`(off 已合 #154 的 main),独立 PR。

## 9. 关键决策记录

| 决策 | 选择 | 理由 / 放弃的备选 |
|---|---|---|
| 视图 | 日历热力图 | 最贴「像日历看每一天」;放弃纯范围选择器(无逐日可视)、每日列表(非日历观感) |
| 范围选择 | 点起止两次选 + 纯服务端 hrefs | 无需客户端 JS:每格 href 由当前 from/to 算下一步选择,状态全在 URL;放弃拖拽框选(要写拖拽 JS) |
| 上色指标 | cost/turns/p95/cache 四选一下拉 | daily 一次查全返回,切换零额外后端成本 |
| 分桶粒度 | 仅到天 | 小时级 YAGNI |
| 接口 | daily 与 aggregates 两个端点 | 各自独立可测;range 复用并扩展 aggregates(加 from/to,兼容 window) |
| 日历跨度 | 固定 ~13 周 | 一屏看 ~3 个月;防任意大范围 daily 慢查 |
