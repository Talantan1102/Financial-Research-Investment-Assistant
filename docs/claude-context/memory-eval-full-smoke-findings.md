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
- **下一步 TODO**(用户决策先后):① 全量回填 target_label 候选列表(个股 ts_code 最确定、高价值)→ 重跑验证写侧回升;② 真信号交记忆系统侧修(持仓边界 / 事件时间 / 偏好 value);③ ~~检索层两 bug(读侧全红根因)~~ 已修;④ 元评估四步收尾(裁判一致率/误差棒/位置翻转/消融区分度)。冒烟日志在 gitignored 的 `smoke_logs/`,分数与归因见本卡。

**③ 读侧全红根因已修完(2026-06-09)**:不是 2 bug 而是**四层**(每层掩盖下一层)——(1)建边没填 search_tokens→search_vector 空→BM25 零召回;(2)BM25 用 plainto_tsquery 整句全 AND→长 query 必零召回(单词「白酒」能召回是假象,SQL 实测整句 plainto=0 / OR=5)→改 to_tsquery OR;(3)embed 真契约 `embed(list[str])->list[list[float]]` 被传 bare string→按字符切片→data 形态错 struct.error(retriever + milvus_outbox 两处)→裹 `[query]` 取 `[0]`;(4)`archival_memory_search` commit 在生产 `expire_on_commit=True` 下 expire 属性、expunge 返回失效对象→调用方访问列属性 DetachedInstanceError(测试 conftest 用 False 掩盖,只在生产/eval 暴露)→search session 置 False。端到端 viewpoint-baijiu 读侧全红→2/7 绿,链路打通;**剩红已是写侧内容保真度(抽取器没把「转中性」轮读成中性 stance),非检索 bug**。四层各有 TDD 守护测试,详账见 plan `2026-06-05-memory-dialogue-eval.md` §检索层根因清账。教训:分层 bug 别被「单词能召回/测试全绿」假象骗;生产与测试 session 配置差异(expire_on_commit)会让 bug 只在真环境暴露——同 [[verify-import-chain-with-smoke-test]] 一脉。

**④ 元评估收尾 + ⑤ 写侧治本(2026-06-09)**:④ 消融 runner 落地(读+写双 knob)、judge golden 24→51(一致率仍 1.000)。消融反向诊断出核心:评估**分不开**完整 vs 削弱,不是评估没区分力,而是**完整版写侧自己贴地板**(old_invalidated 才 6/11)。⑤ 顺藤摸瓜 dump 边实证,**纠正了根因**——不是「转中性没抽出/助手旁白淹没」(中性其实抽到了),真因是 **(甲) 实体规整漂移**(白酒/白酒Ⅱ 落不同节点、演化链断)+ **(乙) 抽取非确定性**(同句「看多高端白酒」不同次被抽成 Industry白酒Ⅱ / Stock茅台 / 整句当实体,幻觉日期)。(甲) 已治本:接申万 registry(`industry_registry.normalize_industry`,白酒系→白酒Ⅱ canonical,7 单测+零回归),但**必要非充分**;(乙) 是主导残留,属抽取器质量/prompt 工程,配 `run_eval --repeat N` 多跑取率(对非确定系统的唯一可信判法)。教训:**别凭单跑红绿/单一假设定根因,dump 实证常推翻直觉**;非确定系统的评估必须多跑报率不报单值。详账见 plan §申万 registry 系统侧治本。

相关:[[memory-dialogue-eval-harness-landed]]
