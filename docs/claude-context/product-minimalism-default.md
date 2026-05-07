---
name: 产品决策默认 aggressive minimalism
description: 作者在产品 brainstorm 中一贯倾向最克制版本,推荐时默认走克制 default,v1.x escape hatch 通过架构留口子方式提供
type: feedback
---

作者在产品 brainstorm 中**一贯倾向最克制版本**。这不是 timid,是有判断的克制 — broad 平台路线的最大风险是"什么都想做永远不 ship",克制对抗这个风险。

**Why**:2026-05-07 持仓监控 brainstorm session 中,作者在每个决策点都选最克制选项 —
- 静默仓位 / 价格触达 / Watch list / CSV 导入 / 券商 API / 推送 → 全推 v1.x
- 异动详情卡 D 区动作 → 砍("没必要")
- 30 分钟刷新 vs 我推的 5 分钟(更克制)
- 已查看回顾区 → 砍
- C-2 / C-7 use case → 砍
- 笔记全文搜索 / 持仓事件历史回看 → 砍

这不是孤立选择,是**贯穿整个 brainstorm 的产品 taste**。Broad 平台路线 § 2 自己也警告"永远在做基础设施看不到 ship"是最大风险,作者本能在对抗这个风险。

**How to apply**:
- **默认推荐克制版本**:在产品决策选项里,推荐时默认把"最克制"标为推荐选项,把"完整"标为可选
- **v1.x escape hatch 用架构留口子方式提供**:不要 v1.0 直接做完整功能,而是 v1.0 做最小子集 + 留接口口子,v1.x 平滑扩展。例子:推送通道接口预留空实现 / `is_silenced` 字段预留默认 false / multi-account user_id schema 留 UI 不暴露
- **不要预设用户行为路径**:作者反对"详情卡 D 区动作按钮"的理由是"不该 patronizing 用户" — 推荐 UI 时避免"自动引导用户下一步动作"的 over-engineering
- **质疑 ChatGPT 替代度**:任何 use case / 功能,先问"用户为什么不去用 ChatGPT?" — 不能给出 3-5 个真痛点的不该立项(C-2 / C-7 砍掉的逻辑)
- **不破坏一致克制气质**:已经定下"v1.0 不做 X"的决策,后续讨论中不要试图重提为"小 polish 加进去"。v1.x 一致性比 v1.0 完整性更重要
