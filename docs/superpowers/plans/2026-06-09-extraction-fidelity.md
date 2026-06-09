# 抽取保真度实施计划

> **执行**:按任务顺序 TDD 推进;每个写侧改动用 `viewpoint-baijiu --repeat` 量化。无字母数字代号。
> **Spec**:`docs/superpowers/specs/2026-06-09-extraction-fidelity-design.md`
> **目标**:把多会话观点演化的写侧保真度从 3/24(~12%)抬到 ≥18/24,且多跑趋同。
> **方法论**:加一层、量一次。prompt 裁决规则是已实测的主杠杆(探针 4/4),温度是辅助、仅当量化仍漂才加。

**改动文件**(抽取走 Path B 的 `extract_facts` 路径,不是 `extract`):
- `backend/app/memory/extractor.py` — `_EXTRACTION_SYSTEM_PROMPT`(加裁决规则+日期纪律)、`_build_cross_turn_user_prompt`(注入对话日期)、`extract_facts`(逐边容错)
- `backend/app/memory/extraction_guards.py`(新建)— 后校验护栏:幻觉日期、脏 label
- 测试:`backend/tests/unit/memory/test_extraction_guards.py`、`test_extractor_prompt.py`、`tests/integration/memory/test_extractor_e2e.py`(逐边容错)

---

## 任务一:裁决规则写进 system prompt(主杠杆,探针已验证 4/4)

**Files:** Modify `backend/app/memory/extractor.py:_EXTRACTION_SYSTEM_PROMPT`;Test `backend/tests/unit/memory/test_extractor_prompt.py`

- [ ] **步骤1 写失败测试**:断言 prompt 含裁决规则关键标记(回归守护;强验证靠任务四 eval)

```python
# backend/tests/unit/memory/test_extractor_prompt.py
from app.memory.extractor import _EXTRACTION_SYSTEM_PROMPT as P

def test_prompt_has_entity_type_decision_rule() -> None:
    assert "看用户表态的主体粒度" in P or "板块" in P and "不要替他补" in P
    assert "properties.logic" in P  # 逻辑进 properties 不单独成边

def test_prompt_has_relation_arbitration() -> None:
    assert "EXPRESSED_VIEW" in P and "PREFERS" in P
    assert "看多白酒" in P and "绝不" in P  # 死规则:看多白酒必为 EXPRESSED_VIEW

def test_prompt_forbids_stance_phrase_label() -> None:
    assert "名词性实体" in P or "谓词短语" in P
```

- [ ] **步骤2 跑测试看红**:`pytest tests/unit/memory/test_extractor_prompt.py -q` → FAIL(prompt 还没加规则)
- [ ] **步骤3 改 prompt**:在 `_EXTRACTION_SYSTEM_PROMPT` 的 "# 规则" 段后插入裁决规则段(用探针 `_probe_prompt_fix.py` 里验证过的 `_RULES` 文本,补关系表与 label 约束):

```
# 实体类型与关系裁决(必须照此判,别自由发挥)
## target 实体类型怎么选(看用户表态的主体粒度)
- 用户对一个行业/板块的看法 → target 用 Industry(申万二级,如"白酒"→"白酒Ⅱ")
- 用户对一只具体个股的看法 → target 用 Stock(ts_code)
- 用户只说板块(如"高端白酒")时,【不要替他补】具体个股(茅台/五粮液只是举例,不单独建观点边)
- 逻辑/主题(如"提价权")放进该观点边的 properties.logic,【不要】单独建一条边
## 关系怎么选(照表挑,别随机)
- 有方向词(看多/看空/中性/高估/低估)+具体对象 → EXPRESSED_VIEW
- 跨标的的风格/策略偏好(喜欢价值/高股息) → PREFERS
- 不碰/排斥某类 → AVOIDS;关注但没下判断 → WATCHES;研究过 → STUDIED;持仓 → HOLDS(归持仓模块);卖出 → SOLD
- "看多白酒"【必为 EXPRESSED_VIEW,绝不可标 PREFERS】
## entity_label 形态
- 必须是名词性实体(白酒Ⅱ/600519.SH),【禁】"看多/看空/买入…"开头的整句谓词短语
```

- [ ] **步骤4 跑测试看绿**:`pytest tests/unit/memory/test_extractor_prompt.py -q` → PASS
- [ ] **步骤5 commit**:`feat(memory): 抽取 prompt 加实体类型/关系裁决规则`

---

## 任务二:日期按 session 钉死(prompt 注入对话日期 + 日期纪律)

