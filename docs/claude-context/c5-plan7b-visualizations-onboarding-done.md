---
name: c5-plan7b-visualizations-onboarding-done
description: C.5 Plan 7B (Frontend 三视图 + 用户心智 onboarding + 月度邮件 spec) ship — Cytoscape graph / Timeline / Audit + onboarding modal + 显式提及 + email body generator
type: project
---

C.5 Plan 7B (Frontend Visualizations + 用户心智 Onboarding + 月度邮件 Spec) ship — 2026-05-11.

## ship 范围

### Frontend 三视图 (spec § 9)

- **MemoryGraph** (`frontend/src/components/memory/MemoryGraph.tsx`):
  Cytoscape.js graph viz, 7 entity_type 颜色, 11 rel_type 中文 label,
  bi-temporal 状态视觉编码 (实线 current / 虚线 ended / 点线 invalidated),
  edge tap 弹 antd Drawer 详情, `highlightEdgeId` prop 接 chat 跳转
- **MemoryTimeline** (`frontend/src/components/memory/MemoryTimeline.tsx`):
  横向时间轴 (纯 SVG/CSS + dayjs, 不引第三方 timeline 库), rel_type 选择 +
  entity 关键字筛 + bar tooltip
- **MemoryAuditLog** (`frontend/src/components/memory/MemoryAuditLog.tsx`):
  antd Table 列 invalidated_at DESC 历史 + Switch 切到 active edge 列表 +
  Popconfirm 一键否决 (单 edge invalidate, cascade 留 P3)

### #8 算法深度补丁 (spec § 11 末尾 #8) 完整覆盖

- **(a) Agent 显式提及来源**: chat `TextMessage.tsx` 识别 `[查看](#mem-{edge_id})`
  anchor → `useNavigate('/memory?highlight_edge={edge_id}')` + MemoryGraph
  接收 highlight_edge 高亮 cytoscape edge
- **(b) Onboarding modal** (`frontend/src/components/memory/MemoryOnboardingModal.tsx`):
  AppShell 顶层一次性挂载, 800ms 微延迟弹窗 (避撞登录 modal), localStorage
  `memory_onboarding_seen_v1` 标记不重弹; 4 类自动记录信息 + 3 项用户控制权
- **(c) 月度邮件 spec backend** (`backend/app/services/memory_email.py`):
  `generate_monthly_digest(session, user_id, ...)` ship body 生成函数 +
  L0/L1 测试; **不 ship 实际发送** (留 P3 hook + Scale-2 用户回路一起做)

### 测试

- vitest unit (Plan 7B 范围 10 文件): 32 项 pass
  - cytoscape smoke (2) + MemoryGraph (5) + MemoryTimeline (4) +
    MemoryAuditLog (4) + MemoryOnboardingModal (3) + TextMessage (9, +2 mem
    anchor case) + memory page index (2) + appshell tests (3)
- Playwright e2e: Plan 7B `tests/e2e/memory-views.spec.ts` 4 项 pass + 1 skip
  (chat anchor dogfood); Plan 7A `memory-page.spec.ts` 3 项 pass
  (placeholder 断言已替换为 empty state)
- backend memory_email: L0 unit 5 项 pass (render / empty / unknown rel /
  invalidate URL / empty 模板) + L1 integration 2 项 pass (top_n 截断 /
  invalidated 不进 digest)
- mypy strict: backend memory_email pass

## 关键决策 (实施期撞实)

- **Cytoscape jsdom 兼容**: cytoscape 实例化在 jsdom 撞 `getContext` 返回
  null → `textureOnViewport` undefined 报错。vitest 用 `vi.mock('react-cytoscapejs')`
  替成空 div 跳过 mount; 真 layout 由 Playwright e2e (chromium) 验
- **Cytoscape 选 cose layout**: dogfood 数据量 (单用户 ~50-200 edge) 下
  force-directed 比 dagre / breadthfirst 更直观; 真上量 1000+ edge 后切
  cola layout 增量 render (P3 hook)
- **Timeline 不引第三方库**: 评估 vis-timeline / react-calendar-timeline
  都 200KB+, 单视图不值得; 纯 SVG/CSS + dayjs ~150 LoC 够用
- **antd Popconfirm 中文按钮空格**: antd v5 自动在中文按钮文本中插入空格
  ("否 决" 不是 "否决"), vitest assertion 改用 `findByRole('button',
  { name: /^否\s*决$/ })` 兼容
- **fakeTimers + waitFor 死锁规避**: `vi.useFakeTimers` 在 React 19 + waitFor
  组合下偶发死锁 (microtask scheduler 冲突); MemoryOnboardingModal vitest
  改用真 setTimeout (3 项总耗时 ~3.6s 可接受)
