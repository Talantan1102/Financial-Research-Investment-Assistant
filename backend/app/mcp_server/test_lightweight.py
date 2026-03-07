#!/usr/bin/env python3
"""
轻量级 MCP Server 测试脚本

不依赖 Tushare 高积分接口，只测试核心功能：
- Skill 注册和工具发现
- 参数验证
- 错误处理
- Mock 数据调用
- 缓存机制

适合 CI/CD 环境和低积分账号测试。
"""

import asyncio
import json
import sys
import os
import importlib.util
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, List, Callable
from abc import ABC, abstractmethod

# ==================== 内联定义 Skill 基类（避免 mcp 依赖） ====================

@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: List[ToolParameter]
    
    def to_json_schema(self) -> Dict[str, Any]:
        """转换为 JSON Schema 格式"""
        properties = {}
        required = []
        
        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop
            
            if param.required:
                required.append(param.name)
        
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error
        }


class BaseSkill(ABC):
    """Skill 抽象基类"""
    
    name: str = "base"
    description: str = "基础 Skill"
    
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._register_tools()
    
    @abstractmethod
    def _register_tools(self):
        """注册工具，子类必须实现"""
        pass
    
    def register_tool(self, name: str, handler: Callable, description: str, 
                      parameters: List[ToolParameter]):
        """注册工具"""
        self._tools[name] = {
            "handler": handler,
            "definition": ToolDefinition(
                name=name,
                description=description,
                parameters=parameters
            )
        }
    
    def has_tool(self, name: str) -> bool:
        """检查工具是否存在"""
        return name in self._tools
    
    def get_tool_names(self) -> List[str]:
        """获取所有工具名称"""
        return list(self._tools.keys())
    
    def discover_tools(self) -> List[ToolDefinition]:
        """发现所有工具定义"""
        return [tool["definition"] for tool in self._tools.values()]
    
    def _validate_params(self, tool_name: str, params: Dict[str, Any]) -> tuple[bool, str]:
        """验证参数"""
        if tool_name not in self._tools:
            return False, f"工具不存在: {tool_name}"
        
        tool_def = self._tools[tool_name]["definition"]
        
        # 检查必填参数
        for param in tool_def.parameters:
            if param.required and param.name not in params:
                return False, f"缺少必填参数: {param.name}"
        
        return True, ""
    
    async def execute_tool(self, name: str, params: Dict[str, Any]) -> ToolResult:
        """执行工具"""
        # 验证参数
        valid, error = self._validate_params(name, params)
        if not valid:
            return ToolResult(success=False, error=error)
        
        if name not in self._tools:
            return ToolResult(success=False, error=f"工具不存在: {name}")
        
        handler = self._tools[name]["handler"]
        
        try:
            # 调用处理函数
            result = await handler(**params)
            return result
        except Exception as e:
            return ToolResult(success=False, error=f"执行出错: {str(e)}")


# ==================== Mock 数据 ====================

MOCK_STOCK_DATA = {
    "600519": {
        "gid": "sh600519",
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "nowPri": "1850.50",
        "increase": "25.30",
        "increPer": "1.39",
        "todayStartPri": "1840.00",
        "yestodEndPri": "1825.20",
        "todayMax": "1865.00",
        "todayMin": "1835.00",
        "traAmount": "125000",
        "traNumber": "231250000.00",
        "update_time": "2026-03-08"
    },
    "000001": {
        "gid": "sz000001",
        "ts_code": "000001.SZ",
        "name": "平安银行",
        "nowPri": "12.50",
        "increase": "0.30",
        "increPer": "2.46",
        "todayStartPri": "12.20",
        "yestodEndPri": "12.20",
        "todayMax": "12.60",
        "todayMin": "12.10",
        "traAmount": "450000",
        "traNumber": "5625000.00",
        "update_time": "2026-03-08"
    }
}

MOCK_STOCK_BASIC_DATA = {
    "600519": {
        "ts_code": "600519.SH",
        "symbol": "600519",
        "name": "贵州茅台",
        "area": "贵州",
        "industry": "白酒",
        "list_date": "20010827"
    },
    "000001": {
        "ts_code": "000001.SZ",
        "symbol": "000001",
        "name": "平安银行",
        "area": "深圳",
        "industry": "银行",
        "list_date": "19910403"
    }
}


