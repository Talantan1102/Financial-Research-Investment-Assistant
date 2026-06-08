# 对话流记忆评估体系 harness 落地 + 首跑五发现(2026-06-05)

**结论**:长期记忆评估体系重建的 harness 全部落地(分支 `feat/memory-dialogue-eval`):脚本 schema / 数据库断言引擎(六种断言) / 写阶段(可控时间戳) / 读阶段(三层判分+不变量开关) / 维度×难度分数表 / live wiring CLI。首段脚本《白酒观点演化》(retail-investor-voice skill 加持的散户口语台词)端到端冒烟六轮迭代后:写管线全链路证明工作(知识更新:中性版生效/旧版作废/四版本链可溯,断言 5/8 绿),读侧全红、病灶锁定检索层。

**Why(首跑就回本的五个系统发现,全部 TDD 修复+独立 commit)**:
1. skip_gate 关键词门白名单全书面语,真实散户口语(看多/转中性/割肉)被静默跳过——书面语测试集永远测不出,口语台词一上就现形;
2. embed 批形态 vs 检索平向量接口漂移;
3. 抽取层 LLM 客户端协议不兼容(`chat(system=...)` 对 LLMService TypeError)——**生产 Path B 批量抽取在真实 LLM 下从未成功过**,cassette mock 掩盖;
4. AGE cypher 失败毒死 PG 事务,catch Python 异常救不了 aborted 事务,"best-effort"名存实亡 → SAVEPOINT;
5. **生产库(industry_assistant)无 AGE 扩展且镜像里不可装**——图镜像生产从未工作;边镜像已降级 best-effort(政策变更:原"AGE 失败→整事务回滚"契约与测试已改写,PG 为 SSOT)。

**How to apply**:
- 跑评估:WSL fria-venv,`PYTHONPATH=. python -m eval.memory_dialogue.run_eval --script eval/memory_dialogue/scripts/viewpoint-baijiu.yaml`(source 仓库根 .env;评估自建独立 user 不污染数据);
- 写新脚本台词必须用 `.claude/skills/retail-investor-voice`(语料+反 AI 腔纪律);故障模式素材看板研报 `/eval/report/memory-failure-modes`;
- 遗留清单与执行进度在 plan 文档末尾(`docs/superpowers/plans/2026-06-05-memory-dialogue-eval.md`):读侧检索两 bug(向量 struct 残留/中文 BM25 零召回)、断言适配值规整(两年→2年)、27 段脚本(任务八五批)未写;
- 用户决策:**先把评估体系搞好(任务八),再回头优化系统问题**;弃答题在检索全空时躺赢,解读分数须连同检索健康度看。

相关:[[c5-cross-session-memory-done]] [[c5-plan8-eval-tests-docs-done]](旧 eval,保留不扩展待退役)
