# 设计:交易日历工具 + 参考日期注入

- 日期:2026-06-15
- 分支:feat/portfolio-overview(用户确认就地建,与并发 session 同源,日期工具与刚落地的持仓/基金/板块工具同族)
- 体裁:设计(spec),落地后进 plan 拆任务

## 这是什么(一句话)

给 chatloop 补上两块"时间感知"能力:① 每轮对话告诉模型**今天几号**(参考日期注入);② 给模型一本可查的**交易日历**(trade_cal 工具),回答"哪天开市/最近交易日/区间交易日"这类只有专门日历才答得准的问题。两块共享同一个"参考日期"概念,故合成一份 spec。

## 为什么要做(背景)

金融场景的"日期"有两个日常日期没有的坑:

1. **股市不是天天开门**:只在工作日开市,且节假日休市(国庆/春节可连休一周)。所以"今天的行情"在周末/节假日是没有数据的,必须回退到**最近一个交易日**。普通日历不知道哪天休市,需要一本权威交易日历。
2. **用户说的日期是相对的**:"近一年""上个季度""最近"——要换算成具体 YYYYMMDD,前提是先知道"今天"。

而代码审计发现一个真窟窿:**当前 chatloop 没有把"今天"注入到模型可见的任何区域**。系统提示按 KV-cache 铁律刻意不含日期(`system_prompt.py`),尾部动态区(`context.py` 区四)只有步数/预算,`ContextDeps` 也没有承载日期的字段。模型只能用训练截止时的"现在"瞎猜相对日期,且静默出错。同时数据层(`TushareService`)没有交易日历方法,旧代码用 `datetime.now()-1天` 粗暴顶替"最近交易日"(遇周末即错)。

## 决策已锁(brainstorm 三问)

1. **参考日期注入只放"今天+星期"**(纯字符串,零数据依赖,热路径干净)。"最近交易日"等日历解析交给 trade_cal 工具的 `latest` 动作,不在每轮窗口组装里查日历。
2. **测试用交易日历内置真实 A 股节假日表**(不止周末规则),保证 mock/离线模式也历法准确、确定性可复现。
3. **工具 + 注入合成一份 spec**。

## 组件一:trade_cal 工具(MCP 数据工具,全动作型)

### 接口

`trade_cal(action, date?, start?, end?)`,action 六选一,按 action 校验参数(与 `get_market_indicators` 的 metric 路由同构):

| action | 必填参数 | 含义 | 返回 |
|--------|----------|------|------|
| `is_open` | date | 这天股市开门吗 | `{action, date, is_open: bool}` |
| `latest` | date | ≤date 的最近交易日(date 本身开市则=date) | `{action, query_date, result_date, is_open_on_query}` |
| `prev` | date | 严格早于 date 的上一交易日 | `{action, query_date, result_date}` |
| `next` | date | 严格晚于 date 的下一交易日 | `{action, query_date, result_date}` |
| `count` | start, end | [start,end] 内交易日数量 | `{action, start, end, count}` |
| `list` | start, end | [start,end] 内交易日列表 | `{action, start, end, count, dates:[...], truncated?}` |

- 日期格式 YYYYMMDD,与现有数据工具一致。
- `list` 沿用 `get_daily` 的 260 上限截断(超出取最近 260 个并置 `truncated=true`),防撑爆上下文。
- 分组:**deferred**(低频,与其它数据工具一致),走 `thin_required={"action":"string"}`。

### 底层数据

- 新增 `TushareService.get_trade_cal(start, end)` 到 Protocol + `RealTushareService`,包 tushare `trade_cal` API(原生每行返回 `cal_date / is_open / pretrade_date`),走既有 `_call_cached`(入参 hash→快照,天然 cassette)。
- `tushare_client.py` 里 `datetime.now()-1天` 那段"最近交易日"占位顺手作废(改走 trade_cal,或标注由本工具取代)。

### 确定性铁律(与 RL/验证集打通的关键)

