"""工具渐进披露的内容层 — 分组/瘦 schema/完整使用文档(spec § 3.2)。

description 模板(spec § 3.1):[功能一句话]。何时用:[触发场景+金融触发词]。
何时不用:[反例→指向相邻工具]。[硬约束]
完整文档零常驻成本(经 search_tools 按需进 messages),可以写厚。

三组(会话内恒定,spec § 3.2):
- 核心组(6,完整 schema):高频数据 + 控制关键工具,description 用 brief;
- 延迟组(8,瘦条目):名字 + brief + 必填参数名/类型(剥 description/enum/示例/可选);
- search_tools(1,内置于 ToolHub):关键词检索本模块文档,top-k 文本进 messages。

实测结论(冒烟 item 8):空 properties:{} 的瘦 schema 会被模型绕开。所以瘦条目
保留必填参数名+类型(可直接调用),细节走 search_docs 检索的完整文档。

注:search_tools 检索结果里出现 load_skill 等技能工具属正常 —— 技能触发主走
稳定前缀的 L1 元数据清单,本模块的文档检索是补充召回(关键词命中即返回),
不代表"应当装载技能",模型仍按 L1 清单的触发判据决策。

参数名与 backend/app/mcp_server/tools/*.py 的真实 TOOL_DEF 逐字核对;
in-process 工具(memory_*/load_skill/run_skill_script/offer_deep_research/
read_cached_result)Phase 3 后续任务才注册实现,本模块只写文档与瘦 schema。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# ---------------------------------------------------------------------------
# ToolDoc
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolDoc:
    name: str
    group: Literal["core", "deferred"]
    brief: str  # 一句话触发描述(瘦条目/core description 用,≤80 字)
    doc: str  # 完整文档:何时用/何时不用/参数细节/示例/硬约束
    thin_required: dict[str, str] | None = None
    # 瘦 schema 保留的必填参数 {名: JSON type};None = core 组不需要;
    # {} = deferred 组但无必填(如 get_news)。


# ---------------------------------------------------------------------------
# 15 个工具文档(8 金融 + 2 记忆 + 2 技能 + 升级 + 取回 + 代码解释器)
# ---------------------------------------------------------------------------

TOOL_DOCS: dict[str, ToolDoc] = {
    # ===== 核心组 =====
    "lookup_ts_code": ToolDoc(
        name="lookup_ts_code",
        group="core",
        brief="股票简称→ts_code(如'神州泰岳'→'300002.SZ')。任何按公司名问数据/财报/估值前,先用它拿准代码,别凭记忆猜。",
        doc=(
            "把 A 股公司简称解析成 ts_code(如 '贵州茅台' → '600519.SH')。\n"
            "何时用:**只要题面给的是公司名(不是六位代码),取任何数据/财报/估值/行情前的第一步**。\n"
            "为什么必须先查:数据类工具都按 ts_code 取数,代码错一位就取到别的公司 → 答案必错。"
            "不要凭记忆背代码(尤其非头部股),一律先 lookup。\n"
            "参数:name(str,必填)—— 股票简称,如 '神州泰岳'。\n"
            "示例:lookup_ts_code(name='东方电气') → {'ts_code': '600875.SH'}。"
        ),
    ),
    # ===== 核心组(6) =====
    "get_stock_quote": ToolDoc(
        name="get_stock_quote",
        group="core",
        brief="查单只 A 股最新日线行情(现价/涨跌)。问某只股票'现在多少钱/今天涨跌'时用。",
        doc=(
            "查单只 A 股最新日线行情(收盘价/涨跌幅/成交)。\n"
            "何时用:用户问某只股票的当前价格、今日涨跌、最新成交等实时市价类问题;"
            "持仓监控里需要现价算市值时;触发词:现价、多少钱、涨了/跌了、今天表现。\n"
            "何时不用:要对比多只股票 → compare_stocks;要 PE/PB/市值/换手等估值面 → "
            "get_market_indicators;要营收/利润/ROE 等财务三表 → get_financial_statements。\n"
            "参数:ts_code(str,必填)—— A 股代码,格式 '600519.SH' / '000001.SZ'"
            "(六位数字 + 交易所后缀,沪 .SH / 深 .SZ)。\n"
            "示例:get_stock_quote(ts_code='600519.SH')。\n"
            "硬约束:ts_code 必须带交易所后缀,裸 '600519' 会校验失败。"
        ),
    ),
    "get_financial_statements": ToolDoc(
        name="get_financial_statements",
        group="core",
        brief="查 A 股财务三表(资产负债/现金流/利润)。问营收利润/偿债/现金流时用。",
        doc=(
            "查单只 A 股最新财务报表数据(三表合并,按 statement 路由)。\n"
            "何时用:用户问营收、净利润、ROE、当期市盈率快照、资产负债、现金流、偿债能力等"
            "基本面/财务数据时;触发词:营收、利润、ROE、负债、现金流、毛利、业绩。\n"
            "何时不用:要实时股价 → get_stock_quote;要 PE 历史分位/贵不贵/资金流 → "
            "get_market_indicators(估值高低判断走它,本工具只给当期 PE 数值快照);"
            "要业绩'预告'(未出报表)→ get_corporate_actions"
            "(action='forecast')。\n"
            "参数:\n"
            "  ts_code(str,必填)—— A 股代码,如 '600519.SH'。\n"
            "  statement(str,必填,枚举)—— 'balance'(资产负债表 + 偿债比率)/"
            "'cashflow'(经营/投资/筹资现金流 + positive_ocf 信号)/"
            "'income'(营收/净利/ROE/市盈率)。\n"
            "  end_date(str,可选,YYYYMMDD)—— 报告期末日。\n"
            "  period(str,可选,枚举 latest|quarterly|annual,默认 latest)—— 仅 "
            "statement='income' 生效。\n"
            "示例:get_financial_statements(ts_code='600519.SH', statement='income')。\n"
            "硬约束:statement 必传且只能是 balance/cashflow/income 三者之一。"
        ),
    ),
    "kb_search": ToolDoc(
        name="kb_search",
        group="core",
        brief="检索内部知识库(研报/财报/政策文档)的公开市场信息。问行业观点/政策时用。",
        doc=(
            "语义检索内部知识库(研报 / 财报 / 政策文档)。\n"
            "何时用:用户问公开市场信息——行业趋势、政策解读、研报观点、宏观判断等"
            "已沉淀进知识库的内容时;触发词:政策、研报、行业、趋势、怎么看待、解读。\n"
            "何时不用:要查'用户个人'的持仓/偏好/历史说过的话 → memory_search"
            "(kb 是公开市场信息,memory 是用户私有上下文,这是这对工具的互斥分界);"
            "要实时新闻 → get_news;知识库没有的最新外部信息 → web_search。\n"
            "参数:\n"
            "  query(str,必填)—— 语义检索查询串。\n"
            "  top_k(int,可选,默认 5,范围 1-20)—— 返回结果数上限。\n"
            "示例:kb_search(query='新能源车下乡政策对销量影响', top_k=5)。\n"
            "硬约束:query 非空。"
        ),
    ),
    "memory_search": ToolDoc(
        name="memory_search",
        group="core",
        brief="检索用户个人记忆(持仓/偏好/历史观点)。涉及'用户自己'的上下文时先查。",
        doc=(
            "检索用户个人的长期记忆 —— 持仓、偏好、风险画像、历史说过的话/观点。\n"
            "何时用:问题涉及'这个用户自己'的上下文——他的持仓、他的偏好、他过去"
            "提到/确认过的事实、他的风险承受度时;纪律:涉及持仓/偏好/历史观点先查记忆。\n"
            "何时不用:要查公开市场信息(研报/政策/行业)→ kb_search"
            "(memory 是用户私有,kb 是公开市场信息,互斥分界);写入记忆 → memory_write。\n"
            "参数:\n"
            "  query(str,必填)—— 检索查询串。\n"
            "  scope(str,可选,枚举 archival|recall|graph,默认 archival)—— "
            "archival 长期事实库 / recall 近期对话回忆 / graph 关系图谱。\n"
            "  k(int,可选,默认 5)—— 返回条数;scope=graph 时 k 无效,"
            "遍历深度由系统控制(默认 2-hop)。\n"
            "示例:memory_search(query='用户持仓与风险偏好', scope='archival', k=5)。\n"
            "硬约束:query 非空。"
        ),
    ),
    "load_skill": ToolDoc(
        name="load_skill",
        group="core",
        brief="装载技能方法论全文(SKILL.md + 资源清单)。识别到匹配技能触发场景时用。",
        doc=(
            "按需装载某个技能的方法论全文(SKILL.md)+ 附属资源清单。\n"
            "何时用:稳定前缀里的技能元数据清单提示某技能匹配当前任务时(如用户问"
            "持仓风险/集中度/回撤/敞口 → 装载对应分析技能);需要技能的分步方法论指导时。\n"
            "何时不用:执行技能附带的脚本 → run_skill_script(装载是读方法论,执行是跑脚本,"
            "语义不同);只是查数据不需要方法论 → 直接调对应数据工具。\n"
            "参数:\n"
            "  name(str,必填)—— 技能名(来自稳定前缀的技能元数据清单)。\n"
            "  resource(str,可选,默认 None)—— 装载该技能的某个附属资源"
            "(资源引用强约束一级深,从 SKILL.md 的资源清单里取名)。\n"
            "示例:load_skill(name='portfolio_risk') / "
            "load_skill(name='portfolio_risk', resource='concentration_rubric')。\n"
            "硬约束:活跃技能方法论常驻不降级;切换技能前不要重复装载已活跃的技能。"
        ),
    ),
    "offer_deep_research": ToolDoc(
        name="offer_deep_research",
        group="core",
        brief="向用户提议升级到深度研究子流程(信号工具)。问题超出快问快答需系统调研时用。",
        doc=(
            "提议把当前问题升级到'深度研究'子流程(一个信号工具,不直接产出答案)。\n"
            "何时用:用户的问题明显超出快问快答的范畴、需要多源系统性调研+成稿"
            "(如'帮我做一份某公司的深度尽调')时;判断当前对话工具链不足以充分回答时。\n"
            "何时不用:普通数据查询/对比/解读这些当前工具能直接回答的 → 别提议升级,"
            "直接用数据工具作答。\n"
            "参数:reason(str,必填)—— 为什么建议升级的一句话理由(给用户看)。\n"
            "示例:offer_deep_research(reason='该问题需跨多份研报与财报系统比对,建议深度研究')。\n"
            "硬约束:同一 turn 内幂等——第二次调用会被拒;调用后本轮工具通道关闭,"
            "下一圈只能基于已有信息简要收尾(熔断由循环代码强制,非文案自律)。"
        ),
    ),
    # ===== 延迟组(8,瘦条目)=====
    "get_market_indicators": ToolDoc(
        name="get_market_indicators",
        group="deferred",
        brief="查 A 股估值/资金面指标(PE/PB/市值/换手 · PE 分位 · 资金流)。问估值贵不贵时用。",
        doc=(
            "查单只 A 股的市场估值 / 资金面指标(按 metric 路由)。\n"
            "何时用:用户问估值贵不贵、PE/PB/市盈率分位、市值、换手率、股息率、"
            "主力资金流向时;触发词:估值、市盈率、PE、市值、换手、资金流、贵不贵。\n"
            "何时不用:要营收/利润/ROE 等财务三表 → get_financial_statements;"
            "要实时股价 → get_stock_quote;要分红记录 → get_corporate_actions"
            "(action='dividend')。\n"
            "参数:\n"
            "  ts_code(str,必填)—— A 股代码,如 '600519.SH'。\n"
            "  metric(str,必填,枚举)—— 'daily_basic'(PE/PB/PS/股息率/市值/换手率快照)/"
            "'pe_history'(PE 历史分位 + 估值带)/'money_flow'(大中单买卖额 + net_lg_signal)。\n"
            "  trade_date(str,可选,YYYYMMDD)—— 仅 metric='daily_basic' 生效。\n"
            "  years_back(int,可选,默认 5)—— 仅 metric='pe_history' 生效(回看年数)。\n"
            "  current_pe(number,可选)—— 仅 metric='pe_history'(覆盖当前 PE)。\n"
            "  start_date / end_date(str,YYYYMMDD)—— 仅 metric='money_flow',且二者必传。\n"
            "示例:get_market_indicators(ts_code='600519.SH', metric='daily_basic')。\n"
            "硬约束:metric 必传且三选一;money_flow 必须同时给 start_date 与 end_date。"
        ),
        thin_required={"ts_code": "string", "metric": "string"},
    ),
    "get_corporate_actions": ToolDoc(
        name="get_corporate_actions",
        group="deferred",
        brief="查 A 股公司行为(业绩预告/分红记录/股东户数变化)。问预告/分红/股东时用。",
        doc=(
            "查单只 A 股的公司行为历史(按 action 路由)。\n"
            "何时用:用户问业绩预告(未出正式报表的预期)、历史分红、股东户数变化/"
            "持股集中度趋势时;触发词:预告、分红、股息、股东户数、集中度。\n"
            "何时不用:要正式财务报表数字 → get_financial_statements;"
            "要 PE/市值等估值 → get_market_indicators。\n"
            "参数:\n"
            "  ts_code(str,必填)—— A 股代码,如 '600519.SH'。\n"
            "  action(str,必填,枚举)—— 'forecast'(业绩预告 + sentiment 信号)/"
            "'dividend'(近年分红 + consistency 评分)/'holder_change'(股东户数趋势 + "
            "集中度标签)。\n"
            "  period(str,可选,YYYYMMDD)—— 仅 action='forecast' 生效。\n"
            "  years_back(int,可选)—— 回看年数;'dividend' 默认 5(1-10),"
            "'holder_change' 默认 2(1-5)。\n"
            "示例:get_corporate_actions(ts_code='600519.SH', action='dividend')。\n"
            "硬约束:action 必传且三选一。"
        ),
        thin_required={"ts_code": "string", "action": "string"},
    ),
    "get_news": ToolDoc(
        name="get_news",
        group="deferred",
        brief="抓最近财经新闻(可按个股过滤)。问'最近有什么消息/新闻'时用。",
        doc=(
            "经 Bocha 搜索抓取最近的财经新闻。\n"
            "何时用:用户问某只股票或大盘'最近有什么消息/新闻/动态',需要时效性资讯时;"
            "触发词:新闻、消息、最近、动态、发生了什么。\n"
            "何时不用:要知识库里沉淀的研报/政策 → kb_search;要泛网检索非新闻类信息 → "
            "web_search;要结构化财务/估值数据 → get_financial_statements / "
            "get_market_indicators。\n"
            "参数(全部可选):\n"
            "  ts_code(str|null,默认 null)—— 个股代码过滤,null 取大盘新闻。\n"
            "  n(int,默认 5,范围 1-20)—— 返回新闻条数。\n"
            "  days_back(int,默认 7,范围 1-90)—— 回看天数。\n"
            "示例:get_news(ts_code='600519.SH', n=5, days_back=7) / get_news()。\n"
            "硬约束:无必填参数;ts_code 给值时须带交易所后缀。"
        ),
        thin_required={},
    ),
    "web_search": ToolDoc(
        name="web_search",
        group="deferred",
        brief="泛网检索最新外部信息(新闻/行业/研报)。知识库与新闻都不够时用。",
        doc=(
            "经 Bocha API 做泛网检索最新外部信息。\n"
            "何时用:内部知识库与财经新闻都覆盖不到的最新外部信息;需要验证某个代码/"
            "名称/事件的事实时;触发词:搜一下、查查、最新、外部。\n"
            "何时不用:已沉淀进知识库的研报/政策 → kb_search;结构化财经新闻 → get_news;"
            "用户个人上下文 → memory_search。\n"
            "参数:\n"
            "  query(str,必填)—— 检索查询串。\n"
            "  search_type(str,可选,枚举 news|industry|report,默认 news)—— 检索类型。\n"
            "  count(int,可选,默认 5,范围 1-20)—— 返回结果数。\n"
            "示例:web_search(query='某公司 借壳上市 进展', search_type='news')。\n"
            "硬约束:query 非空。"
        ),
        thin_required={"query": "string"},
    ),
    "compare_stocks": ToolDoc(
        name="compare_stocks",
        group="deferred",
        brief="并排对比 2-5 只 A 股(行情 + 财务)。问'A 和 B 哪个好/对比'时用。",
        doc=(
            "并排对比 2-5 只 A 股:并行抓各自最新行情 + 财务,返回统一对比列表。\n"
            "何时用:用户要把多只股票放一起比较(谁更便宜、谁基本面更好、横向选股)时;"
            "触发词:对比、比较、哪个好、哪个更、横向。\n"
            "何时不用:只看单只 → get_stock_quote / get_financial_statements;"
            "对比超过 5 只 → 分批调或改用单工具逐个查。\n"
            "参数:ts_codes(array[str],必填,2-5 个元素)—— A 股代码列表。\n"
            "示例:compare_stocks(ts_codes=['600519.SH','000858.SZ'])。\n"
            "硬约束:ts_codes 元素数必须在 2-5 之间;每个代码带交易所后缀。"
        ),
        thin_required={"ts_codes": "array"},
    ),
    "memory_write": ToolDoc(
        name="memory_write",
        group="deferred",
        brief="写入/更新用户记忆(核心块追加/替换 · 长期库插入)。用户明确表达需记住的事实时用。",
        doc=(
            "写入或更新用户的长期记忆(模型主动写的唯一入口,经注入分类器收口)。\n"
            "何时用:用户明确表达了应被长期记住的事实——新的持仓、稳定偏好、风险底线、"
            "纠正了之前的某个事实时。\n"
            "何时不用:只是读取记忆 → memory_search;一次性的临时上下文不必写入。\n"
            "参数(条件必填,dispatch 按真实 schema 校验):\n"
            "  action(str,必填,枚举)—— 'core_append'(向核心块追加)/"
            "'core_replace'(替换核心块某段)/'archival_insert'(插入长期事实库)。\n"
            "  content(str,必填)—— 要写入的内容原文。\n"
            "  block(str,条件必填,枚举 persona|scratchpad)—— action 为 "
            "core_append/core_replace 时必填,指定写入哪个核心块"
            "(persona 长期画像 / scratchpad 近期上下文)。\n"
            "  old_content(str,条件必填)—— action='core_replace' 时必填,被替换的原文"
            "(逐字匹配)。\n"
            "  evidence_quote(str,条件必填)—— 写入依据的用户原话逐字引用(系统逐字校验,"
            "防编造)。\n"
            "示例:memory_write(action='archival_insert', content='用户持有贵州茅台',"
            " evidence_quote='我买了茅台')。\n"
            "硬约束:evidence_quote 必须是用户原话的逐字片段;条件必填填错会收到指导性"
            "错误并需自纠重试。"
        ),
        thin_required={"action": "string", "content": "string"},
    ),
    "run_skill_script": ToolDoc(
        name="run_skill_script",
        group="deferred",
        brief="执行已装载技能附带的脚本(确定性计算)。方法论指明需跑脚本算结果时用。",
        doc=(
            "执行某个已装载技能附带的脚本(确定性计算,执行语义区别于读方法论的 load_skill)。\n"
            "何时用:已 load_skill 且其方法论指明需要运行附带脚本做确定性计算"
            "(如集中度/回撤的数值计算)时。\n"
            "何时不用:只需读方法论 → load_skill;查数据 → 对应数据工具。\n"
            "参数:\n"
            "  skill(str,必填)—— 技能名(须已 load_skill 装载)。\n"
            "  script(str,必填)—— 脚本名(来自该技能的资源清单)。\n"
            "  args(object,可选)—— 传给脚本的参数字典。\n"
            "示例:run_skill_script(skill='portfolio_risk', script='hhi.py',"
            " args={'weights':[0.4,0.3,0.3]})。\n"
            "硬约束:失败回喂结构化三元组(stdout/stderr/return_code)+ 错误码"
            "(超时/输出超限);大输出截断并带 stdout_truncated 标记(写缓存+取回键链路后续接入)。"
        ),
        thin_required={"skill": "string", "script": "string"},
    ),
    "read_cached_result": ToolDoc(
        name="read_cached_result",
        group="deferred",
        brief="按缓存键取回此前被降级/截断的完整工具结果(可分页)。需要老结果原文细节时用。",
        doc=(
            "按缓存键取回此前因降级/截断而压缩掉的完整工具结果(可逆,分页取回)。\n"
            "何时用:窗口里某个工具结果已被降级为 [已缓存@键]+摘要,现在需要它的完整原文"
            "细节(如某个具体数字)时;run_skill_script 大输出写了缓存键需要细看时。\n"
            "何时不用:数据还在窗口里直接读即可;要新数据 → 重新调对应数据工具。\n"
            "参数:\n"
            "  ref(str,必填)—— 缓存键(来自降级占位符或工具返回的 ref/缓存键字段)。\n"
            "  offset(int,可选,默认 0)—— 分页起始偏移。\n"
            "  limit(int,可选)—— 本次取回的长度上限。\n"
            "示例:read_cached_result(ref='cache:abc123', offset=0, limit=2000)。\n"
            "硬约束:ref 必须是系统给出的真实缓存键,不可编造。"
        ),
        thin_required={"ref": "string"},
    ),
    "dispatch_subagents": ToolDoc(
        name="dispatch_subagents",
        # core 组:dispatch 的正确调用依赖 subtasks 数组项的结构(goal/target/output_hint/
        # boundary)。该结构只能经"常驻完整 schema"传达 —— 放 deferred 组时模型只看到 thin
        # 条目(subtasks:array,无项结构),既不知怎么填、又因不显眼而默认走串行单工具
        # (实测浏览器 e2e:deferred 下模型逐只串行查、从不扇出)。故升 core,项结构随
        # 完整 schema 常驻可见(spec §14 开放问题"核心 vs 延迟"由 e2e 实测定为核心)。
        group="core",
        brief="多标的横向对比/多源广度检索/逐只持仓体检时,把这些互不依赖的只读子任务并发派给子助手分头查、收回摘要由你综合(比自己逐只串行快)。",
        doc=(
            "把一组互不依赖、各自只用查的子任务一次性并发派给若干只读子助手,"
            "收回每个子助手的结论摘要,由你综合成最终回答。\n"
            "何时用:多标的横向对比(茅台五粮液宁德比一比)、多信息源广度检索"
            "(KB+新闻+泛网)、逐只持仓体检——这类'N 个同构独立的只读小任务'。\n"
            "何时不用:① 单个事实查询(直接调对应工具即可,别扇出);"
            "② 子任务之间有先后依赖(B 要先看 A 的产出,如先估值再辩论)——"
            "那种留给主循环逐圈串行,别派;③ 要做整份尽调 → 改用 offer_deep_research。\n"
            "参数:\n"
            "  reason(str,必填)—— 为什么要扇出的一句话。\n"
            "  subtasks(array,必填)—— 子任务列表(最多 8 个),每项:\n"
            "    goal(str,必填)、target(str,可选,ts_code/源标识)、"
            "output_hint(str,可选,想要的产出形状)、boundary(str,可选,边界)。\n"
            "示例:dispatch_subagents(reason='对比三只白酒', subtasks=["
            "{'goal':'查茅台现价与营收增速','target':'600519.SH'},"
            "{'goal':'查五粮液现价与营收增速','target':'000858.SZ'}])。\n"
            "硬约束:子助手只读、看不到主对话、互不通信;超过 8 个请分批派;"
            "子助手不会再派子助手、也不会升级深度研究。"
        ),
        thin_required=None,  # core 组:常驻完整 schema,不走 thin 条目
    ),
    "run_python": ToolDoc(
        name="run_python",
        # core 组:run_python 的正确调用依赖 code 参数里的输出契约。放 deferred 组时模型
        # 只看到 thin 条目(剥了参数 description),裸调即写出不符契约的代码(实测)。故升
        # core,契约随 code 参数 description 常驻可见(verify 浏览器实测驱动)。
        group="core",
        brief="写 Python 做计算/画交互图(plotly)。需二次计算或可视化时用。",
        doc=(
            "执行 LLM 当场写的 Python 脚本:数值计算 + 用 plotly 画交互式数据分析图。\n"
            "何时用:用户要的不是单点查询,而是要对数据做二次计算(相关性/增速/加权/"
            "统计)或要一张图(趋势/对比/分布)。触发词:画图、趋势图、对比图、算一下、"
            "相关性、占比、分布。\n"
            "关键:用户常不明说'算'——只要回答需要从工具数据派生出数字(谁涨得多→区间"
            "涨幅、集中度→权重/HHI、回撤→峰谷差、相关性/波动率),就主动先取数再用本工具"
            "实算,别凭印象或心算答(心算的数视同编造)。\n"
            "何时不用:能被单个数据工具直接回答的(查现价→get_stock_quote,查财报→"
            "get_financial_statements)别绕到 run_python;跑预审技能脚本(如 DCF)→ "
            "run_skill_script。\n"
            "写法契约(执行器自动捕获,别 print):\n"
            " - 数据在变量 data(dict)里,直接用,不用读 stdin;\n"
            " - 把图赋给 fig(单张)或 figures(plotly Figure 列表),结论赋给 result;\n"
            " - 不要 print、不要返回图片链接/markdown 图 —— 执行器自动序列化并套统一 iOS 主题。\n"
            "参数:code(str,必填)= 完整脚本;data(object,可选)= 小数据 JSON 直接喂;"
            "data_refs(object,可选)= {变量名: 工具结果 ref} —— 大数据(日线序列等)按引用喂,"
            "执行器自动灌完整数据进 data[变量名],别把长数组手抄进 data。\n"
            "示例:run_python(code='import plotly.graph_objects as go; fig=go.Figure(); "
            'fig.add_bar(x=data["names"], y=data["vals"]); result="已画"\', '
            "data={'names':['股票A','股票B'],'vals':[241,197]})。\n"
            "硬约束:沙箱无网络、无文件读写(open 被禁)、无状态;可用 pandas/numpy/plotly;"
            "超时 30s;图必须用 plotly。画复杂图/要统一风格与配色 → 先 load_skill('charting')。"
        ),
        thin_required=None,  # core 组:常驻完整 schema,不走 thin 条目
    ),
    "get_daily": ToolDoc(
        name="get_daily",
        group="deferred",
        brief="查 A 股日线 K 线序列(OHLC·成交量·时间段)。要看走势/画 K 线/算相关性回撤时用。",
        doc=(
            "查单只 A 股指定日期范围的日线 K 线序列(开高低收+成交量+涨跌幅)。\n"
            "何时用:用户要看价格走势、画 K 线图、需要历史价格序列做相关性/回撤/归一化对比;"
            "触发词:K 线、走势、历史价格、日线、回撤、近一年。\n"
            "何时不用:只要最新现价 → get_stock_quote;要 PE/估值 → get_market_indicators;"
            "要财务 → get_financial_statements。\n"
            "参数:ts_code(str,必填,'600519.SH')、start(str,必填,YYYYMMDD)、"
            "end(str,必填,YYYYMMDD)。\n"
            "返回:列式数组 {ts_code, count, dates[], open[], high[], low[], close[], vol[], "
            "pct_chg[]} —— 可直接喂 run_python 的 go.Candlestick(x=dates, open=..., ...) 或折线。\n"
            "长区间(超过约一年)结果过大时改回 {ts_code, count, summary{...}, ref}:完整序列已缓存,"
            "在 run_python 里用 data_refs={变量名: ref} 一次灌进沙箱算全量(年化/波动/回撤等),"
            "不要分段多次取、不要拿 summary 估算。\n"
            "示例:get_daily(ts_code='600519.SH', start='20250101', end='20250601')。\n"
            "硬约束:ts_code 带后缀;日期 YYYYMMDD;长区间一次取全(不再只给最近一年)。\n"
            "可传 anchor+lookback(日历型,如 1y/6m/3m/ytd)让工具自己定窗口,免先调 trade_cal;"
            "过去 N 个交易日(td)仍需先 trade_cal。"
        ),
        thin_required={"ts_code": "string"},
    ),
    "get_index_daily": ToolDoc(
        name="get_index_daily",
        group="deferred",
        brief="查指数当日涨跌(沪深300等)。问大盘/指数今天多少时用。",
        doc="查指数日线与当日涨跌幅。ts_code 如 000300.SH(沪深300)。",
        thin_required={"ts_code": "string", "start_date": "string", "end_date": "string"},
    ),
    "get_fund_nav": ToolDoc(
        name="get_fund_nav",
        group="deferred",
        brief="查基金类型和净值涨跌,看不穿底层持仓。组合里基金部分的涨跌用它。",
        doc=(
            "查基金类型与每日净值涨跌(场内ETF/场外基金)。\n"
            "何时用:用户组合里有基金仓位,要看该基金今日涨跌/净值;触发词:基金、ETF、净值、基金涨跌。\n"
            "何时不用:查 A 股 → get_stock_quote;查指数 → get_index_daily。\n"
            "注意:本工具只取净值层面涨跌,不穿透基金底层持仓(底层只到季报、滞后)。\n"
            "参数:ts_code(str,必填,基金代码如 110011.OF)、start_date(YYYYMMDD)、end_date(YYYYMMDD)。\n"
            "示例:get_fund_nav(ts_code='110011.OF', start_date='20261101', end_date='20261114')。"
        ),
        thin_required={"ts_code": "string", "start_date": "string", "end_date": "string"},
    ),
    "get_sector_daily": ToolDoc(
        name="get_sector_daily",
        group="deferred",
        brief="查个股所属申万行业 + 该板块当日涨跌幅。持仓监控看板块表现时用。",
        doc=(
            "查某只个股所属申万一级行业 + 该行业指数当日涨跌幅。\n"
            "何时用:用户持仓里有某只股票,想知道它所在板块今天涨跌了多少;"
            "触发词:板块、行业、板块涨跌、行业指数、白酒板块、银行板块。\n"
            "何时不用:查指数本身 → get_index_daily;查个股涨跌 → get_stock_quote。\n"
            "参数:ts_code(str,必填,个股代码如 600519.SH)、trade_date(str,必填,YYYYMMDD)。\n"
            "返回:{industry, index_code, pct_chg};若行业未配置则 pct_chg=null + note 说明。\n"
            "示例:get_sector_daily(ts_code='600519.SH', trade_date='20261114')。\n"
            "硬约束:ts_code 带交易所后缀;trade_date 必须是真实交易日,否则返回空。"
        ),
        thin_required={"ts_code": "string", "trade_date": "string"},
    ),
    "get_portfolio_positions": ToolDoc(
        name="get_portfolio_positions",
        group="deferred",
        brief="查用户当前持仓(股数/成本/市值/浮盈)。问'我的持仓'或要画持仓占比图时用。",
        doc=(
            "返回当前用户的全部持仓:每只的数量/均价/成本/已实现损益/现价/市值/浮盈,"
            "外加 total_market_value。user_id 由系统从会话自动取,模型无需也不能传。\n"
            "何时用:用户问'我现在持有什么/持仓情况/仓位',或要画持仓行业/个股占比饼图、"
            "treemap、市值分布时(用 positions[].market_value 画)。\n"
            "何时不用:查别的股票数据 → get_stock_quote 等;不是问自己持仓的别调。\n"
            "参数:include_silenced(bool,可选,默认 false,是否含静默仓位)。\n"
            "返回:{total_count, total_market_value, positions:[{ts_code, name, quantity, "
            "avg_cost, total_cost, realized_pnl, last_quote_price, market_value, unrealized_pnl}]}。\n"
            "硬约束:只返回当前用户自己的持仓;无持仓时 positions 为空数组(别硬画空图)。"
        ),
        thin_required={},  # 无必填参数
    ),
    "trade_cal": ToolDoc(
        name="trade_cal",
        group="deferred",
        brief="查 A 股交易日历(某天开市吗/最近交易日/区间交易日)。算相对日期、定 trade_date 时用。",
        doc=(
            "查 A 股交易日历(沪深同历)。\n"
            "何时用:用户说相对时间(近一年/上季度/最近)需换算成交易日;周末/节假日要找最近一个"
            "开市日;给其它工具填 trade_date/start/end 前确认是真实交易日;算区间内有多少个交易日。\n"
            "何时不用:已知确切交易日直接用;查行情/财务走对应数据工具。\n"
            "参数:\n"
            "  action(str,必填,枚举)—— window(相对区间一次解析,**优先用**)/is_open(某天是否开市)/"
            "latest(≤该日的最近交易日)/prev(上一交易日)/next(下一交易日)/count(区间交易日数)/"
            "list(区间交易日列表)。\n"
            "  anchor + lookback(window 用)—— anchor=今天(YYYYMMDD,见尾部动态区);"
            "lookback=周期码 1y/6m/3m/1m/30d/20td/ytd。一次返回 {start,end,trading_days,anchor_is_open}。\n"
            "  date(str,条件必填)—— is_open/latest/prev/next 用,YYYYMMDD;相对查询时传'今天'。\n"
            "  start/end(str,条件必填)—— count/list 用,YYYYMMDD。\n"
            "示例:trade_cal(action='window', anchor='20260616', lookback='1y') / "
            "trade_cal(action='latest', date='20260614')。\n"
            "硬约束:date/anchor 一律显式传(工具不假设'今天');算相对区间(近一年/近N月/年初至今)"
            "**优先用 window 一次拿全,别 is_open+latest 拆成多次调**;list 最多返回最近 260 个交易日。"
        ),
        thin_required={"action": "string"},
    ),
}


# ---------------------------------------------------------------------------
# 分组清单(顺序 = schemas_for_llm 产出顺序,位置偏置:高频在前)
# ---------------------------------------------------------------------------

CORE_TOOLS: list[str] = [
    "lookup_ts_code",
    "get_stock_quote",
    "get_financial_statements",
    "kb_search",
    "memory_search",
    "load_skill",
    "offer_deep_research",
    "run_python",
    "dispatch_subagents",
]

DEFERRED_TOOLS: list[str] = [
    "get_market_indicators",
    "get_corporate_actions",
    "get_news",
    "web_search",
    "compare_stocks",
    "memory_write",
    "run_skill_script",
    "read_cached_result",
    "get_daily",
    "get_portfolio_positions",
    "get_index_daily",
    "get_fund_nav",
    "get_sector_daily",
    "trade_cal",
]


# ---------------------------------------------------------------------------
# 瘦 schema
# ---------------------------------------------------------------------------


def thin_schema(doc: ToolDoc) -> dict[str, Any]:
    """OpenAI function 格式的瘦条目:description=brief + 仅必填参数名/类型。

    剥掉 description/enum/示例/可选参数(实测 item 8:空 properties 会被绕开,
    所以保留必填参数名+类型让模型可直接尝试调用,细节走 search_tools 文档)。
    """
    required_spec = doc.thin_required or {}
    properties: dict[str, Any] = {
        name: {"type": json_type} for name, json_type in required_spec.items()
    }
    return {
        "type": "function",
        "function": {
            "name": doc.name,
            "description": doc.brief,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required_spec.keys()),
            },
        },
    }


# ---------------------------------------------------------------------------
# search_docs —— 零依赖确定性关键词检索
# ---------------------------------------------------------------------------


def _cn_bigrams(text: str) -> set[str]:
    """中文 2-gram 集合(只取连续中文字符的 bigram,确定性)。"""
    grams: set[str] = set()
    run: list[str] = []
    for ch in text:
        if "一" <= ch <= "鿿":
            run.append(ch)
        else:
            if len(run) >= 2:
                grams.update(run[i] + run[i + 1] for i in range(len(run) - 1))
            run = []
    if len(run) >= 2:
        grams.update(run[i] + run[i + 1] for i in range(len(run) - 1))
    return grams


def _ascii_tokens(text: str) -> list[str]:
    """英文/工具名 token(小写,按非字母数字下划线切)。"""
    tokens: list[str] = []
    cur: list[str] = []
    for ch in text.lower():
        if ch.isalnum() or ch == "_":
            cur.append(ch)
        else:
            if cur:
                tokens.append("".join(cur))
                cur = []
    if cur:
        tokens.append("".join(cur))
    return tokens


def _score(query: str, doc: ToolDoc) -> int:
    """query 对单个 doc 的匹配分:中文 2-gram 重叠 + 英文子串命中 + 工具名命中加权。"""
    haystack = f"{doc.name} {doc.brief} {doc.doc}"
    score = 0

    # 中文 2-gram 重叠数
    q_grams = _cn_bigrams(query)
    h_grams = _cn_bigrams(haystack)
    score += len(q_grams & h_grams)

    # 英文 token / 工具名:工具名直接命中加重权,其余子串命中 +2
    q_tokens = _ascii_tokens(query)
    name_lower = doc.name.lower()
    h_lower = haystack.lower()
    for tok in q_tokens:
        if not tok:
            continue
        if tok == name_lower:
            score += 10  # 工具名整词直查
        elif tok in name_lower:
            score += 5  # 工具名部分命中
        elif tok in h_lower:
            score += 2  # 文档正文命中

    return score


def search_docs(query: str, k: int = 3) -> list[ToolDoc]:
    """关键词评分检索:query 与每个 doc 的 name+brief+doc 做匹配打分,返回 top-k。

    评分:中文 2-gram 重叠数 + 英文/工具名子串命中加权(工具名整词命中 +10)。
    零第三方依赖,确定性(同分按 TOOL_DOCS 声明序稳定排序)。
    """
    docs = list(TOOL_DOCS.values())
    scored = [(_score(query, d), idx, d) for idx, d in enumerate(docs)]
    # 只保留有命中的;按分降序、同分按声明序(idx 升序)稳定排
    scored = [t for t in scored if t[0] > 0]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [d for _, _, d in scored[:k]]


__all__ = [
    "CORE_TOOLS",
    "DEFERRED_TOOLS",
    "TOOL_DOCS",
    "ToolDoc",
    "search_docs",
    "thin_schema",
]
