"""
Tool schemas for LLM agent prompts — 系统编排两轮架构

与金融研投助手 MCP Server 保持一致的系统编排架构：

【系统编排两轮流程】
- Round 1: skill(name) — LLM 选择合适的 Skill
  系统会自动：获取该 Skill 的工具列表并返回给 LLM

- Round 2: 直接调用具体工具 (如 market_data.get_quote) — LLM 选择合适的工具
  系统会自动：将调用转换为 execute_skill_tool 并执行

【关键要点】
1. LLM 只能看到并调用：
   - skill(name) — Round 1 使用
   - skill_name.tool_name — Round 2 使用（如 market_data.get_quote）

2. LLM 不应直接调用以下系统内部工具：
   - get_skill_tools — 由编排层在 Round 1 后自动调用
   - execute_skill_tool — 由编排层在 Round 2 后自动调用

3. 工具命名格式：
   - Round 1: skill(name="market_data")
   - Round 2: market_data.get_quote({"ts_code": "600519.SH"})
"""

from typing import Optional, List, Dict, Any


# 所有可用的 Skills 定义（直接披露，无需 read_resource）
ALL_SKILLS = {
    "market_data": {
        "description": "股票市场行情数据查询，提供实时股价、PE/PB估值、历史K线、资金流向等",
        "use_when": "股价、行情、涨跌幅、成交量、市盈率(PE)、市净率(PB)、市值、K线、历史走势、资金流向、股票代码查询"
    },
    "financial_analysis": {
        "description": "财务报表分析，计算ROE、ROA、毛利率、净利率等财务指标",
        "use_when": "ROE(净资产收益率)、ROA、营收、净利润、毛利率、资产负债表、现金流量表、同比/环比增长率"
    },
    "sector_analysis": {
        "description": "行业与概念板块分析，支持行业对比、龙头识别、估值对比",
        "use_when": "行业板块、产业链、行业对比、龙头识别、行业估值"
    },
    "risk_assessment": {
        "description": "投资风险评估，评估个股风险等级、提供预警",
        "use_when": "用户关注风险、需要风险评估时"
    },
    "data_analysis": {
        "description": "数据分析与可视化，支持统计分析、趋势预测、图表生成",
        "use_when": "用户需要数据分析、图表展示时使用"
    },
    "web_research": {
        "description": "网络信息搜索，获取新闻、公告、研报等外部信息",
        "use_when": "用户需要最新资讯、新闻、公告时使用"
    },
    "deep_research": {
        "description": "深度研究报告生成，综合多维度数据生成研报",
        "use_when": "用户需要深度研报、综合分析时使用"
    }
}