- **trade_cal 绝不读 `datetime.now()`**:日期一律由参数显式传入。"今天"从注入的参考日期来,模型把具体日期当 `date` 参数传进来。工具因此是纯函数、可 cassette、可复现。
- 单日动作的 `date` 为**必填**(不设"默认今天"的内部回退,否则会引入墙上时钟)。系统提示纪律负责教模型"把尾部给的今天传进来"。

### Mock(确定性 + 真历法)

- `MockTushare` 实现 `get_trade_cal`:**工作日规则 + 内置静态 A 股节假日表**(覆盖测试/验证集关心的年份,如 2023–2026)。已知年份用真历法,超出覆盖年份回退工作日规则并 log 一行提醒。
- 显式区别于既有坑(`mock-tushare-adapter-is-llm-backed`):交易日历**绝不走 LLM**,纯查表,测试可硬断言。
- 维护边界:节假日表逐年更新;覆盖范围与回退规则写进工具/mock 的 docstring。

## 组件二:参考日期注入(动态区)

- `ContextDeps` 新增 `reference_date` 字段(类型 `date`,turn 构造时一次注入)。
- `context.py` 区四(尾部动态区)那行拼成:`(今天 2026-06-15 周日。第 N/M 步,预算剩 ¥x.xx。)`。
  - 放区四符合"动态区放会话级动态"的设计;区四本不吃 KV-cache,每轮重发零额外成本;且"今天"落在模型决策前最后一条消息(recency 有利)。
- 构造 `ContextDeps` 的地方(chat_runner / worker 组装链)用 `date.today()` 填 `reference_date`(生产);eval/RL 传**冻结的 as-of**。
- **一套机制两处用**:`reference_date` = 生产真实今天 / 验证·RL 冻结 as-of,单一注入点。配合 trade_cal 的纯函数性,相对日期的 gold 不随墙上时钟漂移——即"产品侧缺的日期注入"与"验证集侧的 as-of 锚定"同源。

## 组件三:系统提示纪律(静态,不破坏前缀稳定)

`CHAT_SYSTEM_PROMPT`(区一,稳定前缀)增一句**静态指令**(不含日期值,故不违反前缀逐字节铁律):

> 涉及相对时间(近一年/上季度/最近)时,以尾部给出的"今天"为基准换算;需要判断某天是否开市、最近交易日、区间交易日时调 trade_cal,不要自行猜测交易日。

## 接线 + 测试

- `tool_docs.py`:加 trade_cal 的 `ToolDoc`(brief + doc + group=deferred + thin_required),追加进 `DEFERRED_TOOLS`。工具计数 22→23。
- `mcp_server/server.py`:`list_tools` / `call_tool` 注册;chat registry 并入(与 get_daily 等同路径)。
- 测试按 `add-mcp-chat-tool-test-sites` 清单四处同步(#146 漏挂 CI 教训):
  1. progressive_disclosure 工具计数断言(22→23 / deferred 13→14);
  2. cassette `_FAKE_RESULTS` 占位补 trade_cal;
  3. profile 计数断言;
  4. registry/schema 形状断言。
- 新增单测:
  - trade_cal 六动作各一条(含参数校验:单日动作缺 date、区间动作缺 start/end 走指导性错误);
  - Mock 确定性 + 真节假日断言(如某已知国庆日 `is_open=false`、`latest` 回退到节前最后交易日);
  - 区四注入断言(reference_date 出现在尾部消息、格式正确);
  - 系统提示加句后前缀仍逐字节稳定(不破坏 KV-cache 不变量)。

## 不做(YAGNI 边界)

- 不做"披露日/财报期"解析(那是 `get_disclosure_date` 的活,不混进交易日历)。
- 注入不预算"最近交易日"(决策 1:交给工具)。
- 不在工具内做任何 LLM 调用或墙上时钟读取。
- 节假日表不追求历史全量,只覆盖测试/验证集关心的年份 + 工作日回退。

## 验收

- 周末/节假日问"今天行情",模型能经 trade_cal `latest` 落到正确的最近交易日再取数,不再用错日期。
- "近一年/上季度"类相对问法,模型以注入的今天为基准换算。
- mock 模式下交易日历断言全确定性通过;real 模式经 cassette 可复现。
- 四处测试点 + 新单测全绿,CI 不漏挂。
