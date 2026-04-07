"""
Simple finance reward manager for verl-tool.

评分逻辑（最简版，后续可替换）：
  1. format_reward:  是否正确使用了 <tool_call>/<answer> 标签
  2. answer_reward:  <answer> 内容与 ground_truth 的匹配度
  3. efficiency_penalty: 过多 tool call 扣分

总分 = answer_reward * 0.6 + format_reward * 0.3 + efficiency * 0.1
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional

import torch
from verl import DataProto

try:
    from verl.workers.reward_manager import register
except ImportError:
    # fallback: define a no-op register if verl version differs
    def register(name):
        def wrapper(cls):
            cls.name = name
            return cls
        return wrapper


ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)
TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _normalize(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    try:
        num = float(s.replace(",", ""))
        if math.isfinite(num):
            return str(int(num)) if num.is_integer() else f"{num:.6f}".rstrip("0").rstrip(".")
    except Exception:
        pass
    return re.sub(r"\s+", " ", s.lower()).strip(" .,:;!?\n\t")


def _extract_answer(text: str) -> str:
    matches = list(ANSWER_RE.finditer(text))
    if matches:
        return matches[-1].group(1).strip()
    return text.strip()


def _compute_answer_score(pred: str, target: str, tolerance: float = 0.01) -> float:
    npred = _normalize(pred)
    ntarget = _normalize(target)

    # 数值匹配（带容差）
    try:
        vp, vt = float(npred), float(ntarget)
        if math.isfinite(vp) and math.isfinite(vt) and abs(vp - vt) <= tolerance:
            return 1.0
    except Exception:
        pass

    # 字符串包含
    if ntarget and ntarget in npred:
        return 1.0

    # 精确匹配
    return 1.0 if npred == ntarget else 0.0


def _compute_format_score(text: str) -> float:
    score = 0.0
    has_tool_call = bool(TOOL_CALL_RE.search(text))
    has_answer = bool(ANSWER_RE.search(text))

    if has_tool_call:
        score += 0.5
    if has_answer:
        score += 0.5
    return score


def _compute_efficiency_score(text: str, max_calls: int = 6) -> float:
    n_calls = len(TOOL_CALL_RE.findall(text))
    if n_calls == 0:
        return 0.5
    if n_calls <= max_calls:
        return 1.0
    # 超出部分每多一个扣 0.1
    return max(0.0, 1.0 - (n_calls - max_calls) * 0.1)


@register("simple_finance")
class SimpleFinanceRM:
    """最简金融 reward manager，兼容 verl-tool。"""

    name = "simple_finance"

    def __init__(self, tokenizer, num_examine: int = 3, tolerance: float = 0.01, **kwargs):
        self.tokenizer = tokenizer
        self.num_examine = num_examine
        self.tolerance = tolerance

    def __call__(self, data: DataProto, return_dict: bool = False):
        if "rm_scores" in data.batch:
            if return_dict:
                return {"reward_tensor": data.batch["rm_scores"], "reward_extra_info": {}}
            return data.batch["rm_scores"]

        resp_ids = data.batch["responses"]
        attn = data.batch["attention_mask"]
        prompt_ids = data.batch["prompts"]
        prompt_len = prompt_ids.shape[-1]

        reward_tensor = torch.zeros_like(resp_ids, dtype=torch.float32)
        extra: Dict[str, List[Any]] = {"score": [], "format": [], "answer": [], "efficiency": []}

        for i in range(len(data)):
            v_resp = int(attn[i, prompt_len:].sum().item())
            resp_str = self.tokenizer.decode(resp_ids[i, :v_resp], skip_special_tokens=True)

            # 获取 ground truth
            ntb = data[i].non_tensor_batch
            gt = ""
            if isinstance(ntb.get("reward_model"), dict):
                gt = ntb["reward_model"].get("ground_truth", "")
            elif "target_answer" in ntb:
                gt = ntb["target_answer"]

            # 三个分量
            extracted = _extract_answer(resp_str)
            answer_score = _compute_answer_score(extracted, gt, self.tolerance) if gt else 0.5
            format_score = _compute_format_score(resp_str)
            efficiency_score = _compute_efficiency_score(resp_str)

            total = answer_score * 0.6 + format_score * 0.3 + efficiency_score * 0.1

            # reward 放在最后一个有效 token 上
            if v_resp > 0:
                reward_tensor[i, v_resp - 1] = total

            extra["score"].append(total)
            extra["format"].append(format_score)
            extra["answer"].append(answer_score)
            extra["efficiency"].append(efficiency_score)

            # 打印前几条用于调试
            if i < self.num_examine:
                print(f"[SimpleFinanceRM] sample {i}: total={total:.3f} "
                      f"(ans={answer_score:.2f} fmt={format_score:.2f} eff={efficiency_score:.2f})")
                print(f"  extracted: {extracted[:100]}")
                print(f"  gt: {str(gt)[:100]}")

        if return_dict:
            return {"reward_tensor": reward_tensor, "reward_extra_info": extra}
        return reward_tensor
