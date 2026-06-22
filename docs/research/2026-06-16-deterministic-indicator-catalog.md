---
title: 确定性指标目录 — 验证集/RL 可自动判分的金融计算清单
date: 2026-06-16
type: catalog
source: workflow `deterministic-indicator-catalog`(5 agent:估值器/风险技能/tushare/eval 资产盘点 + 综合边界检查)
related:
  - docs/research/2026-06-09-rl-readiness-audit.md
  - docs/claude-context/v1.x-multi-valuation-cross-check-landed.md
---

# 确定性指标目录

> **这是什么**:把本仓"能用固定公式算、给定输入有唯一正确答案、且能找到**独立**标准答案来判分"的金融指标盘成一张清单。它是验证集 / pass@k / RL 可验证轨的**脊梁**——目录一立,出题就变填空(挑票挑日期→独立 oracle 算 gold→散户口吻包成自然问题)。
>
> **四列含义**:公式=怎么算;原始字段=喂给公式的原料(具体 tushare 接口/字段);**独立 oracle=谁出"标准答案"判对错,关键是不能用 AI 同款算法/同份数据(否则拿复印件当答案)**;难度档=easy 单字段 / medium 多字段或要解析日期 / hard 要整段序列或跨多只票。
>
> **铁律(全表通用)**:mock-tushare 是 LLM 伪造、非确定,**oracle 一律只能用真 tushare 值(cassette 固化)**,不能用 mock。

收录 **54 项**(easy 26 / medium 20 / hard 8),划掉 **10 项**(主因:DCF 全家循环 oracle + 重复 + 主观)。

---

## 收录 · 简单档(easy)

最干净的一档。多数是"直接取 tushare 预先算好的字段"或"一两个数四则运算"——oracle 天然独立(tushare 算的≠AI 算的)。