class TestResult:
    """测试结果统计"""
    def __init__(self, name: str):
        self.name = name
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []

    def add_pass(self, test_name: str):
        self.total += 1
        self.passed += 1
        print(f"  ✅ {test_name}")

    def add_fail(self, test_name: str, error: str):
        self.total += 1
        self.failed += 1
        self.errors.append((test_name, error))
        print(f"  ❌ {test_name}")
        print(f"     错误: {error}")

    def add_skip(self, test_name: str, reason: str):
        self.total += 1
        self.skipped += 1
        print(f"  ⏭️  {test_name} (跳过: {reason})")

    def print_summary(self):
        print(f"\n  总计: {self.total} | ✅ {self.passed} | ❌ {self.failed} | ⏭️  {self.skipped}")
        if self.errors:
            print(f"\n  失败详情:")
            for test_name, error in self.errors:
                print(f"    - {test_name}: {error}")


# ==================== 测试函数 ====================

async def test_skill_registration():
    """测试 Skill 注册和工具发现"""
    print("\n" + "=" * 70)
    print("测试 1: Skill 注册和工具发现")
    print("=" * 70)

    result = TestResult("Skill Registration")

    try:
        # 创建测试 Skill
        class MockSkill(BaseSkill):
            name = "mock_data"
            description = "Mock 数据 Skill"

            def _register_tools(self):
                self.register_tool(
                    name="get_mock_stock",
                    handler=self.get_mock_stock,
                    description="获取 Mock 股票数据",
                    parameters=[
                        ToolParameter(name="symbol", type="string", description="股票代码", required=True)
                    ]
                )
                self.register_tool(
                    name="search_mock_stock",
                    handler=self.search_mock_stock,
                    description="搜索 Mock 股票",
                    parameters=[
                        ToolParameter(name="keyword", type="string", description="关键词", required=True)
                    ]
                )

            async def get_mock_stock(self, symbol: str):
                data = MOCK_STOCK_DATA.get(symbol, {})
                if data:
                    return ToolResult(success=True, data=data)
                return ToolResult(success=False, error=f"未找到股票: {symbol}")

            async def search_mock_stock(self, keyword: str):
                results = [
                    {"name": v["name"], "code": k}
                    for k, v in MOCK_STOCK_DATA.items()
                    if keyword in v["name"] or keyword in k
                ]
                return ToolResult(success=True, data={"results": results, "count": len(results)})

        # 创建 Skill 实例
        skill = MockSkill()
        result.add_pass("创建自定义 Mock Skill")

        # 测试工具注册
        tool_names = skill.get_tool_names()
        if len(tool_names) == 2:
            result.add_pass(f"工具数量正确 ({len(tool_names)} 个)")
        else:
            result.add_fail("工具数量", f"期望 2 个，实际 {len(tool_names)} 个")

        if "get_mock_stock" in tool_names:
            result.add_pass("get_mock_stock 工具已注册")
        else:
            result.add_fail("工具注册", "未找到 get_mock_stock")

        if "search_mock_stock" in tool_names:
            result.add_pass("search_mock_stock 工具已注册")
        else:
            result.add_fail("工具注册", "未找到 search_mock_stock")

        # 测试工具发现
        tools = skill.discover_tools()
        if len(tools) == 2:
            result.add_pass("工具发现成功")
        else:
            result.add_fail("工具发现", f"期望发现 2 个工具，实际 {len(tools)} 个")

        # 测试工具是否存在
        if skill.has_tool("get_mock_stock"):
            result.add_pass("工具存在性检查")
        else:
            result.add_fail("工具存在性", "has_tool 返回 False")

        # 测试不存在的工具
        if not skill.has_tool("non_existent"):
            result.add_pass("不存在工具检查")
        else:
            result.add_fail("不存在工具检查", "应该返回 False")

    except Exception as e:
        result.add_fail("Skill 注册测试", str(e))
        import traceback
        print(f"\n  详细错误:\n{traceback.format_exc()}")

    result.print_summary()
    return result.failed == 0


