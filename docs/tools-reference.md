<!-- 由 tools-doc-research workflow 生成 (2026-06-01)，13 工具全部上网核对上游 API 官方文档。 -->
<!-- 核对发现的 4 个用法偏差(kb_search/get_dividend_history/get_forecast/get_pe_history)已于同日修复，本文为修复后状态。 -->

# 工具文档(Tools Reference)
> 一句话说明:本项目 agent 可调用的工具及其上游数据源/API,经官方文档核对。

## 概览表

| 工具 | 上游 API | 用法是否与官方文档一致 | 备注 |
|------|----------|----------------------|------|
| get_stock_quote | Tushare Pro `daily`(日线行情,doc_id=27) | 是 | 字段全对;vol 单位"手"、pct_chg 已是百分比,口径提示非 bug |
| get_financials | Tushare Pro `income`(doc_id=33)+ `fina_indicator`(doc_id=79) | 是 | pe 恒为 0.0(有意设计);period 当前不透传上游 |
| get_balance_sheet | Tushare Pro `balancesheet`(doc_id=36) | 是 | end_date 官方语义是"公告日范围",工具当报告期用(语义风险,非崩溃) |
| get_cashflow | Tushare Pro `cashflow`(doc_id=44) | 是 | 字段逐字一致;report_type 未过滤;需 ≥2000 积分 |
| get_daily_basic | Tushare Pro `daily_basic`(doc_id=32) | 是 | 8 字段全对;pe 亏损为空被压 0.0;市值单位"万元" |
| get_dividend_history | Tushare Pro `dividend`(doc_id=103) | **否(已修)** | `ann_date_start/end` 非官方参数→years_back 失效;已改为按 ann_date 客户端裁剪 |
| get_forecast | Tushare Pro `forecast`(doc_id=45) | **否(已修)** | `period` 是入参名非输出字段；已改用 `end_date` 作报告期排序/取值 |
| get_holder_change | Tushare Pro `stk_holdernumber`(doc_id=166) | 是 | 字段全对;start/end_date 官方按公告日过滤(语义注意点) |
| get_pe_history | Tushare Pro `daily_basic`(doc_id=32) | **否(已修)** | `fields` 误塞进 params 内层→字段投影失效；已改走 `_call_cached` 的独立 fields 参数 |
| get_money_flow | Tushare Pro `moneyflow`(doc_id=170) | 是 | 区间求和大单/中单买卖金额;net_lg_signal 为自定义派生信号(非上游字段) |
| get_news | 博查 Bocha AI Web Search(POST /v1/web-search) | 是 | days_back 为死参数;freshness 固定不传 |
| web_search | 博查 Bocha AI Web Search(POST /v1/web-search) | 是 | 多传 `page:1`(官方无);search_type 未用 freshness;count 锁 20 |
| kb_search | 内部 Milvus 向量检索(pymilvus `MilvusClient.search`) | **否(已修)** | COSINE 下 `1.0 - distance` 排序反转;已改 `similarity = distance`(实测自匹配 distance=1.0 验证) |

## ⚠️ 发现的用法偏差/风险

> ✅ **以下 4 个偏差已于 2026-06-01 全部修复**(kb_search 排序反转、get_dividend_history 区间参数、get_forecast 字段名、get_pe_history fields 位置),并补了/修了对应单测(kb_search 单测原先编码了错误行为,已据 live Milvus 实测——自匹配 distance=1.0——更正)。以下为偏差的原始记录,供追溯。

当前共 4 个工具标记用法偏差(our_usage_correct=false):

1. **get_dividend_history**:两处不一致,一处语义风险。
   - 【输入参数名错 — 导致 years_back 静默失效】service 传 `ann_date_start` / `ann_date_end`,而官方 `dividend` 接口根本没有这两个参数(只有单值 `ann_date` / `record_date` / `ex_date` / `imp_ann_date`)。Tushare 对 params 里不认识的 key 通常静默忽略,因此服务端**不会按日期区间过滤**:`years_back` 完全不生效,返回的是该 ts_code 的全量分红记录(而非近 N 年)。后果:`recent_dividends`、`dividend_consistency`(按"年数"统计)、`avg_dv_ratio_5y` 都是基于全历史而非近 5 年计算,语义错误且随个股历史长度漂移。需改为客户端按 `ann_date` 区间过滤,或仅传 `ts_code` 后在 Python 侧裁剪。
   - 【字段语义 — 命名误导,非运行时错误】`cash_div` 是"税后每股现金分红额"(元/股),不是分红率/股息率。工具把它平均后命名为 `avg_dv_ratio_5y`(dividend yield ratio),名实不符;它实际是"近若干条记录的平均每股现金分红",既不是 ratio 也(因上一条)不保证是 5y。若想要真实股息率需结合股价另算。
   - 字段读取(`ann_date`、`cash_div`)与解包结构正确,顺序兜底 `sort_values("ann_date", ascending=False)` 正确。

2. **get_forecast**:关键不一致。`period` 在官方 `forecast` 中是【入参名】,但【不是输出字段名】—— 输出里报告期字段叫 `end_date`。工具把它当输出字段用,造成两处隐性 bug(不抛异常,但语义错):
   - `get_forecast.py:70` `if "period" in df.columns` 排序分支永不命中(返回 DataFrame 无 `period` 列),实际退化到 `ann_date` 分支排序。多行时仍能"取最新",但靠 ann_date(公告日)而非 end_date(报告期),边界场景(同日多次更正预告 / 跨报告期同日公告)排序结果可能不是预期的"最新报告期"。
   - `get_forecast.py:78` `"period": str(row.get("period", ""))` 永远返回空字符串 `""`,下游拿不到报告期。
   - 修复:把 line 70 列名判断、line 71 sort_values key、line 78 取值的 `period` 改为 `end_date`(返回 dict 的 key 仍可保留 `period`,取值改 `row.get("end_date","")`)。`type`/`p_change_min`/`p_change_max` 字段名与官方一致,信号分类关键词与官方 type 取值集吻合,入参传递也正确。