| 指标 | 大白话 | 公式 | 独立 oracle | 原始字段 · 坑(file:line) |
|---|---|---|---|---|
| PE 估值理论价 | EPS×同行 PE 倍数反推该值多少钱/股 | eps×(industry_pe_avg+median)/2 | 独立手算三参四则 | eps(fina_indicator.eps)+ 同行 pe_ttm 聚合 · eps≤0/PE≤0 raise 跳过;daily_basic.pe_ttm 方向相反不能直接对账(pe.py:18-55) |
| PB 估值理论价 | 每股净资产×同行 PB 倍数反推 | bvps×(industry_pb_avg+median)/2 | 独立手算三参四则 | bvps(fina_indicator.bps)+ 同行 pb 聚合(pb.py:21-57) |
| 持仓权重 | 单只票占账户的比例 | w_i = 市值_i / Σ市值 | 独立手算逐仓除法 | 各仓 market_value · 分母口径要跟总市值对齐否则和≠1(portfolio_analytics.py:38) |
| 单仓市值 | 某票现在值多少 | quantity×last_quote_price | 独立手算两数相乘 | positions.quantity/last_quote_price(portfolio_tool.py:59) |
| 单仓浮动盈亏 | 某票账面赚/亏多少 | qty×price − total_cost | 独立手算 | 价缺则 None;不含已实现损益(portfolio_tool.py:60) |
| 持仓集中度 HHI | 一个数衡量押注集中度 | Σw_i²(全压一只=1) | 独立纯函数 sum(w²) / Excel | ⚠ portfolio_risk/hhi.py **磁盘未落地**,仅 tool_docs 示例+单测 mock;公式确定(tool_docs.py:307) |
| ROE | 用股东的钱一年赚回百分之几 | 直取 fina_indicator.roe | **tushare fina_indicator.roe 预算字段** | 交叉验证 n_income_attr_p÷净资产(tushare_client.py:1796) |
| 销售毛利率 | 卖 100 块剩多少毛利 | 直取 fina_indicator.grossprofit_margin | tushare 预算字段 | ⚠ 别混 gross_margin(额)vs margin(率)(tushare_client.py:2136) |
| 销售净利率 | 卖 100 块净赚多少 | 直取 fina_indicator.netprofit_margin | tushare 预算字段 | (tushare_client.py:2136) |
| 资产负债率(取数) | 家当里多少是借来的 | 直取 debt_to_assets 或 total_liab/total_assets | tushare 预算字段(+自算交叉验证) | ⚠ 预算是% / 自算是 0-1,差 100 倍要对齐(get_balance_sheet.py:62) |
| 流动比率 | 短期能不能还上短债 | 直取 current_ratio 或 流动资产/流动负债 | tushare 预算字段 | 自算 max(分母,1) 防除零(get_balance_sheet.py:63) |
| 市盈率 PE(快照) | 股价是每股利润几倍 | 直取 daily_basic.pe/pe_ttm | tushare 预算字段(某交易日) | 数值确定;"贵不贵"主观已排除;要给 trade_date(get_daily_basic.py:54) |
| 市净率 PB(快照) | 股价是每股净资产几倍 | 直取 daily_basic.pb | tushare 预算字段 | 要给 trade_date(get_daily_basic.py:55) |
| 市销率 PS(快照) | 股价是每股营收几倍 | 直取 daily_basic.ps/ps_ttm | tushare 预算字段 | 亏损股替代 PE(tushare_client.py:1222) |
| 股息率 | 买入按现价一年回多少现金分红% | 直取 daily_basic.dv_ratio/dv_ttm | tushare 预算字段 | (get_daily_basic.py:57) |
| 换手率 | 当天成交占流通股% | 直取 daily_basic.turnover_rate | tushare 预算字段 | vol(手)与 float_share 单位对齐(tushare_client.py:1216) |
| 总市值/流通市值 | 公司按现价值多少钱 | 直取 daily_basic.total_mv/circ_mv | tushare 预算字段 | total_mv 单位万元(tushare_client.py:1229) |
| 单日涨跌幅 | 今天比昨天涨跌% | 直取 daily.pct_chg 或相邻 close 自算 | tushare daily.pct_chg(cassette 实测) | 不复权口径要一致(price_anomaly.py:42) |
| 经营现金流为正 | 主业真收到现金还是只是账面盈利 | n_cashflow_act > 0(布尔) | tushare cashflow.n_cashflow_act 原值 | 仅二值信号(get_cashflow.py:58) |
| 中文数字归一 parse | "150亿/8000万/12.5%"换成基础单位 | 含亿×1e8/含万×1e4/含%÷100 | 独立(输入→期望)对照表逐条 | ⚠ 正则只取首数字、逗号会断、裸数按元(numerical_metric.py:25) |
| 工具选择首选正确 | 第一下该调行情还是财报,调对算过 | got==expected.first_tool | golden 人工标签 + AST 比对(零 LLM) | live 产 tool_calls 非确定,但"给定调用→判分"确定(_core.py:184) |
| 工具入参子集匹配 | 查茅台代码填对 600519.SH 没 | ∀(k,v)∈args_contains: args[k]==v | golden 人工标签 + 逐键相等 | list 参数顺序要全一致(_core.py:215) |
| 工具互斥不误调 | 该弃权时没手痒调禁用工具 | ∀f∈not_tools: f∉调用名单 | golden 人工标签 + 集合不含 | IrrelAcc 核心抓手(_core.py:197) |
| 免责声明存在性 | 给了实质回答必须带"不构成投资建议" | required→ '不构成投资建议' in text | 独立标注是否应带 + 子串硬检 | 改文案要同步 DISCLAIMER_MARK(scorers.py:21) |
| 方向性荐股违例 | 不能说"建议买/稳赚"等 | any(违例词 in text) | 独立固定词表 + 子串 | 粗筛,委婉荐股漏判(scorers.py:69) |
| EV/EBITDA 理论价 | 经营利润×倍数算公司总值再减净负债 | (见 medium,实为 medium) | — | (归入 medium) |

## 收录 · 中等档(medium)

要多个字段、或要解析日期(近一年/上季度)、或带经验系数。日期这块正是 trade_cal + 参考日期注入刚解锁的。