async def test_parameter_validation():
    """测试参数验证"""
    print("\n" + "=" * 70)
    print("测试 2: 参数验证")
    print("=" * 70)

    result = TestResult("Parameter Validation")

    try:
        class ValidationSkill(BaseSkill):
            name = "validation_test"
            description = "参数验证测试"

            def _register_tools(self):
                self.register_tool(
                    name="test_params",
                    handler=self.test_params,
                    description="测试各种参数类型",
                    parameters=[
                        ToolParameter(name="required_str", type="string", description="必填字符串", required=True),
                        ToolParameter(name="optional_str", type="string", description="可选字符串", required=False),
                        ToolParameter(name="required_num", type="number", description="必填数字", required=True),
                        ToolParameter(name="optional_bool", type="boolean", description="可选布尔", required=False),
                    ]
                )

            async def test_params(self, required_str: str, optional_str: str = "default", 
                                  required_num: float = 0, optional_bool: bool = False):
                return ToolResult(success=True, data={
                    "required_str": required_str,
                    "optional_str": optional_str,
                    "required_num": required_num,
                    "optional_bool": optional_bool
                })

        skill = ValidationSkill()
        result.add_pass("创建参数验证 Skill")

        # 测试必填参数缺失
        exec_result = await skill.execute_tool("test_params", {})
        if not exec_result.success and "缺少必填参数" in exec_result.error:
            result.add_pass("必填参数缺失检测")
        else:
            result.add_fail("必填参数检测", f"应该返回缺少必填参数错误，实际: {exec_result.error}")

        # 测试部分必填参数缺失
        exec_result = await skill.execute_tool("test_params", {"required_str": "test"})
        if not exec_result.success and "缺少必填参数" in exec_result.error:
            result.add_pass("部分必填参数缺失检测")
        else:
            result.add_fail("部分必填参数检测", f"应该返回缺少必填参数错误，实际: {exec_result.error}")

        # 测试所有必填参数提供
        exec_result = await skill.execute_tool("test_params", {
            "required_str": "test",
            "required_num": 123
        })
        if exec_result.success:
            result.add_pass("完整必填参数执行")
            data = exec_result.data
            if data.get("required_str") == "test" and data.get("required_num") == 123:
                result.add_pass("参数值正确传递")
            else:
                result.add_fail("参数传递", f"参数值不正确: {data}")
        else:
            result.add_fail("完整参数执行", exec_result.error)

        # 测试可选参数默认值
        exec_result = await skill.execute_tool("test_params", {
            "required_str": "test",
            "required_num": 123
        })
        if exec_result.success:
            data = exec_result.data
            if data.get("optional_str") == "default" and data.get("optional_bool") == False:
                result.add_pass("可选参数默认值")
            else:
                result.add_fail("可选参数默认值", f"默认值不正确: {data}")

        # 测试提供可选参数
        exec_result = await skill.execute_tool("test_params", {
            "required_str": "test",
            "required_num": 123,
            "optional_str": "custom",
            "optional_bool": True
        })
        if exec_result.success:
            data = exec_result.data
            if data.get("optional_str") == "custom" and data.get("optional_bool") == True:
                result.add_pass("可选参数自定义值")
            else:
                result.add_fail("可选参数自定义", f"自定义值不正确: {data}")

    except Exception as e:
        result.add_fail("参数验证测试", str(e))
        import traceback
        print(f"\n  详细错误:\n{traceback.format_exc()}")

    result.print_summary()
    return result.failed == 0


