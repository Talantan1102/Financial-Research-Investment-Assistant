# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""控制流执行引擎 - MCP Server 控制流实现

支持6种控制流：
- sequential: 顺序执行
- for_each: FOR-EACH 循环
- while_loop: WHILE 循环
- if_else: IF-ELSE 分支
- switch: SWITCH 分支
- filter: FILTER 筛选
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger("ControlFlow")


class ControlFlowType(Enum):
    """控制流类型"""
    SEQUENTIAL = "sequential"
    FOR_EACH = "for_each"
    WHILE = "while"
    IF_ELSE = "if_else"
    SWITCH = "switch"
    FILTER = "filter"


@dataclass
class ExecutionContext:
    """执行上下文"""
    variables: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    call_count: int = 0
    max_calls: int = 50  # 最大调用次数限制
    errors: List[Dict[str, Any]] = field(default_factory=list)
    execution_log: List[Dict[str, Any]] = field(default_factory=list)
    
    def log(self, step: str, data: Dict[str, Any]):
        """记录执行日志"""
        self.execution_log.append({
            "step": step,
            "timestamp": datetime.now().isoformat(),
            "data": data
        })
    
    def increment_call(self) -> bool:
        """增加调用计数，返回是否超过限制"""
        self.call_count += 1
        if self.call_count > self.max_calls:
            raise ControlFlowError(f"执行调用次数超过限制 ({self.max_calls})")
        return True
    
    def set_variable(self, name: str, value: Any):
        """设置变量"""
        self.variables[name] = value
    
    def get_variable(self, name: str, default: Any = None) -> Any:
        """获取变量"""
        return self.variables.get(name, default)
    
    def set_result(self, call_id: str, result: Any):
        """设置执行结果"""
        self.results[call_id] = result
    
    def get_result(self, call_id: str) -> Any:
        """获取执行结果"""
        return self.results.get(call_id)


class ControlFlowError(Exception):
    """控制流错误"""
    pass


class ConditionEvaluator:
    """条件表达式求值器"""
    
    @staticmethod
    def evaluate(condition: str, context: ExecutionContext) -> bool:
        """
        评估条件表达式
        
        支持的条件格式：
        - "variable > value"
        - "variable < value"
        - "variable >= value"
        - "variable <= value"
        - "variable == value"
        - "variable != value"
        - "variable in [value1, value2]"
        - "variable.count < value" (特殊语法，用于列表长度)
        
        Args:
            condition: 条件表达式字符串
            context: 执行上下文
            
        Returns:
            条件评估结果
        """
        condition = condition.strip()
        
        # 处理特殊语法: qualified.count < 3
        if ".count" in condition:
            parts = condition.replace(".count", "").strip()
            for op in ["<=", ">=", "==", "!=", "<", ">"]:
                if op in parts:
                    left, right = parts.split(op, 1)
                    var_name = left.strip()
                    var_value = context.get_variable(var_name, [])
                    compare_value = ConditionEvaluator._parse_value(right.strip())
                    count = len(var_value) if isinstance(var_value, list) else 0
                    return ConditionEvaluator._compare(count, op, compare_value)
        
        # 处理 in 操作符
        if " in " in condition:
            left, right = condition.split(" in ", 1)
            var_name = left.strip()
            var_value = context.get_variable(var_name)
            
            # 解析列表
            list_str = right.strip()
            if list_str.startswith("[") and list_str.endswith("]"):
                list_str = list_str[1:-1]
                values = [v.strip().strip('"\'') for v in list_str.split(",")]
                return str(var_value) in values
            return False
        
        # 处理比较操作符
        for op in ["<=", ">=", "==", "!=", "<", ">"]:
            if op in condition:
                left, right = condition.split(op, 1)
                var_name = left.strip()
                var_value = context.get_variable(var_name)
                compare_value = ConditionEvaluator._parse_value(right.strip())
                return ConditionEvaluator._compare(var_value, op, compare_value)
        
        # 简单的布尔值
        if condition.lower() == "true":
            return True
        if condition.lower() == "false":
            return False
        
        # 尝试从上下文获取变量值
        var_value = context.get_variable(condition)
        if var_value is not None:
            return bool(var_value)
        
        raise ControlFlowError(f"无法解析的条件表达式: {condition}")
    
    @staticmethod
    def _parse_value(value_str: str) -> Union[int, float, str, bool]:
        """解析值字符串"""
        value_str = value_str.strip()
        
        # 布尔值
        if value_str.lower() == "true":
            return True
        if value_str.lower() == "false":
            return False
        
        # 字符串（去掉引号）
        if (value_str.startswith('"') and value_str.endswith('"')) or \
           (value_str.startswith("'") and value_str.endswith("'")):
            return value_str[1:-1]
        
        # 数字
        try:
            if "." in value_str:
                return float(value_str)
            return int(value_str)
        except ValueError:
            return value_str
    
    @staticmethod
    def _compare(left: Any, op: str, right: Any) -> bool:
        """比较两个值"""
        try:
            if op == "==":
                return left == right
            elif op == "!=":
                return left != right
            elif op == "<":
                return left < right
            elif op == ">":
                return left > right
            elif op == "<=":
                return left <= right
            elif op == ">=":
                return left >= right
            else:
                raise ControlFlowError(f"未知的操作符: {op}")
        except TypeError as e:
            raise ControlFlowError(f"类型不匹配无法比较: {left} {op} {right} - {e}")


