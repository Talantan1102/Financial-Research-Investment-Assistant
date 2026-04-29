"""Control Flow Engine - 控制流执行引擎

实现6种控制流模式：
- 顺序执行 (sequential)
- FOR-EACH 循环
- WHILE 循环
- IF-ELSE 分支
- SWITCH 分支
- FILTER 筛选
"""

import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ControlFlowType(Enum):
    """控制流类型"""

    SEQUENTIAL = "sequential"
    FOR_EACH = "for_each"
    WHILE = "while"
    IF_ELSE = "if_else"
    SWITCH = "switch"
    FILTER = "filter"


@dataclass
class ToolCall:
    """工具调用定义"""

    skill: str
    tool: str
    arguments: dict[str, Any]
    call_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    iteration: int | None = None
    depends_on: list[str] | None = None


@dataclass
class ControlFlowContext:
    """控制流执行上下文"""

    flow_id: str
    flow_type: ControlFlowType
    variables: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    iteration_count: int = 0
    max_iterations: int = 20
    parallel: bool = True
    max_concurrent: int = 10


@dataclass
class ExecutionResult:
    """执行结果"""

    success: bool
    data: Any = None
    error: str | None = None
    call_id: str | None = None
    execution_time_ms: int | None = None


class ControlFlowExecutor(ABC):
    """控制流执行器基类"""

    def __init__(self, skill_executor: Callable[[str, str, dict[str, Any]], asyncio.Future]):
        self.skill_executor = skill_executor
        self.execution_history: list[dict[str, Any]] = []

    @abstractmethod
    async def execute(
        self, context: ControlFlowContext, config: dict[str, Any]
    ) -> list[ExecutionResult]:
        """执行控制流"""
        pass

    async def execute_tool_call(self, call: ToolCall) -> ExecutionResult:
        """执行单个工具调用"""
        import time

        start_time = time.time()

        try:
            result = await self.skill_executor(call.skill, call.tool, call.arguments)
            execution_time = int((time.time() - start_time) * 1000)

            if isinstance(result, dict):
                success = result.get("success", False)
                data = result.get("data")
                error = result.get("error")
            else:
                success = True
                data = result
                error = None

            return ExecutionResult(
                success=success,
                data=data,
                error=error,
                call_id=call.call_id,
                execution_time_ms=execution_time,
            )
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                success=False, error=str(e), call_id=call.call_id, execution_time_ms=execution_time
            )

    async def execute_parallel(
        self, calls: list[ToolCall], max_concurrent: int = 10
    ) -> list[ExecutionResult]:
        """并行执行多个工具调用"""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def execute_with_semaphore(call: ToolCall) -> ExecutionResult:
            async with semaphore:
                return await self.execute_tool_call(call)

        tasks = [execute_with_semaphore(call) for call in calls]
        return await asyncio.gather(*tasks)

    async def execute_sequential(self, calls: list[ToolCall]) -> list[ExecutionResult]:
        """顺序执行多个工具调用"""
        results = []
        for call in calls:
            result = await self.execute_tool_call(call)
            results.append(result)
            # 如果执行失败且是关键调用，立即停止
            if not result.success:
                break
        return results


class SequentialExecutor(ControlFlowExecutor):
    """顺序执行器"""

    async def execute(
        self, context: ControlFlowContext, config: dict[str, Any]
    ) -> list[ExecutionResult]:
        """顺序执行工具调用"""
        calls = config.get("calls", [])
        tool_calls = [
            ToolCall(
                skill=call["skill"],
                tool=call["tool"],
                arguments=call.get("arguments", {}),
                call_id=call.get("call_id", str(uuid.uuid4())[:8]),
            )
            for call in calls
        ]

        return await self.execute_sequential(tool_calls)


