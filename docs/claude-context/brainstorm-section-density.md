---
name: brainstorm 阶段每节内容控制在决策密度,不做完整 spec dump
description: 用户在 spec 设计 brainstorm 中倾向短决策节,detail / code / prompt / resume 叙事推到 spec doc
type: feedback
---

brainstorm 阶段(section-by-section 推进设计决策)每节**只放跟决策强相关的 ~100 行**。Code 例子 / system prompt 模板 / 完整 trace / 简历叙事这些 gold-plating 内容**写进 spec doc**,**不**在 chat 展开。

**Why**:2026-05-10 C.5 cross-session memory brainstorm 中,作者反馈"每一点展开的内容太多,我看不过来"。我前 6 节(architecture / schema / ontology / write pipeline / read pipeline / tool API)每节 400-600 行,作者认知 overload。问题是 chat 阶段塞了应该等 spec doc 才需要的内容。

**How to apply**:
- brainstorm 节内容专注:**决策本身 + 关键 trade-off + 推荐方向**,~100 行封顶
- 完整 schema SQL / system prompt 全文 / pipeline trace / monitoring SQL / eval golden set / 简历叙事段 → **全部** 推到 spec doc
- 设计 alternative 比较 OK 保留(决策需要),但每个 alternative 1-2 句话讲 trade-off,不展开实现
- 多节有共同主题时考虑批量讲(例如 § 7-9 操作细节合一节),不要每节都全套铺开
- 用户问"展开 X" / "为什么 Y" 时再做深度 elaboration —— 让用户 pull 而不是 push

**作者风格 reaffirm**:作者要"撞工业难题 + 可讲性",但**深度展开放 spec doc**;chat 阶段只对齐方向。这跟 user_portfolio_target 不冲突 —— 深度依然在 deliverable 里,只是不在 chat 里。