# 各Skill的具体工具定义（与金融研投助手 MCP Server 完全一致）
# 注意：参数名称必须与金融研投助手实际注册的一致（ts_code 而不是 symbol）
SKILL_TOOLS = {
    "market_data": [
        {"name": "get_quote", "description": "获取指定股票的实时行情数据，包括当前价格、涨跌幅、成交量等信息", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}}},
        {"name": "search_stock", "description": "根据股票代码或名称关键词搜索股票信息，支持模糊搜索（如'茅台'可匹配'贵州茅台'）", "parameters": {"keyword": {"type": "string", "description": "搜索关键词，可以是股票代码（如'600519'）或股票名称关键词（如'茅台'、'贵州'）", "required": True}}},
        {"name": "get_history", "description": "获取股票历史K线数据，支持日线、周线、月线", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "start_date": {"type": "string", "description": "开始日期，格式YYYYMMDD", "required": False}, "end_date": {"type": "string", "description": "结束日期，格式YYYYMMDD", "required": False}}},
        {"name": "get_stock_basic_info", "description": "获取股票基础信息（行业、地区、上市日期等）", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}}},
        {"name": "get_top_list", "description": "获取龙虎榜每日明细，包含机构买卖数据", "parameters": {"trade_date": {"type": "string", "description": "交易日期，格式YYYYMMDD，默认最近交易日", "required": False}}},
        {"name": "get_money_flow", "description": "获取个股资金流向数据（主力、散户净流入等）", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "trade_date": {"type": "string", "description": "交易日期，格式YYYYMMDD", "required": False}, "start_date": {"type": "string", "description": "开始日期，格式YYYYMMDD", "required": False}, "end_date": {"type": "string", "description": "结束日期，格式YYYYMMDD", "required": False}}},
        {"name": "get_limit_list", "description": "获取每日涨跌停统计", "parameters": {"trade_date": {"type": "string", "description": "交易日期，格式YYYYMMDD，默认最近交易日", "required": False}, "limit_type": {"type": "string", "description": "涨跌停类型：U(涨停)、D(跌停)，默认全部", "required": False}}},
        {"name": "get_company_info", "description": "获取上市公司详细信息（公司简介、联系方式、办公地址等）", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}}},
        {"name": "get_daily_basic", "description": "获取每日指标数据，包括PE、PB、PS、换手率、总市值、流通市值等估值指标", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH，不填写则返回全市场数据", "required": False}, "trade_date": {"type": "string", "description": "交易日期，格式YYYYMMDD，默认最近交易日", "required": False}}},
        {"name": "get_north_money", "description": "获取沪深港通资金流向（北向资金），追踪外资流入流出情况", "parameters": {"start_date": {"type": "string", "description": "开始日期，格式YYYYMMDD", "required": False}, "end_date": {"type": "string", "description": "结束日期，格式YYYYMMDD", "required": False}}},
        {"name": "get_margin", "description": "获取融资融券数据，包括融资余额、融券余额、融资买入额等", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH，不填写则返回全市场数据", "required": False}, "start_date": {"type": "string", "description": "开始日期，格式YYYYMMDD", "required": False}, "end_date": {"type": "string", "description": "结束日期，格式YYYYMMDD", "required": False}}}
    ],
    "financial_analysis": [
        {"name": "calculate_financial_ratios", "description": "计算ROE、ROA、毛利率、净利率、资产负债率等核心财务指标", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "period": {"type": "string", "description": "报告期，如'20231231'，不填则取最新", "required": False}}},
        {"name": "get_income_statement", "description": "获取利润表数据，包括营收、成本、利润等", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "start_date": {"type": "string", "description": "开始日期，格式YYYYMMDD", "required": False}, "end_date": {"type": "string", "description": "结束日期，格式YYYYMMDD", "required": False}, "period": {"type": "string", "description": "报告期类型，如'2023Q4'，可选", "required": False}}},
        {"name": "get_balance_sheet", "description": "获取资产负债表数据，包括资产、负债、股东权益等", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "start_date": {"type": "string", "description": "开始日期，格式YYYYMMDD", "required": False}, "end_date": {"type": "string", "description": "结束日期，格式YYYYMMDD", "required": False}, "period": {"type": "string", "description": "报告期类型，如'2023Q4'，可选", "required": False}}},
        {"name": "get_cash_flow", "description": "获取现金流量表数据，包括经营、投资、筹资活动现金流", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "start_date": {"type": "string", "description": "开始日期，格式YYYYMMDD", "required": False}, "end_date": {"type": "string", "description": "结束日期，格式YYYYMMDD", "required": False}, "period": {"type": "string", "description": "报告期类型，如'2023Q4'，可选", "required": False}}},
        {"name": "get_fina_indicator", "description": "获取一站式财务指标数据，包含ROE、ROA、毛利率等100+指标", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "start_date": {"type": "string", "description": "开始日期，格式YYYYMMDD", "required": False}, "end_date": {"type": "string", "description": "结束日期，格式YYYYMMDD", "required": False}, "period": {"type": "string", "description": "报告期类型，如'2023Q4'，可选", "required": False}}},
        {"name": "analyze_profitability", "description": "分析公司盈利能力，包括毛利率、净利率、ROE趋势等", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "periods": {"type": "integer", "description": "分析期数（季度），默认8个季度", "required": False}}},
        {"name": "analyze_solvency", "description": "分析公司偿债能力，包括流动比率、速动比率、资产负债率等", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "period": {"type": "string", "description": "报告期，如'20231231'，不填则取最新", "required": False}}}
    ],
    "sector_analysis": [
        {"name": "get_industry_list", "description": "获取所有行业分类列表", "parameters": {}},
        {"name": "get_industry_performance", "description": "获取各行业涨跌幅排名", "parameters": {"period": {"type": "string", "description": "周期：1d(日), 5d(周), 20d(月)", "required": False}}},
        {"name": "get_industry_leaders", "description": "获取指定行业的龙头股", "parameters": {"industry": {"type": "string", "description": "行业名称，如'白酒'、'银行'", "required": True}, "by": {"type": "string", "description": "排序依据：market_cap(市值), revenue(营收), profit(利润)", "required": False}, "limit": {"type": "integer", "description": "返回数量", "required": False}}},
        {"name": "compare_industry_metrics", "description": "对比不同行业的财务指标", "parameters": {"industries": {"type": "array", "description": "行业列表，如['白酒', '银行', '医药']", "required": False}, "metric": {"type": "string", "description": "对比指标：roe, gross_margin, net_margin, debt_ratio", "required": False}}},
        {"name": "compare_industry_valuation", "description": "对比不同行业的估值水平(PE、PB、PS)", "parameters": {"industries": {"type": "array", "description": "行业列表", "required": False}}},
        {"name": "get_concept_list", "description": "获取所有概念分类列表", "parameters": {}},
        {"name": "get_concept_stocks", "description": "获取指定概念的成分股", "parameters": {"concept_code": {"type": "string", "description": "概念代码", "required": False}, "concept_name": {"type": "string", "description": "概念名称，如'新能源'、'人工智能'", "required": False}}}
    ],
    "risk_assessment": [
        {"name": "assess_stock_risk", "description": "综合评估股票风险等级，包括市场风险、财务风险、估值风险等", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}}},
        {"name": "assess_valuation_risk", "description": "评估估值风险，分析PE/PB是否过高", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "industry_pe_avg": {"type": "number", "description": "行业平均PE，用于对比", "required": False}}},
        {"name": "assess_financial_risk", "description": "评估财务风险，分析资产负债率、现金流等", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}}},
        {"name": "assess_volatility_risk", "description": "评估股价波动风险，分析历史波动率", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "period": {"type": "string", "description": "计算周期：20d(20日), 60d(60日), 120d(120日)", "required": False}}},
        {"name": "check_risk_warnings", "description": "检查股票的风险预警信号", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}}}
    ],
    "web_research": [
        {"name": "search_stock_news", "description": "搜索指定股票的最新新闻", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "days": {"type": "integer", "description": "搜索最近几天的新闻", "required": False}, "limit": {"type": "integer", "description": "返回新闻数量", "required": False}}},
        {"name": "search_company_announcements", "description": "搜索指定公司的公告", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "category": {"type": "string", "description": "公告类型：all(全部), report(定期报告), major(重大事项), disclosure(信息披露)", "required": False}, "limit": {"type": "integer", "description": "返回公告数量", "required": False}}},
        {"name": "search_industry_news", "description": "搜索指定行业的最新新闻", "parameters": {"industry": {"type": "string", "description": "行业名称，如'白酒'、'新能源'", "required": True}, "days": {"type": "integer", "description": "搜索最近几天的新闻", "required": False}, "limit": {"type": "integer", "description": "返回新闻数量", "required": False}}},
        {"name": "search_research_reports", "description": "搜索指定股票或行业的研究报告", "parameters": {"keyword": {"type": "string", "description": "搜索关键词，可以是股票名称或行业名称", "required": True}, "report_type": {"type": "string", "description": "研报类型：all(全部), rating(评级), earnings(盈利预测), industry(行业)", "required": False}, "limit": {"type": "integer", "description": "返回研报数量", "required": False}}}
    ],
    "data_analysis": [
        {"name": "calculate_statistics", "description": "计算数据的统计指标（均值、标准差、最大值、最小值等）", "parameters": {"data": {"type": "array", "description": "数值数组", "required": True}, "metrics": {"type": "array", "description": "需要计算的指标：mean(均值), std(标准差), min(最小值), max(最大值), median(中位数)", "required": False}}},
        {"name": "analyze_price_trend", "description": "分析价格数据趋势，传入价格数组进行分析", "parameters": {"data": {"type": "array", "description": "价格数据数组，每个元素包含close(收盘价)、date(日期)等字段", "required": True}, "price_field": {"type": "string", "description": "价格字段名，默认为'close'", "required": False}}},
        {"name": "calculate_correlation", "description": "计算两组数据的相关性", "parameters": {"data1": {"type": "array", "description": "第一组数值数组", "required": True}, "data2": {"type": "array", "description": "第二组数值数组", "required": True}}},
        {"name": "calculate_technical_indicators", "description": "计算技术指标（MA、RSI、MACD等），传入价格数据数组", "parameters": {"data": {"type": "array", "description": "价格数据数组，每个元素需包含close(收盘价)、high(最高价)、low(最低价)等字段", "required": True}, "indicators": {"type": "array", "description": "指标列表：ma(移动平均线), rsi(相对强弱指标), macd, boll(布林带)", "required": False}}},
        {"name": "normalize_data", "description": "对数据进行标准化处理（Min-Max或Z-Score）", "parameters": {"data": {"type": "array", "description": "数值数组", "required": True}, "method": {"type": "string", "description": "标准化方法：minmax(最小-最大), zscore(Z-Score)", "required": False}}},
        {"name": "generate_chart_data", "description": "生成图表数据（K线、折线图、柱状图等），传入数据数组进行转换", "parameters": {"data": {"type": "array", "description": "数据数组，每个元素包含日期、价格等字段", "required": True}, "chart_type": {"type": "string", "description": "图表类型：kline(日K), line(折线), bar(柱状), pie(饼图)", "required": False}}}
    ],
    "deep_research": [
        {"name": "generate_stock_report", "description": "生成个股深度研究报告，综合财务、估值、行业等多维度数据", "parameters": {"ts_code": {"type": "string", "description": "TS股票代码，如 600519.SH", "required": True}, "report_type": {"type": "string", "description": "报告类型：comprehensive(综合), valuation(估值), financial(财务)", "required": False}}},
        {"name": "generate_industry_report", "description": "生成行业深度研究报告", "parameters": {"industry": {"type": "string", "description": "行业名称，如'白酒'、'银行'", "required": True}, "focus": {"type": "string", "description": "分析重点：overview(全景), leaders(龙头), valuation(估值), trend(趋势)", "required": False}}},
        {"name": "generate_comparison_report", "description": "生成股票对比分析报告", "parameters": {"symbols": {"type": "array", "description": "TS股票代码列表，如['600519.SH', '000858.SZ']", "required": True}, "dimensions": {"type": "array", "description": "对比维度：valuation(估值), profitability(盈利), growth(成长), risk(风险)", "required": False}}}
    ]
}