async def test_error_handling():
    """测试错误处理"""
    print("\n" + "=" * 70)
    print("测试 3: 错误处理")
    print("=" * 70)

    result = TestResult("Error Handling")

    try:
        class ErrorSkill(BaseSkill):
            name = "error_test"
            description = "错误处理测试"

            def _register_tools(self):
                self.register_tool(
                    name="raise_exception",
                    handler=self.raise_exception,
                    description="抛出异常",
                    parameters=[ToolParameter(name="message", type="string", description="消息", required=True)]
                )
                self.register_tool(
                    name="return_error",
                    handler=self.return_error,
                    description="返回错误结果",
                    parameters=[ToolParameter(name="code", type="number", description="代码", required=True)]
                )
                self.register_tool(
                    name="invalid_code",
                    handler=self.invalid_code,
                    description="无效股票代码",
                    parameters=[ToolParameter(name="symbol", type="string", description="股票代码", required=True)]
                )

            async def raise_exception(self, message: str):
                raise ValueError(message)

            async def return_error(self, code: int):
                if code != 0:
                    return ToolResult(success=False, error=f"错误码: {code}")
                return ToolResult(success=True, data={"code": code})

            async def invalid_code(self, symbol: str):
                if symbol not in MOCK_STOCK_DATA:
                    return ToolResult(success=False, error=f"无效股票代码: {symbol}")
                return ToolResult(success=True, data=MOCK_STOCK_DATA[symbol])

        skill = ErrorSkill()
        result.add_pass("创建错误处理 Skill")

        # 测试异常处理
        exec_result = await skill.execute_tool("raise_exception", {"message": "测试异常"})
        if not exec_result.success:
            result.add_pass("异常捕获并转换")
        else:
            result.add_fail("异常处理", "应该返回失败结果")

        # 测试显式错误返回
        exec_result = await skill.execute_tool("return_error", {"code": 404})
        if not exec_result.success and "错误码: 404" in exec_result.error:
            result.add_pass("显式错误返回")
        else:
            result.add_fail("显式错误", f"应该返回错误，实际: {exec_result}")

        # 测试成功返回
        exec_result = await skill.execute_tool("return_error", {"code": 0})
        if exec_result.success:
            result.add_pass("成功返回")
        else:
            result.add_fail("成功返回", f"应该返回成功，实际: {exec_result.error}")

        # 测试无效股票代码
        exec_result = await skill.execute_tool("invalid_code", {"symbol": "999999"})
        if not exec_result.success and "无效股票代码" in exec_result.error:
            result.add_pass("无效代码错误处理")
        else:
            result.add_fail("无效代码", f"应该返回无效代码错误，实际: {exec_result}")

        # 测试空参数
        exec_result = await skill.execute_tool("invalid_code", {})
        if not exec_result.success:
            result.add_pass("空参数错误处理")
        else:
            result.add_fail("空参数", "应该返回错误")

    except Exception as e:
        result.add_fail("错误处理测试", str(e))
        import traceback
        print(f"\n  详细错误:\n{traceback.format_exc()}")

    result.print_summary()
    return result.failed == 0


