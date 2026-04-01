"""
Parse model-generated tool calls from response text.

Supports Qwen3-style `<tool_call>` XML tags and fallback regex patterns.
"""

import json
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class ParsedToolCall:
    tool_name: str
    parameters: Dict[str, Any]


@dataclass
class ParsedTrajectory:
    turns: List[Dict[str, Any]]
    final_answer: str
    tools_used: List[str]


class ToolCallParser:
    """Parse tool calls from model-generated text."""

    def __init__(self):
        # XML-style tool call patterns
        self.tool_call_patterns = [
            # <tool_call> {"name": "xxx", "arguments": {...}} </tool_call>
            re.compile(
                r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
                re.DOTALL
            ),
            # <tool_call name="xxx"> {"arg": "val"} </tool_call>
            re.compile(
                r'<tool_call\s+name=["\']([^"\']+)["\']>\s*(.*?)\s*</tool_call>',
                re.DOTALL
            ),
            # Fallback: ```json {"name": "xxx", ...} ```
            re.compile(
                r'```(?:json)?\s*\n?(\{[\s\S]*?"name"[\s\S]*?\})\s*```',
                re.DOTALL
            ),
        ]

    def parse(self, text: str) -> ParsedTrajectory:
        """
        Parse a complete model response into trajectory segments.

        Strategy:
        1. Split text by tool call tags.
        2. Each segment before a tool call is "reasoning".
        3. Each tool call block is parsed into a tool call.
        4. Text after the last tool call is the final answer.
        """
        text = text.strip()
        if not text:
            return ParsedTrajectory(turns=[], final_answer="", tools_used=[])

        turns: List[Dict[str, Any]] = []
        tools_used: List[str] = []

        # Find all tool call occurrences
        tool_calls = self._extract_all_tool_calls(text)

        if not tool_calls:
            # No tool calls, entire text is final answer
            return ParsedTrajectory(turns=[], final_answer=text, tools_used=[])

        # Split text by tool call positions
        segments = []
        last_end = 0
        for tc, start, end in tool_calls:
            reasoning = text[last_end:start].strip()
            segments.append(("reasoning", reasoning))
            segments.append(("tool_call", tc))
            last_end = end

        final_answer = text[last_end:].strip()

        # Group into turns
        current_reasoning = ""
        for seg_type, seg_content in segments:
            if seg_type == "reasoning":
                current_reasoning += "\n" + seg_content if current_reasoning else seg_content
            elif seg_type == "tool_call":
                turns.append({
                    "reasoning": current_reasoning.strip(),
                    "tool_call": seg_content,
                })
                tools_used.append(seg_content.tool_name)
                current_reasoning = ""

        return ParsedTrajectory(
            turns=turns,
            final_answer=final_answer,
            tools_used=tools_used,
        )

    def _extract_all_tool_calls(
        self, text: str
    ) -> List[tuple[ParsedToolCall, int, int]]:
        """Extract all tool calls with their positions."""
        results: List[tuple[ParsedToolCall, int, int]] = []
        seen_spans: set[tuple[int, int]] = set()

        for pattern in self.tool_call_patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                if (start, end) in seen_spans:
                    continue
                seen_spans.add((start, end))

                tc = self._parse_single_match(match, pattern)
                if tc:
                    results.append((tc, start, end))

        # Sort by position
        results.sort(key=lambda x: x[1])
        return results

    def _parse_single_match(
        self, match: re.Match, pattern: re.Pattern
    ) -> Optional[ParsedToolCall]:
        """Parse a single regex match into ParsedToolCall."""
        groups = match.groups()

        # Pattern 2: name attribute + arguments body
        if len(groups) == 2 and not groups[1].strip().startswith("{"):
            # Could be <tool_call name="x"> body not JSON - skip
            pass

        # Try to extract name and arguments from JSON
        if len(groups) == 1 or (len(groups) == 2 and groups[1].strip().startswith("{")):
            if len(groups) == 2 and groups[1].strip().startswith("{"):
                tool_name = groups[0].strip()
                args_text = groups[1].strip()
                try:
                    parameters = json.loads(args_text)
                    if not isinstance(parameters, dict):
                        parameters = {"arguments": parameters}
                    return ParsedToolCall(tool_name=tool_name, parameters=parameters)
                except json.JSONDecodeError:
                    return None
            else:
                json_text = groups[0].strip()
                try:
                    data = json.loads(json_text)
                    if isinstance(data, dict):
                        tool_name = data.get("name") or data.get("tool_name", "")
                        parameters = data.get("arguments", data.get("parameters", {}))
                        if not isinstance(parameters, dict):
                            parameters = {"value": parameters}
                        if tool_name:
                            return ParsedToolCall(tool_name=tool_name, parameters=parameters)
                except json.JSONDecodeError:
                    pass

        # Fallback: treat the matched block as name + JSON body
        if len(groups) == 2:
            tool_name = groups[0].strip()
            body = groups[1].strip()
            try:
                parameters = json.loads(body)
                if not isinstance(parameters, dict):
                    parameters = {"value": parameters}
            except json.JSONDecodeError:
                parameters = {"raw": body}
            return ParsedToolCall(tool_name=tool_name, parameters=parameters)

        return None

    def parse_qwen3_format(self, text: str) -> ParsedTrajectory:
        """
        Parse Qwen3 chat-template style tool calls.

        Qwen3 may output:
        <tool_call>
        {"name": "market_data.get_quote", "arguments": {"ts_code": "600519.SH"}}
        </tool_call>
        """
        return self.parse(text)