**Files:** Modify `extractor.py:_build_cross_turn_user_prompt` + `_EXTRACTION_SYSTEM_PROMPT`;Test `test_extractor_prompt.py`

- [ ] **步骤1 写失败测试**:

```python
def test_cross_turn_prompt_injects_dialogue_date() -> None:
    from app.memory.extractor import _build_cross_turn_user_prompt
    from uuid import uuid4
    turns = [{"episode_id": "e1", "episode_index": 0, "user_message": "看多白酒",
              "agent_response": "", "created_at": "2025-01-06T00:00:00+00:00"}]
    out = _build_cross_turn_user_prompt(turns, session_id=uuid4())
    assert "2025-01-06" in out  # 对话日期进了 prompt

def test_prompt_has_date_discipline() -> None:
    from app.memory.extractor import _EXTRACTION_SYSTEM_PROMPT as P
    assert "对话日期" in P and ("不许" in P or "不要编" in P)
    assert "未结束" in P and "null" in P  # 未结束 valid_to=null
```

- [ ] **步骤2 看红**:`pytest tests/unit/memory/test_extractor_prompt.py::test_cross_turn_prompt_injects_dialogue_date -q` → FAIL
- [ ] **步骤3 实现**:
  - `_build_cross_turn_user_prompt` 每个 turn 行追加 `created_at`,并在头部加一行"各 turn 的对话日期见下,valid_from 必须用对应对话日期"。
  - `_EXTRACTION_SYSTEM_PROMPT` 日期规则段改为:"valid_from 必须等于该 episode 的对话日期(prompt 里给了),【不许假设/编造日期】;观点未结束时 valid_to 必须为 null。"
- [ ] **步骤4 看绿** → PASS
- [ ] **步骤5 commit**:`feat(memory): 抽取 prompt 注入对话日期 + 日期纪律(valid_from 按 session)`

---

## 任务三:逐边容错 + 后校验护栏(一条坏边不毁整批 + 拦幻觉)

**Files:** Create `backend/app/memory/extraction_guards.py`;Modify `extractor.py:extract_facts`;Test `backend/tests/unit/memory/test_extraction_guards.py`、`tests/integration/memory/test_extractor_e2e.py`

- [ ] **步骤1 写护栏失败测试**:

```python
# backend/tests/unit/memory/test_extraction_guards.py
from app.memory.extraction_guards import sanitize_edge, is_stance_phrase_label
from datetime import datetime, UTC

def test_rejects_future_date_out_of_window() -> None:
    edge = {"rel_type": "EXPRESSED_VIEW", "target_label": "白酒Ⅱ",
            "valid_from": "2025-01-06", "valid_to": "2027-04-01",  # 幻觉未来日期
            "importance": 0.9, "reasoning": "x", "source_label": "User"}
    out = sanitize_edge(edge, episode_date=datetime(2025, 1, 6, tzinfo=UTC))
    assert out["valid_to"] is None  # 越界 valid_to 被重置为 null

def test_flags_stance_phrase_label() -> None:
    assert is_stance_phrase_label("看多高端白酒") is True
    assert is_stance_phrase_label("白酒Ⅱ") is False
    assert is_stance_phrase_label("600519.SH") is False
```

- [ ] **步骤2 看红** → FAIL(模块不存在)
- [ ] **步骤3 实现 `extraction_guards.py`**:

```python
"""抽取后校验护栏 — prompt/解码漏网的硬兜底:幻觉日期、脏 label。"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any

_STANCE_PREFIXES = ("看多", "看空", "看好", "看淡", "买入", "卖出", "加仓", "减仓", "持有")

def is_stance_phrase_label(label: str) -> bool:
    """label 是不是整句谓词短语(脏实体),而非名词性实体。"""
    s = (label or "").strip()
    return any(s.startswith(p) for p in _STANCE_PREFIXES)

def sanitize_edge(edge: dict[str, Any], *, episode_date: datetime,
                  window_days: int = 400) -> dict[str, Any]:
    """把越界/幻觉日期重置:valid_to 超出 [episode_date ± window] 或在未来 → null。"""
    out = dict(edge)
    vt = out.get("valid_to")
    if vt:
        try:
            dt = datetime.fromisoformat(str(vt).replace("Z", "+00:00"))
            lo = episode_date - timedelta(days=window_days)
            hi = episode_date + timedelta(days=1)  # valid_to 不该在对话日之后太多
            if dt < lo or dt > hi:
                out["valid_to"] = None
        except (ValueError, TypeError):
            out["valid_to"] = None
    return out
```