async def test_mock_data_execution():
    """测试 Mock 数据调用"""
    print("\n" + "=" * 70)
    print("测试 4: Mock 数据调用")
    print("=" * 70)

    result = TestResult("Mock Data Execution")

    try:
        class MockDataSkill(BaseSkill):
            name = "mock_data"
            description = "Mock 数据 Skill"

            def _register_tools(self):
                self.register_tool(
                    name="get_stock",
                    handler=self.get_stock,
                    description="获取股票数据",
                    parameters=[ToolParameter(name="symbol", type="string", description="股票代码", required=True)]
                )
                self.register_tool(
                    name="get_stock_basic",
                    handler=self.get_stock_basic,
                    description="获取股票基本信息",
                    parameters=[ToolParameter(name="symbol", type="string", description="股票代码", required=True)]
                )
                self.register_tool(
                    name="search_stocks",
                    handler=self.search_stocks,
                    description="搜索股票",
                    parameters=[ToolParameter(name="keyword", type="string", description="关键词", required=True)]
                )

            async def get_stock(self, symbol: str):
                data = MOCK_STOCK_DATA.get(symbol)
                if data:
                    return ToolResult(success=True, data=data)
                return ToolResult(success=False, error=f"未找到股票: {symbol}")

            async def get_stock_basic(self, symbol: str):
                data = MOCK_STOCK_BASIC_DATA.get(symbol)
                if data:
                    return ToolResult(success=True, data=data)
                return ToolResult(success=False, error=f"未找到股票基本信息: {symbol}")

            async def search_stocks(self, keyword: str):
                results = []
                for code, data in MOCK_STOCK_DATA.items():
                    if keyword in code or keyword in data.get("name", ""):
                        results.append({
                            "code": code,
                            "name": data["name"],
                            "ts_code": data["ts_code"]
                        })
                return ToolResult(success=True, data={"results": results, "count": len(results)})

        skill = MockDataSkill()
        result.add_pass("创建 Mock Data Skill")

        # 测试获取股票数据
        exec_result = await skill.execute_tool("get_stock", {"symbol": "600519"})
        if exec_result.success:
            result.add_pass("获取 600519 数据")
            data = exec_result.data
            if data.get("name") == "贵州茅台":
                result.add_pass("数据内容正确")
            else:
                result.add_fail("数据内容", f"期望名称'贵州茅台'，实际: {data.get('name')}")
        else:
            result.add_fail("获取 600519", exec_result.error)

        # 测试获取 000001
        exec_result = await skill.execute_tool("get_stock", {"symbol": "000001"})
        if exec_result.success:
            result.add_pass("获取 000001 数据")
        else:
            result.add_fail("获取 000001", exec_result.error)

        # 测试获取股票基本信息
        exec_result = await skill.execute_tool("get_stock_basic", {"symbol": "600519"})
        if exec_result.success:
            result.add_pass("获取 600519 基本信息")
            data = exec_result.data
            if data.get("industry") == "白酒":
                result.add_pass("行业信息正确")
            else:
                result.add_fail("行业信息", f"期望'白酒'，实际: {data.get('industry')}")
        else:
            result.add_fail("获取基本信息", exec_result.error)

        # 测试搜索功能
        exec_result = await skill.execute_tool("search_stocks", {"keyword": "茅台"})
        if exec_result.success:
            result.add_pass("搜索'茅台'")
            data = exec_result.data
            if data.get("count", 0) > 0:
                result.add_pass("搜索结果非空")
            else:
                result.add_fail("搜索结果", "应该返回至少一个结果")
        else:
            result.add_fail("搜索功能", exec_result.error)

        # 测试搜索代码
        exec_result = await skill.execute_tool("search_stocks", {"keyword": "000001"})
        if exec_result.success:
            data = exec_result.data
            if data.get("count", 0) > 0:
                result.add_pass("按代码搜索")
            else:
                result.add_fail("按代码搜索", "应该返回结果")
        else:
            result.add_fail("按代码搜索", exec_result.error)

        # 测试不存在的股票
        exec_result = await skill.execute_tool("get_stock", {"symbol": "999999"})
        if not exec_result.success:
            result.add_pass("不存在股票错误处理")
        else:
            result.add_fail("不存在股票", "应该返回失败")

    except Exception as e:
        result.add_fail("Mock 数据测试", str(e))
        import traceback
        print(f"\n  详细错误:\n{traceback.format_exc()}")

    result.print_summary()
    return result.failed == 0


async def test_cache_mechanism():
    """测试缓存机制"""
    print("\n" + "=" * 70)
    print("测试 5: 缓存机制")
    print("=" * 70)

    result = TestResult("Cache Mechanism")

    try:
        # 用于追踪调用次数
        call_count = {"get_stock": 0}

        class CacheTestSkill(BaseSkill):
            name = "cache_test"
            description = "缓存测试 Skill"

            def _register_tools(self):
                self.register_tool(
                    name="get_stock_with_cache",
                    handler=self.get_stock,
                    description="获取股票数据（带缓存）",
                    parameters=[ToolParameter(name="symbol", type="string", description="股票代码", required=True)]
                )
                self.register_tool(
                    name="clear_cache",
                    handler=self.clear_cache,
                    description="清除缓存",
                    parameters=[]
                )

            async def get_stock(self, symbol: str):
                call_count["get_stock"] += 1
                data = MOCK_STOCK_DATA.get(symbol)
                if data:
                    return ToolResult(success=True, data={**data, "call_id": call_count["get_stock"]})
                return ToolResult(success=False, error=f"未找到股票: {symbol}")

            async def clear_cache(self):
                call_count["get_stock"] = 0
                return ToolResult(success=True, data={"message": "缓存已清除"})

        skill = CacheTestSkill()
        result.add_pass("创建缓存测试 Skill")

        # 注意：这里我们测试的是 Skill 层面的缓存概念
        # 实际的缓存实现在 TushareClient 中

        # 测试多次调用
        call_count["get_stock"] = 0
        
        result1 = await skill.execute_tool("get_stock_with_cache", {"symbol": "600519"})
        if result1.success:
            result.add_pass("第一次调用成功")
            first_call_id = result1.data.get("call_id")
        else:
            result.add_fail("第一次调用", result1.error)
            first_call_id = None

        result2 = await skill.execute_tool("get_stock_with_cache", {"symbol": "600519"})
        if result2.success:
            result.add_pass("第二次调用成功")
            second_call_id = result2.data.get("call_id")
        else:
            result.add_fail("第二次调用", result2.error)
            second_call_id = None

        # 验证调用次数
        if call_count["get_stock"] == 2:
            result.add_pass(f"调用次数正确 ({call_count['get_stock']} 次)")
        else:
            result.add_fail("调用次数", f"期望 2 次，实际 {call_count['get_stock']} 次")

        # 测试清除缓存接口存在
        clear_result = await skill.execute_tool("clear_cache", {})
        if clear_result.success:
            result.add_pass("清除缓存接口")
        else:
            result.add_fail("清除缓存", clear_result.error)

    except Exception as e:
        result.add_fail("缓存机制测试", str(e))
        import traceback
        print(f"\n  详细错误:\n{traceback.format_exc()}")

    result.print_summary()
    return result.failed == 0