def get_tool_schemas(allowed_tools: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    获取 LLM 可用的工具 schemas（系统编排两轮架构）

    【关键设计】
    1. Round 1 工具: skill(name) —— LLM 调用以选择 Skill
    2. Round 2 工具: skill_name.tool_name —— LLM 直接调用具体工具
    3. 系统内部工具 (get_skill_tools, execute_skill_tool) 不在此暴露

    【调用流程】
    1. LLM 调用 skill(name="market_data") 选择 Skill
    2. 编排层自动调用 get_skill_tools 获取工具列表
    3. LLM 调用 market_data.get_quote({...}) 选择具体工具
    4. 编排层自动转换为 execute_skill_tool 执行

    Args:
        allowed_tools: 允许的工具列表，None 表示返回所有工具

    Returns:
        工具 schema 列表，包含 skill + 所有具体工具
    """
    all_tools = []

    # ============ Round 1: Skill 选择 ============
    # 这是 LLM 唯一需要调用的"元工具"，用于选择要使用的 Skill
    all_tools.append({
        "type": "function",
        "function": {
            "name": "skill",
            "description": "【Round 1 - 必须首先调用】选择合适的 Skill 来处理任务。分析用户意图，选择最能满足需求的 Skill。"
                         "可选: market_data(股价/估值/K线)、financial_analysis(财务指标/ROE/毛利率)、"
                         "sector_analysis(行业分析/龙头)、risk_assessment(风险评估)、"
                         "data_analysis(统计计算)、web_research(新闻公告)、deep_research(深度研报)。"
                         "调用后会自动获取该 Skill 的可用工具列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "选择的 Skill 名称",
                        "enum": list(ALL_SKILLS.keys())
                    }
                },
                "required": ["name"]
            }
        }
    })
    
    # ============ Round 2: 具体工具（格式: skill_name.tool_name）============
    for skill_name, tools in SKILL_TOOLS.items():
        for tool in tools:
            # 构建参数 schema
            properties = {}
            required = []
            for param_name, param_info in tool.get("parameters", {}).items():
                properties[param_name] = {
                    "type": param_info.get("type", "string"),
                    "description": param_info.get("description", "")
                }
                if param_info.get("required", False):
                    required.append(param_name)

            # MCP 工具名格式: skill_name.tool_name
            tool_full_name = f"{skill_name}.{tool['name']}"

            all_tools.append({
                "type": "function",
                "function": {
                    "name": tool_full_name,
                    "description": f"【{skill_name}】{tool['description']}",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required
                    }
                }
            })
    
    if not allowed_tools:
        return all_tools
    
    # 过滤指定工具
    filtered_tools = []
    for tool in all_tools:
        tool_name = tool.get("function", {}).get("name", "")
        if tool_name in allowed_tools:
            filtered_tools.append(tool)
    
    return filtered_tools


def get_all_tool_names() -> List[str]:
    """Get all available tool names（与金融研投助手一致）"""
    names = ["skill"]  # Round 1
    # Round 2: 所有具体工具
    for skill_name, tools in SKILL_TOOLS.items():
        for tool in tools:
            names.append(f"{skill_name}.{tool['name']}")
    return names


def get_skills_info() -> Dict[str, Dict[str, str]]:
    """获取所有 Skills 的信息（用于 Prompt）"""
    return ALL_SKILLS


def get_tools_by_resource(resource_type: str) -> List[Dict[str, Any]]:
    """
    Get tools for a specific resource type.
    
    原生 MCP 架构下，resource_type 参数不再使用，始终返回所有原生 MCP 工具。
    """
    return get_tool_schemas()


# 兼容旧代码的别名
get_finance_research_tool_schemas = get_tool_schemas


__all__ = [
    "ALL_SKILLS",
    "SKILL_TOOLS",
    "get_tool_schemas",
    "get_all_tool_names",
    "get_tools_by_resource",
    "get_finance_research_tool_schemas",
]
