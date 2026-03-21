"""MCP Server 单元测试"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock

from app.mcp_server.server import FinancialResearchMCPServer, get_mcp_server
from app.mcp_server.control_flow.engine import ControlFlowEngine, ControlFlowType, ToolCall
from app.mcp_server.error_handler import ErrorHandler, ErrorType, get_error_handler
from app.mcp_server.skills.base import ToolResult


class TestFinancialResearchMCPServer:
    """测试MCP Server"""

    @pytest.fixture
    def server(self):
        """创建Server实例"""
        return FinancialResearchMCPServer()

    def test_server_initialization(self, server):
        """测试Server初始化"""
        assert server is not None
        assert len(server.skill_instances) == 7
        assert server.control_flow_engine is not None
        assert "market_data" in server.skill_instances
        assert "financial_analysis" in server.skill_instances
        assert "sector_analysis" in server.skill_instances
        assert "risk_assessment" in server.skill_instances
        assert "deep_research" in server.skill_instances
        assert "web_research" in server.skill_instances
        assert "data_analysis" in server.skill_instances

    def test_get_available_skills(self, server):
        """测试获取可用Skills"""
        skills = server.get_available_skills()
        assert len(skills) == 7
        
        skill_names = [s["name"] for s in skills]
        assert "market_data" in skill_names
        assert "financial_analysis" in skill_names

    def test_get_tools_for_skills(self, server):
        """测试获取Skills的工具"""
        tools = server.get_tools_for_skills(["market_data", "financial_analysis"])
        assert "market_data" in tools
        assert "financial_analysis" in tools
        assert len(tools["market_data"]["tools"]) == 11
        assert len(tools["financial_analysis"]["tools"]) == 7

    @pytest.mark.asyncio
    async def test_execute_tools_parallel(self, server):
        """测试并行执行工具"""
        tool_calls = [
            {"skill": "market_data", "tool": "get_quote", "arguments": {"symbol": "600519"}, "call_id": "call_001"},
            {"skill": "market_data", "tool": "get_daily_basic", "arguments": {"symbol": "600519"}, "call_id": "call_002"},
        ]

        # Mock execute_tools以避免实际API调用
        with patch.object(server, '_execute_skill_tool', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {"success": True, "data": {"test": "data"}}
            
            result = await server.execute_tools(tool_calls, execution_mode="parallel")
            
            assert "success" in result
            assert "results" in result
            assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_execute_tools_sequential(self, server):
        """测试顺序执行工具"""
        tool_calls = [
            {"skill": "market_data", "tool": "get_quote", "arguments": {"symbol": "600519"}, "call_id": "call_001"},
        ]

        with patch.object(server, '_execute_skill_tool', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {"success": True, "data": {"test": "data"}}
            
            result = await server.execute_tools(tool_calls, execution_mode="sequential")
            
            assert result["success"] is True

    def test_get_server_info(self, server):
        """测试获取Server信息"""
        info = server.get_server_info()
        assert info["name"] == "金融研投助手 MCP Server"
        assert info["version"] == "2.0.0"
        assert len(info["skills"]) == 7
        assert info["total_tools"] == 43  # 11+7+7+5+3+4+6

    @pytest.mark.asyncio
    async def test_analyze_stock(self, server):
        """测试分析股票便捷方法"""
        with patch.object(server, 'execute_tools', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {"success": True, "results": []}
            
            result = await server.analyze_stock("600519", "comprehensive")
            
            assert result is not None
            mock_execute.assert_called_once()

    def test_skill_selection_prompt(self, server):
        """测试Skill选择Prompt生成"""
        prompt = server.get_skill_selection_prompt("分析茅台股票")
        assert "market_data" in prompt
        assert "financial_analysis" in prompt
        assert "分析茅台股票" in prompt

    def test_tool_execution_prompt(self, server):
        """测试工具执行Prompt生成"""
        prompt = server.get_tool_execution_prompt(
            "分析茅台",
            ["market_data", "financial_analysis"],
            {"name": "茅台", "symbol": "600519"}
        )
        assert "market_data" in prompt
        assert "600519" in prompt

    def test_response_generation_prompt(self, server):
        """测试回复生成Prompt"""
        prompt = server.get_response_generation_prompt(
            "分析茅台",
            {"market_data": {"quote": {}}},
            {"total_api_calls": 3, "success_count": 3}
        )
        assert "分析茅台" in prompt
        assert "行情概况" in prompt


class TestControlFlowEngine:
    """测试控制流引擎"""

    @pytest.fixture
    def mock_executor(self):
        """创建Mock执行器"""
        async def mock_skill_executor(skill, tool, arguments):
            return {"success": True, "data": {"test": "data"}}
        return mock_skill_executor

    @pytest.fixture
    def engine(self, mock_executor):
        """创建控制流引擎"""
        return ControlFlowEngine(mock_executor)

    @pytest.mark.asyncio
    async def test_sequential_execution(self, engine):
        """测试顺序执行"""
        config = {
            "calls": [
                {"skill": "market_data", "tool": "get_quote", "arguments": {"symbol": "600519"}},
            ]
        }
        
        result = await engine.execute(ControlFlowType.SEQUENTIAL, config)
        
        assert result["success"] is True
        assert result["flow_type"] == "sequential"

    @pytest.mark.asyncio
    async def test_for_each_execution(self, engine):
        """测试FOR-EACH执行"""
        config = {
            "items": ["600519", "000858", "600809"],
            "template": {
                "skill": "market_data",
                "tool": "get_quote",
                "arguments": {"symbol": "{item}"}
            },
            "parallel": True,
            "max_concurrent": 3
        }
        
        result = await engine.execute(ControlFlowType.FOR_EACH, config)
        
        assert result["success"] is True
        assert result["flow_type"] == "for_each"
        assert result["summary"]["total"] == 3

    @pytest.mark.asyncio
    async def test_unknown_flow_type(self, engine):
        """测试未知控制流类型"""
        result = await engine.execute("unknown_type", {})
        
        assert result["success"] is False
        assert "Unknown control flow type" in result["error"]

    def test_execution_history(self, engine):
        """测试执行历史"""
        history = engine.get_execution_history()
        assert isinstance(history, list)


class TestErrorHandler:
    """测试错误处理器"""

    @pytest.fixture
    def handler(self):
        """创建错误处理器"""
        return ErrorHandler()

    def test_classify_rate_limit_error(self, handler):
        """测试限流错误分类"""
        error = Exception("API rate limit exceeded. Please try again later.")
        error_info = handler.handle_error(error, "market_data.get_quote")
        
        assert error_info.error_type == ErrorType.RATE_LIMIT
        assert error_info.error_code == "TUSHARE_RATE_LIMIT"
        assert error_info.retry_after_seconds == 60
        assert error_info.is_critical is True

    def test_classify_network_error(self, handler):
        """测试网络错误分类"""
        error = Exception("Network timeout while connecting to API")
        error_info = handler.handle_error(error, "market_data.get_quote")
        
        assert error_info.error_type == ErrorType.NETWORK_ERROR
        assert error_info.is_critical is True

    def test_classify_validation_error(self, handler):
        """测试参数错误分类"""
        error = Exception("Invalid parameter: symbol is required")
        error_info = handler.handle_error(error, "market_data.get_quote")
        
        assert error_info.error_type == ErrorType.VALIDATION_ERROR
        assert error_info.error_code == "INVALID_PARAMETER"

    def test_should_stop_execution(self, handler):
        """测试是否应停止执行"""
        # 关键错误应停止
        critical_error = handler.handle_error(Exception("rate limit"), "financial.calculate_ratios")
        assert handler.should_stop_execution(critical_error) is True

    def test_generate_user_options(self, handler):
        """测试生成用户选项"""
        error = Exception("rate limit")
        error_info = handler.handle_error(error, "market_data.get_quote")
        options = handler.generate_user_options(error_info)
        
        assert len(options) > 0
        option_actions = [opt.action for opt in options]
        assert "retry" in option_actions
        assert "abort" in option_actions

    def test_format_error_response(self, handler):
        """测试格式化错误响应"""
        error = Exception("rate limit")
        error_info = handler.handle_error(error, "market_data.get_quote")
        response = handler.format_error_response(error_info)
        
        assert response["status"] == "ERROR"
        assert "error" in response
        assert "user_options" in response

    def test_critical_data_check(self, handler):
        """测试关键数据检查"""
        assert handler.is_critical_data_missing("roe") is True
        assert handler.is_critical_data_missing("gross_margin") is True
        assert handler.is_critical_data_missing("some_other_data") is False


class TestSkills:
    """测试Skills"""

    def test_market_data_skill_tools(self):
        """测试MarketDataSkill工具数量"""
        from app.mcp_server.skills.market_data import MarketDataSkill
        skill = MarketDataSkill()
        assert skill.tool_count == 11
        assert skill.has_tool("get_quote")
        assert skill.has_tool("get_daily_basic")

    def test_financial_analysis_skill_tools(self):
        """测试FinancialAnalysisSkill工具数量"""
        from app.mcp_server.skills.financial_analysis import FinancialAnalysisSkill
        skill = FinancialAnalysisSkill()
        assert skill.tool_count == 7
        assert skill.has_tool("calculate_financial_ratios")
        assert skill.has_tool("get_fina_indicator")

    def test_sector_analysis_skill_tools(self):
        """测试SectorAnalysisSkill工具数量"""
        from app.mcp_server.skills.sector_analysis import SectorAnalysisSkill
        skill = SectorAnalysisSkill()
        assert skill.tool_count == 7
        assert skill.has_tool("get_industry_list")
        assert skill.has_tool("get_industry_leaders")

    def test_risk_assessment_skill_tools(self):
        """测试RiskAssessmentSkill工具数量"""
        from app.mcp_server.skills.risk_assessment import RiskAssessmentSkill
        skill = RiskAssessmentSkill()
        assert skill.tool_count == 5
        assert skill.has_tool("assess_stock_risk")
        assert skill.has_tool("assess_valuation_risk")

    def test_deep_research_skill_tools(self):
        """测试DeepResearchSkill工具数量"""
        from app.mcp_server.skills.deep_research import DeepResearchSkill
        skill = DeepResearchSkill()
        assert skill.tool_count == 3
        assert skill.has_tool("generate_stock_report")

    def test_web_research_skill_tools(self):
        """测试WebResearchSkill工具数量"""
        from app.mcp_server.skills.web_research import WebResearchSkill
        skill = WebResearchSkill()
        assert skill.tool_count == 4
        assert skill.has_tool("search_stock_news")

    def test_data_analysis_skill_tools(self):
        """测试DataAnalysisSkill工具数量"""
        from app.mcp_server.skills.data_analysis import DataAnalysisSkill
        skill = DataAnalysisSkill()
        assert skill.tool_count == 6
        assert skill.has_tool("calculate_statistics")


class TestToolResult:
    """测试ToolResult"""

    def test_tool_result_success(self):
        """测试成功结果"""
        result = ToolResult(success=True, data={"key": "value"})
        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.error is None

    def test_tool_result_failure(self):
        """测试失败结果"""
        result = ToolResult(success=False, error="Something went wrong")
        assert result.success is False
        assert result.data is None
        assert result.error == "Something went wrong"

    def test_tool_result_to_dict(self):
        """测试转换为字典"""
        result = ToolResult(success=True, data={"key": "value"})
        d = result.to_dict()
        assert d["success"] is True
        assert d["data"] == {"key": "value"}


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