@dataclass
class ToolCall:
    """工具调用定义"""
    skill: str
    tool: str
    arguments: Dict[str, Any]
    call_id: str
    depends_on: Optional[List[str]] = None
    iteration: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill": self.skill,
            "tool": self.tool,
            "arguments": self.arguments,
            "call_id": self.call_id,
            "depends_on": self.depends_on,
            "iteration": self.iteration
        }


@dataclass
class ControlFlowDefinition:
    """控制流定义"""
    type: ControlFlowType
    id: str
    
    # FOR-EACH / WHILE
    items: Optional[List[Any]] = None
    item_var: Optional[str] = None
    
    # WHILE
    condition: Optional[str] = None
    max_iterations: int = 20
    
    # IF-ELSE / FILTER
    filter_condition: Optional[str] = None
    if_condition: Optional[str] = None
    else_branch: Optional[List[ToolCall]] = None
    
    # SWITCH
    switch_variable: Optional[str] = None
    cases: Optional[Dict[str, List[ToolCall]]] = None
    default_case: Optional[List[ToolCall]] = None
    
    # 通用
    tool_calls: Optional[List[ToolCall]] = None
    parallel: bool = True
    max_concurrent: int = 10
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "id": self.id,
            "items": self.items,
            "item_var": self.item_var,
            "condition": self.condition,
            "max_iterations": self.max_iterations,
            "filter_condition": self.filter_condition,
            "if_condition": self.if_condition,
            "switch_variable": self.switch_variable,
            "parallel": self.parallel,
            "max_concurrent": self.max_concurrent
        }