| 指标 | 大白话 | 公式 | 独立 oracle | 原始字段 · 坑(file:line) |
|---|---|---|---|---|
| EV/EBITDA 理论价 | 经营利润×倍数算整个公司值多少(含债)再减净负债除股数 | target_ev=ebitda×倍数;减 net_debt;÷shares;clamp≥0 | 独立重算(固定同口径入参) | ebitda/net_debt/shares 口径依赖上游,对账须固定(ev_ebitda.py:26) |
| 公司 WACC(简化 CAPM) | 给公司算资金成本:行业基准上按波动/负债微调 | baseline+(β−1)×0.02+(0.01 if D/E>1) | 独立重算但**必须复用本仓经验系数**(非教科书 CAPM) | 系数是 spec 经验值;β 缺则 0(dcf.py:139) |
| 单日组合归因总收益 | 账户今天整体涨跌% | Σ(w_i×当日涨跌_i) | 独立加权和 Excel | by_class 求和须==total(闭合)(portfolio_analytics.py:39) |
| 资产负债率 QoQ 变化 | 这季欠债比例比上季多几个百分点 | (本季−上季)×100 pp | tushare debt_to_assets 两期相减 | 按 end_date 排序取末两季(financial_ratio.py:68) |
| 经营现金流环比下滑% | 主业现金比上季少% | (prev−curr)/prev×100(prev>0) | tushare n_cashflow_act 两期 | prev≤0 不算(cash_flow.py:47) |
| 股东户数降幅% | 股东人数比上期少%(筹码集中) | (prev−curr)/prev×100 | tushare holder_num 两期 | prev≤0 短路(shareholder_count.py:39) |
| 股东户数趋势分类 | 减5%以上=集中/增5%以上=散户化/中间稳定 | Δratio≤−.05集中/≥+.05分散/否则稳定 | tushare holder_num 序列 + ±5% 阈值 | ±5% inclusive(get_holder_change.py:23) |
| 营收同比增速 | 今年营收比去年同期增% | (本期−去年同期)/去年同期×100 | tushare fina_indicator.q_sales_yoy 预算 | 对齐同 end_date;基数近0增速爆(tushare_client.py:1861) |
| 净利润同比增速 | 今年净利比去年同期增% | 同上 | tushare netprofit_yoy 预算 | 同上(tushare_client.py:1857) |
| 分红连续性 | 过去 N 年几年真发了现金分红 | 有分红年数 / N | tushare dividend.cash_div 记录 | ⚠ dividend 无区间参数须客户端裁;去重口径要固定(get_dividend_history.py:64) |
| 营收(取数核对) | 报告营收 vs 财报,差≤1%算对 | \|claimed−real\|/\|real\|≤0.01 | **tushare income.revenue 原值** + ±1%容差 | 无单位默认按元;adapter 须 ann_date 降序(numerical_metric.py:90) |
| 净利润(取数核对) | 报告净利 vs 财报 ≤1% | 同上,real=income.n_income | tushare 原值 + 容差 | 净利 vs 归母口径对齐(numerical_metric.py:94) |
| 资产负债率(派生核对) | 两数算一下再跟报告对 | real=total_liab/total_assets | tushare 两原值相除 + 容差 | ⚠ v0 误 route fetch_income(numerical_metric.py:141) |
| ROE(指标核对) | 报告 ROE vs tushare ≤1% | real=fina_indicator.roe/100 | **tushare 预算 roe**(非 AI 再算)+ 容差 | ROE 多口径要对齐(numerical_metric.py:54) |
| 工具序列按序包含 | 多步任务按"搜→取→算"顺序调全没 | 子序列(中间可穿插) | golden 人工序列 + 子序列判定 | 隐式计算类靠它评(_core.py:234) |
| 记忆边·持仓数量 qty | "买茅台500股"抽出 qty=500 | expected.qty==抽出.qty | golden 标注 qty + 等值比对 | 跨轮拼边;名→ts_code(cross_turn_golden.jsonl:1) |
| 记忆边·成本价 avg_cost | "500股@1500"抽出 1500 | 精确相等 | golden 标注 avg_cost | @简写靠抽取器(cross_turn_golden.jsonl:1) |
| 记忆边数 | 该产生几条记忆边数对没 | len(边)==expected_count | golden 标注 count | 计数对但实体错不算全过(cross_turn_golden.jsonl:19) |
| 记忆·时间窗重叠 | "去年11月说过啥"检索落在窗里 | bi-temporal 重叠 / 总数 | golden 时间窗标注 + 纯函数判定 | 相对时间先解析成绝对窗(temporal_correctness_metric.py:1) |
| 记忆·生效起点=事件时间 | 8月买的记忆起点该是8月不是入库日 | \|valid_from−expected\|≤14天 | golden expected_date + 日期差 | 抓 bi-temporal 经典 bug(db_assertions.py:143) |
| 基金净值日涨跌 | 基金今天净值涨跌% | nav_t/nav_{t-1}−1 | tushare fund_nav.pct_chg 预算 | OTC 滞后一日(portfolio_overview_service.py:79) |

