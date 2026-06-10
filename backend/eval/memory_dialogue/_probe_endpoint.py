"""只读端点能力探针(抽取保真度 spec 开放问题①去风险,不碰生产代码)。

直接打抽取真用的端点(deepseek-v4-flash / DashScope 兼容端),用真实抽取 system prompt
+ 最会漂的白酒台词,在 默认温 / 低温0.1 / 低温+json_object 三档各跑 N 次,量:
- 端点是否接受 temperature / response_format=json_object(API 报错=不支持);
- JSON 格式守约率(能不能稳定 json.loads);
- 关键边(rel_type, target_label, target 的 entity_type)的方差(降温降了多少漂)。

用法:PYTHONPATH=. python -m eval.memory_dialogue._probe_endpoint
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from app.config.llm_config import LLMConfig
from app.memory.extractor import _EXTRACTION_SYSTEM_PROMPT
from app.services.tier_router import V0_DEFAULT_MODEL
from openai import OpenAI

N = 4  # 每档跑几次

# 最会漂的输入:同一句同时映射 行业(白酒Ⅱ)/个股(茅台五粮液)/概念(提价权)
USER_MSG = "我自己基本研究完了 结论就是高端白酒值得拿 起码三年 我就认提价权这一条 茅台五粮液都行"
AGENT_MSG = "(总结用户观点:看多高端白酒,核心逻辑提价权,持有期三年)"
USER_PROMPT = f"# Episode\n当前对话日期=2025-01-06\nUser: {USER_MSG}\nAgent: {AGENT_MSG}"

CONFIGS: list[tuple[str, dict[str, Any]]] = [
    ("默认(现状,无温/无json)", {}),
    ("低温0.1", {"temperature": 0.1}),
    ("低温0.1+json_object", {"temperature": 0.1, "response_format": {"type": "json_object"}}),
]


def _signature(raw: str) -> str | None:
    """从一次抽取输出里取关键观点边的签名 (rel_type, target_label, target_entity_type)。"""
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    edges = obj.get("edges", [])
    ents = {e.get("entity_label"): e.get("entity_type") for e in obj.get("entities", [])}
    # 取第一条 EXPRESSED_VIEW / PREFERS / 含"白酒/茅台/提价"的边
    for e in edges:
        tgt = e.get("target_label", "")
        if e.get("rel_type") in ("EXPRESSED_VIEW", "PREFERS") or any(
            k in str(tgt) for k in ("白酒", "茅台", "五粮", "提价")
        ):
            return f"{e.get('rel_type')} → {tgt}({ents.get(tgt, '?')})"
    return "(无观点边)"


def main() -> None:
    config = LLMConfig()
    client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    full_prompt = f"{_EXTRACTION_SYSTEM_PROMPT}\n\n{USER_PROMPT}"
    print(f"模型={V0_DEFAULT_MODEL}  端点={config.base_url}\n输入:{USER_MSG[:40]}…\n" + "=" * 70)

    for name, extra in CONFIGS:
        print(f"\n### {name}")
        parse_ok = 0
        sigs: list[str] = []
        api_err = None
        for _ in range(N):
            try:
                r = client.chat.completions.create(
                    model=V0_DEFAULT_MODEL,
                    messages=[{"role": "user", "content": full_prompt}],
                    max_tokens=2048,
                    **extra,
                )
                raw = r.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001
                api_err = str(exc)[:200]
                break
            sig = _signature(raw)
            if sig is not None:
                parse_ok += 1
                sigs.append(sig)
            else:
                sigs.append("✗JSON解析失败")
        if api_err:
            print(f"  ⚠️ 端点不接受该参数:{api_err}")
            continue
        print(f"  JSON 守约:{parse_ok}/{N}")
        print(f"  关键边方差:{len(set(sigs))} 种 / {N} 次")
        for s, c in Counter(sigs).most_common():
            print(f"    {c}× {s}")


if __name__ == "__main__":
    main()
