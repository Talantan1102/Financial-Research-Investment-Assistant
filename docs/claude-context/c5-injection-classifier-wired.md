---
name: c5-injection-classifier-wired
description: C.5 S1 修复 — is_prompt_injection 在 Plan 5 自卡声称已接通但实际是死代码, 现已真接进 4 个写入入口 + 生产链路 e2e 守护
type: project
---

C.5 S1 dead-code fix ship — 2026-05-11.

## 背景:dead-code bug

Plan 5 自卡(`c5-plan5-cost-optimization-done.md`)写:
> spec § 11 末尾 #2 prompt injection classifier 规则层 (12 高置信 pattern ...)
> Plan 4 archival_memory_insert 写入前过滤 episode 内容

代码层 audit 撞实:`is_prompt_injection` 在 `backend/app/memory/injection_classifier.py:86` 定义,12 patterns + 30 case golden + L0 单元测试齐全,但**生产链路无任何调用点**:
- `archival_memory_insert.py` 只 import `evidence_quote_in_episode` + `EvidenceNotFoundError`,不 import `is_prompt_injection`
- `core_memory_append.py` / `core_memory_replace.py` 完全不接
- `LLMExtractor.extract` / `extract_facts` 直接把 episode 喂 LLM,无前置过滤
- `test_poison_attacks.py` 5 个测试全在测 `is_prompt_injection(text)` 函数本身,**没有 production-path e2e**

结果:`拦截率 ≥ 0.95` 的 Plan 8 验收指标在生产链路上是 0%,所有 ship 的 prompt injection 防御 demo-only。

## ship 范围(4 写入入口 + 1 异常类 + 测试守护)

| 入口 | 检查点 | 命中行为 |
|---|---|---|
| `archival_memory_insert.py` MCP tool | episode_text(user+agent 拼接) | raise `PromptInjectionDetectedError`, 不写 PG/AGE/Milvus, mcp_tool_call_log 记 error |
| `core_memory_append.py` MCP tool | `content` 入参 | raise `PromptInjectionDetectedError`, 不写 working_blocks |
| `core_memory_replace.py` MCP tool | `new_content` 入参 | raise `PromptInjectionDetectedError`, 不写 working_blocks |
| `LLMExtractor.extract` (Path A 单 episode) | user_message + agent_response | 返空 `ExtractionOutput`, 不调 LLM, log warn(不 raise 避免阻塞 caller) |
| `LLMExtractor.extract_facts` (Path B 跨 5 turn) | 每 turn 的 user_message + agent_response | **整 chunk** 返空 list, 不调 LLM(保守 — 一颗老鼠屎污染整 chunk) |

新异常类 `PromptInjectionDetectedError(ValueError)` 在 `injection_classifier.py` 加完,继承 ValueError 保持 caller `except ValueError` 向后兼容。err message 含命中 `pattern_id` + `confidence` 给 audit log 用。

## 关键决策

- **extract / extract_facts 不 raise**:Path B 一个 batch 含多 chunk,raise 整个 batch fail。返空 + log 让 Path B runner 走 failure_matrix 的 0-edge 分支,跟 LLM 抽不到东西的语义对齐。caller(`path_b_runner`)不需要改。
- **extract_facts chunk 整体丢弃**:5 turn 滑窗存在跨 turn 引用,只剔单 turn 会留下断章语义,LLM 仍可能抽出错的事实。保守选项是整 chunk 跳过,跨轮抽取的覆盖范围会有 hole 但比"漏抽 + 抽错"安全。
- **`archival_memory_insert` 不另查 source_label/target_label**:registry whitelist 已约束 entity_type;label 来源是 episode_text → evidence_quote 已经强制 substring 校验。攻击面已闭。
- **template substitution sanitize 暂不做**:`memory_tool_usage.md` 的 `{{persona_block}}` / `{{scratchpad_block}}` 在 Plan 6 supervisor 实际没接(`chat_planner.py` 走了独立的 `_PLANNER_PROMPT_TEMPLATE`),当前不是 immediate exploit。等加载点真接时再补 scrub layer。

## 测试守护

- **L0 unit** `backend/tests/unit/memory/test_injection_wiring.py`(新)— 11 case:
  - 异常类继承关系
  - extract / extract_facts 拦截 + LLM `chat` 未被调
  - core_memory_append / replace 拦截 + storage 调用未发生
  - regression: 安全输入仍正常通过
- **L1 integration** `backend/tests/integration/memory/test_mcp_tools_e2e.py`(扩)— 加 `test_archival_memory_insert_rejects_injection_in_episode`:真 PG seed 含 injection 的 episode,验证 raise + edge 0 行 + audit log 记 error
- **L2 e2e** `backend/tests/e2e/memory/test_poison_attacks.py`(扩)— 加 `test_extractor_blocks_all_attack_cases_via_production_path`:20 attack case 走 LLMExtractor.extract 真链路,block rate ≥ 0.95 + 用 `fake_llm.chat.call_count` 增量区分"被分类器拦截"vs"LLM 返空",杜绝 false-pass

ship 时 541 unit pass + 6/6 poison_attacks e2e pass + ruff/mypy strict 0 error。

## 已知未覆盖(留 S2 plan)

S1 修的是写入路径上的 prompt-injection 拦截,**memory poisoning 还有第二类威胁**(账号被黑后大批量虚构持仓注入)需要单独 plan,不在本次 ship 范围:
- mcp_tool_call_log 速率/异常 detection
- HOLDS 写入跟 v1.0 B-3 持仓监控对账
- 新设备 session quarantine + bulk-revoke API
- bi-temporal forensics rollback 工具

S2 这块工程量上要单独 plan 9,跟 S1 解耦。

## 关键文件 ref

- `backend/app/memory/injection_classifier.py` — `PromptInjectionDetectedError` 新增
- `backend/app/mcp_server/tools/memory/archival_memory_insert.py` — episode_text 检查接入
- `backend/app/mcp_server/tools/memory/core_memory_append.py` — content 检查接入
- `backend/app/mcp_server/tools/memory/core_memory_replace.py` — new_content 检查接入
- `backend/app/memory/extractor.py` — `extract` / `extract_facts` 前置过滤
- `backend/tests/unit/memory/test_injection_wiring.py` — L0 11 case 新
- `backend/tests/integration/memory/test_mcp_tools_e2e.py` — L1 1 case 扩
- `backend/tests/e2e/memory/test_poison_attacks.py` — L2 1 case 扩
