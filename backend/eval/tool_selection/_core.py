"""工具选择 / 技能触发离线评测的共享核心(Task 6.2,spec § 5.2 + § 3.4)。

评测换靶(spec § 5.2):不走 LLM-as-Judge —— 直接比对 ChatLoopAgent 的
SUTOutput.tool_calls **首选工具**(AST 比对 + 该调时调 / 不该调时弃权双指标 +
按桶分桶 + 多轮序列口径)。比 Judge 更便宜、更确定。

golden 行格式(jsonl,``//`` 开头行为注释,与 c5_memory_golden 惯例一致):
    {"case_id": "ts-001", "category": "single_tool",
     "user_input": "贵州茅台现在多少钱?",
     "expected": {"first_tool": "get_stock_quote",
                  "args_contains": {"ts_code": "600519.SH"}},
     "bucket": "金融数据"}

expected 至少含一键(四选一,可组合):
  - first_tool (str | null):首选业务工具名;null = 应弃权(不调任何业务工具);
  - args_contains (dict):首个工具调用的 args 须包含这些键值(子集匹配);
  - not_tools (list[str]):这些工具**不该**在本轮被调用(升级弃权 / 技能近似负例);
  - tools_sequence_contains (list[str]):多轮口径,工具调用序列须按序包含这些工具
      (含机制工具 search_tools —— 延迟工具该搜先搜)。

bucket 枚举(分桶准确率):金融数据 / 记忆 / 知识库 / 升级 / 技能 / 弃权。

--- 两种运行模式 ---

dry(默认,CI 可跑,零 LLM):只校验 golden schema + 打印分桶/类目统计。
live(--live,联调阶段跑,≈ 一次 45+ 次 LLM 调用):构造真件 ChatLoopAgent
  (真 LLMService + ToolHub 含真 tool_docs schema + FakeNoopHub dispatch),
  评测只看模型的**第一轮选择**:
    - 普通 case:gate_cfg max_steps=1,跑一圈即停,SUTOutput.tool_calls 即首轮选择;
    - tools_sequence case:max_steps=2,且 dispatch 对 search_tools 真跑
      (本地纯函数无副作用)其余 noop —— 让模型能看到检索结果再选目标工具。

指标(spec § 5.2 双指标 + 分桶):
  - RelAcc:该调工具的 case(first_tool 非 null 或有 tools_sequence)里首选/序列正确的占比;
  - IrrelAcc:该弃权的 case(first_tool=null 或仅 not_tools)里正确弃权 / 未误调的占比;
  - 分桶准确率:每个 bucket 内 case 通过率;
  - 总表 markdown。

--strict:任一桶低于阈值 exit 1(阈值见 ``THRESHOLDS``,拍脑袋初始值,注释说明待校准)。
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

# --- 枚举与阈值 ------------------------------------------------------------

VALID_BUCKETS: tuple[str, ...] = (
    "金融数据",
    "记忆",
    "知识库",
    "升级",
    "技能",
    "弃权",
)

# expected 允许的键(至少含其一)
_EXPECTED_KEYS: tuple[str, ...] = (
    "first_tool",
    "args_contains",
    "not_tools",
    "tools_sequence_contains",
)

# 阈值:拍脑袋初始值,待 --live 跑出真实分布后校准(spec § 5.2 未给硬数字)。
# RelAcc 0.8 = 该调时八成调对;IrrelAcc 0.7 = 该弃权时七成正确弃权(弃权更难,放宽)。
RELACC_THRESHOLD = 0.8
IRRELACC_THRESHOLD = 0.7


# --- golden 行 / 加载器(fail-loud)----------------------------------------


@dataclass(frozen=True)
class GoldenCase:
    """单条评测金标准。expected 至少含一键(加载时校验)。"""

    case_id: str
    category: str
    user_input: str
    expected: dict[str, Any]
    bucket: str
    skill: str | None = None  # 技能触发 golden 专用:标注目标技能(其余 None)


def _fail(msg: str) -> NoReturn:
    raise ValueError(f"tool-selection golden 校验失败: {msg}")


def _validate_case(raw: dict[str, Any], seen_ids: set[str]) -> GoldenCase:
    """单行 dict → GoldenCase,fail-loud(必填缺失 / expected 空 / bucket 越界 / id 重复)。"""
    for key in ("case_id", "category", "user_input", "expected", "bucket"):
        if key not in raw:
            _fail(f"缺失必填字段 {key!r}: {raw!r}")

    case_id = raw["case_id"]
    if not isinstance(case_id, str) or not case_id.strip():
        _fail(f"case_id 须为非空字符串: {raw!r}")
    if case_id in seen_ids:
        _fail(f"case_id 重复: {case_id!r}")

    expected = raw["expected"]
    if not isinstance(expected, dict):
        _fail(f"{case_id}: expected 须为对象")
    present = [k for k in _EXPECTED_KEYS if k in expected]
    if not present:
        _fail(
            f"{case_id}: expected 至少含一键 {_EXPECTED_KEYS!r},实得 {sorted(expected)!r}"
        )

    bucket = raw["bucket"]
    if bucket not in VALID_BUCKETS:
        _fail(f"{case_id}: bucket {bucket!r} 不在枚举 {VALID_BUCKETS!r} 内")

    if not isinstance(raw["user_input"], str) or not raw["user_input"].strip():
        _fail(f"{case_id}: user_input 须为非空字符串")

    seen_ids.add(case_id)
    return GoldenCase(
        case_id=case_id,
        category=str(raw["category"]),
        user_input=raw["user_input"],
        expected=expected,
        bucket=bucket,
        skill=raw.get("skill"),
    )


def load_golden(path: Path) -> list[GoldenCase]:
    """读 jsonl(``//`` 注释行跳过),逐行校验,fail-loud。空集报错(防路径写错)。"""
    if not path.exists():
        _fail(f"golden 文件不存在: {path}")
    cases: list[GoldenCase] = []
    seen_ids: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            _fail(f"第 {lineno} 行不是合法 JSON: {e}")
        if not isinstance(raw, dict):
            _fail(f"第 {lineno} 行须为对象")
        cases.append(_validate_case(raw, seen_ids))
    if not cases:
        _fail(f"golden 文件无有效 case: {path}")
    return cases


# --- case 分类:该调 vs 该弃权 ---------------------------------------------


def is_abstain_case(case: GoldenCase) -> bool:
    """该弃权 case:first_tool 显式为 null,或只给了 not_tools(无正向 first_tool/序列)。"""
    exp = case.expected
    if exp.get("first_tool", "__MISSING__") is None:
        return True
    has_positive = (
        exp.get("first_tool") not in (None, "__MISSING__")
        or "tools_sequence_contains" in exp
    )
    return not has_positive


# --- 单 case 评分(纯函数,SUT 输出 → 通过/不通过)--------------------------


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    bucket: str
    is_abstain: bool
    passed: bool
    detail: str


def _first_business_tool(tool_calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    """首个业务工具调用(search_tools 已被 ChatLoopAgent 排除,这里直接取首个)。"""
    return tool_calls[0] if tool_calls else None


def score_case(case: GoldenCase, tool_calls: list[dict[str, Any]]) -> CaseScore:
    """比对 SUT 的 tool_calls(已排除 search_tools)与 expected,产出通过/不通过。

    tool_calls:list of {"tool_name": str, "args": dict}(从 SUTOutput.tool_calls 投影)。
    多键 expected 取**全部满足**(AND):first_tool 对 + args_contains 子集 +
    not_tools 不出现 + 序列按序包含。
    """
    exp = case.expected
    names = [tc["tool_name"] for tc in tool_calls]
    reasons: list[str] = []
    ok = True

    # not_tools:这些工具不该出现
    for forbidden in exp.get("not_tools", []) or []:
        if forbidden in names:
            ok = False
            reasons.append(f"误调了不该调的 {forbidden}")

    # first_tool
    if "first_tool" in exp:
        want = exp["first_tool"]
        first = _first_business_tool(tool_calls)
        got = first["tool_name"] if first else None
        if want is None:
            if got is not None:
                ok = False
                reasons.append(f"应弃权但调了 {got}")
        else:
            if got != want:
                ok = False
                reasons.append(f"首选应为 {want},实得 {got!r}")
            elif "args_contains" in exp and first is not None:
                args = first.get("args", {})
                for k, v in exp["args_contains"].items():
                    if args.get(k) != v:
                        ok = False
                        reasons.append(f"args[{k!r}] 应为 {v!r},实得 {args.get(k)!r}")
    elif "args_contains" in exp:
        # 无 first_tool 但有 args_contains:对首个工具校验
        first = _first_business_tool(tool_calls)
        if first is None:
            ok = False
            reasons.append("应有工具调用但实际弃权")
        else:
            args = first.get("args", {})
            for k, v in exp["args_contains"].items():
                if args.get(k) != v:
                    ok = False
                    reasons.append(f"args[{k!r}] 应为 {v!r},实得 {args.get(k)!r}")

    # tools_sequence_contains:按序子序列(允许中间穿插其它工具)
    seq = exp.get("tools_sequence_contains")
    if seq and not _is_subsequence(seq, names):
        ok = False
        reasons.append(f"工具序列应按序包含 {seq},实得 {names}")

    return CaseScore(
        case_id=case.case_id,
        bucket=case.bucket,
        is_abstain=is_abstain_case(case),
        passed=ok,
        detail="; ".join(reasons) if reasons else "ok",
    )


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """needle 是否为 haystack 的按序子序列(中间可穿插)。"""
    it = iter(haystack)
    return all(item in it for item in needle)


# --- 聚合指标 --------------------------------------------------------------


@dataclass
class EvalReport:
    total: int = 0
    rel_total: int = 0
    rel_pass: int = 0
    irrel_total: int = 0
    irrel_pass: int = 0
    by_bucket: dict[str, list[bool]] = field(default_factory=lambda: defaultdict(list))
    case_scores: list[CaseScore] = field(default_factory=list)

    @property
    def rel_acc(self) -> float:
        return self.rel_pass / self.rel_total if self.rel_total else 1.0

    @property
    def irrel_acc(self) -> float:
        return self.irrel_pass / self.irrel_total if self.irrel_total else 1.0

    def bucket_acc(self, bucket: str) -> float:
        results = self.by_bucket.get(bucket, [])
        return (sum(results) / len(results)) if results else 1.0


def aggregate(scores: list[CaseScore]) -> EvalReport:
    rep = EvalReport()
    for s in scores:
        rep.total += 1
        rep.case_scores.append(s)
        rep.by_bucket[s.bucket].append(s.passed)
        if s.is_abstain:
            rep.irrel_total += 1
            rep.irrel_pass += int(s.passed)
        else:
            rep.rel_total += 1
            rep.rel_pass += int(s.passed)
    return rep


def assert_thresholds(rep: EvalReport) -> list[str]:
    """对照阈值收集失败项(--strict 用)。"""
    failures: list[str] = []
    if rep.rel_acc < RELACC_THRESHOLD:
        failures.append(f"RelAcc {rep.rel_acc:.3f} < {RELACC_THRESHOLD}")
    if rep.irrel_acc < IRRELACC_THRESHOLD:
        failures.append(f"IrrelAcc {rep.irrel_acc:.3f} < {IRRELACC_THRESHOLD}")
    return failures


# --- 报告 ------------------------------------------------------------------


def format_dry_report(cases: list[GoldenCase], title: str) -> str:
    """dry 模式:只统计 golden 构成(零 LLM)。"""
    by_bucket: dict[str, int] = defaultdict(int)
    by_cat: dict[str, int] = defaultdict(int)
    abstain = 0
    for c in cases:
        by_bucket[c.bucket] += 1
        by_cat[c.category] += 1
        if is_abstain_case(c):
            abstain += 1
    lines = [
        f"# {title} — golden 构成(dry,零 LLM)",
        "",
        f"- 总 case 数:{len(cases)}",
        f"- 该调:{len(cases) - abstain} / 该弃权:{abstain}",
        "",
        "## 分桶",
    ]
    for b in VALID_BUCKETS:
        if by_bucket.get(b):
            lines.append(f"- {b}: {by_bucket[b]}")
    lines.append("")
    lines.append("## 分类目(category)")
    for cat in sorted(by_cat):
        lines.append(f"- {cat}: {by_cat[cat]}")
    return "\n".join(lines)


def format_live_report(rep: EvalReport, failures: list[str], title: str) -> str:
    """live 模式:双指标 + 分桶 + 失败明细的 markdown 总表。"""
    lines = [
        f"# {title} — 评测报告(live)",
        "",
        f"- 总 case 数:{rep.total}",
        f"- **RelAcc**(该调时首选/序列对):{rep.rel_acc:.3f} "
        f"({rep.rel_pass}/{rep.rel_total},阈值 {RELACC_THRESHOLD})",
        f"- **IrrelAcc**(该弃权时正确弃权):{rep.irrel_acc:.3f} "
        f"({rep.irrel_pass}/{rep.irrel_total},阈值 {IRRELACC_THRESHOLD})",
        "",
        "## 分桶准确率",
        "",
        "| 桶 | 通过 / 总 | 准确率 |",
        "|---|---|---|",
    ]
    for b in VALID_BUCKETS:
        results = rep.by_bucket.get(b, [])
        if not results:
            continue
        lines.append(f"| {b} | {sum(results)}/{len(results)} | {rep.bucket_acc(b):.3f} |")
    lines.append("")
    failed = [s for s in rep.case_scores if not s.passed]
    if failed:
        lines.append("## 未通过明细")
        lines.append("")
        for s in failed:
            lines.append(f"- `{s.case_id}` [{s.bucket}]: {s.detail}")
    lines.append("")
    lines.append(f"Failures(阈值): {failures or 'none'}")
    return "\n".join(lines)
