"""只读探针②:验证「加 prompt 规则」能否把抽取从系统性错纠正过来(写 plan 前的决定性一测)。

探针①发现:默认温下模型对「看多高端白酒」稳定地错(PREFERS→600519.SH Stock),不是随机。
所以头号杠杆是 prompt 规则。本探针对比 基线 prompt vs 加了「实体类型决策+关系裁决表」的
增强 prompt,同输入各跑 N 次,看关键边是否从 PREFERS→Stock 切到 EXPRESSED_VIEW→白酒Ⅱ(Industry)。

用法:PYTHONPATH=. python -u -m eval.memory_dialogue._probe_prompt_fix
"""

from __future__ import annotations

import json
from collections import Counter

from app.config.llm_config import LLMConfig
from app.memory.extractor import _EXTRACTION_SYSTEM_PROMPT
from app.services.tier_router import V0_DEFAULT_MODEL
from openai import OpenAI

N = 4
USER_MSG = "我自己基本研究完了 结论就是高端白酒值得拿 起码三年 我就认提价权这一条 茅台五粮液都行"
AGENT_MSG = "(总结用户观点:看多高端白酒,核心逻辑提价权,持有期三年)"
USER_PROMPT = f"# Episode\n当前对话日期=2025-01-06\nUser: {USER_MSG}\nAgent: {AGENT_MSG}"

# 增强段:实体类型决策 + 关系裁决表(spec 第三层的 prompt 形态草案,本探针验证其有效性)
_RULES = """\

# 实体类型与关系裁决(必须照此判,别自由发挥)
## target 实体类型怎么选(按用户表态的主体粒度)
- 用户对一个行业/板块的看法 → target 用 Industry(申万二级,如"白酒"→"白酒Ⅱ")
- 用户对一只具体个股的看法 → target 用 Stock(ts_code)
- 用户只说板块(如"高端白酒")时,【不要】替他补具体个股(茅台/五粮液只是举例,不单独建观点边)
- 逻辑/主题(如"提价权")放进该观点边的 properties.logic,【不要】单独建一条边
## 关系怎么选
- 有方向词(看多/看空/中性/高估/低估)+ 具体对象 → EXPRESSED_VIEW
- 跨标的的风格/策略偏好(喜欢价值/高股息) → PREFERS
- "看多白酒"【必为 EXPRESSED_VIEW,绝不可标 PREFERS】
"""

VARIANTS = [
    ("基线 prompt", _EXTRACTION_SYSTEM_PROMPT),
    ("增强 prompt(加裁决规则)", _EXTRACTION_SYSTEM_PROMPT + _RULES),
]


def _signature(raw: str) -> str:
    try:
        obj = json.loads(raw)
    except Exception:
        return "✗JSON解析失败"
    ents = {e.get("entity_label"): e.get("entity_type") for e in obj.get("entities", [])}
    for e in obj.get("edges", []):
        tgt = e.get("target_label", "")
        if e.get("rel_type") in ("EXPRESSED_VIEW", "PREFERS") or any(
            k in str(tgt) for k in ("白酒", "茅台", "五粮", "提价")
        ):
            return f"{e.get('rel_type')} → {tgt}({ents.get(tgt, '?')})"
    return "(无观点边)"


def main() -> None:
    config = LLMConfig()
    client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    print(
        f"模型={V0_DEFAULT_MODEL}\n判定:期望从 PREFERS→Stock 纠正为 EXPRESSED_VIEW→白酒Ⅱ(Industry)\n"
        + "=" * 70
    )
    for name, sys_prompt in VARIANTS:
        print(f"\n### {name}")
        sigs = []
        for _ in range(N):
            try:
                r = client.chat.completions.create(
                    model=V0_DEFAULT_MODEL,
                    messages=[{"role": "user", "content": f"{sys_prompt}\n\n{USER_PROMPT}"}],
                    max_tokens=2048,
                    temperature=0.1,
                    timeout=60,
                )
                sigs.append(_signature(r.choices[0].message.content or ""))
            except Exception as exc:  # noqa: BLE001
                sigs.append(f"✗调用失败:{str(exc)[:80]}")
        for s, c in Counter(sigs).most_common():
            print(f"    {c}× {s}")


if __name__ == "__main__":
    main()
