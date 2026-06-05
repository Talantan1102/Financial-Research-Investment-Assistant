"""真实依赖 wiring — 仅 CLI(run_eval)用,测试不 import 本模块。

生成走 balanced 档、裁判走 fast 档(LLMService);检索与抽取的真实接通
在任务七(端到端冒烟)按 HierarchicalMemory / 批量抽取链路的现场签名补齐:
build_live_runners 当前对未接通的部分 fail loud,绝不静默降级。
"""

from __future__ import annotations

from typing import Any

from app.services.openai_client import build_llm_service_from_env

GENERATE_PROMPT = """\
你是用户的金融研究助手。仅基于下面检索到的记忆回答用户问题;
记忆里没有的信息明确说"你没有跟我聊过这个,我没有这个信息",不要编造。

[检索到的记忆]
{facts}

[用户问题]
{question}
"""

JUDGE_PROMPT = """\
你是评估裁判。按下面的评分标准判断回答是否合格,只输出 yes 或 no。

[问题] {question}
[回答] {answer}
[评分标准] {rubric}
"""


class LiveGenerator:
    def __init__(self) -> None:
        self._llm = build_llm_service_from_env()

    async def generate(self, query: str, facts: list[Any]) -> str:
        facts_text = "\n".join(f"- {f}" for f in facts) or "(空)"
        resp = self._llm.chat(
            prompt=GENERATE_PROMPT.format(facts=facts_text, question=query),
            tier="balanced",
        )
        return str(resp.content)


class LiveJudge:
    def __init__(self) -> None:
        self._llm = build_llm_service_from_env()

    async def judge(self, question: str, answer: str, rubric: str) -> bool:
        resp = self._llm.chat(
            prompt=JUDGE_PROMPT.format(question=question, answer=answer, rubric=rubric),
            tier="fast",
        )
        return str(resp.content).strip().lower().startswith("yes")


async def build_live_runners() -> tuple[Any, Any]:
    """构造 (write_runner, read_runner),真 PG + 真抽取 + 真检索。

    任务七接通:HierarchicalMemory(检索)与批量抽取链路(写入)的构造
    依赖 session factory / Milvus client / embed service,按现场签名填。
    """
    raise NotImplementedError(
        "live wiring 在端到端冒烟任务接通(需要 HierarchicalMemory 与批量抽取的"
        "现场构造参数);在那之前 CLI 不可用——fail loud,不静默降级"
    )