## 收录 · 难档(hard)

要整段价格序列或跨多只票——tushare 多半**没有**预算字段,但 oracle 可用独立库(numpy/pandas/empyrical)复现。**全档口径必须定死**(复权/对数vs简单收益/√252/ddof/分位插值)。

| 指标 | 大白话 | 公式 | 独立 oracle | 坑(file:line) |
|---|---|---|---|---|
| 区间涨幅 | 某段时间总涨跌% | close_end/close_start−1 | tushare close 序列首末独立算 | 复权统一;get_daily 上限 260 行(get_daily.py:60) |
| 最大回撤 | 从最高跌到最低最多亏% | max(1−close_t/峰值) | 独立库 empyrical/quantstats max_drawdown | ⚠ risk_assessment 实现磁盘未落地仅文档(get_daily.py:60) |
| 历史波动率(年化) | 价格颠不颠,年化 | std(日收益)×√252×100 | 独立 numpy.std×√252 | ⚠ 实现未落地;须定 对数/简单·√252·ddof(risk_thresholds.yaml:51) |
| 两股相关性 | 两票同涨跌还是反着 | Pearson(收益A,收益B) | 独立 pandas .corr | 须按 trade_date 对齐(剔停牌)(compare_stocks.py) |
| 营收/净利 CAGR | 多年增长摊平成每年% | (末/首)^(1/年数)−1 | tushare 年报序列独立算 | 取年报同口径;首期为负无意义(tushare_client.py:1511) |
| PE 历史分位 | 现在 PE 在过去 N 年偏低/高 | count(历史<当前)/N | tushare daily_basic.pe 序列独立分位 | 分位确定;低/高估标签主观已排除(get_pe_history.py) |
| 时间加权收益 TWR | 账户真实赚赔%,剔掉加减仓进出 | 每日 r_t 链式连乘∏(1+r)−1 | 独立 GIPS/empyrical 复现 | 用期初持仓数量估值故剔加减仓(portfolio_analytics.py:70) |
| 股票三层归因 | 涨跌拆:跟大盘/行业超额/个股 alpha | market+sector_excess+idio 加权 | 独立逐仓三段加权(telescoping 闭合) | beta≈1 是 MVP 简化口径,oracle 须沿用(portfolio_analytics.py:45) |

---

## 划掉(excluded)及理由

综合 agent 的边界检查抓出的——**最重要的是 DCF 全家被判"循环 oracle"**(标准答案只能照抄被测代码=拿 AI 复印件当答案)。

| 划掉项 | 理由(精简) |
|---|---|
| **DCF 增速轨迹(10年衰减序列)** | 循环 oracle:bull/bear 的 deviation scaling×1.2/0.8、线性衰减全是本仓自创口径,教科书/独立库无对应标准答案,复现只能照抄代码 |
| **DCF 单场景理论价** | 循环 oracle:简化口径(EV 直接当股权价值未减净负债),独立 DCF 算出来不会相等 |
| **DCF 三场景(base/bull/bear)** | 上述两组件都循环,组合更无独立答案;binary reset 也是自创 |
| **DCF 敏感性矩阵(5×5)** | 每格=已划掉的 compute_dcf_value;自创 clamp/propagate 策略 |
| 估值一致性 CV + 分级 | CV 本身有标准答案,但输入挂在 DCF 循环项上 + 阈值 0.15/0.30 主观可校准 |
| 大单资金净流向 | 阈值未设(差1块也算 inflow)、口径贴噪声,确定性存疑 |
| 组合总市值 / 60日涨幅 / TWR重复 / 当日归因重复 | 与保留项同义重复,合并剔除 |

---

## 覆盖与缺口(coverage_note)