class ControlFlowExecutor:
    """控制流执行器"""
    
    def __init__(self, skill_registry: Dict[str, Any]):
        """
        初始化执行器
        
        Args:
            skill_registry: Skill 注册表 {skill_name: skill_instance}
        """
        self.skill_registry = skill_registry
        self.condition_evaluator = ConditionEvaluator()
    
    async def execute(
        self,
        flow: ControlFlowDefinition,
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """
        执行控制流
        
        Args:
            flow: 控制流定义
            context: 执行上下文
            
        Returns:
            执行结果
        """
        context.log("execute_start", {"flow_type": flow.type.value, "flow_id": flow.id})
        
        if flow.type == ControlFlowType.SEQUENTIAL:
            return await self._execute_sequential(flow, context)
        elif flow.type == ControlFlowType.FOR_EACH:
            return await self._execute_for_each(flow, context)
        elif flow.type == ControlFlowType.WHILE:
            return await self._execute_while(flow, context)
        elif flow.type == ControlFlowType.IF_ELSE:
            return await self._execute_if_else(flow, context)
        elif flow.type == ControlFlowType.SWITCH:
            return await self._execute_switch(flow, context)
        elif flow.type == ControlFlowType.FILTER:
            return await self._execute_filter(flow, context)
        else:
            raise ControlFlowError(f"未知的控制流类型: {flow.type}")
    
    async def _execute_sequential(
        self,
        flow: ControlFlowDefinition,
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """顺序执行"""
        results = []
        
        if flow.parallel and flow.tool_calls:
            # 并行执行（无依赖的工具）
            results = await self._execute_parallel(flow.tool_calls, context, flow.max_concurrent)
        else:
            # 顺序执行
            for call in flow.tool_calls or []:
                result = await self._execute_tool_call(call, context)
                results.append(result)
        
        return {
            "flow_type": "sequential",
            "flow_id": flow.id,
            "execution_mode": "parallel" if flow.parallel else "sequential",
            "results": results,
            "total_calls": len(results)
        }
    
    async def _execute_for_each(
        self,
        flow: ControlFlowDefinition,
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """FOR-EACH 循环执行"""
        if not flow.items:
            raise ControlFlowError("FOR-EACH 循环需要 items 参数")
        if not flow.item_var:
            raise ControlFlowError("FOR-EACH 循环需要 item_var 参数")
        
        all_results = []
        iteration_results = []
        
        for idx, item in enumerate(flow.items):
            # 设置迭代变量
            context.set_variable(flow.item_var, item)
            context.set_variable(f"{flow.item_var}_index", idx)
            
            # 创建迭代特定的工具调用
            iteration_calls = []
            for call in flow.tool_calls or []:
                # 替换参数中的变量
                new_args = self._substitute_variables(call.arguments, context)
                new_call = ToolCall(
                    skill=call.skill,
                    tool=call.tool,
                    arguments=new_args,
                    call_id=f"{call.call_id}_iter{idx}",
                    iteration=idx
                )
                iteration_calls.append(new_call)
            
            # 执行本轮迭代的工具调用
            if flow.parallel:
                batch_results = await self._execute_parallel(
                    iteration_calls, context, flow.max_concurrent
                )
            else:
                batch_results = []
                for call in iteration_calls:
                    result = await self._execute_tool_call(call, context)
                    batch_results.append(result)
            
            iteration_results.append({
                "iteration": idx,
                "item": item,
                "results": batch_results
            })
            all_results.extend(batch_results)
        
        return {
            "flow_type": "for_each",
            "flow_id": flow.id,
            "total_iterations": len(flow.items),
            "parallel": flow.parallel,
            "iteration_results": iteration_results,
            "total_calls": len(all_results)
        }
    
    async def _execute_while(
        self,
        flow: ControlFlowDefinition,
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """WHILE 循环执行"""
        if not flow.condition:
            raise ControlFlowError("WHILE 循环需要 condition 参数")
        
        iteration = 0
        all_results = []
        iteration_results = []
        
        while iteration < flow.max_iterations:
            # 评估条件
            condition_met = self.condition_evaluator.evaluate(flow.condition, context)
            
            context.log("while_iteration", {
                "iteration": iteration,
                "condition": flow.condition,
                "condition_met": condition_met
            })
            
            if not condition_met:
                break
            
            # 执行本轮迭代的工具调用
            iteration_calls = []
            for call in flow.tool_calls or []:
                new_args = self._substitute_variables(call.arguments, context)
                new_call = ToolCall(
                    skill=call.skill,
                    tool=call.tool,
                    arguments=new_args,
                    call_id=f"{call.call_id}_iter{iteration}",
                    iteration=iteration
                )
                iteration_calls.append(new_call)
            
            if flow.parallel:
                batch_results = await self._execute_parallel(
                    iteration_calls, context, flow.max_concurrent
                )
            else:
                batch_results = []
                for call in iteration_calls:
                    result = await self._execute_tool_call(call, context)
                    batch_results.append(result)
            
            iteration_results.append({
                "iteration": iteration,
                "results": batch_results,
                "condition_state": dict(context.variables)
            })
            all_results.extend(batch_results)
            
            iteration += 1
        
        if iteration >= flow.max_iterations:
            context.log("while_max_iterations", {"max_iterations": flow.max_iterations})
        
        return {
            "flow_type": "while",
            "flow_id": flow.id,
            "total_iterations": iteration,
            "max_reached": iteration >= flow.max_iterations,
            "iteration_results": iteration_results,
            "total_calls": len(all_results)
        }
    
    async def _execute_if_else(
        self,
        flow: ControlFlowDefinition,
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """IF-ELSE 分支执行"""
        if not flow.if_condition:
            raise ControlFlowError("IF-ELSE 分支需要 if_condition 参数")
        
        # 评估条件
        condition_met = self.condition_evaluator.evaluate(flow.if_condition, context)
        
        context.log("if_else_evaluation", {
            "condition": flow.if_condition,
            "result": condition_met
        })
        
        # 选择分支
        if condition_met:
            selected_calls = flow.tool_calls or []
            selected_branch = "if"
        else:
            selected_calls = flow.else_branch or []
            selected_branch = "else"
        
        # 执行选中的分支
        results = []
        for call in selected_calls:
            result = await self._execute_tool_call(call, context)
            results.append(result)
        
        return {
            "flow_type": "if_else",
            "flow_id": flow.id,
            "condition": flow.if_condition,
            "condition_result": condition_met,
            "selected_branch": selected_branch,
            "results": results,
            "total_calls": len(results)
        }
    
    async def _execute_switch(
        self,
        flow: ControlFlowDefinition,
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """SWITCH 分支执行"""
        if not flow.switch_variable:
            raise ControlFlowError("SWITCH 分支需要 switch_variable 参数")
        
        # 获取变量值
        switch_value = context.get_variable(flow.switch_variable)
        
        context.log("switch_evaluation", {
            "variable": flow.switch_variable,
            "value": switch_value
        })
        
        # 匹配 case
        selected_calls = None
        selected_case = None
        
        if flow.cases:
            for case_value, case_calls in flow.cases.items():
                if str(switch_value) == case_value:
                    selected_calls = case_calls
                    selected_case = case_value
                    break
        
        # 使用 default
        if selected_calls is None and flow.default_case:
            selected_calls = flow.default_case
            selected_case = "default"
        
        if selected_calls is None:
            return {
                "flow_type": "switch",
                "flow_id": flow.id,
                "variable": flow.switch_variable,
                "value": switch_value,
                "matched_case": None,
                "results": [],
                "total_calls": 0
            }
        
        # 执行选中的 case
        results = []
        for call in selected_calls:
            result = await self._execute_tool_call(call, context)
            results.append(result)
        
        return {
            "flow_type": "switch",
            "flow_id": flow.id,
            "variable": flow.switch_variable,
            "value": switch_value,
            "matched_case": selected_case,
            "results": results,
            "total_calls": len(results)
        }
    
    async def _execute_filter(
        self,
        flow: ControlFlowDefinition,
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """FILTER 筛选执行"""
        if not flow.filter_condition:
            raise ControlFlowError("FILTER 需要 filter_condition 参数")
        
        # 首先执行所有工具调用获取数据
        all_results = []
        for call in flow.tool_calls or []:
            result = await self._execute_tool_call(call, context)
            all_results.append(result)
        
        # 将结果存入上下文
        context.set_variable("filter_input", all_results)
        
        # 执行筛选
        filtered_results = []
        for idx, result in enumerate(all_results):
            context.set_variable("filter_item", result)
            context.set_variable("filter_index", idx)
            
            if self.condition_evaluator.evaluate(flow.filter_condition, context):
                filtered_results.append(result)
        
        return {
            "flow_type": "filter",
            "flow_id": flow.id,
            "condition": flow.filter_condition,
            "input_count": len(all_results),
            "output_count": len(filtered_results),
            "filtered_results": filtered_results,
            "total_calls": len(all_results)
        }
    
    async def _execute_parallel(
        self,
        calls: List[ToolCall],
        context: ExecutionContext,
        max_concurrent: int
    ) -> List[Dict[str, Any]]:
        """并行执行工具调用"""
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def execute_with_limit(call: ToolCall) -> Dict[str, Any]:
            async with semaphore:
                return await self._execute_tool_call(call, context)
        
        tasks = [execute_with_limit(call) for call in calls]
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _execute_tool_call(
        self,
        call: ToolCall,
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """执行单个工具调用"""
        context.increment_call()
        
        # 检查依赖
        if call.depends_on:
            for dep_id in call.depends_on:
                if dep_id not in context.results:
                    return {
                        "call_id": call.call_id,
                        "success": False,
                        "error": f"依赖的调用 {dep_id} 尚未完成"
                    }
        
        # 获取 Skill
        skill = self.skill_registry.get(call.skill)
        if not skill:
            return {
                "call_id": call.call_id,
                "success": False,
                "error": f"Skill '{call.skill}' 不存在"
            }
        
        # 执行工具
        try:
            result = await skill.execute_tool(call.tool, call.arguments)
            context.set_result(call.call_id, result)
            
            return {
                "call_id": call.call_id,
                "skill": call.skill,
                "tool": call.tool,
                "success": result.success,
                "data": result.data if result.success else None,
                "error": result.error if not result.success else None,
                "iteration": call.iteration
            }
        except Exception as e:
            error_info = {
                "call_id": call.call_id,
                "skill": call.skill,
                "tool": call.tool,
                "success": False,
                "error": str(e),
                "iteration": call.iteration
            }
            context.errors.append(error_info)
            return error_info
    
    def _substitute_variables(
        self,
        arguments: Dict[str, Any],
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """替换参数中的变量"""
        result = {}
        
        for key, value in arguments.items():
            if isinstance(value, str):
                # 替换 ${variable} 格式的变量
                if value.startswith("${") and value.endswith("}"):
                    var_name = value[2:-1]
                    result[key] = context.get_variable(var_name)
                else:
                    result[key] = value
            elif isinstance(value, dict):
                result[key] = self._substitute_variables(value, context)
            elif isinstance(value, list):
                result[key] = [
                    self._substitute_variables({"_": item}, context)["_"] 
                    if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        
        return result


# 便捷函数
def create_sequential_flow(
    tool_calls: List[ToolCall],
    flow_id: str = "sequential_flow",
    parallel: bool = True
) -> ControlFlowDefinition:
    """创建顺序执行控制流"""
    return ControlFlowDefinition(
        type=ControlFlowType.SEQUENTIAL,
        id=flow_id,
        tool_calls=tool_calls,
        parallel=parallel
    )


def create_for_each_flow(
    items: List[Any],
    item_var: str,
    tool_calls: List[ToolCall],
    flow_id: str = "for_each_flow",
    parallel: bool = True,
    max_concurrent: int = 10
) -> ControlFlowDefinition:
    """创建 FOR-EACH 控制流"""
    return ControlFlowDefinition(
        type=ControlFlowType.FOR_EACH,
        id=flow_id,
        items=items,
        item_var=item_var,
        tool_calls=tool_calls,
        parallel=parallel,
        max_concurrent=max_concurrent
    )


def create_while_flow(
    condition: str,
    tool_calls: List[ToolCall],
    flow_id: str = "while_flow",
    max_iterations: int = 20,
    parallel: bool = False
) -> ControlFlowDefinition:
    """创建 WHILE 控制流"""
    return ControlFlowDefinition(
        type=ControlFlowType.WHILE,
        id=flow_id,
        condition=condition,
        tool_calls=tool_calls,
        max_iterations=max_iterations,
        parallel=parallel
    )


def create_if_else_flow(
    if_condition: str,
    if_calls: List[ToolCall],
    else_calls: List[ToolCall] = None,
    flow_id: str = "if_else_flow"
) -> ControlFlowDefinition:
    """创建 IF-ELSE 控制流"""
    return ControlFlowDefinition(
        type=ControlFlowType.IF_ELSE,
        id=flow_id,
        if_condition=if_condition,
        tool_calls=if_calls,
        else_branch=else_calls or []
    )


def create_switch_flow(
    switch_variable: str,
    cases: Dict[str, List[ToolCall]],
    default_case: List[ToolCall] = None,
    flow_id: str = "switch_flow"
) -> ControlFlowDefinition:
    """创建 SWITCH 控制流"""
    return ControlFlowDefinition(
        type=ControlFlowType.SWITCH,
        id=flow_id,
        switch_variable=switch_variable,
        cases=cases,
        default_case=default_case
    )


def create_filter_flow(
    filter_condition: str,
    tool_calls: List[ToolCall],
    flow_id: str = "filter_flow"
) -> ControlFlowDefinition:
    """创建 FILTER 控制流"""
    return ControlFlowDefinition(
        type=ControlFlowType.FILTER,
        id=flow_id,
        filter_condition=filter_condition,
        tool_calls=tool_calls
    )
