---
name: 9 个 use case 重新分类(3 支柱 + 组件 + 砍 2 个)
description: 之前"9 个 use case 共享底座"叙事是虚的,brainstorm 后重新分类 — 仅 3 个独立支柱,其他是组件或显式不做
type: project
---

之前 `docs/superpowers/specs/2026-05-03-product-positioning-v1-roadmap.md` § 3 列的 9 个 use case "共享底座"叙事是**虚的**:9 个里有 2 个该砍、4 个是组件、真独立只有 3 个。

**重新分类**(2026-05-07 brainstorm,sediment 在 `docs/superpowers/specs/2026-05-07-v1.0-portfolio-monitoring-design.md` § 1 决策 2):

```
独立支柱(3 个 — 真独立 use case):
  ├── B-1 深度尽调       — 长报告、5-10 分钟、慢思考(已 ship v0.8.4)
  ├── B-3+C-4 持仓监控   — 一体两面,后台 daemon + 用户视角(v1.0)
  └── C-3 事件追踪       — 时间线 + A 股标的映射(留 v1.x)

组件(寄生在支柱里):
  ├── B-7 报告追问       — 寄生在 B-1
  ├── C-1 个股研究       — 寄生在 B-3 持仓 / 升级到 B-1
  └── C-5 财报速读       — 寄生在 B-3 监控 / B-1 财务节

显式不做(ChatGPT 强项,我们做不过):
  ├── C-2 行业判断       — 通用 LLM 在宏观行业判断上强,KB 13 篇覆盖不了
  └── C-7 术语解释       — 通用 LLM 教学解释能力远超任何垂类产品
```

**Why**:用"能否独立打 ChatGPT"硬度测试发现 — C-2 / C-7 是 ChatGPT 强项做不过(留着稀释产品定位);C-1 / C-5 / B-7 真痛点只有 1.5 个,孤立看够不上单飞门槛(必须靠平台集成才成立);C-3 能独立打但工程跟 B-1 重复 + dogfood 频率低,留 v1.x。

**How to apply**:
- 后续讨论 use case 优先级时,只考虑 3 个支柱;组件随宿主走
- 简历叙事改成"**3 个支柱场景 + 组件式延伸,显式做了 use case 取舍砍掉 ChatGPT 强项的领域**" — "做减法的产品判断"是比"做加法的工程能力"更值钱的简历点
- 不要往 v1.0/v1.x 塞 C-2 / C-7 — 已显式不做
- v0.8.4 / v0.8.5 / v0.9.x 已 ship 的 5-agent + plan_registry + 6 节报告基建,主要是为 B-1 + 后续支柱准备
