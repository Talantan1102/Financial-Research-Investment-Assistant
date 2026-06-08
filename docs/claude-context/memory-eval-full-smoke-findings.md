# 对话流记忆评估 · 全量 26 段首轮冒烟发现(2026-06-08)

**结论**:28 段脚本里 26 段完成首轮真 LLM 冒烟(观点演化族 8 + 持仓仲裁/弃答/偏好/时间四族 18,time-sequence-chain 补跑、机动段未写)。写侧数据库断言总体通过率约 35%——但低分**绝大多数是脚本 label 未对齐 + 评估期望的设计目标系统尚未实现**,不是记忆系统记错。冒烟抓到 4 类真系统信号 + 1 个自引入 harness bug(已修),正是评估驱动开发的价值兑现。

**Why(四类真信号,评估的核心产出)**:
1. **持仓陈述被写进记忆图** ⭐(持仓仲裁族头号发现):用户口头说「茅台加到700股」,抽取器照建 HOLDS 边(库里实有 600519.SH/300750.SZ/688981.SH 的 HOLDS 边)。评估体系定的策略 A(持仓归模块、不入记忆)在写管线侧**尚未实现**——抽取白名单含 HOLDS,系统当前行为是正常抽持仓。要让持仓仲裁通过,需在抽取器加「持仓陈述不建 HOLDS、路由持仓模块」的边界逻辑。
2. **事件时间打成默认值**:大量边 valid_from = 2025-01-01(年初默认)而非对话发生日,valid_from_is_event_time 断言据此红——时间戳语义真翻车,正是知识更新维度「事件时间 vs 录入时间」要抓的。
3. **偏好边 properties 空**:AVOIDS/PREFERS 边建了但 value 空(「不碰」这个态度没进 properties),fact_active 的 value_contains 全落空——抽取器对偏好类关系只建边不填语义值。
4. **观点抽取粒度拆碎**:脚本预期「看好 AI 算力的光模块」挂一个 target,抽取器拆成 Concept:AI算力 + Concept:光模块 + Concept:算力缺口 多条边,断言粒度对不上(chain 2/10、ripple 3/10 主因)。
另:读侧 7 道题跨全部 26 段几乎全红——检索层两个已知 bug(向量 struct.error + 中文 BM25 零召回)致全部拒答,与本批写侧发现无关、归上一轮遗留。

**How to apply(回填依据 + 待办)**:
- **harness bug 已修**:write_phase 对候选列表 target_label 的 count 断言基线用 str(list) 当 key、与 run_check 的 tuple key 永不相等 → 误报「无基线」;已传原值由 _label_key 统一规范(回归测试 test_count_no_increase_with_list_label_has_baseline)。
- **label 规整映射表**(查库实证,批量回填 target_label 用):个股→ts_code(茅台 600519.SH / 宁德 300750.SZ / 五粮液 000858.SZ / 泸州老窖 000568.SZ);白酒→[白酒, 白酒II, 白酒Ⅱ];医药→医药生物(Sector);消费→消费(Concept,非 Industry);AI算力/光模块/铜缆/题材股→拆成多 Concept(候选列表只能部分救,粒度差异需断言适配)。dump 脚本 `backend/eval/memory_dialogue/smoke_logs/_label_dump.py`。
- **下一步 TODO**(用户决策先后):① 全量回填 target_label 候选列表(个股 ts_code 最确定、高价值)→ 重跑验证写侧回升;② 真信号交记忆系统侧修(持仓边界 / 事件时间 / 偏好 value);③ 检索层两 bug(读侧全红根因);④ 元评估四步收尾(裁判一致率/误差棒/位置翻转/消融区分度)。冒烟日志在 gitignored 的 `smoke_logs/`,分数与归因见本卡。

相关:[[memory-dialogue-eval-harness-landed]]