3. **get_pe_history**:`fields` 参数位置放错。在 `tushare_service.py` 第 162、166 行,`"fields": "pe"` 被塞进了 **params 字典内部**(`{ts_code, start_date, end_date, fields:"pe"}`),而 `TushareClient.call(api_name, params, fields=None)` 期望 `fields` 作为独立的第三个参数、最终写入请求 body 的顶层 `body["fields"]`。`_call_cached` 只透传 `(api_name, params)`,从不传 `fields=`,导致 `fields` 永远落在 params 里、顶层 fields 始终为 None。后果(非崩溃,隐性误用):Tushare 忽略 params 内的未知键 `fields`,且因顶层无 fields 而返回**全部默认列**(含 pe),故 `history["pe"]` 仍能取到、不报错——但字段投影完全失效,每次拉回全字段、浪费带宽,并使缓存 key(按 params 哈希)携带无效 fields。建议改为 `fields` 走 `call` 的独立参数,或 `self._client.call("daily_basic", {ts_code,...}, fields="pe")`。另:percentile 用 `(pe_series < current_pe).sum() / n` 计算,未对负 PE(亏损公司)过滤,仅 dropna;负 PE 混入会扭曲分位与 min_pe(算法层风险,非 API 不一致)。

4. **kb_search**:一处会导致检索结果排序完全反转的 correctness bug(load-bearing)。位置 `backend/app/services/kb_search_service.py:121` `similarity = max(0.0, 1.0 - distance)`。索引在 `milvus_client.py:99` 建为 `metric_type="COSINE"`。据 Milvus 官方文档,COSINE 度量下 search 返回的 `distance` 字段**就是余弦相似度本身**([-1,1],越大越相似),而非 L2 那种距离值。因此 `1.0 - distance` 把语义彻底搞反:完全相同向量(cosine=1.0)→ similarity=0.0(被当成最差);正交向量(cosine=0.0)→ similarity=1.0(被当成最好)。下游 `results.sort(key=lambda h: h.similarity, reverse=True)[:top_k]` 因此返回**最不相关**的 chunk,`threshold` 过滤方向也同步反掉;`max(0.0, ...)` 还把 [-1,1] 负相关区裁成 0 丢信息。建议修复:`similarity = distance`(若需归一化到 [0,1] 可用 `(distance + 1) / 2`,纯排序场景直接用 distance 并去掉 `max(0.0, ...)`)。其余 pymilvus search 参数名/返回结构解包/HNSW 建索引用法均与官方一致。

## 各工具详情

## get_stock_quote

**用途**:返回单只 A 股最近一个交易日的日线行情快照(收盘价、涨跌幅、成交量)。内部取最近 5 天日线窗口,按 trade_date 降序取最新一行,映射为精简 quote dict。

**入参**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | A 股代码,如 `600519.SH` |

**返回字段**

| 字段 | 类型 | 来源(Tushare daily 列) | 说明 |
|------|------|------|------|
| ts_code | str | ts_code | 股票代码 |
| price | float | close | 收盘价 |
| change_pct | float | pct_chg | 涨跌幅(百分比数值,如 1.5 = +1.5%) |
| volume | float | vol | 成交量(单位:手) |

异常:tushare 未配置 → ToolError;get_daily 失败 → ToolError;窗口内无数据(df.empty)→ ToolError。

**上游 API**

Tushare Pro HTTP API,`api_name="daily"`(A 股日线行情)。调用链:`StockQuoteTool.run` → `TushareService.get_daily(ts_code, start, end)` → `_call_cached("daily", {ts_code, start_date, end_date})` → `TushareClient.call` POST `http://api.tushare.pro`,请求体 `{api_name, token, params}`,从响应 `data.fields`/`data.items` 构造 DataFrame。
官方文档:https://tushare.pro/document/2?doc_id=27

daily 接口要点:盘后(交易日 15:00–16:00 入库)、不复权、不提供停牌期数据;基础积分单次最多返回 6000 行(约单票 23 年),频率上限随积分等级(基础 500 次/分)。

**调用示例**

```python
tool = StockQuoteTool(tushare=tushare_service)
result = await tool.run(StockQuoteArgs(ts_code="600519.SH"))
# {"ts_code": "600519.SH", "price": 1689.0, "change_pct": 1.23, "volume": 31200.0}
```

底层等价的上游请求体:

```json
{
  "api_name": "daily",
  "token": "<TUSHARE_TOKEN>",
  "params": {"ts_code": "600519.SH", "start_date": "20260527", "end_date": "20260601"}
}
```

**已知问题 / 风险**

- 参数名/字段名与官方文档完全一致,无运行时 KeyError 风险(且 `row.get(..., default)` 已兜底)。
- `volume` 单位为"手"(非"股"),`change_pct` 已是百分比数值(未 ×100/÷100),下游需按此口径解读。
- 字段缺失时兜底为 `0.0`,极端情况(如停牌)可能把"无数据"表示成 `price=0.0`;不过 `df.empty` 先行抛错已覆盖大部分场景。
- 未传 `trade_date` 精确日期,而用 5 天滑动窗口取最新行,跨长假可能仍命中较旧交易日(逻辑正确,只是"最新"语义随节假日浮动)。

---

## get_financials

### 用途
返回给定 A 股(ts_code)的关键财务指标:营业总收入(revenue)、归母净利润(net_profit)、净资产收益率(roe)。PE 始终返回 0.0,需另行通过 `get_daily_basic` 获取。数据源为 Tushare Pro 利润表(income)+ 财务指标(fina_indicator)两接口。

### 入参

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| ts_code | str | 是 | — | A 股代码,如 `600519.SH` |
| period | "latest" \| "quarterly" \| "annual" | 否 | "latest" | 工具层语义档位;当前实现不透传上游,三值在 mock 层等价 |

