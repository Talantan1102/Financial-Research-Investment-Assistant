"""
Unit tests for training/reward/ module.
"""

import pytest

from training.reward.parser import ToolCallParser, ParsedTrajectory, ParsedToolCall
from training.reward.rule_reward import RuleBasedReward
from training.reward.ground_truth_cache import GroundTruthCache


class TestToolCallParser:
    def test_parse_no_tool_calls(self):
        parser = ToolCallParser()
        result = parser.parse("这是最终回答。")
        assert result.turns == []
        assert result.final_answer == "这是最终回答。"
        assert result.tools_used == []

    def test_parse_single_tool_call(self):
        parser = ToolCallParser()
        text = (
            "让我查询股价。\n"
            '<tool_call>\n{"name": "market_data.get_quote", "arguments": {"ts_code": "600519.SH"}}\n</tool_call>\n'
            "当前股价是 1500 元。"
        )
        result = parser.parse(text)
        assert len(result.turns) == 1
        assert result.turns[0]["reasoning"] == "让我查询股价。"
        assert result.turns[0]["tool_call"].tool_name == "market_data.get_quote"
        assert result.turns[0]["tool_call"].parameters == {"ts_code": "600519.SH"}
        assert result.tools_used == ["market_data.get_quote"]
        assert "1500" in result.final_answer

    def test_parse_multiple_tool_calls(self):
        parser = ToolCallParser()
        text = (
            "第一步：查询行情\n"
            '<tool_call>\n{"name": "market_data.get_quote", "arguments": {"ts_code": "600519.SH"}}\n</tool_call>\n'
            "第二步：查询财务指标\n"
            '<tool_call>\n{"name": "financial_analysis.get_fina_indicator", "arguments": {"ts_code": "600519.SH"}}\n</tool_call>\n'
            "综上，贵州茅台..."
        )
        result = parser.parse(text)
        assert len(result.turns) == 2
        assert result.tools_used == [
            "market_data.get_quote",
            "financial_analysis.get_fina_indicator",
        ]

    def test_parse_with_name_attribute(self):
        parser = ToolCallParser()
        text = (
            '分析中...<tool_call name="market_data.get_quote">'
            '{"ts_code": "600519.SH"}'
            "</tool_call>\n"
            "答案是 1500。"
        )
        result = parser.parse(text)
        assert len(result.turns) == 1
        assert result.turns[0]["tool_call"].tool_name == "market_data.get_quote"


class TestRuleBasedReward:
    def test_efficiency_within_range(self):
        reward = RuleBasedReward()
        trajectory = {
            "turns": [{}, {}, {}],
            "tools_used": ["a", "b", "c"],
            "final_answer": "结论：...",
        }
        seed_tags = {
            "verifiable": False,
            "min_tools": 2,
            "max_tools": 5,
            "expected_turns": 3,
        }
        score = reward._calculate_efficiency(trajectory, seed_tags)
        assert score == 1.0

    def test_efficiency_too_few_tools(self):
        reward = RuleBasedReward()
        trajectory = {
            "turns": [{}],
            "tools_used": ["a"],
            "final_answer": "结论",
        }
        seed_tags = {
            "min_tools": 4,
            "max_tools": 8,
            "expected_turns": 3,
        }
        score = reward._calculate_efficiency(trajectory, seed_tags)
        assert 0.0 < score < 1.0

    def test_efficiency_too_many_turns(self):
        reward = RuleBasedReward()
        trajectory = {
            "turns": [{}, {}, {}, {}, {}, {}],
            "tools_used": ["a", "b", "c"],
            "final_answer": "结论",
        }
        seed_tags = {
            "min_tools": 2,
            "max_tools": 5,
            "expected_turns": 3,
        }
        score = reward._calculate_efficiency(trajectory, seed_tags)
        assert 0.5 <= score < 1.0

    def test_format_reward(self):
        reward = RuleBasedReward()
        trajectory = {
            "turns": [{"reasoning": "我分析了数据"}],
            "final_answer": "综上所述，答案是 1500。",
            "tools_used": ["a"],
        }
        score = reward._calculate_format(trajectory)
        assert score > 0.0

    def test_calculate_non_verifiable(self):
        reward = RuleBasedReward()
        trajectory = {
            "turns": [{"reasoning": "分析"}],
            "tools_used": ["a", "b"],
            "final_answer": "结论",
        }
        seed_tags = {
            "verifiable": False,
            "min_tools": 1,
            "max_tools": 5,
            "expected_turns": 2,
        }
        total = reward.calculate(trajectory, seed_tags)
        assert 0.0 <= total <= 1.0

    def test_accuracy_with_verifiable_fields(self):
        reward = RuleBasedReward()
        trajectory = {
            "turns": [],
            "tools_used": [],
            "final_answer": "roe: 25.5",
        }
        seed_tags = {
            "verifiable": True,
            "verifiable_fields": [
                {"field": "roe", "tolerance": 0.5, "weight": 1.0}
            ],
            "ground_truth": {"roe": 25.8},
        }
        score = reward._calculate_accuracy(trajectory, seed_tags)
        assert score == 1.0


class TestGroundTruthCache:
    def test_set_and_get(self, tmp_path):
        cache = GroundTruthCache(cache_dir=str(tmp_path / "gt_cache"))
        cache.set("600519.SH", "pe_ratio", 35.2)
        value = cache.get("600519.SH", "pe_ratio")
        assert value == 35.2

    def test_cache_miss(self, tmp_path):
        cache = GroundTruthCache(cache_dir=str(tmp_path / "gt_cache"))
        value = cache.get("000001.SZ", "roe")
        assert value is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
