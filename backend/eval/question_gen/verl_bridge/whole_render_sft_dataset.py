"""整体渲染版 MultiTurn SFT Dataset —— 修复 Qwen3 跨家蒸馏 reasoning 丢失。

## 为什么需要它

verl 自带 `MultiTurnSFTDataset` 是**逐轮** apply_chat_template 再拼接。Qwen3 模板对
**单条** assistant 消息会**丢弃 `reasoning_content`**(不渲染成 `<think>`),只有**整体多轮**
渲染才会对每个 assistant 轮保留 `<think>`。我们的 SFT 数据是 DeepSeek 教师生成、含
`reasoning_content` 的跨家蒸馏数据 —— 用逐轮版训练 = 教师推理链 100% 丢失,等于没在蒸馏 think。

实测(Qwen3-8B tokenizer):
- 逐轮渲染:`<think>` 出现 0 次,loss_mask sum=231(仅 tool_call/答案)
- 整体渲染:每个 assistant 轮都保留 `<think>`(50 样本 280/280),loss_mask sum=615(含推理)

## 做法

整体 apply_chat_template 拿 input_ids(think 正确保留),再按
`<|im_start|>assistant\n … <|im_end|>` span 重建 loss_mask:assistant 头部不计 loss、
内容(含 `<think>`/`<tool_call>`/答案)到 `<|im_end|>`(含)计 loss;user/tool 段(tool 结果
在 Qwen3 里渲成 `<|im_start|>user`)全 0。padding/truncation/position_ids 复用父类口径。

## 用法(verl sft_trainer)

  data.custom_cls.path=backend/eval/question_gen/verl_bridge/whole_render_sft_dataset.py
  data.custom_cls.name=WholeRenderMultiTurnSFTDataset

不再需要 data.ignore_input_ids_mismatch(本类不走逐轮 sanity_check)。
"""

from __future__ import annotations

import torch
import torch.nn.functional as F  # noqa: N812
from verl.utils.dataset.multiturn_sft_dataset import DatasetPadMode, MultiTurnSFTDataset
from verl.utils.py_functional import convert_nested_value_to_list_recursive


class WholeRenderMultiTurnSFTDataset(MultiTurnSFTDataset):
    """整体渲染 + span-based loss_mask,保留跨家蒸馏的 reasoning。"""

    def _special_ids(self):
        tok = self.tokenizer
        return {
            "im_start": tok.convert_tokens_to_ids("<|im_start|>"),
            "im_end": tok.convert_tokens_to_ids("<|im_end|>"),
            "assistant": tok.encode("assistant", add_special_tokens=False),
            "nl": tok.encode("\n", add_special_tokens=False),
        }

    @staticmethod
    def _build_loss_mask(ids: list[int], sp: dict) -> list[int]:
        """assistant 轮(头部除外)→ 内容..<|im_end|>(含)计 loss;其余 0。"""
        ims, ime = sp["im_start"], sp["im_end"]
        id_asst, id_nl = sp["assistant"], sp["nl"]
        la, lnl = len(id_asst), len(id_nl)
        n = len(ids)
        lm = [0] * n
        i = 0
        while i < n:
            if ids[i] == ims and ids[i + 1 : i + 1 + la] == id_asst:
                j = i + 1 + la
                if ids[j : j + lnl] == id_nl:  # 吃掉 assistant 头后的换行
                    j += lnl
                k = j
                while k < n and ids[k] != ime:
                    k += 1
                if k < n:
                    k += 1  # 含 <|im_end|>,让模型学会收尾
                for t in range(j, k):
                    lm[t] = 1
                i = k
            else:
                i += 1
        return lm

    def __getitem__(self, item):
        row_dict = self.dataframe.iloc[item].to_dict()
        messages = convert_nested_value_to_list_recursive(row_dict[self.messages_key])
        tools = self.tools[item] if self.tools is not None else None
        enable_thinking = (
            self.enable_thinking[item]
            if self.enable_thinking is not None
            else self.enable_thinking_default
        )
        kwargs = {**self.apply_chat_template_kwargs}
        if enable_thinking is not None:
            kwargs["enable_thinking"] = bool(enable_thinking)

        # 整体渲染:Qwen3 对每个 assistant 轮保留 <think>
        enc = self.tokenizer.apply_chat_template(
            messages,
            tools=tools,
            add_generation_prompt=False,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            **kwargs,
        )
        input_ids = enc["input_ids"][0]
        attention_mask = enc["attention_mask"][0]

        sp = self._special_ids()
        loss_mask = torch.tensor(
            self._build_loss_mask(input_ids.tolist(), sp), dtype=attention_mask.dtype
        )
        assert input_ids.shape == loss_mask.shape == attention_mask.shape

        position_ids = torch.arange(input_ids.shape[0], dtype=torch.long)

        sequence_length = input_ids.shape[0]
        if self.pad_mode == DatasetPadMode.RIGHT:
            if sequence_length < self.max_length:
                pad_id = (
                    self.tokenizer.pad_token_id if self.tokenizer.pad_token_id is not None else 0
                )
                pad_n = self.max_length - sequence_length
                input_ids = torch.cat(
                    (input_ids, torch.full((pad_n,), pad_id, dtype=input_ids.dtype))
                )
                attention_mask = torch.cat(
                    (attention_mask, torch.zeros((pad_n,), dtype=attention_mask.dtype))
                )
                loss_mask = torch.cat((loss_mask, torch.zeros((pad_n,), dtype=loss_mask.dtype)))
                position_ids = F.pad(position_ids, (0, pad_n), value=0)
            elif sequence_length > self.max_length:
                input_ids, attention_mask, loss_mask, position_ids = self._truncate(
                    input_ids, attention_mask, loss_mask, position_ids, sequence_length
                )
            return {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "position_ids": position_ids,
                "loss_mask": loss_mask,
            }
        elif self.pad_mode == DatasetPadMode.NO_PADDING:
            if sequence_length > self.max_length and self.truncation == "error":
                raise ValueError(f"{sequence_length=} is larger than {self.max_length=}")
            if len(input_ids) > self.max_length:
                input_ids = input_ids[: self.max_length]
                loss_mask = loss_mask[: self.max_length]
                position_ids = position_ids[..., : self.max_length]
            return {
                "input_ids": input_ids,
                "position_ids": position_ids,
                "loss_mask": loss_mask,
            }
        raise ValueError(f"Unknown pad_mode {self.pad_mode}")

    def _truncate(self, input_ids, attention_mask, loss_mask, position_ids, sequence_length):
        if self.truncation == "left":
            sl = slice(-self.max_length, None)
        elif self.truncation == "right":
            sl = slice(0, self.max_length)
        elif self.truncation == "error":
            raise ValueError(f"{sequence_length=} is larger than {self.max_length=}")
        else:
            raise ValueError(f"Unknown truncation method {self.truncation}")
        return (
            input_ids[sl],
            attention_mask[sl],
            loss_mask[sl],
            position_ids[..., sl],
        )