### 返回字段

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| ts_code | str | 入参回显 | 股票代码 |
| period | str | 入参回显 | 请求档位 |
| revenue | float | income.`total_revenue` | 营业总收入,取 end_date 最新一行 |
| net_profit | float | income.`n_income_attr_p` | 归母净利润(不含少数股东损益) |
| roe | float | fina_indicator.`roe` | 净资产收益率 |
| pe | float | 恒为 0.0 | fina_indicator 不含 PE,需用 get_daily_basic |

### 上游 API
- **Tushare Pro `income`(利润表)** — 文档 https://www.tushare.pro/document/2?doc_id=33。必填 `ts_code`;读取输出字段 `end_date` / `total_revenue` / `n_income_attr_p`(官方均存在,拼写一致)。
- **Tushare Pro `fina_indicator`(财务指标数据)** — 文档 https://tushare.pro/document/2?doc_id=79。必填 `ts_code`;读取 `end_date` / `roe`。官方输出**不含** PE/PE_TTM,故 pe 硬编 0.0。
- 调用链:`GetFinancialsTool.run` → `TushareService.get_income/get_fina_indicator`(仅传 `{"ts_code": ...}`)→ `_call_cached` → `TushareClient.call`,返回 pandas DataFrame,工具按 `end_date` 降序取首行。

### 调用示例
```python
tool = GetFinancialsTool(tushare=tushare_service)
result = await tool.run(FinancialsArgs(ts_code="600519.SH", period="latest"))
# => {"ts_code": "600519.SH", "period": "latest",
#     "revenue": 1.5e11, "net_profit": 6.2e10, "roe": 31.5, "pe": 0.0}
```

### 已知问题 / 风险
- **pe 恒为 0.0**:这是有意设计(fina_indicator 无 PE 字段),非 bug;但调用方若直接用此 pe 做估值会得到 0,必须改用 `get_daily_basic`。description 已显式提示。
- **period 不透传上游**:三档当前等价,真实路径不区分季报/年报。后续若需区分,应把 period 映射为官方 `period`(YYYYMMDD)或按 `report_type` 过滤。
- 字段读取均有 `.empty` 与 `.get(col, 0.0) or 0.0` 兜底,空数据不崩溃;无解包数目偏差。与官方文档核对后**用法正确**。

---

## get_balance_sheet

### 用途
拉取 A 股上市公司资产负债表关键科目,并在 Python 侧派生两项偿债能力指标供 LLM 消费:
- `asset_liability_ratio` = total_liab / max(total_assets, 1.0)(资产负债率)
- `current_ratio` = total_cur_assets / max(total_cur_liab, 1.0)(流动比率)

多行时按 `end_date` 降序取最新一期;空数据返回 `{"ts_code": ..., "error": "no data"}`。

### 入参(BalanceSheetArgs)
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | 股票代码,如 `600000.SH` |
| end_date | str \| None | 否 | 传给上游 `balancesheet` 的 end_date 参数(注意:官方语义是「公告日期范围止」,非报告期) |

### 返回字段
```json
{
  "ts_code": "600000.SH",
  "end_date": "20231231",
  "total_assets": 1.0e12,
  "total_liab": 8.0e11,
  "total_cur_assets": 5.0e11,
  "total_cur_liab": 4.0e11,
  "asset_liability_ratio": 0.80,
  "current_ratio": 1.25
}
```
其中 `total_assets / total_liab / total_cur_assets / total_cur_liab / end_date` 直接取自上游同名列,两个 ratio 为本地派生。

### 上游 API
Tushare Pro `balancesheet`(资产负债表),官方文档:https://tushare.pro/document/2?doc_id=36
- 调用链:`GetBalanceSheetTool.run` → `TushareService.get_balance_sheet(ts_code, end_date)` → `_call_cached("balancesheet", params)` → `TushareClient.call` POST `http://api.tushare.pro`。
- 工具仅传 `ts_code`(+ 可选 `end_date`),不指定 `fields`,依赖上游默认字段集返回上述列。
- 官方输出字段拼写经核对与工具读取的 5 列完全一致。

### 调用示例
```python
tool = GetBalanceSheetTool(tushare=service)
result = await tool.run(BalanceSheetArgs(ts_code="600000.SH", end_date="20231231"))
# result["asset_liability_ratio"] -> 0.80
```

### 已知问题 / 风险
1. **end_date 语义易混(非崩溃)**:Tushare 官方 `end_date` 入参过滤的是「公告日期」范围,真正按报告期筛选应使用 `period`(季末日,如 `20231231`)。工具把 end_date 当报告期选择器用——当用户恰好传季末日时多数能命中,但传公告日时结果会与预期错位。建议改用 `period` 或在描述中标注 end_date 实为公告日过滤。
2. **未显式传 fields**:依赖上游默认字段集包含这 5 列(当前成立);若 Tushare 调整默认字段集,`float(row["total_assets"])` 会 KeyError。可考虑显式传 `fields` 锁定列集。
3. 上游需 2000 积分权限;`balancesheet_vip` 才能批量取全市场单季度数据(本工具未用)。

---

## get_cashflow

### 用途
拉取单只 A 股的现金流量表关键科目(经营/投资/筹资三类现金流净额),并在 Python 侧派生一个结构化布尔信号 `positive_ocf`(经营活动现金流是否为正),供 LLM/Analyst 消费。设计上刻意保持"单 API、确定性"(LLM_MODE=none 下可复现):不在本 tool 内做真实 OCF/净利润比率(那需跨 income/财务接口),只给粗粒度信号,完整比率由 Analyst 跨 `get_financials` 计算。

### 入参
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | 股票代码,如 `600000.SH` |
| end_date | str | 否 | 报告期期末日期(YYYYMMDD);不传则取该股全部历史,工具取最新一期 |

(底层 Tushare `cashflow` 还支持 ann_date / f_ann_date / start_date / period / report_type / comp_type / is_calc,本工具未透传。)

### 返回字段
工具返回 dict:
- `ts_code` — 回显股票代码
- `end_date` — 最新报告期(取 DataFrame 按 end_date 降序后的首行)
- `n_cashflow_act` — 经营活动产生的现金流量净额(OCF)
- `n_cashflow_inv_act` — 投资活动产生的现金流量净额
- `n_cash_flows_fnc_act` — 筹资活动产生的现金流量净额
- `positive_ocf` — bool,`n_cashflow_act > 0`

