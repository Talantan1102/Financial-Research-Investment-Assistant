# LLM-Based Mock 方案

## 核心思想

对于查询类工具，不返回静态数据，而是调用 LLM 动态生成符合工具语义的返回结果。

```
用户查询 "贵州茅台" → LLM Mock Engine → 生成真实股票数据

用户搜索 "新能源汽车" → LLM Mock Engine → 生成搜索结果
```

---

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM Mock Engine                          │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Tool Parser  │→ │ Prompt Gen   │→ │ LLM Call     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         ↓                 ↓                  ↓             │
│  解析工具名和参数    生成带约束的Prompt   调用LLM生成       │
│         ↓                 ↓                  ↓             │
│  ┌────────────────────────────────────────────────────┐   │
│  │              Response Validator                     │   │
│  │  - JSON 格式校验                                   │   │
│  │  - 字段完整性检查                                 │   │
│  │  - 数值合理性检查                                 │   │
│  └────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 按工具的 LLM Mock Prompt 设计

### 1. market_data.get_quote

```python
GET_QUOTE_MOCK_PROMPT = '''你是一个股票市场数据生成器。请根据用户查询的股票代码，生成逼真的实时行情数据。

输入参数:
- symbol: {symbol} (股票代码)

输出要求:
1. 返回 JSON 格式，包含以下字段:
{{
  "success": true,
  "data": {{
    "gid": "股票代码(带市场前缀)",
    "name": "股票中文名称",
    "nowPri": "当前价格(字符串，保留2位小数)",
    "increase": "涨跌额",
    "increPer": "涨跌幅百分比",
    "todayStartPri": "今日开盘价",
    "yestodEndPri": "昨日收盘价",
    "todayMax": "今日最高价",
    "todayMin": "今日最低价",
    "traAmount": "成交量(手)",
    "traNumber": "成交金额(元)",
    "update_time": "更新时间(YYYYMMDD)"
  }}
}}

2. 数据合理性约束:
   - 当前价格应在昨日收盘价的 ±10% 范围内(A股涨跌停限制)
   - 涨跌幅和涨跌额要匹配: increase = nowPri - yestodEndPri
   - 今日最高价 ≥ 当前价格 ≥ 今日最低价
   - 成交量和金额要合理(茅台通常数十亿成交额)

3. 根据股票代码推断:
   - 600/601/603 开头 → 沪市主板，带 sh 前缀
   - 000/001/002 开头 → 深市主板/中小板
   - 300/301 开头 → 创业板
   - 688 开头 → 科创板

请直接返回 JSON，不要有其他说明。'''
```

### 2. web_research.web_search

```python
WEB_SEARCH_MOCK_PROMPT = '''你是一个网络搜索结果生成器。请根据用户查询生成逼真的搜索结果。

输入参数:
- query: {query} (搜索关键词)
- num_results: {num_results} (期望结果数量，默认10)

输出要求:
1. 返回 JSON 格式:
{{
  "success": true,
  "data": {{
    "results": [
      {{
        "url": "https://...",
        "name": "文章标题",
        "summary": "内容摘要(50-100字)",
        "snippet": "搜索摘要片段",
        "site_name": "网站名称",
        "site_icon": "",
        "source": "web",
        "timestamp": "2025-03-15"
      }}
    ],
    "total": 总结果数,
    "query": "原始查询"
  }}
}}

2. 内容相关性约束:
   - 所有结果必须与查询主题相关
   - 标题要吸引人点击
   - 摘要要概括核心内容
   - 来源网站要真实存在(新浪、腾讯、36氪、知乎等)

3. 多样性要求:
   - 包含不同类型来源(新闻、论坛、博客、百科)
   - 包含不同观点(正面、中性、负面)
   - 包含不同时效性内容(最新、近期、历史)

请直接返回 JSON。'''
```

### 3. market_data.get_history

```python
GET_HISTORY_MOCK_PROMPT = '''你是一个股票历史数据生成器。请生成指定股票的K线历史数据。

输入参数:
- symbol: {symbol} (股票代码)
- period: {period} (周期: daily/weekly/monthly)
- start_date: {start_date} (开始日期)
- end_date: {end_date} (结束日期)
- limit: {limit} (返回条数)

输出要求:
1. 返回 JSON 格式:
{{
  "success": true,
  "data": [
    {{
      "date": "2025-03-01",
      "open": 1800.00,
      "high": 1850.00,
      "low": 1790.00,
      "close": 1825.00,
      "volume": 25000,
      "amount": 45000000
    }}
  ]
}}

2. 数据合理性约束:
   - high ≥ max(open, close) ≥ low
   - 价格变动要平滑，不能突变
   - 相邻日期的收盘价要连续
   - 成交量要有波动，不是固定值
   - 整体趋势可以是上涨、下跌或震荡

3. 根据股票类型设定价格区间:
   - 高价股(茅台): 1500-2000
   - 中价股: 50-200
   - 低价股: 5-20

请直接返回 JSON。'''
```

