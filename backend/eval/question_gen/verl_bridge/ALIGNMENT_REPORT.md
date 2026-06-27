# verl tool_box(Path B)工具对齐报告

> 2026-06-27。逐工具核对 verl RL rollout 工具(Path B)与 gold/Path A 一致性,
> 经真实 `ToolBox.exec(as_of=20260612)` 验证。背景见 `field_reachability_map.md`。

## 结论

**7/7 工具对齐**(6 数据工具 + run_python)。修复 2 处字段缺口,4 个本就对齐,
run_python 是同款沙箱无对齐问题。回归:`test_get_daily_basic` + `test_get_stock_daily` 7 passed。

**关键前提**:verl tool_box 用的是**和 Path A 同一批工具类**(`app.tools.*`),非另写实现。
对齐 = 确保 (a) args_schema 有 `as_of` 字段(tool_box 据此注入钉基准日)(b) 输出含 gold 所需字段。

## 逐工具验证表

| 工具 | 对齐 | 验证(ToolBox.exec, as_of=20260612) | 处置 |
|---|---|---|---|
| lookup_ts_code | ✅ | name="贵州茅台" → 600519.SH | 纯查码无时间维,本就对齐(Path B 专属,解锁多股) |
| get_stock_quote | ✅ | price=1291.91 @as_of | args 有 as_of,tool_box 注入,本就对齐 |
| get_pe_history | ✅ | 分位=0.0206 @as_of | args 有 as_of,本就对齐 |
| **get_daily_basic** | ✅(修) | trade_date=20260612 **==as_of 钉住** pe=19.62 | **缺 as_of → 加字段**,run() 用 as_of 当 trade_date |
| **get_stock_daily** | ✅(修) | 首项含 **pct_chg=-1.24** | **输出缺 pct_chg → 补**(波动/相关需,gold 走 pct_chg 非 close 比值) |
| get_financials | ✅ | FY2024 营收=1709亿 eps=68.64 | end_date 选期(模型传"X年报"),本就对齐;描述含 end_date 提示 |
| run_python | ✅ | 同款 SkillExecutor 沙箱 | 计算面,两路径同实现,无对齐问题 |

## 修复(均加法、不破坏 Path A)

1. **get_daily_basic**:`DailyBasicArgs` 加 `as_of` 字段;run() `trade_date = as_of or trade_date`。
   Path A 走 MCP handler 直传 trade_date(不传 as_of)→ 默认 None 不受影响。
   修前:verl 不钉 → 返回最新快照漂移;修后:钉到出题日,与 gold 同期。
2. **get_stock_daily**:输出每项加 `pct_chg`(NaN/缺列→None)。
   修前:只给 close → 波动/相关被迫用 close 比值(拆股/分红偏差);修后:与 Path A MCP get_daily 的 pct_chg[] 对齐。

## 覆盖性核对

verl tool_box 的 6 数据工具 + run_python **覆盖全部 9 意图**:
stock_study→get_stock_daily · snapshot→daily_basic · financial_report/verify/trend→get_financials ·
valuation→financials+daily_basic · valuation_percentile→pe_history · position/portfolio→quote/stock_daily ·
多股→lookup_ts_code · 计算→run_python。**无缺失工具。**

## 残留(非阻塞)

- get_financials 的**内部描述** end_date nudge 比 MCP 版弱(MCP:"MUST pass else latest")。
  Path B 模型靠 SFT 学会传 end_date + 现有提示,验证通过;若 RL 期发现取期错可再强化。
- TWR/归因(组合算法题)无专用工具——这是**能力缺口非对齐缺口**(Path A 也没有),搁置中。
