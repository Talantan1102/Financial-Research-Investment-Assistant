# D4 字段可达性地图(出题端 gold ↔ 答题端工具)

> 2026-06-26 生成。静态交叉引用 gold 侧(generator/operators/indicator_oracle/valuation_helpers/portfolio_analytics)
> ↔ 工具侧(app/tools + app/mcp_server/tools + verl tool_box),11-agent workflow + 三组对抗校验(全 `all_correct`,零修正)。
> **Path A** = pass@k eval 实际跑的工具面(MCP chat_tools + build_real_hub)。**Path B** = verl RL rollout 的 tool_box。

## 头号结论

**Path A 上 31 个(意图×指标)全部可达,0 个硬数据缺口。** 本 session 修完 get_financials 后,
没有题会因"取不到 gold 需要的原始字段"而 passed=0。**可达性已收敛,不会再冒新的字段缺口。**

剩下的问题**不是可达性**,是另两类(见下):**退化(工具直接吐答案)** + **Path B 训练面分布漂移**。

## 一、可达性表(✅ 全可达)

| intent | 指标 | gold 需要的原始字段 | 提供工具(Path A) | 留住推理空间? |
|---|---|---|---|---|
| stock_study | 涨幅/回撤/波动/CAGR/相关/排序/筛选 | close / pct_chg / trade_date | MCP get_daily(columnar) | ✅ 自己算 |
| snapshot_quote | PE/PB/换手率/股息率 | pe/pb/turnover_rate/dv_ratio @as_of | get_market_indicators[daily_basic] | ⚠ 取数题,无算可留(设计如此) |
| financial_report | 营收/净利 | revenue/n_income(元) | get_financials | ✅ 元→亿转换 |
| financial_report | ROE/资产负债率/毛利率 | roe/debt_to_assets/grossprofit_margin | get_financials(本session补) | ⚠ 查表比率,直给 |
| financial_verify | 核对营收/净利 | revenue/n_income | get_financials | ✅ 转换+比对 |
| trend_signal | 营收同比/净利同比 | or_yoy/netprofit_yoy | get_financials.revenue_yoy/net_profit_yoy | ❗ 退化(直给,见二) |
| valuation_calc | PE/PB理论价 | eps/bps(标的)+ pe/pb(同行) | get_financials + get_market_indicators[daily_basic] | ✅ 自己算 avg/median×eps |
| valuation_percentile | PE历史分位 | pe 序列 + 当前 pe | get_market_indicators[pe_history] | ❗❗ 退化最严重(见二) |
| position_calc | 单仓市值/浮盈 | close(qty/cost 题面自带) | get_stock_quote@as_of | ✅ 自己算 |
| portfolio_calc | 权重/HHI/TWR/归因 | close(+ pct_chg 归因) | MCP get_daily / get_stock_quote | ✅ 自己算(run_python 闸守) |

**TWR/归因不是缺口**:它们没有专用工具,但原料(close/pct_chg)可达,是"算法题"——模型在 run_python 里算,
`requires_run_python` 第二道闸防心算蒙数。之前 pass 率低(TWR 55%)是多步计算难度,非数据不可达。

## 二、推理空间退化(10/31 行 reasoning_gap=false)—— 真正要决策的地方

工具直接吐出 gold 的答案 → 那道题"训不到东西"(模型只是把工具结果抄下来)。分三档:

- **(a) 设计如此,非退化(4 行)**:snapshot PE/PB/换手率/股息率。本就是"取数题",gold = 一个原始字段,没有计算可留。✅ 可接受。
- **(b) 查表比率,轻度(3 行)**:ROE/资产负债率/毛利率。工具直接返回 fina_indicator 的比率 = gold。tushare 原语,口径所限自己裸算反而超容差。⚠ 可接受。
- **(c) 真退化,值得处理(3 行)**:
  - ❗❗ **PE历史分位**(最该警惕):这是**难档**意图、本应有真推理空间,但 `get_pe_history` 算的分位 **与 oracle 逐字节相同**,且原始 PE 序列在 Path A **取不到**(daily_basic 只给单日、get_daily 只给 close 不给 pe)→ 工具把成品答案直接交出,`run_python` 闸也救不回(模型把成品过一遍 run_python 就过闸)。**这题现在训不到"算分位"的能力。**
  - ❗ **营收同比/净利同比**:工具把 or_yoy/netprofit_yoy 直接当 revenue_yoy/net_profit_yoy 返回 = gold,零中间计算。

  **决策选项**(待定,非阻塞):① 接受其为"取数题"降档;② 给 pe_history 增一个只返回**原始 PE 序列**的模式,让模型自己算分位(恢复推理空间);③ 同比题改成给两年 revenue 让模型自己算(但有 tushare 重述基数口径风险)。

## 三、跨切面风险(非缺口,影响准确率/训练分布)

1. **❗ Path B(RL 训练面)分布漂移**——影响真正的 RL rollout,不影响 eval pass@k:
   - verl `get_stock_daily` 只给 {trade_date, close},**无 pct_chg** → 波动/相关的口径在训练面**不可达**,模型被迫用 close 比值 → 拆股/分红系统性偏差。
   - verl `daily_basic`/`financials` **无 as_of 字段** → tool_box 不注入 → 返回**最新**快照而非 as_of → PE/PB/市值在训练面漂移。
   - **这是训练数据真分布问题,值得在 RL 跑前对齐 verl tool_box。**
2. **可发现性**:MCP `get_financial_statements` 的描述只写了 "revenue/net profit/ROE/P/E",**eps/bps/gross_margin/debt_to_assets/yoy 在返回 JSON 里但描述没点名** → 模型可能不知道能取 → 即使字段补了,pass 率仍可能偏低。**(本 session 顺手修:已在描述里点名这些字段)**
3. **end_date 钉期**:所有 财报/估值/同比 行都必须传 `end_date=20241231`,否则 `_select_period_row` 落到最新期。(已加 nudge)
4. **资产负债率口径冲突**:`statement=balance` 给的是 0-1 分数(total_liab/total_assets),`statement=income` 给的是 % → 模型若走 balance 路径会 100× 错位。建议引导走 income.debt_to_assets。
5. **compare_stocks 陷阱**:不钉 as_of + period 硬编码 'latest' + pe=0.0,多股对比会偏期/偏日。不是任何计价意图的自然工具,但是个坑。
6. **name→code 不对称**:`lookup_ts_code` 只在 verl(Path B)注册,Path A 无 name→code 工具 → 多股题靠模型记 ts_code(POOL 全大盘股,缓解但依赖参数记忆)。

## 四、行动清单(对着勾)

- [x] get_financials 暴露 eps/bps/gross_margin/debt_to_assets(本 session)
- [x] MCP financial_statements 加 end_date nudge(本 session)
- [x] **MCP financial_statements 描述点名 eps/bps/gross_margin/debt_to_assets(可发现性,本 session 顺手补)**
- [x] **决策(2026-06-26 作者定):PE历史分位 / 同比 退化 → 降档当"取数题"接受,不加 raw-series 模式。** 原则:不为了难度而故意加难度。这些题仍是有效样本(教正确工具选择/years_back/as_of/字段/×100 口径),只是不要求"从零算分位"。get_pe_history 维持现状。
- [ ] RL 跑前对齐 verl tool_box:get_stock_daily 加 pct_chg、daily_basic/financials 加 as_of 字段(Path B 分布)
- [ ] 引导 资产负债率 走 income.debt_to_assets(避 balance 0-1 口径冲突)
