# 设计:trade_cal 复合动作 `window`(一次解析相对区间 / 方法 B)

- 日期:2026-06-16
- 体裁:工具能力扩展设计(承 trade_cal 历法工具 + 参考日期注入)
- related: docs/superpowers/specs/2026-06-16-computation-caliber-freeze-design.md

## 为什么

pass@k 重测里观察到:agent 把"近一年"这类相对区间落成交易日窗口时,**反复调 trade_cal**——`is_open(今天)` → `latest` → 区间起点 → 区间终点,一次一问。次数**随题而异**:简单题(无相对区间)0–1 次,"近一年涨幅"实测 3–4 次,多窗口/多边界确认的 5–6 次。这不是正确性问题(答案对),是**步数虚高 + 费 token + 链路变长**(将来 RL 功劳分配更难)。

根因:trade_cal 现有 6 动作(`is_open/latest/prev/next/count/list`)**每个只回答一个小问题**;注入只给"今天",agent 只能把"一次查询"硬拆成多次往返。

## 决策:方法 B —— 把"一次拿全"的能力补到工具里

加 trade_cal 第 7 个动作 `window`:给"今天 + 一个周期码",**一次**返回解析好的交易日窗口。把"解析一个相对区间"所需的往返(随题而异,常见 1–4 次,边界确认多时更多)收成**每个窗口 1 次**。注意 `window` 自身的调用数 = 该题需要的**不同窗口数**:单窗口题 1 次,"近一年 vs 近三月"这类 2 次,无相对区间则 0 次——省的是"每个窗口的那 N 次",不是一个固定的"4→1"。

不选方法 A(并行多次调用):日期解析有先后依赖(先知道今天开不开市),A 批量不起来;且 A 只压墙上时间,不减往返次数与上下文。
不选方法 C(把窗口算进每轮注入):违背已定的"注入只给今天"决策,且每轮都要算一次窗口。
B 把先后依赖收进工具内部的普通代码,LLM 只来回 1 次、上下文只多 1 份合并结果。

附带收益:`window` 让 agent 取到的窗口**确定化**,与 computation-caliber-freeze 的 method B(oracle 读 agent 实际窗口)天然互补——窗口由确定性工具产出,oracle 复算更稳。

## 契约

**动作 `window`**

输入:
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `action` | str | 是 | 固定 `"window"` |
| `anchor` | str | 是 | YYYYMMDD,"今天"/as-of。显式传,handle 绝不读时钟(与现有动作一致) |
| `lookback` | str | 是 | 周期码(见下) |

输出(JSON):
```json
{
  "action": "window",
  "anchor": "20260616",
  "lookback": "1y",
  "start": "20250616",
  "end": "20260616",
  "trading_days": 243,
  "anchor_is_open": true
}
```

**周期码语法**(小语法,一个解析器覆盖全目录窗口):

| 码 | 含义 | start 口径 |
|---|---|---|
| `<N>y` | 近 N 年 | anchor 年份 −N、同月日(2/29 溢出夹到 2/28)后,**向后顺延到最近交易日** |
| `<N>m` | 近 N 月 | anchor 减 N 个月(日溢出夹到目标月末)后,向后顺延到最近交易日 |
| `<N>d` | 近 N 自然日 | anchor 减 N 个自然日后,向后顺延到最近交易日 |
| `<N>td` | 近 N 个交易日 | 使 [start, end] 恰好含 N 个交易日(从 end 往前数 N−1 个交易日) |
| `ytd` | 年初至今 | anchor 所在年 1 月 1 日后,向后顺延到当年首个交易日 |

`N` 为正整数;非法码(空/不匹配/N≤0)返回参数校验错误并列出合法形式。

**两端口径(精确)**

- `end` = ≤ anchor 的最近交易日(= 现有 `latest` 语义施于 anchor)。anchor 本身是交易日则 end=anchor。
- 日历型(`Ny/Nm/Nd/ytd`):算出 `raw_start`(上表),`start` = **≥ raw_start 的首个交易日**(raw_start 落在周末/节假日就顺延)。
- 计数型(`Ntd`):`start` = 从 `end` 往前数到第 N 个交易日那天([start,end] 恰含 N 个交易日)。**历史不足 N**:start=可得最早交易日,`trading_days` 返回实际数(< N),不报错。
- `trading_days` = [start, end] 闭区间内交易日数。
- `anchor_is_open` = anchor 是否为交易日(顺手给,免得 agent 再单调一次 `is_open`)。