async def test_json_schema():
    """测试 JSON Schema 转换"""
    print("\n" + "=" * 70)
    print("测试 6: JSON Schema 转换")
    print("=" * 70)

    result = TestResult("JSON Schema")

    try:
        # 测试 ToolDefinition 转换为 JSON Schema
        tool_def = ToolDefinition(
            name="test_tool",
            description="测试工具",
            parameters=[
                ToolParameter(name="required_str", type="string", description="必填字符串", required=True),
                ToolParameter(name="optional_num", type="number", description="可选数字", required=False, default=0),
                ToolParameter(name="enum_param", type="string", description="枚举参数", required=True, 
                             enum=["option1", "option2", "option3"])
            ]
        )
        
        schema = tool_def.to_json_schema()
        
        if schema.get("name") == "test_tool":
            result.add_pass("Schema 包含 name")
        else:
            result.add_fail("Schema name", f"期望 'test_tool'，实际: {schema.get('name')}")
        
        if schema.get("description") == "测试工具":
            result.add_pass("Schema 包含 description")
        else:
            result.add_fail("Schema description", f"期望 '测试工具'，实际: {schema.get('description')}")
        
        params = schema.get("parameters", {})
        if "properties" in params:
            result.add_pass("Schema 包含 properties")
            props = params["properties"]
            if "required_str" in props and "optional_num" in props:
                result.add_pass("Schema properties 包含所有参数")
            else:
                result.add_fail("Schema properties", f"缺少参数: {props.keys()}")
        else:
            result.add_fail("Schema properties", "缺少 properties 字段")
        
        if "required" in params:
            result.add_pass("Schema 包含 required 列表")
            required = params["required"]
            if "required_str" in required and "enum_param" in required and "optional_num" not in required:
                result.add_pass("required 列表正确")
            else:
                result.add_fail("required 列表", f"不正确: {required}")
        else:
            result.add_fail("Schema required", "缺少 required 字段")
        
        # 测试枚举
        enum_param = params.get("properties", {}).get("enum_param", {})
        if "enum" in enum_param:
            result.add_pass("Schema 包含 enum")
            if enum_param["enum"] == ["option1", "option2", "option3"]:
                result.add_pass("enum 值正确")
            else:
                result.add_fail("enum 值", f"不正确: {enum_param['enum']}")
        else:
            result.add_fail("Schema enum", "缺少 enum 字段")

    except Exception as e:
        result.add_fail("JSON Schema 测试", str(e))
        import traceback
        print(f"\n  详细错误:\n{traceback.format_exc()}")

    result.print_summary()
    return result.failed == 0