### 4. financial_analysis.get_financial_report

```python
FINANCIAL_REPORT_MOCK_PROMPT = '''你是一个财务报表生成器。请生成指定公司的财务报表数据。

输入参数:
- symbol: {symbol} (股票代码)
- report_type: {report_type} (报表类型: income/balance/cashflow)

输出要求:
1. 根据 report_type 返回对应报表:

收入表(income):
{{
  "success": true,
  "data": {{
    "report_date": "2025-12-31",
    "total_revenue": 15000000000,
    "operating_revenue": 14800000000,
    "gross_profit": 8000000000,
    "operating_profit": 5000000000,
    "net_profit": 4000000000,
    "eps": 31.50,
    "roe": 0.25
  }}
}}

资产负债表(balance):
{{
  "success": true,
  "data": {{
    "report_date": "2025-12-31",
    "total_assets": 250000000000,
    "total_liabilities": 50000000000,
    "shareholders_equity": 200000000000,
    "current_assets": 80000000000,
    "current_liabilities": 40000000000
  }}
}}

现金流量表(cashflow):
{{
  "success": true,
  "data": {{
    "report_date": "2025-12-31",
    "net_cash_from_operations": 6000000000,
    "net_cash_from_investing": -2000000000,
    "net_cash_from_financing": -3000000000
  }}
}}

2. 财务合理性约束:
   - 收入表: 营业收入 > 毛利 > 营业利润 > 净利润
   - 资产负债表: 资产 = 负债 + 股东权益
   - 数据规模要符合公司体量(茅台 vs 小公司)
   - 同比增长率要合理(-20% 到 +50%)

请直接返回 JSON。'''
```

---

## 实现代码

```python
# mocks/llm_mock_engine.py

import json
import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass
from openai import AsyncOpenAI

@dataclass
class LLMMockConfig:
    model: str = "qwen-max"  # 或 gpt-4
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.7
    max_retries: int = 3

class LLMMockEngine:
    """基于 LLM 的 Mock 数据生成引擎"""
    
    # 工具到 Prompt 的映射
    PROMPTS = {
        "market_data.get_quote": GET_QUOTE_MOCK_PROMPT,
        "market_data.get_history": GET_HISTORY_MOCK_PROMPT,
        "market_data.get_stock_basic_info": GET_STOCK_BASIC_INFO_MOCK_PROMPT,
        "market_data.get_top_list": GET_TOP_LIST_MOCK_PROMPT,
        "market_data.get_money_flow": GET_MONEY_FLOW_MOCK_PROMPT,
        "market_data.get_limit_list": GET_LIMIT_LIST_MOCK_PROMPT,
        "market_data.get_company_info": GET_COMPANY_INFO_MOCK_PROMPT,
        "web_research.web_search": WEB_SEARCH_MOCK_PROMPT,
        "web_research.deep_search": WEB_SEARCH_MOCK_PROMPT,  # 复用
        "web_research.extract_webpage": EXTRACT_WEBPAGE_MOCK_PROMPT,
        "financial_analysis.get_financial_report": FINANCIAL_REPORT_MOCK_PROMPT,
    }
    
    def __init__(self, config: LLMMockConfig):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url
        )
    
    async def generate(self, skill: str, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """生成 Mock 数据"""
        tool_key = f"{skill}.{tool}"
        prompt_template = self.PROMPTS.get(tool_key)
        
        if not prompt_template:
            raise ValueError(f"No mock prompt for {tool_key}")
        
        # 填充参数到 prompt
        prompt = prompt_template.format(**params)
        
        # 调用 LLM
        for attempt in range(self.config.max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.config.temperature
                )
                
                content = response.choices[0].message.content
                
                # 提取 JSON
                data = self._extract_json(content)
                
                # 验证结果
                if self._validate(tool_key, data, params):
                    return data
                else:
                    print(f"Validation failed, retrying...")
                    
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt == self.config.max_retries - 1:
                    raise
        
        return {"success": False, "error": "Failed to generate mock data"}
    
    def _extract_json(self, content: str) -> Dict:
        """从 LLM 响应中提取 JSON"""
        # 尝试直接解析
        try:
            return json.loads(content)
        except:
            pass
        
        # 提取 ```json 代码块
        import re
        patterns = [
            r'```json\s*\n(.*?)\n```',
            r'```\s*\n(.*?)\n```',
            r'\{.*\}'  # 直接提取最外层 JSON
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match)
                except:
                    continue
        
        raise ValueError("Could not extract JSON from response")
    
    def _validate(self, tool_key: str, data: Dict, params: Dict) -> bool:
        """验证生成的数据"""
        # 基础结构验证
        if not isinstance(data, dict):
            return False
        
        if "success" not in data:
            return False
        
        # 工具特定验证
        validators = {
            "market_data.get_quote": self._validate_quote,
            "market_data.get_history": self._validate_history,
            "web_research.web_search": self._validate_search,
        }
        
        validator = validators.get(tool_key)
        if validator:
            return validator(data, params)
        
        return True
    
    def _validate_quote(self, data: Dict, params: Dict) -> bool:
        """验证股票行情数据"""
        try:
            d = data.get("data", {})
            # 数值关系验证
            now_pri = float(d.get("nowPri", 0))
            yestod_end = float(d.get("yestodEndPri", 0))
            increase = float(d.get("increase", 0))
            
            # 涨跌幅验证
            if abs(now_pri - yestod_end - increase) > 0.01:
                return False
            
            # 涨跌停限制
            change_pct = (now_pri - yestod_end) / yestod_end
            if abs(change_pct) > 0.11:  # 允许一点误差
                return False
            
            return True
        except:
            return False
    
    def _validate_history(self, data: Dict, params: Dict) -> bool:
        """验证历史数据"""
        try:
            history = data.get("data", [])
            if not history:
                return False
            
            for item in history:
                high = float(item.get("high", 0))
                low = float(item.get("low", 0))
                open_price = float(item.get("open", 0))
                close = float(item.get("close", 0))
                
                if not (high >= max(open_price, close) >= low):
                    return False
            
            return True
        except:
            return False
    
    def _validate_search(self, data: Dict, params: Dict) -> bool:
        """验证搜索结果"""
        try:
            results = data.get("data", {}).get("results", [])
            query = params.get("query", "")
            
            # 检查相关性（简单检查关键词）
            keywords = query.split()
            for result in results:
                content = f"{result.get('name', '')} {result.get('summary', '')}"
                # 至少包含一个关键词
                if not any(kw in content for kw in keywords):
                    return False
            
            return True
        except:
            return False