无数据时返回 `{"ts_code": ..., "error": "no data"}`。

### 上游 API
- 接口: Tushare Pro `cashflow`(现金流量表)
- 调用: HTTP POST `http://api.tushare.pro`,body `{"api_name":"cashflow","token":...,"params":{"ts_code":...,"end_date":...}}`;未传 `fields`,返回全部默认字段。响应取 `data.fields`(列)+ `data.items`(行)组 DataFrame。
- 文档: https://tushare.pro/document/2?doc_id=44
- 权限: 需 ≥2000 积分(单季全市场用 cashflow_vip,需 5000 积分)。

### 调用示例
```python
tool = GetCashflowTool(tushare)
result = await tool.run(CashflowArgs(ts_code="600000.SH", end_date="20231231"))
# -> {
#   "ts_code": "600000.SH", "end_date": "20231231",
#   "n_cashflow_act": ..., "n_cashflow_inv_act": ...,
#   "n_cash_flows_fnc_act": ..., "positive_ocf": True/False
# }
```

### 已知问题 / 风险
- 字段映射正确: 三个现金流字段名与官方逐字一致,尤其易拼错的 `n_cash_flows_fnc_act`(fnc + 复数 cash_flows)无误。
- report_type 未过滤: 工具仅按 end_date 降序取首行,未指定/过滤 report_type。同一报告期若存在合并/母公司/调整等多条记录,取到的口径取决于上游返回顺序,可能非预期的合并年报口径。需严格口径时应透传 report_type 或在取行前过滤。
- 缺省回落 0.0: 字段缺失时 `row.get(..., 0.0) or 0.0` 把"缺数据"与"真值 0"混淆(不报错,但语义模糊),会影响 positive_ocf 判定。
- 积分门槛: token 积分不足时上游返回 code≠0,client 抛 TushareError——属配置问题而非代码缺陷。

---

## get_daily_basic

**用途**:返回某只 A 股的最新估值快照 —— 市盈率(pe)、市净率(pb)、市销率(ps)、股息率(dv_ratio)、总市值(total_mv)、流通市值(circ_mv)、换手率(turnover_rate)。无派生字段,直透 Tushare raw 值;PE 历史分位等派生信号由 `PeHistoryTool` 另算。

### 入参(DailyBasicArgs)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | 股票代码,如 `600519.SH` |
| trade_date | str \| None | 否 | 交易日期 YYYYMMDD;缺省取今天 |

### 返回字段(dict)

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| trade_date | str | 交易日期 |
| pe | float | 市盈率(总市值/净利润;亏损为空,工具回落 0.0) |
| pb | float | 市净率(总市值/净资产) |
| ps | float | 市销率 |
| dv_ratio | float | 股息率(%) |
| total_mv | float | 总市值(万元) |
| circ_mv | float | 流通市值(万元) |
| turnover_rate | float | 换手率(%) |

空数据时返回 `{"ts_code": ..., "error": "no data"}`;多行时按 trade_date 降序取最新一行。

### 上游 API

Tushare Pro `daily_basic`(每日指标 / Daily Basic)。
doc_url: https://tushare.pro/document/2?doc_id=32
- 入参:ts_code / trade_date 二选一(本工具总是同时传 ts_code + trade_date),另支持 start_date / end_date。
- 数据更新:交易日每日 15:00～17:00;单次最多 6000 条;需 ≥2000 积分调用。
- 调用链:`GetDailyBasicTool.run` → `TushareService.get_daily_basic` → `_call_cached("daily_basic", {ts_code, trade_date})` → `TushareClient.call`,等价官方 `pro.daily_basic(ts_code='600519.SH', trade_date='20260601')`。

### 调用示例

```python
tool = GetDailyBasicTool()
result = await tool.run(DailyBasicArgs(ts_code="600519.SH", trade_date="20260601"))
# {
#   "ts_code": "600519.SH", "trade_date": "20260601",
#   "pe": 28.5, "pb": 9.2, "ps": 13.1, "dv_ratio": 1.8,
#   "total_mv": 21000000.0, "circ_mv": 21000000.0, "turnover_rate": 0.45
# }
```

### 已知问题 / 风险

1. **pe 对亏损公司为空**:官方明确"亏损的 PE 为空",工具用 `float(... or 0.0)` 把 None/NaN 压成 0.0,不报错但会让亏损股显示 pe=0,下游若直接比较"低 PE = 便宜"会被误导(派生信号应走 PeHistoryTool)。
2. **单位为万**:total_mv / circ_mv 单位是"万元",total_share 等是"万股",工具直透不换算,下游需注意量纲。
3. **字段/参数全部与官方一致**,无拼写或解包数目偏差,无运行时错配风险。

---

## get_dividend_history

**用途**:返回某只 A 股近若干年的分红记录(`recent_dividends`:`{ann_date, cash_div}` 列表),并派生两个指标:`avg_dv_ratio_5y`(平均每股现金分红)与 `dividend_consistency`(0-1,有非零现金分红的年份占比,衡量是否为稳定分红公司)。

源码:`backend/app/tools/get_dividend_history.py`,经 `RealTushareService.get_dividend_history`(`backend/app/services/tushare_service.py:197`)调用上游。

### 入参(工具 args_schema)

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| ts_code | str | 是 | — | TS 股票代码,如 `600848.SH` |
| years_back | int | 否 | 5 | 回溯年数,约束 `1 ≤ n ≤ 10`(注意:见"已知问题",当前未真正生效) |

### 返回(工具输出)

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 回显股票代码 |
| recent_dividends | list[{ann_date:str, cash_div:float}] | 分红记录,按 `ann_date` 倒序(最新在前) |
| avg_dv_ratio_5y | float | 平均每股现金分红(命名为 ratio 但实为金额,见已知问题) |
| dividend_consistency | float | [0,1],非零现金分红记录占比 |
| error | str | 无数据时返回 `{"ts_code", "error":"no data"}` |

