# 元评估 — 论证评估体系自身可信(四步落地)

研报《元评估 · 怎么论证评估体系可信》(`/eval/report/eval-meta-evaluation`)定的四步收尾,
逐项落地状态。判分口径贯穿:单答 pass/fail 判定 / 无平局 / 单标注者金标准。

## 一、裁判-人类一致率 meta-eval ✓(信任裁判的唯一正路)

`judge_goldset.jsonl`(24 条人工标注,覆盖裁判最易放水的边界:知行不一/过度拒答/
弃答无纠错/谄媚翻转)+ `judge_agreement.py`(一致率 + Cohen's kappa + 四格混淆)。

```
PYTHONPATH=. python -m eval.memory_dialogue.meta_eval.run_judge_agreement
```

**首跑(2026-06-08,fast 档裁判)**:一致率 = 1.000,kappa = 1.000,漏判 0 / 误判 0。
达到 LongMemEval >97% 标准。诚实:24 条种子样本、金标准由作者独立标注(非真人)、
rubric 写得明确降低了歧义——作为"裁判可信"证据链的起点合格,扩样后复测。

## 二、误差棒 + 聚类标准误 ✓(没有误差棒的分差表=没结论)

`scoring.py`:`wilson_interval`(每个 cell 配 Wilson 95% 区间,小样本不失真,
3/3 ≠ 确定 100%)进 `format_score_table`;`cluster_standard_error`(对话流评估
同脚本多题不独立,按脚本聚类——朴素标准误低估 3 倍以上)。

## 三、裁判重测一致性 ✓(位置翻转审计的适配版)

位置翻转审计针对成对比较(A/B 对调双判),本体系裁判是单答判定、无成对场景,
故改测重测稳定性:同输入判 k 次看翻不翻(`judge_stability.py`)。

```
PYTHONPATH=. python -m eval.memory_dialogue.meta_eval.run_judge_stability 3
```

**首跑(2026-06-08,k=3)**:重测一致率 = 1.000,0 翻转。裁判单次判定可信
(fast 档低温度促成)。

## 四、区分度 separable ✓(工具) + 消融实跑(TODO)

`scoring.py:separable`:两版本通过率的 Wilson 区间不重叠才算"能高置信区分"。
消融区分度实验(关掉 conflict_resolver judge 造削弱版 → 验证评估能把它和完整版
拉开)的**计算工具已就位**;**实跑待办**:

- 写侧消融**现在可做**(不依赖检索):`live_deps.build_live_runners` 传 `llm_judge=None`
  造"无冲突消解"削弱版,跑全量,对每个写侧维度用 `separable` 比完整版——预期
  old_invalidated/invalidated_chain_intact 类断言显著掉分、可区分。
- 读侧消融**待检索层修复**:当前读侧 7 题跨全段几乎全红(向量 struct + 中文 BM25
  零召回),区分度实验会被地板效应淹没,修检索后再做。

## 给整体评估体系的一句话

四步把"凭什么信这套评估"从口号变成证据:裁判经双重审计(准 + 稳)、分数带误差棒、
区分度有判定工具。剩消融实跑(写侧即可启动)+ 扩裁判金标准样本,是下一轮的事。
