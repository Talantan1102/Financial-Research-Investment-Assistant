#!/usr/bin/env python3
"""
Resource + Tool 协同架构流程可视化 - 贵州茅台示例

新架构设计（符合 MCP 规范）：
- Round 1: list_resources() 返回 7 个 Skill URI
- Round 2: read_resource(uri="skill://xxx") 获取 SKILL.md，标记 Skill 为 discovered  
- Round 3: list_tools() 根据 discovered_skills 动态返回 Tools (skill_name.tool_name 格式)
- Round 4: call_tool(name="skill_name.tool_name", args) 直接执行
"""
import json

def load_data():
    with open('results/ds_synthesized_qa/trajectories.jsonl', 'r') as f:
        trajectories = [json.loads(line) for line in f]
    with open('results/ds_synthesized_qa/synthesized_qa.jsonl', 'r') as f:
        qas = [json.loads(line) for line in f]
    return trajectories[2], qas[2]  # 茅台示例

def print_flow():
    traj, qa = load_data()
    
    print("""
╔════════════════════════════════════════════════════════════════════════════════╗
║              Resource + Tool 协同架构 (Progressive Disclosure)                   ║
╚════════════════════════════════════════════════════════════════════════════════╝

问题: """ + qa['question'] + """
种子: """ + traj['seed_data'] + """

┌────────────────────────────────────────────────────────────────────────────────┐
│                      Round 1: 发现所有 Resources                                 │
│                     ──────────────────────────────                              │
│                                                                                  │
│   目标: 获取所有可用的 Skill URIs                                                │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────┐               │
│   │  调用: unified_finance:list_resources()                      │               │
│   │                                                             │               │
│   │  返回: 7 个 Skill Resources                                 │               │
│   │        - skill://market_data (市场数据)                      │               │
│   │        - skill://financial_analysis (财务分析)               │               │
│   │        - skill://sector_analysis (行业分析)                  │               │
│   │        - skill://risk_assessment (风险评估)                  │               │
│   │        - skill://data_analysis (数据分析)                    │               │
│   │        - skill://web_research (网络研究)                     │               │
│   │        - skill://deep_research (深度研究)                    │               │
│   └─────────────────────────────────────────────────────────────┘               │
│                              ↓                                                   │
│   LLM 现在知道: "有 7 个 Skills 可用"                                             │
└────────────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌────────────────────────────────────────────────────────────────────────────────┐
│                      Round 2: 读取 Skill Resource                                │
│                     ──────────────────────────────                              │
│                                                                                  │
│   目标: 读取感兴趣的 Skill 文档，将其标记为 discovered                             │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────┐               │
│   │  调用: unified_finance:read_resource(                       │               │
│   │            uri="skill://market_data"                        │               │
│   │         )                                                   │               │
│   │                                                             │               │
│   │  返回: SKILL.md 完整文档                                     │               │
│   │        - 业务描述: 股票市场行情数据查询                        │               │
│   │        - 数据源: Tushare Pro API                            │               │
│   │        - 支持市场: A股、港股                                  │               │
│   │        - 可用工具数: 8个                                      │               │
│   │                                                             │               │
│   │  (market_data 被标记为 discovered)                          │               │
│   └─────────────────────────────────────────────────────────────┘               │
│                              ↓                                                   │
│   LLM 现在知道: "market_data Skill 可以获取实时行情、历史K线等数据"                │
└────────────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌────────────────────────────────────────────────────────────────────────────────┐
│                      Round 3: 发现具体工具                                       │
│                     ─────────────────────────                                   │
│                                                                                  │
│   目标: 获取已发现 Skills 的具体工具列表                                          │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────┐               │
│   │  调用: unified_finance:list_tools()                          │               │
│   │                                                             │               │
│   │  返回: market_data 的 11 个工具                              │               │
│   │        - market_data.get_quote: 获取实时行情                  │               │
│   │        - market_data.get_history: 获取历史K线                 │               │
│   │        - market_data.get_stock_basic_info: 获取基础信息       │               │
│   │        - market_data.get_daily_basic: 获取估值指标 (PE, PB)   │               │
│   │        - ...                                                │               │
│   └─────────────────────────────────────────────────────────────┘               │
│                              ↓                                                   │
│   LLM 现在知道: "要获取股价需要用 market_data.get_quote，参数是 symbol"          │
└────────────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌────────────────────────────────────────────────────────────────────────────────┐
│                      Round 4: 执行具体工具                                       │
│                     ─────────────────────────                                   │
│                                                                                  │
│   目标: 通过 call_tool 执行具体工具 (skill_name.tool_name 格式)                   │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────┐               │
│   │  调用: unified_finance:call_tool(                            │               │
│   │            name="market_data.get_quote",                    │               │
│   │            arguments={"symbol": "600519"}                   │               │
│   │         )                                                   │               │
│   │                                                             │               │
│   │  返回: {                                                    │               │
│   │           "name": "贵州茅台",                                │               │
│   │           "nowPri": "1850.50",  ← 当前股价                  │               │
│   │           "increPer": "1.39",                                │               │
│   │           ...                                               │               │
│   │        }                                                    │               │
│   └─────────────────────────────────────────────────────────────┘               │
│                              ↓                                                   │
│   继续调用其他工具...                                                             │
│   - call_tool(name="market_data.get_stock_basic_info", ...)                      │
│   - call_tool(name="market_data.get_daily_basic", ...)                           │
│   - ... (多轮工具调用，逐步收集信息)                                              │
└────────────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌────────────────────────────────────────────────────────────────────────────────┐
│                              生成答案                                            │
│                     ─────────────────────                                       │
│                                                                                  │
│   基于收集的数据:                                                                 │
│   - 实时股价: 1850.50元                                                          │
│   - 市盈率 PE: 28.74                                                             │
│                                                                                  │
│   答案: """ + qa['answer'] + """                                        │
└────────────────────────────────────────────────────────────────────────────────┘

╔════════════════════════════════════════════════════════════════════════════════╗
║                              关键设计点                                          ║
╠════════════════════════════════════════════════════════════════════════════════╣
║                                                                                  ║
║  1. 渐进式披露 (4轮流程)                                                          ║
║     ────────────────────                                                        ║
║     ❌ 错误方式: LLM 直接看到 45 个工具，选择困难                                 ║
║     ✅ 正确方式: LLM 按轮次发现，逐步了解工具                                     ║
║                                                                                  ║
║  2. Resource + Tool 协同                                                         ║
║     ───────────────────                                                         ║
║     Round 1: list_resources()    → 获取所有 Skill URIs                          ║
║     Round 2: read_resource(uri)  → 读取 SKILL.md，标记 discovered               ║
║     Round 3: list_tools()        → 获取已发现 Skills 的工具                     ║
║     Round 4: call_tool(name)     → 执行工具 (skill_name.tool_name)              ║
║                                                                                  ║
║  3. 工具名格式                                                                   ║
║     ────────────                                                               ║
║     ❌ 旧格式: execute_skill_tool(skill_name="market_data",                     ║
║                                  tool_name="get_quote", ...)                    ║
║     ✅ 新格式: call_tool(name="market_data.get_quote", ...)                     ║
║                                                                                  ║
║  4. 与 MCP Server 一致                                                           ║
║     ───────────────────                                                         ║
║     - 相同的 Resource URI 格式 (skill://xxx)                                    ║
║     - 相同的渐进式披露流程                                                       ║
║     - 相同的工具名格式 (skill_name.tool_name)                                   ║
║                                                                                  ║
╚════════════════════════════════════════════════════════════════════════════════╝
""")