### 上游 API

- **接口**:Tushare Pro `dividend`(分红送股数据)
- **传输**:`TushareClient` POST `http://api.tushare.pro`,body `{api_name:"dividend", token, params, fields?}`,返回 `{code, msg, data:{fields, items}}`,客户端用 `fields` 作列名、`items` 作行构造 DataFrame
- **官方文档**:https://tushare.pro/document/2?doc_id=103
- **官方输入参数**(至少一个不为空):`ts_code` / `ann_date` / `record_date` / `ex_date` / `imp_ann_date`(均为单值 YYYYMMDD,**无日期区间参数**)
- **关键输出字段**:`ts_code, end_date, ann_date, div_proc, stk_div, cash_div(税后每股现金分红), cash_div_tax(税前), record_date, ex_date, pay_date, ...`
- **权限**:需账户积分 ≥ 2000

### 调用示例

```python
tool = GetDividendHistoryTool()  # 自动 build_tushare_service()
result = await tool.run(DividendHistoryArgs(ts_code="600848.SH", years_back=5))
# => {
#   "ts_code": "600848.SH",
#   "recent_dividends": [{"ann_date": "20230615", "cash_div": 0.5}, ...],
#   "avg_dv_ratio_5y": 0.42,
#   "dividend_consistency": 1.0,
# }
```

服务层实际发往 Tushare 的 body(当前实现):
```json
{"api_name": "dividend",
 "params": {"ts_code": "600848.SH", "ann_date_start": "20210601", "ann_date_end": "20260601"}}
```

### 已知问题 / 风险

1. **`years_back` 静默失效(参数名错)**:service 传 `ann_date_start` / `ann_date_end`,官方 `dividend` 接口无此参数(仅单值 `ann_date`)。Tushare 会忽略未知参数 → 服务端不按日期过滤,返回全量历史分红。`recent_dividends` / `dividend_consistency` / `avg_dv_ratio_5y` 实际基于全历史而非近 N 年,语义错误。修复:仅传 `ts_code`,在 Python 侧按 `ann_date` 截取近 N 年;或确认接口确不支持区间后改用客户端裁剪。
2. **`avg_dv_ratio_5y` 命名误导**:`cash_div` 是税后每股现金分红"金额"(元/股),不是股息率/分红率;且因 #1 也不保证是 5y。真正股息率需结合股价计算。
3. **税前/税后**:用了 `cash_div`(税后)。若下游期望税前需改用 `cash_div_tax`。
4. **顺序兜底正确**:已用 `sort_values("ann_date", ascending=False)` 处理 Tushare 顺序不保证的问题。
5. **字段读取正确**:`ann_date`、`cash_div` 拼写与官方一致,DataFrame 解包结构与 Tushare 返回一致,无运行时解包错误。

---

## get_forecast

**用途**:拉取某只 A 股的最新一期业绩预告,并派生一个情绪信号(positive/neutral/negative),供 agent 在持仓监控 / 研究场景下快速判断预告方向。

**入参**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | 股票代码,如 `000001.SZ` |
| period | str | 否 | 报告期(季度末 YYYYMMDD,如年报 `20171231`);省略则按 ts_code 拉全部历史 |

**返回**(工具层 dict)

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 回显股票代码 |
| period | str | 报告期(⚠ 当前实现恒为空,见已知问题) |
| type | str | 预告类型(预增/预减/扭亏/首亏/续亏/续盈/略增/略减) |
| p_change_min | float | 净利润变动幅度下限(%) |
| p_change_max | float | 净利润变动幅度上限(%) |
| signal | str | 派生信号:positive(预增/扭亏/略增/续盈)/ negative(预减/首亏/续亏/略减)/ neutral |

无数据时返回 `{"ts_code": ..., "error": "no data"}`。

**上游 API**:Tushare Pro `forecast`(业绩预告),官方文档 <https://tushare.pro/document/2?doc_id=45>(需 ≥2000 积分,按单只股票拉历史;全市场用 `forecast_vip`)。
- 官方输出字段:ts_code / ann_date / **end_date(报告期)** / type / p_change_min / p_change_max / net_profit_min / net_profit_max / last_parent_net / first_ann_date / summary / change_reason。

**调用示例**

```python
tool = GetForecastTool(tushare=svc)
result = await tool.run(ForecastArgs(ts_code="000001.SZ"))
# -> {"ts_code": "000001.SZ", "period": "", "type": "预增",
#     "p_change_min": 30.0, "p_change_max": 50.0, "signal": "positive"}
```

**已知问题 / 风险**

1. **字段名错配(P1,语义 bug 但不抛异常)**:`period` 是官方 `forecast` 的【入参名】,但官方【输出字段叫 `end_date`】,输出中无 `period` 列。后果:
   - `get_forecast.py:78` 返回的 `period` 恒为 `""`,下游拿不到报告期。
   - `get_forecast.py:70` 的 `if "period" in df.columns` 排序分支永不命中,退化到 `ann_date`(公告日)排序;多数情况能取到最新行,但"取最新报告期"的语义不保证(应按 end_date 排序)。
   - 修复:line 70/71/78 的 `period` 改用 `end_date`(返回 dict 的 key 可保留 `period`,取值改 `row.get("end_date","")`)。
2. type / p_change_min / p_change_max 与官方字段名一致,signal 分类关键词与官方 type 取值集吻合,无问题。
3. 积分门槛:`forecast` 需 2000 积分,低积分账号会被上游拒绝,需在 TushareClient 层处理报错。

---

## get_holder_change

**用途**:返回某 A 股近 N 年的股东户数(holder_num)快照序列,并派生一个筹码趋势信号 trend(集中 / 散户化 / 稳定),用于研判筹码集中度变化。

**入参**(工具 args_schema = HolderChangeArgs):

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| ts_code | str | 是 | — | TS 股票代码,如 `300199.SZ` |
| years_back | int | 否 | 2 | 回看年数,范围 1–5;service 层据此生成 start_date=N 年前、end_date=今天 |

