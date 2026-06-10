"""裁判-人类一致率 meta-eval(元评估研报落地第一项)。

信任 LLM 裁判的唯一正路:先拿人工金标准测裁判与人类的一致率,达标才放它自动
跑全集(LongMemEval 同款流程:>97% 一致才上岗)。本模块算一致率 + Cohen's
kappa(扣除随机一致)+ 四格混淆,并强制声明口径——脱离口径的一致率数字没意义
(元评估研报第 24 条)。

判分口径(本体系):
- 单答判定(judge 对一个答案判 pass/fail),非成对比较——故位置翻转审计不适用,
  改以裁判重测一致性(judge_stability)审稽,见同目录。
- 无平局(pass/fail 二元)。
- 单标注者金标准(作品级:金标准由人/Claude 独立判定,非多人共识)——故不报
  人-人基线,kappa 用来补"超越随机"这一维。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JudgePair:
    case_id: str
    human_pass: bool
    llm_pass: bool


@dataclass(frozen=True)
class AgreementReport:
    n: int
    agreement: float  # 朴素一致率 = 一致数 / n
    kappa: float  # Cohen's kappa,扣除随机一致
    both_pass: int
    both_fail: int
    human_pass_llm_fail: int  # 裁判漏判(比人严)
    human_fail_llm_pass: int  # 裁判误判(比人松,放水)


def compute_agreement(pairs: list[JudgePair]) -> AgreementReport:
    n = len(pairs)
    if n == 0:
        return AgreementReport(0, 0.0, 0.0, 0, 0, 0, 0)
    bp = sum(1 for p in pairs if p.human_pass and p.llm_pass)
    bf = sum(1 for p in pairs if not p.human_pass and not p.llm_pass)
    hp_lf = sum(1 for p in pairs if p.human_pass and not p.llm_pass)
    hf_lp = sum(1 for p in pairs if not p.human_pass and p.llm_pass)

    agree = (bp + bf) / n
    # Cohen's kappa:po=观测一致,pe=随机期望一致(由两边边际乘积)
    po = agree
    human_pass_rate = (bp + hp_lf) / n
    llm_pass_rate = (bp + hf_lp) / n
    pe = human_pass_rate * llm_pass_rate + (1 - human_pass_rate) * (1 - llm_pass_rate)
    kappa = 1.0 if pe >= 1.0 else (po - pe) / (1 - pe)

    return AgreementReport(
        n=n,
        agreement=agree,
        kappa=kappa,
        both_pass=bp,
        both_fail=bf,
        human_pass_llm_fail=hp_lf,
        human_fail_llm_pass=hf_lp,
    )


def format_report(r: AgreementReport) -> str:
    lines = [
        "裁判-人类一致率 meta-eval",
        "=" * 44,
        f"样本 n = {r.n}(口径:单答判定 / pass-fail 无平局 / 单标注者金标准)",
        f"一致率 agreement = {r.agreement:.3f}",
        f"Cohen's kappa     = {r.kappa:.3f}(扣除随机一致;<0.4 弱 / 0.4-0.6 中 / >0.8 强)",
        "-" * 44,
        "四格混淆(人 × 裁判):",
        f"  都通过 {r.both_pass}   都不通过 {r.both_fail}",
        f"  裁判漏判(人过裁判没过)  {r.human_pass_llm_fail}",
        f"  裁判误判(人没过裁判放水) {r.human_fail_llm_pass}",
        "-" * 44,
        "纪律:达标(对长期记忆建议对齐 LongMemEval >97%)后裁判才可自动跑全集;",
        "未达标先改判分 rubric 重测,不裸信裁判。",
    ]
    return "\n".join(lines)
