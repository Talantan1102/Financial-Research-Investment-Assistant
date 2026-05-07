---
name: docs/claude-context/
description: 项目级 Claude 上下文 — 跨机/跨 session 共享的项目知识、设计决策、测试约定
---

# 这是什么

供 Claude Code（以及任何接手项目的人）参考的**项目级上下文**：

- 设计决策的 *why*（不是文档里"做了什么"那种 spec/plan，而是"为什么这么决定"）
- 测试约定 / fixture 模式 / 工程惯例
- 已 ship 阶段性里程碑的速记 + 已知坑

## 跟 `docs/superpowers/{specs,plans}/` 的区别

| 这里（`claude-context/`） | `superpowers/specs/` | `superpowers/plans/` |
|---|---|---|
| 短，**结论 + why + how to apply** | 长，决策评估全过程 | 长，逐步实施 task list |
| 给 Claude 当 working memory | 给人/agent 评估方案 | 给 agent 推 PR |
| 长期保留，老化即更新 | 一次性，spec 完成即定格 | 一次性，plan 跑完即归档 |

## 怎么被读到

仓库根 `CLAUDE.md` 链到这里。任何在本仓库工作的 Claude Code session 启动时会自动读 `CLAUDE.md`，进而引用本目录的卡片。

## 加新卡片

文件名小写中划线，YAML frontmatter 必填 `name` / `description` / `type`（`project | feedback | reference`）。`feedback` 和 `project` 类型的卡片正文用三段式：结论 + **Why** + **How to apply**。

加新卡片记得在 `CLAUDE.md` 里加一行索引指针。