**返回字段**(工具对外输出):

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| recent_holder_nums | list[{end_date, holder_num}] | 按 end_date 升序的各期股东户数([0]=最早,[-1]=最新) |
| trend | "concentration" / "dispersion" / "stable" | 最新 vs 最早户数变化:≤ -5% 集中 / ≥ +5% 散户化 / 否则稳定;数据 < 2 期时为 stable |
| error | str | 无数据时返回 `{"ts_code", "error": "no data"}` |

**上游 API**:Tushare Pro `stk_holdernumber`(股东户数),POST http://api.tushare.pro。
- 文档:https://tushare.pro/document/2?doc_id=166
- 调用路径:`tool.run` → `TushareService.get_holder_change(ts_code, years_back)` → `_call_cached("stk_holdernumber", {ts_code, start_date, end_date})` → `TushareClient.call` → `pd.DataFrame(items, columns=fields)`。
- 我们传的入参 `ts_code` / `start_date` / `end_date` 均为官方合法参数。
- 我们读取的列 `end_date`、`holder_num` 与官方输出字段名**完全一致**;client 直接用上游 `fields`/`items` 构表,不做重命名。
- 权限:该接口需 600 积分;限频随积分等级而定。

**调用示例**:

```python
tool = GetHolderChangeTool(tushare=svc)
result = await tool.run(HolderChangeArgs(ts_code="300199.SZ", years_back=2))
# {
#   "ts_code": "300199.SZ",
#   "recent_holder_nums": [
#       {"end_date": "20220930", "holder_num": 91200.0},
#       {"end_date": "20240331", "holder_num": 83000.0},
#   ],
#   "trend": "concentration",
# }
```

对应底层上游调用(等价 tushare 官方 SDK 写法):

```python
pro.stk_holdernumber(ts_code="300199.SZ", start_date="20240601", end_date="20260601")
# 返回列: ts_code, ann_date, end_date, holder_num
```

**已知问题 / 风险**:
- **无运行时错误风险**:字段名 holder_num / end_date、返回结构、解包数目均与官方文档对得上。
- **语义注意点(非 bug)**:官方把 start_date/end_date 定义为"公告开始/结束日期"(按 ann_date 过滤),工具却把这段窗口当作"持仓快照时间窗"。因 stk_holdernumber 不规则披露,实务上多数情况仍能取到窗口内披露的各期户数;但严格说"按公告日过滤" ≠ "按报告期(end_date)过滤",极端边界可能漏掉"报告期在窗内、公告日在窗外"的记录。若需严格按报告期取数,可改用官方 `enddate` 入参。
- trend 阈值为闭区间(-5% / +5% 临界值分别归 concentration / dispersion),与 docstring 表述一致。
- 日期用 UTC `datetime.now(UTC)` 生成,跨年漂移已用 relativedelta 规避。

---

## get_pe_history

### 用途
返回某只 A 股当前 PE 相对过去 N 年历史分布的分位(historical_percentile),并派生 min/max/median PE 及估值带 `valuation_band`(低估/合理/高估)。用于估值高低的快速判断。

### 入参
| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| ts_code | str | 是 | — | 股票代码,如 `600519.SH` |
| years_back | int (1-10) | 否 | 5 | 历史回溯年数 |

### 返回字段
| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| current_pe | float | 当前 PE(取最新交易日 daily_basic.pe) |
| historical_percentile | float | 0-1,当前 PE 在历史分布中的分位 |
| min_pe / max_pe / median_pe | float | 历史 PE 的最小/最大/中位 |
| valuation_band | str | 派生:<0.3 低估 / 0.3-0.7 合理 / ≥0.7 高估 |
| error | str | 无数据时返回 `{"ts_code":..,"error":"no data"}` |

注:最新 PE 取不到(空或 NaN)时 service 层显式 `raise ValueError`,**不**静默回退 0.0(避免伪造"史上最便宜"买入信号)。

### 上游 API
- **Tushare Pro `daily_basic`(每日指标)**,HTTP POST `http://api.tushare.pro`
- 文档:https://tushare.pro/document/2?doc_id=32 ;HTTP 调用规范:https://tushare.pro/document/1?doc_id=130
- 入参 `ts_code` / `trade_date` / `start_date` / `end_date`(YYYYMMDD);输出含 `pe`、`pe_ttm` 等。需 ≥2000 积分。
- 两次调用:① 历史序列 `start_date+end_date`;② 最新值 `trade_date=今天`。

### 调用示例
```python
tool = GetPeHistoryTool(tushare=svc)
result = await tool.run(PeHistoryArgs(ts_code="600519.SH", years_back=5))
# -> {"ts_code":"600519.SH","current_pe":28.4,"historical_percentile":0.62,
#     "min_pe":15.1,"max_pe":58.7,"median_pe":31.2,"valuation_band":"合理"}
```

### 已知问题 / 风险
1. **`fields` 参数位置错误(确认偏差)**:`tushare_service.get_pe_history` 把 `"fields":"pe"` 放进了 `params` 字典,而官方规范要求 `fields` 为请求 body 的**顶层字段**;`TushareClient.call` 的 `fields=` 形参也从未被传入。结果是字段投影失效、上游返回全字段(pe 仍在内,故不报错),属隐性误用/浪费带宽,并污染按 params 哈希的缓存 key。修复:`self._client.call("daily_basic", {ts_code,...}, fields="pe")`。
2. **负 PE 未过滤**:分位计算仅 `dropna`,亏损公司的负 PE/异常值会扭曲分位与 min_pe(算法层风险)。
3. `pe` vs `pe_ttm`:当前用静态 `pe`,若需 TTM 口径应改取 `pe_ttm`(业务口径选择,非 bug)。

---

## get_money_flow