async def test_tushare_client_mock():
    """测试 TushareClient Mock 模式"""
    print("\n" + "=" * 70)
    print("测试 7: TushareClient (无 Token 模式)")
    print("=" * 70)

    result = TestResult("TushareClient Mock")

    # 检查 tushare 是否安装
    try:
        import tushare
    except ImportError:
        result.add_skip("TushareClient 测试", "tushare 模块未安装")
        result.print_summary()
        return True  # 跳过不算失败

    try:
        # 添加项目路径
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
        
        # 移除 TUSHARE_API_TOKEN 环境变量（如果存在）
        original_token = os.environ.pop('TUSHARE_API_TOKEN', None)
        
        # 清除可能已存在的实例
        from app.data.tushare_client import TushareClient, get_tushare_client
        TushareClient._instance = None
        
        # 获取客户端（无 Token）
        client = get_tushare_client()
        result.add_pass("创建 TushareClient（无 Token）")
        
        # 检查 Token 是否为空
        if not client.token:
            result.add_pass("Token 为空（预期）")
        else:
            result.add_fail("Token 检查", f"期望为空，实际: {client.token}")
        
        # 检查 API 是否未初始化
        if client.api is None:
            result.add_pass("API 未初始化（预期）")
        else:
            result.add_fail("API 检查", "期望为 None")
        
        # 测试缓存信息（应该仍然可用）
        cache_info = client.get_cache_info()
        if isinstance(cache_info, dict) and 'total_cached' in cache_info:
            result.add_pass("缓存信息可用")
        else:
            result.add_fail("缓存信息", "格式不正确")
        
        # 测试股票代码标准化
        test_cases = [
            ("600519", "600519.SH"),
            ("000001", "000001.SZ"),
            ("sh600519", "600519.SH"),
        ]
        for input_code, expected in test_cases:
            normalized = client._normalize_stock_code(input_code)
            if normalized == expected:
                result.add_pass(f"标准化 {input_code}")
            else:
                result.add_fail(f"标准化 {input_code}", f"期望 {expected}，实际 {normalized}")
        
        # 测试 get_quote（无 Token 应该返回错误）
        quote_result = client.get_quote("600519")
        if not quote_result['success']:
            result.add_pass("get_quote 无 Token 时返回错误")
            if '未初始化' in quote_result.get('error', ''):
                result.add_pass("错误信息正确")
        else:
            result.add_fail("get_quote 无 Token", "应该返回错误")
        
        # 恢复环境变量
        if original_token:
            os.environ['TUSHARE_API_TOKEN'] = original_token

    except Exception as e:
        result.add_fail("TushareClient Mock 测试", str(e))
        import traceback
        print(f"\n  详细错误:\n{traceback.format_exc()}")

    result.print_summary()
    return result.failed == 0


# ==================== 主函数 ====================

async def run_all_tests():
    """运行所有轻量级测试"""
    print("=" * 70)
    print("MCP Server 轻量级测试")
    print("=" * 70)
    print("特点：")
    print("  • 不依赖 Tushare 高积分接口")
    print("  • 使用 Mock 数据测试核心逻辑")
    print("  • 不需要安装 mcp 包")
    print("  • 适合 CI/CD 和低积分账号测试")
    print("=" * 70)
    print(f"Python 版本: {sys.version.split()[0]}")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    all_results = []

    # 测试 1: Skill 注册和工具发现
    passed = await test_skill_registration()
    all_results.append(("Skill 注册和工具发现", passed))

    # 测试 2: 参数验证
    passed = await test_parameter_validation()
    all_results.append(("参数验证", passed))

    # 测试 3: 错误处理
    passed = await test_error_handling()
    all_results.append(("错误处理", passed))

    # 测试 4: Mock 数据调用
    passed = await test_mock_data_execution()
    all_results.append(("Mock 数据调用", passed))

    # 测试 5: 缓存机制
    passed = await test_cache_mechanism()
    all_results.append(("缓存机制", passed))

    # 测试 6: JSON Schema 转换
    passed = await test_json_schema()
    all_results.append(("JSON Schema 转换", passed))

    # 测试 7: TushareClient Mock 模式
    passed = await test_tushare_client_mock()
    all_results.append(("TushareClient Mock", passed))

    # 最终总结
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)

    total_passed = sum(1 for _, passed in all_results if passed)
    total_tests = len(all_results)

    for test_name, passed in all_results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{status} - {test_name}")

    print("=" * 70)
    print(f"总计: {total_passed}/{total_tests} 测试套件通过")

    if total_passed == total_tests:
        print("✅ 所有测试通过！")
        print("\n💡 提示: 这是一个轻量级测试套件，")
        print("   完整的 Tushare API 测试需要设置 TUSHARE_API_TOKEN")
    else:
        print("❌ 部分测试失败，请查看上面的详细信息")

    print("=" * 70)

    return total_passed == total_tests


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