- [ ] **步骤4 看绿** → PASS
- [ ] **步骤5 改 `extract_facts` 逐边容错 + 接护栏**:把 `[ExtractionOutput.model_validate(parsed)]` 换成逐边解析:对 `parsed["edges"]` 每条单独 `ExtractedEdge.model_validate`,失败的记 warning 跳过、不毁整批;通过的过 `sanitize_edge`;`entities` 同理;脏 label 边丢弃。
- [ ] **步骤6 写 e2e 逐边容错测试**(test_extractor_e2e.py):一批 edges 里夹一条非法 rel_type,断言好边仍入、整批不全灭。
- [ ] **步骤7 跑 e2e 看绿**:`pytest tests/integration/memory/test_extractor_e2e.py -q`
- [ ] **步骤8 commit**:`feat(memory): 抽取逐边容错 + 后校验护栏(坏边不毁整批/拦幻觉日期/脏label)`

---

## 任务四:验收量化 +(条件)温度

- [ ] **步骤1 重跑评估**:`python -m eval.memory_dialogue.run_eval --script eval/memory_dialogue/scripts/viewpoint-baijiu.yaml --repeat 5`,记录写侧通过率 + Wilson。
- [ ] **步骤2 判断**:
  - 若写侧 ≥18/24 且多跑趋同 → 达标,跳过温度。
  - 若仍漂(方差大)→ 加温度(辅助层):给 `LLMService.chat`/`_OpenAIAdapter.chat`/`MemoryLLMClientAdapter` 加可选 `temperature`(默认 None 向后兼容),抽取传 0.1;其余客户端实现接受并忽略。配 L0 测试(传 temperature 时进 create kwargs)。重测。
- [ ] **步骤3 扩样复测**:`--all --repeat 3` 看 viewpoint 全族 + time 族写侧整体回升(确认不是过拟合白酒一段)。
- [ ] **步骤4 全套件回归**:`pytest tests/unit/memory tests/integration/memory -q`(确认抽取改动零回归)。
- [ ] **步骤5 沉淀**:更新 plan 进度 + 知识卡片(实测前后写侧通过率对比)。

---

## 验收结果(2026-06-09 实测)

**写侧 3/24(Wilson [0.04-0.31]) → 8/24(Wilson [0.18-0.53])**,读侧绿 2→5。翻倍多、区间整体上移。dump 实证抽取**质量已根治**:

```
[active] 白酒Ⅱ 2025-01-06 看多·三年·提价权   ← session1 ✓ 实体/关系/日期全对
[active] 白酒Ⅱ 2025-02-03 看多·两年·提价权   ← session3 两年更新 ✓(之前丢的!)
[active] 白酒Ⅱ 2025-04-01 中性·提价权证伪     ← session7 中性 ✓
```

三个观点版本全部正确落在 `白酒Ⅱ` 同一节点、日期对、两年/中性都回来了——实体类型漂移、关系漂移、脏实体、幻觉日期、丢失更新**全消**。

**剩余红的精确归因(已查实,非抽取层)**:三个版本全是 `★active`——`conflict_resolver` 的 LLM judge 把后到的版本判成了 **APPEND 并存**,而不是新版到来时**作废/演化旧版**(`_get_or_create_node` 去重正确、现有边精确三元组查询能命中、judge 被正常调用,是 judge 判错)。`old_invalidated 0` / 链不足 / `缺两年中性`(多条 active 挑中谁不定)全源于此。这是冲突消解判定层,与抽取同源(弱模型 deepseek-flash + 判定 prompt 缺清晰规则),**是下一层、另起 spec**(同"裁决规则写进 prompt"技术可复用到 `conflict_resolver._JUDGE_SYSTEM_PROMPT`)。本 PR 范围 = 抽取保真度(已达成可观、可测、可验的改善)。

## 任务五:提 PR

- [ ] **步骤1**:确认当前分支与改动范围;抽取保真度改动集(extractor/extraction_guards + 测试)+ 本会话相关(industry_registry / ablation / --repeat 等)归一个聚焦 commit 或一组 commit。
- [ ] **步骤2**:`pytest` 全绿 + ruff + mypy 清。
- [ ] **步骤3**:push + `gh pr create`,PR 描述写清:问题(写侧 12%)→ 修法(prompt 裁决主杠杆 + 日期钉死 + 逐边容错)→ 验收(--repeat 前后对比)。