- **用途**: 拉取某只 A 股在指定日期区间内的资金流向数据（按小单/中单/大单/特大单分桶的买入与卖出金额），并在区间内对各桶金额求和，派生出大单净流向信号 `net_lg_signal`（大单买入金额 > 大单卖出金额则 `inflow`，否则 `outflow`）。

- **入参**:

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | 股票代码，如 `002149.SZ` |
| start_date | str | 是 | 起始日期，`YYYYMMDD` |
| end_date | str | 是 | 结束日期，`YYYYMMDD` |

- **返回字段**: `ts_code` / `start_date` / `end_date`（回显）+ `buy_lg_amount` / `sell_lg_amount` / `buy_md_amount` / `sell_md_amount`（区间求和，单位万元）+ `net_lg_signal`（派生：`inflow`/`outflow`）。上游空数据时返回 `{"ts_code": ..., "error": "no data"}`。

- **上游 API**: Tushare Pro `moneyflow`（个股资金流向），https://tushare.pro/document/2?doc_id=170
  - 上游入参 `ts_code` / `trade_date` / `start_date` / `end_date`（本工具固定传 ts_code + start_date + end_date）。
  - 上游输出按交易日逐行，四档分桶 `*_sm_*`(小单<5万)/`*_md_*`(5–20万)/`*_lg_*`(20–100万)/`*_elg_*`(≥100万) 各自 buy/sell × vol/amount，外加 `net_mf_vol`/`net_mf_amount`。金额单位万元、量单位手。

- **用法示例**:
```python
tool = GetMoneyFlowTool()
result = await tool.run(MoneyFlowArgs(ts_code="002149.SZ", start_date="20190115", end_date="20190315"))
# => {"ts_code":"002149.SZ","buy_lg_amount":12345.6,"sell_lg_amount":9876.5,
#     "buy_md_amount":4321.0,"sell_md_amount":5432.1,"net_lg_signal":"inflow", ...}
```

- **已知问题/风险**: **未发现偏差**。读取的 `buy_lg_amount`/`sell_lg_amount`/`buy_md_amount`/`sell_md_amount` 列名与官方完全一致且对缺列有 `in df.columns` 保护；入参名一致；返回以 dict 显式 key 构造无解包风险。设计取舍（非缺陷）：只透出大单/中单 4 个金额桶、未透小单/特大单及 `net_mf_amount`；`net_lg_signal` 是自定义派生信号，`buy==sell` 时归 `outflow`。

## get_news

**用途**:获取最近的财经资讯(可指定个股 ts_code 或大盘)。底层不走 Tushare,而是把查询拼成中文关键词后走博查(Bocha)Web Search,返回归一化的新闻条目列表。

**入参**(`NewsArgs`):

| 参数 | 类型 | 默认 | 约束 | 说明 |
|------|------|------|------|------|
| ts_code | str \| None | None | — | 股票代码;非空时作为 query 前缀 |
| n | int | 5 | 1–20 | 返回条数,映射到上游 `count` |
| days_back | int | 7 | 1–90 | 回溯天数 — **当前实现未使用(见已知问题)** |

query 构造:`f"{ts_code} 最近新闻"`(无 ts_code 时为 `"最近新闻"`)。

**返回**:`dict`,形如:
```json
{"items": [
  {"title": "...", "url": "...", "summary": "...",
   "snippet": "...", "site_name": "...", "date": "..."}
]}
```
字段由 `BochaClient._normalize` 从上游 `data.webPages.value[]` 映射:`name→title`、`url→url`、`summary(回退 snippet)→summary`、`snippet→snippet`、`siteName→site_name`、`datePublished→date`。

**上游 API**:博查 Bocha AI Web Search,`POST https://api.bochaai.com/v1/web-search`,认证 `Authorization: Bearer <BOCHA_API_KEY>`。文档:https://open.bochaai.com/

实际请求体(BochaClient):`{"query": query, "summary": true, "count": n, "page": 1}`。上游另支持 `freshness`(oneDay/oneWeek/oneMonth/oneYear/noLimit)、`include`/`exclude`,本工具未使用。

运行模式由 `BOCHA_MODE` 决定:`mock`(默认,LLM 驱动的 MockBochaService,search_type="news")/ `real`(真 HTTP,经 ReliableBochaService 叠加限流/熔断/配额/成本预算/重试)。

**调用示例**:
```python
from app.services.bocha_factory import build_bocha_service_from_env
from app.tools.get_news import GetNewsTool, NewsArgs

tool = GetNewsTool(bocha=build_bocha_service_from_env())
result = await tool.run(NewsArgs(ts_code="600519.SH", n=5, days_back=7))
for it in result["items"]:
    print(it["title"], it["date"], it["url"])
```

**已知问题 / 风险**:
- 字段名/嵌套路径(`data.webPages.value`)/解包与官方文档**一致,无运行时错误风险**。
- **days_back 是死参数**:被 schema 校验但 `run()` 从未使用,既没拼进 query 也没映射到上游 `freshness`,因此"最近 N 天"无任何硬时间过滤,功能描述与实现不符。建议映射为 freshness 并由 BochaClient 透传。
- BochaClient payload 写死未暴露 `freshness`,新闻"新鲜度"仅靠中文关键词软约束。

---

## web_search

**用途**:调用博查(Bocha)Web Search API 搜索全网,获取最新资讯或一般性信息,供 agent 检索实时外部知识。通过环境变量 `BOCHA_MODE` 在 mock(LLM 生成,默认)与 real(真实 Bocha API)之间切换。

**入参**(`WebSearchArgs`):

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| query | str | (必填) | 搜索词 |
| search_type | `"news"` \| `"industry"` \| `"report"` | `"news"` | 仅工具层语义:`news` 给 query 追加"最近新闻",`report` 追加"研报",`industry` 原样;**不传给上游** |
| count | int (1-20) | 5 | 返回条数 |

**返回**:`{"items": [{"title", "url", "summary", "snippet", "site_name", "date"}, ...]}`。各字段由上游响应归一化而来。