class ForEachExecutor(ControlFlowExecutor):
    """FOR-EACH 循环执行器"""

    async def execute(
        self, context: ControlFlowContext, config: dict[str, Any]
    ) -> list[ExecutionResult]:
        """执行FOR-EACH循环"""
        items = config.get("items", [])
        item_template = config.get("template", {})
        parallel = config.get("parallel", True)
        max_concurrent = config.get("max_concurrent", 10)
        item_var_name = config.get("item_var", "item")

        all_results = []
        tool_calls = []

        for i, item in enumerate(items):
            # 创建当前迭代的工具调用
            call_config = self._substitute_variables(item_template, item, item_var_name, i)
            tool_call = ToolCall(
                skill=call_config["skill"],
                tool=call_config["tool"],
                arguments=call_config.get("arguments", {}),
                call_id=f"{call_config.get('call_id', 'call')}_{i}",
                iteration=i,
            )
            tool_calls.append(tool_call)

        if parallel:
            results = await self.execute_parallel(tool_calls, max_concurrent)
        else:
            results = await self.execute_sequential(tool_calls)

        return results

    def _substitute_variables(
        self, template: dict[str, Any], item: Any, item_var: str, index: int
    ) -> dict[str, Any]:
        """替换模板中的变量"""
        import json

        template_str = json.dumps(template)

        # 替换 item.property
        if isinstance(item, dict):
            for key, value in item.items():
                placeholder = f"{{{item_var}.{key}}}"
                template_str = template_str.replace(placeholder, json.dumps(value))

        # 替换 item 本身
        template_str = template_str.replace(f"{{{item_var}}}", json.dumps(item))
        template_str = template_str.replace(f"{{{item_var}_index}}", str(index))

        return json.loads(template_str)


class WhileExecutor(ControlFlowExecutor):
    """WHILE 循环执行器"""

    async def execute(
        self, context: ControlFlowContext, config: dict[str, Any]
    ) -> list[ExecutionResult]:
        """执行WHILE循环"""
        condition = config.get("condition", "")
        max_iterations = config.get("max_iterations", 20)
        template = config.get("template", {})
        condition_checker = config.get("condition_checker")

        all_results = []
        iteration = 0

        while iteration < max_iterations:
            # 检查循环条件
            if condition_checker and not condition_checker(context):
                break

            # 执行本轮迭代
            call_config = self._prepare_iteration(template, context, iteration)
            tool_call = ToolCall(
                skill=call_config["skill"],
                tool=call_config["tool"],
                arguments=call_config.get("arguments", {}),
                call_id=f"while_{iteration}",
                iteration=iteration,
            )

            result = await self.execute_tool_call(tool_call)
            all_results.append(result)

            # 更新上下文
            context.iteration_count = iteration + 1
            context.results[f"iteration_{iteration}"] = result

            # 如果执行失败，立即停止
            if not result.success:
                break

            iteration += 1

        return all_results

    def _prepare_iteration(
        self, template: dict[str, Any], context: ControlFlowContext, iteration: int
    ) -> dict[str, Any]:
        """准备单次迭代的调用配置"""
        import copy

        config = copy.deepcopy(template)

        # 替换上下文变量
        if "arguments" in config:
            for key, value in config["arguments"].items():
                if isinstance(value, str) and value.startswith("$"):
                    var_name = value[1:]
                    config["arguments"][key] = context.variables.get(var_name)

        return config


class IfElseExecutor(ControlFlowExecutor):
    """IF-ELSE 分支执行器"""

    async def execute(
        self, context: ControlFlowContext, config: dict[str, Any]
    ) -> list[ExecutionResult]:
        """执行IF-ELSE分支"""
        condition = config.get("condition", "")
        evaluator = config.get("condition_evaluator")
        if_branch = config.get("if_branch", {})
        else_branch = config.get("else_branch", {})

        # 评估条件
        condition_result = False
        if evaluator:
            condition_result = evaluator(context)

        context.variables["__condition_result__"] = condition_result

        # 选择分支
        selected_branch = if_branch if condition_result else else_branch
        calls = selected_branch.get("calls", [])

        tool_calls = [
            ToolCall(
                skill=call["skill"],
                tool=call["tool"],
                arguments=call.get("arguments", {}),
                call_id=call.get("call_id", str(uuid.uuid4())[:8]),
            )
            for call in calls
        ]

        return await self.execute_sequential(tool_calls)


class SwitchExecutor(ControlFlowExecutor):
    """SWITCH 分支执行器"""

    async def execute(
        self, context: ControlFlowContext, config: dict[str, Any]
    ) -> list[ExecutionResult]:
        """执行SWITCH分支"""
        variable = config.get("variable", "")
        cases = config.get("cases", [])
        default_case = config.get("default", {})

        # 获取变量值
        variable_value = context.variables.get(variable)

        # 查找匹配的分支
        selected_branch = default_case
        for case in cases:
            if case.get("value") == variable_value:
                selected_branch = case
                break

        calls = selected_branch.get("calls", [])
        tool_calls = [
            ToolCall(
                skill=call["skill"],
                tool=call["tool"],
                arguments=call.get("arguments", {}),
                call_id=call.get("call_id", str(uuid.uuid4())[:8]),
            )
            for call in calls
        ]

        return await self.execute_sequential(tool_calls)


