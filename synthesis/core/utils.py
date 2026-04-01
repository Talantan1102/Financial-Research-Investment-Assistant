import asyncio
import json
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Tuple, Type
from dataclasses import dataclass, field
import pdb

import openai


@dataclass
class TokenStats:
    """Token usage statistics tracker"""
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0

    # Per-model pricing (USD per 1M tokens)
    PRICING = {
        "deepseek-v3.2": {"input": 0.28, "output": 0.42},
        "deepseek-v3": {"input": 0.28, "output": 0.42},
        "qwen-max": {"input": 1.6, "output": 6.4},  # USD
    }

    def add_usage(self, model: str, input_tokens: int, output_tokens: int):
        """Add token usage for a single call"""
        self.total_calls += 1
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens

        # Calculate cost
        pricing = self.PRICING.get(model, self.PRICING.get("deepseek-v3.2"))
        cost = (input_tokens / 1_000_000) * pricing["input"] + \
               (output_tokens / 1_000_000) * pricing["output"]
        self.total_cost_usd += cost

    def report(self) -> str:
        """Generate usage report"""
        return f"""
📊 Token Usage Report:
   Total API Calls: {self.total_calls}
   Input Tokens: {self.total_input_tokens:,}
   Output Tokens: {self.total_output_tokens:,}
   Total Tokens: {self.total_input_tokens + self.total_output_tokens:,}
   Estimated Cost: ${self.total_cost_usd:.4f} USD (~¥{self.total_cost_usd * 7.2:.2f})
"""

# Global token stats instance
token_stats = TokenStats()


def create_openai_client(api_key: str, base_url: str) -> openai.OpenAI:
    if not api_key:
        raise ValueError("Missing api_key in synthesis config")
    if not base_url:
        raise ValueError("Missing base_url in synthesis config")
    return openai.OpenAI(api_key=api_key, base_url=base_url)


def extract_json_object(text: str) -> str:
    """Extract the first complete JSON object from text (forward scan)."""
    if not text:
        return text
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def extract_xml_block(text: str, root_tag: str = "response") -> str:
    """Extract the first XML block with the given root tag."""
    if not text:
        return text
    pattern = rf"<{root_tag}\b[^>]*>.*?</{root_tag}>"
    match = re.search(pattern, text, flags=re.DOTALL)
    return match.group(0) if match else text


def parse_action_xml(text: str) -> Dict[str, Any]:
    """Parse XML into {intent, action:{tool_name, parameters}}."""
    def _find_tag(raw: str, tag: str) -> str:
        match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", raw, flags=re.DOTALL)
        return (match.group(1).strip() if match else "")

    xml_text = extract_xml_block(text, root_tag="response")
    intent = ""
    tool_name = ""
    parameters: Dict[str, Any] = {}
    if "<response" in xml_text:
        root = ET.fromstring(xml_text)
        intent = (root.findtext("intent") or "").strip()
        action_el = root.find("action")
        if action_el is not None:
            tool_name = (action_el.findtext("tool_name") or "").strip()
            params_text = (action_el.findtext("parameters") or "").strip()
        else:
            tool_name = (root.findtext("tool_name") or "").strip()
            params_text = (root.findtext("parameters") or "").strip()
    else:
        intent = _find_tag(text, "intent")
        tool_name = _find_tag(text, "tool_name")
        params_text = _find_tag(text, "parameters")

    if params_text:
        try:
            parameters = json.loads(params_text)
        except Exception:
            parameters = {}
    return {
        "intent": intent,
        "action": {
            "tool_name": tool_name,
            "parameters": parameters
        }
    }


def chat_completion(
    client: openai.OpenAI,
    *,
    max_retries: int = 3,
    retry_wait: float = 0.5,
    retry_backoff: float = 2.0,
    retry_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    **kwargs: Any
) -> Any:
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except retry_exceptions:
            if attempt >= max_retries:
                raise
            time.sleep(retry_wait * (retry_backoff ** attempt))


async def async_chat_completion(
    client: openai.OpenAI,
    model: str = "",
    *,
    max_retries: int = 3,
    retry_wait: float = 0.5,
    retry_backoff: float = 2.0,
    retry_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    **kwargs: Any
) -> Any:
    global token_stats
    loop = asyncio.get_event_loop()
    for attempt in range(max_retries + 1):
        try:
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(model=model, **kwargs)
            )
            # Track token usage
            if hasattr(response, 'usage') and response.usage:
                input_tokens = response.usage.prompt_tokens or 0
                output_tokens = response.usage.completion_tokens or 0
                token_stats.add_usage(model, input_tokens, output_tokens)
            return response
        except retry_exceptions as e:
            if attempt >= max_retries:
                raise
            await asyncio.sleep(retry_wait * (retry_backoff ** attempt))