```

---

## 与 AgentFlow 集成

```python
# 修改 synthesis/core/worker.py

from mocks.llm_mock_engine import LLMMockEngine, LLMMockConfig

class MockableSandboxWorker(SandboxWorker):
    """支持 LLM Mock 的 Worker"""
    
    def __init__(self, config: SynthesisConfig, worker_id: Optional[str] = None):
        super().__init__(config, worker_id)
        
        # 初始化 LLM Mock 引擎
        self.llm_mock = None
        if config.llm_mock_config:
            self.llm_mock = LLMMockEngine(config.llm_mock_config)
    
    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any], **kwargs) -> Any:
        """执行工具，支持 Mock"""
        
        # 解析 skill 和 tool
        if "." in tool_name:
            skill, tool = tool_name.rsplit(".", 1)
        else:
            skill = "default"
            tool = tool_name
        
        # 检查是否应该 Mock
        if self._should_mock(skill, tool):
            print(f"[LLM Mock] {tool_name} -> 生成模拟数据")
            return await self.llm_mock.generate(skill, tool, parameters)
        
        # 真实调用
        return await super().execute_tool(tool_name, parameters, **kwargs)
    
    def _should_mock(self, skill: str, tool: str) -> bool:
        """判断是否应该使用 Mock"""
        # 检查配置中的 Mock 策略
        mock_config = self.config.mock_strategy.get(skill, {})
        
        # 按工具配置
        if isinstance(mock_config, dict):
            return mock_config.get(tool, False)
        
        # 按 skill 配置
        return mock_config == "llm_mock"
```

---

## 配置示例

```yaml
# config/synthesis_llm_mock.yaml

# LLM Mock 配置
llm_mock:
  enabled: true
  model: "qwen-max"
  api_key: "${DASHSCOPE_API_KEY}"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  temperature: 0.7

# Mock 策略
mock_strategy:
  market_data:
    mode: "llm_mock"  # 整个 skill 都用 LLM Mock
  
  web_research:
    mode: "selective"
    tools:
      web_search: "llm_mock"
      deep_search: "llm_mock"
      knowledge_search: "real"
      extract_webpage: "real"
  
  financial_analysis:
    mode: "selective"
    tools:
      get_financial_report: "llm_mock"
      calculate_financial_ratios: "real"
      compare_financial_data: "real"

# 混合策略：部分真实调用验证
hybrid:
  enabled: true
  real_call_ratio: 0.1  # 10% 真实调用用于验证
```

---

## 成本估算

| 工具 | 单次 Token | 单次成本 | 1000 次成本 |
|------|-----------|---------|------------|
| get_quote | ~500 | ¥0.005 | ¥5 |
| web_search | ~1000 | ¥0.01 | ¥10 |
| get_history | ~2000 | ¥0.02 | ¥20 |
| get_financial_report | ~1500 | ¥0.015 | ¥15 |

**总计**: 生成 1000 条合成数据，LLM Mock 成本约 **¥50-100**

（相比真实调用 Tushare + 搜索 API 的 ¥50,000+，节省 99.8%）

---

## 质量保证

1. **Self-Consistency**: 同一参数多次调用，结果应一致
2. **Semantic Correctness**: 股票名称与代码匹配
3. **Numerical Validity**: 价格、财务数据符合数学关系
4. **Temporal Consistency**: 时间序列数据连续合理

需要我实现完整的代码吗？