class FilterExecutor(ControlFlowExecutor):
    """FILTER 筛选执行器"""

    async def execute(
        self, context: ControlFlowContext, config: dict[str, Any]
    ) -> list[ExecutionResult]:
        """执行FILTER筛选"""
        source = config.get("source", "")
        filter_condition = config.get("condition", "")
        filter_func = config.get("filter_func")

        # 获取源数据
        source_data = context.results.get(source, [])

        if not isinstance(source_data, list):
            return [ExecutionResult(success=False, error=f"Source '{source}' is not a list")]

        # 执行筛选
        if filter_func:
            filtered_items = [item for item in source_data if filter_func(item)]
        else:
            filtered_items = source_data

        return [
            ExecutionResult(
                success=True,
                data={
                    "filtered_items": filtered_items,
                    "input_count": len(source_data),
                    "output_count": len(filtered_items),
                },
                call_id="filter_result",
            )
        ]


class ControlFlowEngine:
    """控制流引擎 - 统一入口"""

    def __init__(self, skill_executor: Callable[[str, str, dict[str, Any]], asyncio.Future]):
        self.skill_executor = skill_executor
        self.executors: dict[ControlFlowType, ControlFlowExecutor] = {
            ControlFlowType.SEQUENTIAL: SequentialExecutor(skill_executor),
            ControlFlowType.FOR_EACH: ForEachExecutor(skill_executor),
            ControlFlowType.WHILE: WhileExecutor(skill_executor),
            ControlFlowType.IF_ELSE: IfElseExecutor(skill_executor),
            ControlFlowType.SWITCH: SwitchExecutor(skill_executor),
            ControlFlowType.FILTER: FilterExecutor(skill_executor),
        }
        self.execution_history: list[dict[str, Any]] = []

    async def execute(
        self,
        flow_type: str | ControlFlowType,
        config: dict[str, Any],
        context: ControlFlowContext | None = None,
    ) -> dict[str, Any]:
        """
        执行控制流

        Args:
            flow_type: 控制流类型
            config: 控制流配置
            context: 执行上下文（可选）

        Returns:
            执行结果
        """
        if isinstance(flow_type, str):
            flow_type = ControlFlowType(flow_type)

        if flow_type not in self.executors:
            return {
                "success": False,
                "error": f"Unknown control flow type: {flow_type}",
                "results": [],
            }

        # 创建或更新上下文
        if context is None:
            context = ControlFlowContext(
                flow_id=str(uuid.uuid4())[:8],
                flow_type=flow_type,
                max_iterations=config.get("max_iterations", 20),
                parallel=config.get("parallel", True),
                max_concurrent=config.get("max_concurrent", 10),
            )

        executor = self.executors[flow_type]

        try:
            results = await executor.execute(context, config)

            # 记录执行历史
            execution_record = {
                "flow_id": context.flow_id,
                "flow_type": flow_type.value,
                "iteration_count": context.iteration_count,
                "success_count": sum(1 for r in results if r.success),
                "failure_count": sum(1 for r in results if not r.success),
                "results": [
                    {
                        "call_id": r.call_id,
                        "success": r.success,
                        "error": r.error,
                        "execution_time_ms": r.execution_time_ms,
                    }
                    for r in results
                ],
            }
            self.execution_history.append(execution_record)

            return {
                "success": all(r.success for r in results),
                "flow_id": context.flow_id,
                "flow_type": flow_type.value,
                "results": results,
                "summary": {
                    "total": len(results),
                    "success": sum(1 for r in results if r.success),
                    "failure": sum(1 for r in results if not r.success),
                },
            }

        except Exception as e:
            return {
                "success": False,
                "flow_id": context.flow_id,
                "flow_type": flow_type.value,
                "error": str(e),
                "results": [],
            }

    def get_execution_history(self) -> list[dict[str, Any]]:
        """获取执行历史"""
        return self.execution_history

    def clear_history(self):
        """清空执行历史"""
        self.execution_history = []