def print_trajectory_detail():
    """打印详细的轨迹数据"""
    traj, qa = load_data()
    
    print("\n" + "="*80)
    print("实际生成的 Trajectory 数据 (用于 GRPO 训练)")
    print("="*80)
    
    print(f"\n问题: {qa['question']}")
    print(f"答案: {qa['answer']}")
    print(f"\n轨迹深度: {traj['total_depth']}")
    print(f"节点数: {len(traj['nodes'])}")
    
    print("\n" + "-"*80)
    print("工具调用序列:")
    print("-"*80)
    
    for i, node in enumerate(traj['nodes'], 1):
        action = node.get('action', {})
        if not action:
            continue
        
        tool = action.get('tool_name', '')
        params = action.get('parameters', {})
        
        # 判断是哪一轮 (新架构)
        if tool == 'unified_finance:list_resources':
            round_name = "Round 1 - 发现 Resources"
        elif tool == 'unified_finance:read_resource':
            round_name = "Round 2 - 读取 Resource"
        elif tool == 'unified_finance:list_tools':
            round_name = "Round 3 - 发现工具"
        elif tool == 'unified_finance:call_tool':
            round_name = "Round 4 - 执行工具"
        # 向后兼容旧 API
        elif tool == 'unified_finance:skill':
            round_name = "Round 1 - Skill选择 (旧API)"
        elif tool == 'unified_finance:get_skill_tools':
            round_name = "Round 2 - 工具发现 (旧API)"
        elif tool == 'unified_finance:execute_skill_tool':
            round_name = "Round 3 - 工具执行 (旧API)"
        else:
            round_name = "UNKNOWN"
        
        print(f"\n步骤 {i}: [{round_name}]")
        print(f"  工具: {tool}")
        print(f"  参数: {json.dumps(params, ensure_ascii=False)}")
        
        # 显示关键参数
        if tool == 'unified_finance:call_tool':
            name = params.get('name', '')
            args = params.get('arguments', {})
            print(f"  → 执行: {name}({args})")
        elif tool == 'unified_finance:execute_skill_tool':
            skill = params.get('skill_name', '')
            tool_name = params.get('tool_name', '')
            args = params.get('arguments', {})
            print(f"  → 执行: {skill}.{tool_name}({args})")

if __name__ == "__main__":
    print_flow()
    print_trajectory_detail()