**上游 API**:博查 Bocha AI Web Search,`POST https://api.bochaai.com/v1/web-search`,鉴权 `Authorization: Bearer <BOCHA_API_KEY>`。官方文档:https://open.bochaai.com/
- 实际请求体(`BochaClient`):`{"query": <拼接后 query>, "summary": true, "count": <count>, "page": 1}`
- 官方请求参数:`query`(必填)、`freshness`、`summary`、`count`(1-50, 默认 10)、`include`/`exclude`
- 响应结果列表路径 `data.webPages.value[]`,每项字段 `name` / `url` / `snippet` / `summary` / `siteName` / `datePublished`

**调用示例**:
```python
from app.services.bocha_factory import build_bocha_service_from_env
from app.tools.web_search import WebSearchTool, WebSearchArgs

tool = WebSearchTool(bocha=build_bocha_service_from_env())
result = await tool.run(WebSearchArgs(query="宁德时代", search_type="news", count=5))
# result == {"items": [{"title": ..., "url": ..., "summary": ..., "snippet": ...,
#                       "site_name": ..., "date": ...}, ...]}
```
对应底层 HTTP:
```bash
curl --location 'https://api.bochaai.com/v1/web-search' \
  --header 'Authorization: Bearer <BOCHA_API_KEY>' \
  --header 'Content-Type: application/json' \
  --data '{"query": "宁德时代 最近新闻", "summary": true, "count": 5}'
```

**已知问题 / 风险**:
- **`page` 多余参数**:`BochaClient.search()` 发送了 `"page": 1`,官方文档无该参数(此接口用 `count` 控量、无分页)。多余字段一般被忽略,不报错,但建议删除以贴合官方契约。
- **未用 `freshness`**:`search_type=news/report` 用拼接 query 文本模拟时效,而非官方 `freshness=oneWeek`/`oneDay`,时效过滤不如原生精确(功能未充分利用,非 bug)。
- **`count` 上限 20**:工具锁 1-20,官方支持到 50;保守取值,不影响正确性。
- 字段映射与官方完全一致(`name→title`、`siteName→site_name`、`datePublished→date` 等),**无字段名拼写错误、无解包数目偏差,无运行时错误风险**。

---

## kb_search

### 用途
搜索内部知识库(研报 `kb_research` / 财报 `kb_financial` / 政策 `kb_policy` 三类 corpus)。把 `query` 经 EmbeddingService 编码成 1024d 向量,在指定(或全部)collection 上并发做 Milvus 向量检索,合并后按相似度降序、threshold 过滤、top_k 截断返回。`KB_MODE=mock` 走固定 stub,`KB_MODE=real` 走 Milvus。

### 入参(`KbSearchArgs`)
| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `query` | str | 是 | — | 检索文本 |
| `top_k` | int | 否 | 5 | 范围 1–20,合并后截断 |
| `collections` | list[str] \| None | 否 | None | None=查全部 3 个;非法名抛 ValueError |
| `threshold` | float \| None | 否 | None | 过滤 `similarity >= threshold` |
| `filters` | dict \| None | 否 | None | 走字段白名单,非白名单抛 ValueError |

filter 白名单:公共 `pub_date_after` / `pub_date_before` / `source_type`;research 专属 `broker`/`industry`/`rating`/`analyst`;financial 专属 `company_code`/`fiscal_year`/`fiscal_quarter`/`section`;policy 专属 `issuer`/`scope`。`pub_date_after/before` 翻译成 `pub_date >= / <= "v"` 表达式。

### 返回字段
```json
{
  "items": [
    {
      "chunk_id": "string",
      "chunk_text": "string",
      "similarity": 0.0,
      "doc_id": "...", "chunk_index": 0, "pub_date": "...",
      "source_url": "...", "source_type": "...",
      "broker": "...", "company_code": "...", "issuer": "..."
    }
  ]
}
```
`similarity` ∈ [0,1] 设计语义为越大越相关;其余 metadata 字段随 collection 而异(经 `output_fields=["*"]` 取回的全部 scalar 字段)。

### 上游 API
内部 Milvus 向量检索,无外部 HTTP API。底层调用 pymilvus `MilvusClient.search(collection_name, data=[vec], limit=top_k, filter=expr, output_fields=["*"])`,索引为 HNSW + `metric_type="COSINE"`。返回 `List[List[dict]]`,每命中含 `id` / `distance` / `entity`。
- doc_url: https://milvus.io/api-reference/pymilvus/v2.5.x/MilvusClient/Vector/search.md
- 度量语义: https://milvus.io/docs/metric.md(COSINE:`distance` 即余弦相似度,[-1,1],越大越相似)

### 调用示例
```python
tool = KbSearchTool(kb_service)
out = await tool.run(KbSearchArgs(
    query="光伏行业 2025 装机预期",
    collections=["kb_research"],
    top_k=3,
    threshold=0.3,
    filters={"industry": "光伏", "pub_date_after": "2025-01-01"},
))
for it in out["items"]:
    print(it["similarity"], it["chunk_text"][:50], it.get("broker"))
```

### 已知问题 / 风险
- **[严重] 相似度计算把 COSINE 排序方向搞反**(`kb_search_service.py:121`):索引用 COSINE,Milvus 返回的 `distance` 本身就是余弦相似度(越大越相似),但代码做 `similarity = max(0.0, 1.0 - distance)`,导致完全相同向量(cos=1)算出 similarity=0、正交向量(cos=0)算出 similarity=1。结果是 `sort(reverse=True)[:top_k]` 返回**最不相关**的 chunk,`threshold` 过滤方向也反。修复:`similarity = distance`(并去掉 `max(0.0,...)` 的裁剪)。
- `output_fields=["*"]` 会把 `vector` 字段也可能带回(pymilvus 行为视版本而定),当前下游只 pop chunk_id/chunk_text/distance,若 entity 含 `vector` 会被塞进 metadata 造成体积膨胀,建议显式列出 output_fields 而非 `["*"]`。
- 多 collection 各取 top_k 再合并截断 top_k,跨 collection 的相对相似度可比性依赖 distance 语义正确(同样被上面的 bug 影响)。