**数据获取**:handle 仍走 `build_tushare_service().get_trade_cal(start, end)`(real 走 tushare API / mock 走确定性历法,与现有动作同源)。
- 日历型:取 `get_trade_cal(raw_start, anchor)` 的开市日,极小/极大即 start/end。
- 计数型:取 `get_trade_cal(end 往前 N×2+30 自然日, anchor)` 的开市日,end=最大开市日,窗口=≤end 的最后 N 个,start=其首个。

## 范围内 / 不做

**做**:`window` 动作 + 周期码解析 + 上述口径 + 三处接线 + 单测。

**不做(YAGNI)**:
- 不改现有 6 动作(纯新增,零回归);
- 不改注入(仍只给"今天";不走方法 C);
- 不支持"上季度/上月"等命名期(目录未用;要再加);不支持自定义起止对(那是现有 `count/list` 的活);
- 不强制 agent 必须用 `window`(能力到位即可;adoption 先靠文档 nudge,RL 再强化)。

## 接线(3 处)

1. **`backend/app/mcp_server/tools/trade_cal.py`**:
   - 新增 `_WINDOW = {"window"}`,并入 `_ACTIONS`;
   - `inputSchema.properties` 加 `anchor` / `lookback`;`TOOL_DEF.description` 补一句 window 用法;
   - handle 加 window 分支:校验 anchor/lookback → 解析周期 → 取历法 → 算 start/end/trading_days/anchor_is_open → `_ok(...)`;
   - 周期解析与月/年回退做成模块内纯函数(`_parse_lookback`、`_minus_years`、`_minus_months`),可单测。
2. **`backend/app/chatloop/tool_docs.py`** trade_cal 的 `doc`:加 `window` 动作说明 + "近一年"示例 + nudge:"算相对区间优先用 `window` 一次拿全,别 `is_open`+`latest` 拆成多次"。
3. **`backend/app/chatloop/system_prompt.py`**:把"要交易日/最近交易日调 trade_cal"那句改成"相对区间用 trade_cal 的 `window` 一次解析(给今天+周期),别自己减日期或拆多次"。

## 错误处理

- anchor 非 8 位 YYYYMMDD → `[参数校验失败] window 需要 anchor(8 位 YYYYMMDD)`;
- lookback 非法 → `[参数校验失败] lookback 形如 1y/6m/30d/20td/ytd`;
- 历法返回空(anchor 远超覆盖年份等)→ 返回 error 说明区间无交易日,不抛异常。

## 测试(确定性 mock 历法,可复现)

| 用例 | 断言 |
|---|---|
| `window(20260616, 1y)` | start=20250616 / end=20260616 / trading_days 与 `count(20250616,20260616)` 一致 / anchor_is_open=true |
| `window(20260616, ytd)` | start=20260105(2026 首个交易日;0101/0102 元旦休) / end=20260616 |
| `window(20260616, 20td)` | trading_days=20 / start 为 end 前数第 20 个交易日 |
| anchor 落周末 `window(20260620, 1y)`(6/20 周六) | anchor_is_open=false / end=≤该日最近交易日 |
| raw_start 落节假日 | start 顺延到下一交易日(非 raw_start 当天) |
| `window(20260616, "xy")` 等非法码 | 返回参数校验错误,含合法形式提示 |
| `_parse_lookback` 纯函数 | `1y/6m/30d/20td/ytd` 解析正确;`0y`/空/`abc` 报错 |

回归:现有 6 动作单测全过(纯新增不应触动)。

## 验收

- `window` 单测全过,覆盖 5 种周期码 + 周末/节假日顺延 + 非法码;
- live 重跑一道"近一年"题,trace 里该窗口的日期解析从多次 trade_cal(此前实测 3–6 次)收成 1 次 `window`(多窗口题按窗口数计;adoption 由文档 nudge 引导,允许 agent 仍偶尔多调,能力已可用);
- 现有 trade_cal 6 动作 + chat profile 计数测试零回归。

## 阶段

1. `_parse_lookback` + 月/年回退纯函数 + 单测;
2. handle 加 window 分支 + inputSchema/TOOL_DEF + window 单测;
3. tool_docs + system_prompt 接线 + 文档 nudge;
4. 回归 + live 抽测一道"近一年" → 看 trace 日期解析次数下降。
