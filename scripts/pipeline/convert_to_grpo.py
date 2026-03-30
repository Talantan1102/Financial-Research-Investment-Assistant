#!/usr/bin/env python3
"""
将 AgentFlow 生成的数据转换为 GRPO 训练格式

GRPO 数据格式:
{
  "messages": [
    {"role": "system", "content": "系统提示"},
    {"role": "user", "content": "问题"},
    {"role": "assistant", "content": "思考过程", "tool_calls": [...]},
    {"role": "tool", "content": "工具返回结果"},
    ...
  ],
  "metadata": {...}
}
"""
import json
import sys
from pathlib import Path

def convert_to_grpo_format(qa_file, traj_file, output_file):
    """Convert AgentFlow output to GRPO training format"""
    
    # Load QA pairs
    qa_list = []
    with open(qa_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                qa_list.append(json.loads(line))
    
    # Load trajectories
    traj_dict = {}
    with open(traj_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                traj = json.loads(line)
                traj_dict[traj['trajectory_id']] = traj
    
    grpo_data = []
    
    for qa in qa_list:
        traj_id = qa['trajectory_id']
        traj = traj_dict.get(traj_id)
        
        if not traj:
            print(f"⚠️ Trajectory not found: {traj_id}")
            continue
        
        # Build messages
        messages = []
        
        # System message
        messages.append({
            "role": "system",
            "content": "你是一个金融研究助手，可以使用工具来分析股票、行业和财务数据。请逐步思考并使用合适的工具来回答问题。"
        })
        
        # User message (question context)
        messages.append({
            "role": "user", 
            "content": f"请回答以下问题：{qa['question']}\\n\\n背景：{traj.get('seed_data', '')}"
        })
        
        # Build assistant's thought process and tool calls from trajectory
        tool_calls = []
        observations = []
        
        for node in traj.get('nodes', []):
            action = node.get('action', {})
            tool_name = action.get('tool_name', '')
            params = action.get('parameters', {})
            observation = node.get('observation', '')
            intent = node.get('intent', '')
            
            # Skip if no action
            if not tool_name:
                continue
            
            # Record tool call
            tool_calls.append({
                "tool_name": tool_name,
                "parameters": params,
                "intent": intent
            })
            
            # Record observation
            observations.append({
                "tool_name": tool_name,
                "result": observation[:500] if len(observation) > 500 else observation  # Truncate long outputs
            })
        
        # Assistant message with reasoning and tool calls
        reasoning = "\\n".join([
            f"Step {i+1}: {call['intent']}" 
            for i, call in enumerate(tool_calls)
        ])
        
        messages.append({
            "role": "assistant",
            "content": f"让我逐步分析这个问题。\\n\\n{reasoning}",
            "tool_calls": tool_calls
        })
        
        # Tool observation messages
        for obs in observations:
            messages.append({
                "role": "tool",
                "content": f"工具 {obs['tool_name']} 返回结果：\\n{obs['result']}",
                "name": obs['tool_name']
            })
        
        # Final answer
        messages.append({
            "role": "assistant",
            "content": f"根据以上分析，我的答案是：\\n{qa['answer']}"
        })
        
        # Build GRPO item
        grpo_item = {
            "messages": messages,
            "metadata": {
                "question": qa['question'],
                "answer": qa['answer'],
                "trajectory_id": traj_id,
                "source_id": traj.get('source_id', ''),
                "depth": traj.get('total_depth', 0),
                "node_count": len(traj.get('nodes', [])),
                "tool_call_count": len(tool_calls)
            }
        }
        
        grpo_data.append(grpo_item)
    
    # Save output (JSONL format)
    with open(output_file, 'w', encoding='utf-8') as f:
        for item in grpo_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"✅ Converted {len(grpo_data)} items to GRPO format")
    print(f"   Output: {output_file}")
    
    return grpo_data


def print_grpo_example(grpo_data, index=0):
    """Print a GRPO example for inspection"""
    if not grpo_data or index >= len(grpo_data):
        print("No data to display")
        return
    
    item = grpo_data[index]
    print("\\n" + "="*80)
    print(f"GRPO Example {index + 1}")
    print("="*80)
    print(f"Metadata: {json.dumps(item['metadata'], ensure_ascii=False, indent=2)}")
    print(f"\\nMessages ({len(item['messages'])}):")
    for i, msg in enumerate(item['messages'], 1):
        print(f"\\n--- Message {i} ({msg['role']}) ---")
        content = msg['content']
        if len(content) > 300:
            content = content[:300] + "..."
        print(content)
        if 'tool_calls' in msg:
            print(f"\\nTool calls: {len(msg['tool_calls'])}")
            for tc in msg['tool_calls']:
                print(f"  - {tc['tool_name']}: {tc['parameters']}")


def analyze_grpo_data(grpo_data):
    """Analyze GRPO data statistics"""
    print("\\n" + "="*80)
    print("GRPO 数据统计")
    print("="*80)
    
    total = len(grpo_data)
    print(f"总样本数: {total}")
    
    if total == 0:
        return
    
    # Tool call statistics
    tool_counts = []
    depths = []
    
    for item in grpo_data:
        meta = item['metadata']
        tool_counts.append(meta.get('tool_call_count', 0))
        depths.append(meta.get('depth', 0))
    
    print(f"平均工具调用数: {sum(tool_counts)/len(tool_counts):.1f}")
    print(f"平均轨迹深度: {sum(depths)/len(depths):.1f}")
    print(f"最大工具调用数: {max(tool_counts)}")
    print(f"最小工具调用数: {min(tool_counts)}")
    
    # Check data quality
    has_answer = sum(1 for item in grpo_data if item['metadata'].get('answer') and '未提供' not in item['metadata']['answer'])
    print(f"有具体答案的样本: {has_answer}/{total} ({100*has_answer/total:.1f}%)")


if __name__ == "__main__":
    import sys
    
    # Default paths
    qa_file = "results/ds_synthesized_qa/synthesized_qa.jsonl"
    traj_file = "results/ds_synthesized_qa/trajectories.jsonl"
    output_file = "results/grpo_training_data.jsonl"
    
    # Allow custom paths
    if len(sys.argv) > 1:
        qa_file = sys.argv[1]
    if len(sys.argv) > 2:
        traj_file = sys.argv[2]
    if len(sys.argv) > 3:
        output_file = sys.argv[3]
    
    print("="*80)
    print("AgentFlow -> GRPO 数据转换")
    print("="*80)
    print(f"QA file: {qa_file}")
    print(f"Trajectory file: {traj_file}")
    print(f"Output file: {output_file}")
    
    # Convert
    grpo_data = convert_to_grpo_format(qa_file, traj_file, output_file)
    
    # Analyze
    analyze_grpo_data(grpo_data)
    
    # Show example
    if grpo_data:
        print_grpo_example(grpo_data, 0)
