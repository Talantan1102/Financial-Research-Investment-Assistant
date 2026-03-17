#!/usr/bin/env python3
"""
渐进式披露流程可视化 - 贵州茅台示例
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
║                    渐进式披露 (Progressive Disclosure) 完整流程                  ║
╚════════════════════════════════════════════════════════════════════════════════╝

问题: """ + qa['question'] + """
种子: """ + traj['seed_data'] + """

┌────────────────────────────────────────────────────────────────────────────────┐
│                         ROUND 1: Skill 选择 (元工具)                             │
│                     ─────────────────────────────────                           │
│                                                                                  │
│   目标: LLM 不知道有哪些 Skill，需要先了解业务领域                                  │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────┐               │
│   │  调用: unified_finance:skill(name="market_data")             │               │
│   │                                                             │               │
│   │  返回: SKILL.md 完整文档                                     │               │
│   │        - 业务描述: 股票市场行情数据查询                        │               │
│   │        - 数据源: Tushare Pro API                            │               │
│   │        - 支持市场: A股、港股                                  │               │
│   │        - 可用工具数: 8个                                      │               │
│   └─────────────────────────────────────────────────────────────┘               │
│                              ↓                                                   │
│   LLM 现在知道: "market_data Skill 可以获取实时行情、历史K线等数据"                 │
└────────────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌────────────────────────────────────────────────────────────────────────────────┐
│                         ROUND 2: 工具发现 (元工具)                               │
│                     ─────────────────────────────────                           │
│                                                                                  │
│   目标: 知道 Skill 后，需要获取具体的工具列表和参数                                │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────┐               │
│   │  调用: unified_finance:get_skill_tools(name="market_data")   │               │
│   │                                                             │               │
│   │  返回: 11个工具的 JSON Schema                                │               │
│   │        - get_quote: 获取实时行情 (参数: symbol)              │               │
│   │        - get_history: 获取历史K线 (参数: symbol, period)     │               │
│   │        - get_stock_basic_info: 获取基础信息                  │               │
│   │        - get_daily_basic: 获取估值指标 (PE, PB等)            │               │
│   │        - ...                                                │               │
│   └─────────────────────────────────────────────────────────────┘               │
│                              ↓                                                   │
│   LLM 现在知道: "要获取股价需要用 get_quote，参数是 symbol"                        │
└────────────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌────────────────────────────────────────────────────────────────────────────────┐
│                         ROUND 3: 工具执行 (元工具)                               │
│                     ─────────────────────────────────                           │
│                                                                                  │
│   目标: 有了工具信息，通过统一的 execute_skill_tool 执行具体工具                   │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────┐               │
│   │  调用: unified_finance:execute_skill_tool(                   │               │
│   │            skill_name="market_data",                         │               │
│   │            tool_name="get_quote",                            │               │
│   │            arguments={"symbol": "600519"}                    │               │
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
│   - get_stock_basic_info → 获取行业、上市日期                                     │
│   - get_daily_basic → 获取 PE (28.74)                                           │
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
║  1. 元工具架构 (3个工具 vs 45个工具)                                              ║
║     ────────────────────────────────                                            ║
║     ❌ 错误方式: LLM 直接看到 45 个工具，选择困难                                 ║
║     ✅ 正确方式: LLM 只看到 3 个元工具，逐步发现所需工具                          ║
║                                                                                  ║
║  2. 工具调用唯一入口                                                            ║
║     ─────────────────                                                         ║
║     ❌ 错误方式: 直接调用 get_quote(symbol="600519")                             ║
║     ✅ 正确方式: execute_skill_tool(skill_name="market_data",                   ║
║                                    tool_name="get_quote",                       ║
║                                    arguments={"symbol": "600519"})              ║
║                                                                                  ║
║  3. 信息逐步披露                                                                ║
║     ─────────────────                                                         ║
║     Round 1: 了解有什么 Skill (业务层面)                                         ║
║     Round 2: 了解 Skill 下有什么工具 (功能层面)                                   ║
║     Round 3: 执行具体工具获取数据 (数据层面)                                      ║
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
        
        # 判断是哪一轮
        if tool == 'unified_finance:skill':
            round_name = "ROUND 1 - Skill选择"
        elif tool == 'unified_finance:get_skill_tools':
            round_name = "ROUND 2 - 工具发现"
        elif tool == 'unified_finance:execute_skill_tool':
            round_name = "ROUND 3 - 工具执行"
        else:
            round_name = "UNKNOWN"
        
        print(f"\n步骤 {i}: [{round_name}]")
        print(f"  工具: {tool}")
        print(f"  参数: {json.dumps(params, ensure_ascii=False)}")
        
        # 显示关键参数
        if tool == 'unified_finance:execute_skill_tool':
            skill = params.get('skill_name', '')
            tool_name = params.get('tool_name', '')
            args = params.get('arguments', {})
            print(f"  → 执行: {skill}.{tool_name}({args})")

if __name__ == "__main__":
    print_flow()
    print_trajectory_detail()