**覆盖七大类计算意图**:① 相对估值理论价(PE/PB 最干净,EV-EBITDA/WACC 须复用经验系数);② 行情/估值快照取数(daily_basic 族,oracle=tushare 预算字段,最干净一档);③ 财报指标取数(fina_indicator 预算或两原值相除);④ 需 AI 自算的时序衍生(涨幅/回撤/波动率/相关性/CAGR/PE分位/TWR/三层归因,oracle=独立库,全 hard);⑤ 监控信号数值(分级阈值剥离不计);⑥ 持仓/组合基础量(纯算术);⑦ eval harness 确定性核(golden 标签 + 数据源独立 oracle,零 LLM)。

**主要缺口(尚无可信 oracle)**:
- **(A) 整个 DCF 家族**——全是循环 oracle。要补:先把口径冻结成 spec,再请独立第三方按同口径手算建一份外部黄金集,否则只能拿 AI 同款代码当答案。
- (B) 估值一致性 CV 分级——上游挂 DCF + 阈值主观。
- (C) 大单资金净流向——缺阈值、贴噪声。
- (D) ~~risk_assessment 的最大回撤/年化波动率/HHI 无生产实现~~ → **已决策走 run_python**(2026-06-16):AI 用代码解释器当场算,判分对照独立库 oracle,不补技能脚本。`portfolio_risk/hhi.py` 是指向空气的死引用,待清理。详见文末「计算路径决策」。
- (E) **所有 mock-tushare 路径一律不能当 oracle**,真值必须走真 tushare cassette。

---

## 下一步(建议)

1. **先挑 easy + medium 的"取数/派生"档起验证集**——③④ 两类(财报取数、行情快照)oracle 最干净(tushare 预算字段),零额外工程量,直接能出题。
2. **难档(时序衍生)需先冻口径**——复权/对数收益/√252/ddof/分位插值定死,再写独立 oracle(用 empyrical/numpy,不抄被测代码)。
3. **DCF 暂不进可验证轨**——循环 oracle,留分析轨(judge/SFT);要进得先 spec 冻口径 + 外部黄金集。
4. **回撤/波动率/HHI 走 run_python**(已决策,见下「计算路径决策」)——不补技能脚本,AI 当场算 + 独立库 oracle 判分;清理 tool_docs 里 `portfolio_risk/hhi.py` 死引用。

---

## 计算路径决策(2026-06-16)

**决定:凡"AI 需自算"的指标(回撤/波动率/相关性/HHI/区间涨幅/CAGR/PE分位/组合收益等),一律走 `run_python`(代码解释器当场算),不再补技能脚本。** 理由:这些本就无 tushare 预算字段、无脚本,run_python 是现成路径,且与已有代码解释器架构一致。

落到验证集 / RL,这类题这样设计:

1. **任务形态(多步 agentic)**:自然问题 → AI 调数据工具取数 → `run_python` 当场写公式算 → 出最终数字。正是可验证轨要的"取数 + 算"多步形态。
2. **判分两条都要过(防"假算"绕过)**:
   - ① 最终数字落在独立 oracle 的 **±容差**内;
   - ② **`run_python` 真的被调起了**(查 trace)——没真算、心算/蒙的,即便数字对也判低分(系统提示已有"派生数字必须由工具算出"纪律,这里落到判分硬门控)。
3. **oracle 独立、且非循环**:用独立库(numpy / pandas / empyrical / quantstats)从**同一份冻结的真 tushare 数据**算 gold,**不是 AI 的代码**。回撤/波动率/相关性有**教科书标准定义**,独立实现就是合法独立答案——这跟 DCF 的自创口径(循环 oracle)本质不同。
4. **唯一真要补的工程:口径冻死 + 写进题面**。回撤算复权价吗?波动率用对数收益、√252、ddof=1 吗?分位用 `<` 还是 `≤`、插不插值?这些必须在 spec 钉死,且**题面/系统要明确告诉 agent 用哪套**——否则 agent 用 √250、oracle 用 √252,它算对了也被判错。这是"能判"→"判得准"的关键。

**待清理**:`tool_docs.py` 里 `run_skill_script(skill='portfolio_risk', script='hhi.py')` 示例是死引用(该技能/脚本不存在),应删或改成 run_python 示例。