- **TextMessage 现需 router context**: 加 `useNavigate` 后所有
  `<TextMessage>` 调用方需 `<MemoryRouter>` 包一层; 老 7 case 同步更新
- **memory_email sync Session**: 项目 memory 表统一 `sqlalchemy.orm.Session`
  (跟 memory_router / hierarchical 一致), 不引 AsyncSession 异步分歧
- **mypy ORM column attr 转 str**: ORM 实例的 column (`edge.rel_type`) 在
  mypy 下推 `Column[str]`, 显式 `str(edge.rel_type)` 转 str 才 pass
  REL_TYPE_LABELS_ZH.get
- **Plan 7A 测试同步更新**: 三 placeholder testid 被替换为真组件 →
  Plan 7A index.test.tsx + memory-page.spec.ts 把 placeholder 断言改成
  对应 empty state 文本 (此偏离 plan 文件描述但属合理协同)
- **AppShell 挂 onboarding**: 跟 plan 推荐的 App.tsx 顶层不同, 改挂 AppShell
  内部 (AuthGuard 之内, logout 用户不会撞 onboarding); 同时也避免 ThemedRoot
  / login / register 路径误弹
- **e2e Playwright 路由顺序**: 跟 Plan 7A memory-page.spec.ts 一致, 先
  `**` catch-all 再具体 endpoint (Playwright 后注册的 wins)

## 跟 spec 决策对齐

- spec § 9 视图 1/2/3 全部 ship
- spec § 11 末尾 #8 (a)(b)(c) 三补丁全部覆盖
- spec § 11 末尾 #8 验证目标 "用户调研 5 人首次 session 后 4/5 知道有 memory
  系统": Plan 7B 提供机制 (modal + 显式提及), 实际调研留 dogfood 阶段验
- spec 月度邮件打开率 ≥ 30%: 实际发送 P3 后才能收集

## 关键文件 ref

### Frontend
- `frontend/src/components/memory/MemoryGraph.tsx` (+ `.styles.ts`)
- `frontend/src/components/memory/MemoryTimeline.tsx`
- `frontend/src/components/memory/MemoryAuditLog.tsx`
- `frontend/src/components/memory/MemoryOnboardingModal.tsx`
- `frontend/src/components/memory/__tests__/*.test.tsx` (5 文件)
- `frontend/src/components/chat/TextMessage.tsx` (改造识别 mem anchor)
- `frontend/src/layout/app-shell/index.tsx` (挂 onboarding)
- `frontend/src/pages/memory/index.tsx` (Plan 7A ship, 7B 挂三 tab)
- `frontend/tests/e2e/memory-views.spec.ts` (Plan 7B Playwright)

### Backend
- `backend/app/services/memory_email.py`
- `backend/tests/unit/services/test_memory_email.py`
- `backend/tests/integration/memory/test_memory_email_e2e.py`

### Deps
- `frontend/package.json` 加 cytoscape ^3.30 (resolved 3.33.3) +
  react-cytoscapejs ^2.0 + @types/cytoscape ^3.21

## P3 hook ref (留待 v1.x)

1. **邮件实际发送** (`backend/app/tasks/memory_email_worker.py`)
   - 触发: Scale-2 "用户回路 first-class" 上线
   - 实施: Celery monthly cron + SMTP/SendGrid + unsubscribe 链接处理 +
     调 `app.services.memory_email.generate_monthly_digest()` 取 body
2. **Memory edge edit** (改 edge 内容)
   - 触发: dogfood 反馈 "否决太重, 只是想改个数字"
   - 实施: bi-temporal 改写 (原 edge invalidate + 新 edge insert with same
     valid_from)
   - 文件: `frontend/src/components/memory/MemoryEditModal.tsx` + backend
     `PATCH /api/v0/memory/edges/{edge_id}`
3. **Cascade invalidate** (削 HOLDS 自动连带相关 EXPRESSED_VIEW)
   - 触发: dogfood 撞实 "否决了 HOLDS 茅台, 但 EXPRESSED_VIEW 茅台还在"
   - 实施: LLM 判断 cascade 候选 + 用户确认 UI
   - 文件: `backend/app/memory/cascade_resolver.py`
4. **Backend prompt 集成 [查看](#mem-...) anchor 输出**
   - Plan 7B 只 ship frontend 识别 + onboarding 文案承诺 "我会显式提示";
     backend archival_memory_search result formatter 改让 LLM 输出含
     `[查看](#mem-{edge_id})` 留 Plan 4 result template Edit 或 Plan 8
     dogfood phase 补
5. **AlphaScout chat landing 品牌 / onboarding 不交叉**
   - landing.spec.ts 在 main HEAD 已 fail (chat landing 仍用旧品牌
     "Financial Research Assistant"); 修 chat landing 品牌不在 Plan 7B 范围
