# C.5 Plan 7B — Frontend 可视化 + 用户心智 Onboarding + 月度邮件 Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan 7A 已 ship `/memory` 路由 + 5 endpoint API + `memory-api.ts` client。Plan 7B 在此底座上 ship 三视图可视化(MemoryGraph / MemoryTimeline / MemoryAuditLog)+ 用户心智 #8 算法深度补丁(显式提及来源 + onboarding modal + 月度邮件 spec backend stub)。

**Architecture:**
- 三视图组件在 `frontend/src/components/memory/` 下,共用 Plan 7A 的 `memory-api.ts` 拉数据
- MemoryGraph 用 cytoscape + react-cytoscapejs(本 Plan Task 1 加依赖),7 节点类型不同颜色 + 11 边类型 hover detail + bi-temporal 状态视觉编码(实线/虚线/灰)
- MemoryTimeline 用纯 SVG/CSS 横向时间轴(不引第三方 timeline 库,避免无谓依赖膨胀),支持 rel_type / entity 筛选 + edge hover detail
- MemoryAuditLog 用 antd Table 列 invalidated_at DESC,显示 invalidated reason + 一键否决(单 edge,不做 cascade — cascade 留 P3)
- MemoryOnboardingModal 用 antd Modal,首次 session 强弹窗,localStorage key `memory_onboarding_seen_v1` 标记不重复
- Chat message renderer 改造(`frontend/src/components/chat/TextMessage.tsx` 已有)识别 `[查看](#mem-{edge_id})` anchor pattern,渲染成跳转 `/memory?highlight_edge={edge_id}` 的 link
- Backend `app/services/memory_email.py` 提供 `generate_monthly_digest(user_id) -> str` 函数返 markdown body,**不 ship 实际发送**(P3 hook)

**Tech Stack:**
- Frontend:复用 antd 5.24 + react 19 + react-router-dom 6.29 + vitest + playwright(都已在 package.json)
- 新加 frontend deps:`cytoscape@^3.30` + `react-cytoscapejs@^2.0`(Task 1 装)
- Backend:复用 SQLAlchemy / asyncpg(Plan 1 已 ship 的 4 PG 表 model),不引模板引擎,markdown 直接 f-string 拼

**Source Spec:** `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md` § 9(/memory page UI)+ § 11 末尾 #8(用户心智模型 + 信任危机)

**Shared Contracts:** `docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md` § 1(file structure)+ § 6(test fixture)+ § 10(API endpoints)

**Plan 7B 不在范围**(留 P3 / 后续 Plan):
- ❌ 邮件 service 实际发送(SMTP / SendGrid 等;留 P3 hook,跟 Scale-2 用户回路一起做)
- ❌ Memory edge edit(改 edge 内容)— P3 hook,涉及 bi-temporal 改写
- ❌ Memory edge invalidate cascade(削掉一条 HOLDS 自动连带相关 EXPRESSED_VIEW)— P3 hook
- ❌ Routing eval / 50 golden case — Plan 8
- ❌ /memory 路由 + 5 backend endpoint(Plan 7A 已 ship)
- ❌ 6 MCP tool / 3-way hybrid 检索(Plan 3/4)

**工期估算:2.5 天 wall time**(Task 1 装依赖 0.2 天 + Task 2-4 三视图组件 1.3 天 + Task 5 onboarding modal 0.2 天 + Task 6 chat 显式提及 0.3 天 + Task 7 邮件 spec backend 0.3 天 + Task 8 e2e + 收束 0.2 天)

---

## File Structure

```
frontend/
├── package.json                                  # 改 (Task 1):加 cytoscape + react-cytoscapejs
├── src/
│   ├── components/memory/
│   │   ├── MemoryGraph.tsx                       # 新 (Task 2) ~180 LoC
│   │   ├── MemoryGraph.styles.ts                 # 新 (Task 2) 颜色 / 边样式常量 ~40 LoC
│   │   ├── MemoryTimeline.tsx                    # 新 (Task 3) ~150 LoC
│   │   ├── MemoryAuditLog.tsx                    # 新 (Task 4) ~100 LoC
│   │   ├── MemoryOnboardingModal.tsx             # 新 (Task 5) ~80 LoC
│   │   └── __tests__/
│   │       ├── MemoryGraph.test.tsx              # 新 (Task 2) 5 项 vitest
│   │       ├── MemoryTimeline.test.tsx           # 新 (Task 3) 4 项 vitest
│   │       ├── MemoryAuditLog.test.tsx           # 新 (Task 4) 4 项 vitest
│   │       └── MemoryOnboardingModal.test.tsx    # 新 (Task 5) 3 项 vitest
│   ├── components/chat/
│   │   └── TextMessage.tsx                       # 改 (Task 6):识别 [查看](#mem-...) anchor
│   ├── components/chat/__tests__/
│   │   └── TextMessage.test.tsx                  # 改 (Task 6):加 memory link 渲染 case
│   ├── app/memory/page.tsx                       # 改 (Task 2/3/4):挂三视图(Plan 7A 已建空 page)
│   └── lib/memory-api.ts                         # 复用 (Plan 7A ship)
└── playwright/
    └── memory.spec.ts                            # 新 (Task 8) ~120 LoC e2e

backend/
├── app/services/
│   ├── memory_email.py                           # 新 (Task 7) ~120 LoC
│   └── __init__.py                               # 不动
└── tests/
    ├── unit/services/
    │   └── test_memory_email.py                  # 新 (Task 7) 4 项 L0
    └── integration/services/
        └── test_memory_email_integration.py      # 新 (Task 7) 2 项 L1

docs/claude-context/
└── c5-plan7b-visualizations-onboarding-done.md   # 新 (Task 8) 知识卡
```

**严守契约 § 1**:Plan 7A + Plan 7B 共用 `frontend/src/app/memory/page.tsx` + `frontend/src/components/memory/*`。即使现仓 Vite + React Router 风格主体在 `pages/`,Plan 7A 已按契约 § 1 建立 `app/memory/page.tsx` 路径(Plan 7A 自带 router 注册)。Plan 7B 严格沿用,不重定义。

---

## Task 1: 加 cytoscape 依赖 + smoke test 初始化

**Why this task:** Cytoscape 是 visualization 主依赖,先单独装 + smoke test verify 可以 import + 初始化空 graph,免得在 Task 2 实施时撞 SSR / version / type 问题。

**Files:**
- Modify: `frontend/package.json` — 加 cytoscape + react-cytoscapejs + 类型
- Create: `frontend/src/components/memory/__tests__/cytoscape.smoke.test.tsx` — smoke test

- [ ] **Step 1: 装依赖**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
pnpm add cytoscape@^3.30 react-cytoscapejs@^2.0
pnpm add -D @types/cytoscape@^3.21
```

如本仓用 npm 改 `npm install ...`(本仓 README / CI 验证)。

- [ ] **Step 2: 写 smoke test**

```tsx
// frontend/src/components/memory/__tests__/cytoscape.smoke.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import CytoscapeComponent from "react-cytoscapejs";
import cytoscape from "cytoscape";

describe("cytoscape smoke", () => {
  it("可以 import cytoscape 库", () => {
    expect(cytoscape).toBeDefined();
    expect(typeof cytoscape).toBe("function");
  });

  it("可以渲染空 cytoscape 组件", () => {
    const elements = [{ data: { id: "a" } }];
    const { container } = render(
      <CytoscapeComponent
        elements={elements}
        style={{ width: "100px", height: "100px" }}
      />,
    );
    expect(container).toBeTruthy();
  });
});
```

- [ ] **Step 3: 跑 smoke test**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
pnpm vitest run src/components/memory/__tests__/cytoscape.smoke.test.tsx
```

预期 2 项 pass。如 jsdom 抱怨 canvas missing:smoke test 仅验 import / render-not-throw,不验真实 layout(graph 的 layout 算法依赖真 canvas,留 playwright e2e 验)。

- [ ] **Step 4: 验 build 通过(无 type error)**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
pnpm build 2>&1 | tail -30
```

如 react-cytoscapejs 的 type 不全,加 `frontend/src/types/react-cytoscapejs.d.ts` 一行 `declare module 'react-cytoscapejs';`,但**优先用官方 type**。

- [ ] **Step 5: commit**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/components/memory/__tests__/cytoscape.smoke.test.tsx
git commit -m "feat(c5-plan7b): add cytoscape + react-cytoscapejs deps + smoke test"
```

---

## Task 2: MemoryGraph.tsx — Cytoscape graph viz(7 节点类型 + 11 边类型 + bi-temporal 视觉编码)

**Why this task:** spec § 9 视图 1 主体。让用户**可视化**自己的 memory graph,7 类节点(User / Stock / Industry / Sector / Metric / Strategy / Concept)用不同颜色,11 类 rel_type 在 hover 时显示 detail,bi-temporal 状态(current / ended / invalidated)用线型区分。

**Files:**
- Create: `frontend/src/components/memory/MemoryGraph.styles.ts` — 颜色 / 边样式常量
- Create: `frontend/src/components/memory/MemoryGraph.tsx`
- Create: `frontend/src/components/memory/__tests__/MemoryGraph.test.tsx`
- Modify: `frontend/src/app/memory/page.tsx` — Plan 7A 已建,挂 `<Tabs>` 含 `<MemoryGraph />`

- [ ] **Step 1: 写 styles.ts(常量先,方便 test 引用)**

```ts
// frontend/src/components/memory/MemoryGraph.styles.ts
export const ENTITY_COLORS: Record<string, string> = {
  User: "#1890ff",       // 蓝 - 自己
  Stock: "#52c41a",      // 绿 - 持仓 / 标的
  Industry: "#fa8c16",   // 橙 - 申万行业
  Sector: "#faad14",     // 黄 - 概念板块
  Metric: "#722ed1",     // 紫 - 指标
  Strategy: "#eb2f96",   // 粉 - 策略
  Concept: "#13c2c2",    // 青 - 抽象概念
};

export const ENTITY_FALLBACK_COLOR = "#d9d9d9";

export const REL_TYPE_LABELS: Record<string, string> = {
  HOLDS: "持仓",
  WATCHES: "关注",
  PREFERS: "偏好",
  AVOIDS: "回避",
  EXPRESSED_VIEW: "表态",
  SOLD: "卖出",
  STUDIED: "研究",
  COMPARED: "对比",
  BELONGS_TO: "属于",
  HAS_CONCEPT: "含概念",
  CORRELATED_WITH: "相关",
};

export const EDGE_STYLE_BY_STATUS = {
  current: { lineStyle: "solid", color: "#262626", width: 2 },     // 实线黑 - 当前 (valid_to=NULL)
  ended: { lineStyle: "dashed", color: "#8c8c8c", width: 1.5 },     // 虚线灰 - 历史 (valid_to set)
  invalidated: { lineStyle: "dotted", color: "#bfbfbf", width: 1 }, // 点线浅灰 - 撤销 (invalidated_at set)
};

export type GraphNode = {
  node_id: string;
  entity_type: string;
  entity_label: string;
  properties?: Record<string, unknown>;
};

export type GraphEdge = {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  rel_type: string;
  valid_from: string;
  valid_to: string | null;
  invalidated_at: string | null;
  importance: number;
  reasoning: string | null;
};

export function classifyEdgeStatus(edge: GraphEdge): "current" | "ended" | "invalidated" {
  if (edge.invalidated_at) return "invalidated";
  if (edge.valid_to) return "ended";
  return "current";
}
```

- [ ] **Step 2: 写 MemoryGraph.tsx**

```tsx
// frontend/src/components/memory/MemoryGraph.tsx
import { useEffect, useMemo, useRef, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import type { Core, ElementDefinition } from "cytoscape";
import { Spin, Empty, Drawer, Descriptions, Tag } from "antd";
import { fetchMemoryGraph } from "@/lib/memory-api";
import {
  ENTITY_COLORS,
  ENTITY_FALLBACK_COLOR,
  REL_TYPE_LABELS,
  EDGE_STYLE_BY_STATUS,
  classifyEdgeStatus,
  type GraphNode,
  type GraphEdge,
} from "./MemoryGraph.styles";

interface Props {
  highlightEdgeId?: string | null;  // Task 6 chat 跳转过来时高亮某条 edge
}

export default function MemoryGraph({ highlightEdgeId }: Props) {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchMemoryGraph()
      .then((data) => {
        if (cancelled) return;
        setNodes(data.nodes);
        setEdges(data.edges);
        setError(null);
      })
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  // 高亮跳转的 edge(Task 6 用)
  useEffect(() => {
    if (!cyRef.current || !highlightEdgeId) return;
    const cy = cyRef.current;
    cy.elements().removeClass("highlighted");
    const target = cy.getElementById(highlightEdgeId);
    if (target.length > 0) {
      target.addClass("highlighted");
      cy.center(target);
    }
  }, [highlightEdgeId, edges]);

  const elements: ElementDefinition[] = useMemo(() => {
    const nodeEls: ElementDefinition[] = nodes.map((n) => ({
      data: {
        id: n.node_id,
        label: n.entity_label,
        entity_type: n.entity_type,
      },
    }));
    const edgeEls: ElementDefinition[] = edges.map((e) => ({
      data: {
        id: e.edge_id,
        source: e.source_node_id,
        target: e.target_node_id,
        rel_type: e.rel_type,
        rel_label: REL_TYPE_LABELS[e.rel_type] ?? e.rel_type,
        status: classifyEdgeStatus(e),
      },
    }));
    return [...nodeEls, ...edgeEls];
  }, [nodes, edges]);

  const stylesheet = useMemo(
    () => [
      {
        selector: "node",
        style: {
          "background-color": (ele: cytoscape.NodeSingular) =>
            ENTITY_COLORS[ele.data("entity_type")] ?? ENTITY_FALLBACK_COLOR,
          label: "data(label)",
          "font-size": 11,
          "text-valign": "center",
          "text-halign": "center",
          color: "#fff",
          width: 40,
          height: 40,
        },
      },
      {
        selector: "edge",
        style: {
          width: (ele: cytoscape.EdgeSingular) =>
            EDGE_STYLE_BY_STATUS[ele.data("status") as keyof typeof EDGE_STYLE_BY_STATUS]
              ?.width ?? 1,
          "line-color": (ele: cytoscape.EdgeSingular) =>
            EDGE_STYLE_BY_STATUS[ele.data("status") as keyof typeof EDGE_STYLE_BY_STATUS]
              ?.color ?? "#bfbfbf",
          "line-style": (ele: cytoscape.EdgeSingular) =>
            EDGE_STYLE_BY_STATUS[ele.data("status") as keyof typeof EDGE_STYLE_BY_STATUS]
              ?.lineStyle ?? "solid",
          "target-arrow-shape": "triangle",
          "target-arrow-color": (ele: cytoscape.EdgeSingular) =>
            EDGE_STYLE_BY_STATUS[ele.data("status") as keyof typeof EDGE_STYLE_BY_STATUS]
              ?.color ?? "#bfbfbf",
          "curve-style": "bezier",
          label: "data(rel_label)",
          "font-size": 9,
          "text-rotation": "autorotate",
        },
      },
      {
        selector: "edge.highlighted",
        style: {
          "line-color": "#fa541c",
          "target-arrow-color": "#fa541c",
          width: 4,
          "z-index": 999,
        },
      },
    ],
    [],
  );

  if (loading) return <Spin size="large" />;
  if (error) return <Empty description={`加载失败:${error}`} />;
  if (nodes.length === 0)
    return <Empty description="还没有 memory — 先聊几条试试" />;

  return (
    <>
      <CytoscapeComponent
        elements={elements}
        stylesheet={stylesheet as never}
        layout={{ name: "cose", animate: false }}
        style={{ width: "100%", height: "600px", background: "#fafafa" }}
        cy={(cy: Core) => {
          cyRef.current = cy;
          cy.on("tap", "edge", (evt) => {
            const edgeId = evt.target.id();
            const found = edges.find((e) => e.edge_id === edgeId);
            if (found) setSelectedEdge(found);
          });
        }}
      />
      <Drawer
        open={!!selectedEdge}
        onClose={() => setSelectedEdge(null)}
        title="Memory Edge 详情"
        width={420}
      >
        {selectedEdge && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="关系">
              {REL_TYPE_LABELS[selectedEdge.rel_type] ?? selectedEdge.rel_type}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={
                classifyEdgeStatus(selectedEdge) === "current" ? "green" :
                classifyEdgeStatus(selectedEdge) === "ended" ? "orange" : "default"
              }>
                {classifyEdgeStatus(selectedEdge)}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="valid_from">{selectedEdge.valid_from}</Descriptions.Item>
            <Descriptions.Item label="valid_to">
              {selectedEdge.valid_to ?? "(进行中)"}
            </Descriptions.Item>
            <Descriptions.Item label="importance">{selectedEdge.importance}</Descriptions.Item>
            <Descriptions.Item label="reasoning">{selectedEdge.reasoning ?? "—"}</Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </>
  );
}
```

- [ ] **Step 3: 写 vitest(5 项)**

```tsx
// frontend/src/components/memory/__tests__/MemoryGraph.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import MemoryGraph from "../MemoryGraph";
import * as api from "@/lib/memory-api";
import { classifyEdgeStatus, type GraphEdge } from "../MemoryGraph.styles";

vi.mock("@/lib/memory-api");

const mkEdge = (overrides: Partial<GraphEdge> = {}): GraphEdge => ({
  edge_id: "e1",
  source_node_id: "n1",
  target_node_id: "n2",
  rel_type: "HOLDS",
  valid_from: "2025-01-01",
  valid_to: null,
  invalidated_at: null,
  importance: 0.9,
  reasoning: null,
  ...overrides,
});

describe("MemoryGraph", () => {
  beforeEach(() => vi.resetAllMocks());

  it("loading 时渲染 Spin", () => {
    vi.mocked(api.fetchMemoryGraph).mockReturnValue(new Promise(() => {}));
    render(<MemoryGraph />);
    expect(document.querySelector(".ant-spin")).toBeTruthy();
  });

  it("空 graph 渲染 Empty 提示", async () => {
    vi.mocked(api.fetchMemoryGraph).mockResolvedValue({ nodes: [], edges: [] });
    render(<MemoryGraph />);
    await waitFor(() => expect(screen.getByText(/还没有 memory/)).toBeTruthy());
  });

  it("API 报错时渲染错误提示", async () => {
    vi.mocked(api.fetchMemoryGraph).mockRejectedValue(new Error("network down"));
    render(<MemoryGraph />);
    await waitFor(() =>
      expect(screen.getByText(/加载失败.*network down/)).toBeTruthy(),
    );
  });

  it("classifyEdgeStatus 正确区分 current / ended / invalidated", () => {
    expect(classifyEdgeStatus(mkEdge())).toBe("current");
    expect(classifyEdgeStatus(mkEdge({ valid_to: "2025-06-01" }))).toBe("ended");
    expect(classifyEdgeStatus(mkEdge({ invalidated_at: "2025-09-01" }))).toBe(
      "invalidated",
    );
  });

  it("有 nodes 时渲染 cytoscape 容器", async () => {
    vi.mocked(api.fetchMemoryGraph).mockResolvedValue({
      nodes: [
        { node_id: "n1", entity_type: "User", entity_label: "我" },
        { node_id: "n2", entity_type: "Stock", entity_label: "茅台" },
      ],
      edges: [mkEdge()],
    });
    const { container } = render(<MemoryGraph />);
    await waitFor(() =>
      expect(container.querySelector('[data-id], canvas')).toBeTruthy(),
    );
  });
});
```

- [ ] **Step 4: 把 MemoryGraph 挂到 page.tsx(Plan 7A 已建)**

```tsx
// frontend/src/app/memory/page.tsx — 改造
import { useSearchParams } from "react-router-dom";
import { Tabs } from "antd";
import MemoryGraph from "@/components/memory/MemoryGraph";

export default function MemoryPage() {
  const [searchParams] = useSearchParams();
  const highlightEdge = searchParams.get("highlight_edge");

  return (
    <div style={{ padding: 24 }}>
      <h1>我的 Memory</h1>
      <Tabs
        defaultActiveKey="graph"
        items={[
          {
            key: "graph",
            label: "Graph",
            children: <MemoryGraph highlightEdgeId={highlightEdge} />,
          },
          // Timeline / Audit 在 Task 3/4 加
        ]}
      />
    </div>
  );
}
```

- [ ] **Step 5: 跑 vitest + commit**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
pnpm vitest run src/components/memory/__tests__/MemoryGraph.test.tsx
```

预期 5 项 pass。

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
git add frontend/src/components/memory/MemoryGraph.tsx \
  frontend/src/components/memory/MemoryGraph.styles.ts \
  frontend/src/components/memory/__tests__/MemoryGraph.test.tsx \
  frontend/src/app/memory/page.tsx
git commit -m "feat(c5-plan7b): MemoryGraph cytoscape viz with bi-temporal edge styling"
```

---

## Task 3: MemoryTimeline.tsx — 横向时间轴 view

**Why this task:** spec § 9 视图 2。让用户看自己对某 entity 的观点 / 持仓**演化轨迹**(例:2024-08 重仓茅台 → 2025-03 卖出 → 2025-09 重买)。

**Files:**
- Create: `frontend/src/components/memory/MemoryTimeline.tsx`
- Create: `frontend/src/components/memory/__tests__/MemoryTimeline.test.tsx`
- Modify: `frontend/src/app/memory/page.tsx` — 加 timeline tab

- [ ] **Step 1: 写 MemoryTimeline.tsx(纯 SVG/CSS,不引第三方 timeline)**

```tsx
// frontend/src/components/memory/MemoryTimeline.tsx
import { useEffect, useMemo, useState } from "react";
import { Spin, Empty, Select, Input, Tag, Tooltip } from "antd";
import dayjs from "dayjs";
import { fetchMemoryTimeline } from "@/lib/memory-api";
import { REL_TYPE_LABELS, classifyEdgeStatus, type GraphEdge } from "./MemoryGraph.styles";

const REL_COLORS: Record<string, string> = {
  HOLDS: "#52c41a",
  SOLD: "#ff4d4f",
  WATCHES: "#1890ff",
  PREFERS: "#13c2c2",
  AVOIDS: "#faad14",
  EXPRESSED_VIEW: "#722ed1",
  STUDIED: "#eb2f96",
};

interface TimelineEdge extends GraphEdge {
  source_label: string;
  target_label: string;
}

export default function MemoryTimeline() {
  const [edges, setEdges] = useState<TimelineEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterRel, setFilterRel] = useState<string | null>(null);
  const [filterEntity, setFilterEntity] = useState("");

  useEffect(() => {
    setLoading(true);
    fetchMemoryTimeline()
      .then((data) => setEdges(data.edges))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    return edges.filter((e) => {
      if (filterRel && e.rel_type !== filterRel) return false;
      if (filterEntity) {
        const q = filterEntity.toLowerCase();
        if (
          !e.source_label.toLowerCase().includes(q) &&
          !e.target_label.toLowerCase().includes(q)
        )
          return false;
      }
      return true;
    });
  }, [edges, filterRel, filterEntity]);

  // 计算时间轴 viewport(min valid_from → now)
  const { minDate, maxDate } = useMemo(() => {
    if (filtered.length === 0)
      return { minDate: dayjs().subtract(1, "year"), maxDate: dayjs() };
    const dates = filtered.map((e) => dayjs(e.valid_from));
    const ends = filtered.map((e) =>
      e.valid_to ? dayjs(e.valid_to) : dayjs(),
    );
    return {
      minDate: dayjs.min ? (dayjs.min(...dates) as dayjs.Dayjs) : dates[0],
      maxDate: dayjs.max ? (dayjs.max(...ends) as dayjs.Dayjs) : ends[ends.length - 1],
    };
  }, [filtered]);

  if (loading) return <Spin size="large" />;
  if (edges.length === 0)
    return <Empty description="还没有时间序列 — 先聊几条试试" />;

  const totalDays = Math.max(1, maxDate.diff(minDate, "day"));
  const ROW_HEIGHT = 32;
  const BAR_HEIGHT = 18;

  return (
    <div>
      <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="按关系类型筛"
          style={{ width: 180 }}
          value={filterRel}
          onChange={setFilterRel}
          options={Object.entries(REL_TYPE_LABELS).map(([k, v]) => ({
            value: k,
            label: v,
          }))}
        />
        <Input
          placeholder="按实体名筛(如 茅台)"
          style={{ width: 200 }}
          value={filterEntity}
          onChange={(e) => setFilterEntity(e.target.value)}
          allowClear
        />
        <span data-testid="timeline-count">{filtered.length} 条</span>
      </div>

      <div
        data-testid="timeline-canvas"
        style={{
          position: "relative",
          height: filtered.length * ROW_HEIGHT + 40,
          background: "#fafafa",
          padding: 16,
          overflowX: "auto",
        }}
      >
        {/* 横轴标尺 */}
        <div style={{ position: "absolute", top: 0, left: 16, right: 16, fontSize: 11, color: "#8c8c8c" }}>
          <span>{minDate.format("YYYY-MM")}</span>
          <span style={{ float: "right" }}>{maxDate.format("YYYY-MM")}</span>
        </div>

        {filtered.map((e, i) => {
          const startDays = dayjs(e.valid_from).diff(minDate, "day");
          const endDays = (e.valid_to ? dayjs(e.valid_to) : maxDate).diff(minDate, "day");
          const leftPct = (startDays / totalDays) * 100;
          const widthPct = ((endDays - startDays) / totalDays) * 100;
          const status = classifyEdgeStatus(e);

          return (
            <Tooltip
              key={e.edge_id}
              title={
                <div>
                  <div>{REL_TYPE_LABELS[e.rel_type]}: {e.source_label} → {e.target_label}</div>
                  <div>{e.valid_from} → {e.valid_to ?? "(进行中)"}</div>
                  <div>importance: {e.importance}</div>
                  {e.reasoning && <div>{e.reasoning}</div>}
                </div>
              }
            >
              <div
                data-testid={`timeline-bar-${e.edge_id}`}
                style={{
                  position: "absolute",
                  top: i * ROW_HEIGHT + 24,
                  left: `${leftPct}%`,
                  width: `${Math.max(widthPct, 0.5)}%`,
                  height: BAR_HEIGHT,
                  background: REL_COLORS[e.rel_type] ?? "#bfbfbf",
                  opacity: status === "invalidated" ? 0.3 : status === "ended" ? 0.7 : 1,
                  borderRadius: 4,
                  fontSize: 10,
                  color: "#fff",
                  padding: "2px 6px",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  cursor: "pointer",
                }}
              >
                {e.source_label} → {e.target_label}
              </div>
            </Tooltip>
          );
        })}
      </div>

      <div style={{ marginTop: 16, fontSize: 12, color: "#8c8c8c" }}>
        {Object.entries(REL_TYPE_LABELS).map(([k, v]) => (
          <Tag key={k} color={REL_COLORS[k] ?? "default"}>{v}</Tag>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 写 vitest(4 项)**

```tsx
// frontend/src/components/memory/__tests__/MemoryTimeline.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import MemoryTimeline from "../MemoryTimeline";
import * as api from "@/lib/memory-api";

vi.mock("@/lib/memory-api");

const mkEdge = (overrides = {}) => ({
  edge_id: "e1",
  source_node_id: "n1",
  target_node_id: "n2",
  rel_type: "HOLDS",
  valid_from: "2025-01-01",
  valid_to: null,
  invalidated_at: null,
  importance: 0.9,
  reasoning: null,
  source_label: "我",
  target_label: "茅台",
  ...overrides,
});

describe("MemoryTimeline", () => {
  beforeEach(() => vi.resetAllMocks());

  it("加载中渲染 Spin", () => {
    vi.mocked(api.fetchMemoryTimeline).mockReturnValue(new Promise(() => {}));
    render(<MemoryTimeline />);
    expect(document.querySelector(".ant-spin")).toBeTruthy();
  });

  it("空 timeline 渲染 Empty", async () => {
    vi.mocked(api.fetchMemoryTimeline).mockResolvedValue({ edges: [] });
    render(<MemoryTimeline />);
    await waitFor(() => expect(screen.getByText(/还没有时间序列/)).toBeTruthy());
  });

  it("渲染所有 edge bars", async () => {
    vi.mocked(api.fetchMemoryTimeline).mockResolvedValue({
      edges: [
        mkEdge({ edge_id: "e1" }),
        mkEdge({ edge_id: "e2", rel_type: "SOLD", target_label: "茅台" }),
      ],
    });
    render(<MemoryTimeline />);
    await waitFor(() => {
      expect(screen.getByTestId("timeline-bar-e1")).toBeTruthy();
      expect(screen.getByTestId("timeline-bar-e2")).toBeTruthy();
    });
  });

  it("entity 关键字筛选生效", async () => {
    vi.mocked(api.fetchMemoryTimeline).mockResolvedValue({
      edges: [
        mkEdge({ edge_id: "e1", target_label: "茅台" }),
        mkEdge({ edge_id: "e2", target_label: "五粮液" }),
      ],
    });
    render(<MemoryTimeline />);
    await waitFor(() => screen.getByTestId("timeline-bar-e1"));
    const input = screen.getByPlaceholderText(/按实体名筛/);
    fireEvent.change(input, { target: { value: "茅台" } });
    await waitFor(() => {
      expect(screen.queryByTestId("timeline-bar-e1")).toBeTruthy();
      expect(screen.queryByTestId("timeline-bar-e2")).toBeNull();
    });
  });
});
```

- [ ] **Step 3: 把 timeline 挂到 page.tsx**

```tsx
// frontend/src/app/memory/page.tsx — 加 timeline tab
import MemoryTimeline from "@/components/memory/MemoryTimeline";

// items 里加:
{ key: "timeline", label: "Timeline", children: <MemoryTimeline /> },
```

- [ ] **Step 4: 跑 vitest + commit**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
pnpm vitest run src/components/memory/__tests__/MemoryTimeline.test.tsx
```

预期 4 项 pass。

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
git add frontend/src/components/memory/MemoryTimeline.tsx \
  frontend/src/components/memory/__tests__/MemoryTimeline.test.tsx \
  frontend/src/app/memory/page.tsx
git commit -m "feat(c5-plan7b): MemoryTimeline horizontal time-axis with rel/entity filter"
```

---

## Task 4: MemoryAuditLog.tsx — invalidated edge 列表 + 一键否决

**Why this task:** spec § 9 视图 3 + #8 用户回路 first-class hook。让用户看到系统**记错过什么 + 何时纠正**(被动 audit),同时给当前 active edge 提供"一键否决"按钮(主动 hook)。

**Files:**
- Create: `frontend/src/components/memory/MemoryAuditLog.tsx`
- Create: `frontend/src/components/memory/__tests__/MemoryAuditLog.test.tsx`
- Modify: `frontend/src/app/memory/page.tsx` — 加 audit tab

- [ ] **Step 1: 写 MemoryAuditLog.tsx**

```tsx
// frontend/src/components/memory/MemoryAuditLog.tsx
import { useEffect, useState } from "react";
import { Table, Tag, Button, Popconfirm, message, Empty, Spin, Switch } from "antd";
import type { ColumnsType } from "antd/es/table";
import { fetchMemoryAudit, fetchMemoryGraph, invalidateMemoryEdge } from "@/lib/memory-api";
import { REL_TYPE_LABELS, classifyEdgeStatus, type GraphEdge } from "./MemoryGraph.styles";

interface AuditRow extends GraphEdge {
  source_label: string;
  target_label: string;
}

export default function MemoryAuditLog() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showActive, setShowActive] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    setLoading(true);
    const fetcher = showActive ? fetchMemoryGraph : fetchMemoryAudit;
    fetcher()
      .then((data: { edges: AuditRow[]; nodes?: unknown }) => setRows(data.edges))
      .finally(() => setLoading(false));
  }, [showActive, reloadKey]);

  const handleInvalidate = async (edgeId: string) => {
    try {
      await invalidateMemoryEdge(edgeId);
      message.success("已否决,该 edge 不会再影响后续 retrieval");
      setReloadKey((k) => k + 1);
    } catch (e) {
      message.error(`否决失败: ${e}`);
    }
  };

  const columns: ColumnsType<AuditRow> = [
    {
      title: "状态",
      key: "status",
      width: 100,
      render: (_, row) => {
        const s = classifyEdgeStatus(row);
        return (
          <Tag color={s === "current" ? "green" : s === "ended" ? "orange" : "default"}>
            {s}
          </Tag>
        );
      },
    },
    {
      title: "Fact",
      key: "fact",
      render: (_, row) => (
        <span>
          {row.source_label} <Tag>{REL_TYPE_LABELS[row.rel_type] ?? row.rel_type}</Tag>{" "}
          {row.target_label}
        </span>
      ),
    },
    { title: "valid_from", dataIndex: "valid_from", width: 120 },
    {
      title: "valid_to",
      dataIndex: "valid_to",
      width: 120,
      render: (v) => v ?? "—",
    },
    {
      title: "invalidated_at",
      dataIndex: "invalidated_at",
      width: 140,
      render: (v) => v ?? "—",
    },
    { title: "reasoning", dataIndex: "reasoning", ellipsis: true },
    {
      title: "操作",
      key: "action",
      width: 110,
      render: (_, row) => {
        if (classifyEdgeStatus(row) !== "current") {
          return <span style={{ color: "#bfbfbf" }}>—</span>;
        }
        return (
          <Popconfirm
            title="确认否决这条 fact?"
            description="否决后该 edge 不再参与未来 retrieval(可在 audit 看到记录)"
            onConfirm={() => handleInvalidate(row.edge_id)}
            okText="否决"
            cancelText="取消"
          >
            <Button danger size="small" data-testid={`invalidate-btn-${row.edge_id}`}>
              一键否决
            </Button>
          </Popconfirm>
        );
      },
    },
  ];

  if (loading) return <Spin size="large" />;
  if (rows.length === 0)
    return (
      <div>
        <ToggleBar showActive={showActive} setShowActive={setShowActive} />
        <Empty description={showActive ? "没有 active edge" : "暂无被纠正的记录(说明 memory 工作得不错)"} />
      </div>
    );

  return (
    <div>
      <ToggleBar showActive={showActive} setShowActive={setShowActive} />
      <Table
        rowKey="edge_id"
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 20 }}
        size="small"
      />
    </div>
  );
}

function ToggleBar({ showActive, setShowActive }: { showActive: boolean; setShowActive: (v: boolean) => void }) {
  return (
    <div style={{ marginBottom: 16, display: "flex", gap: 12, alignItems: "center" }}>
      <Switch checked={showActive} onChange={setShowActive} data-testid="toggle-active" />
      <span>{showActive ? "显示 active edge(可一键否决)" : "显示 invalidated 历史(audit log)"}</span>
    </div>
  );
}
```

- [ ] **Step 2: 写 vitest(4 项)**

```tsx
// frontend/src/components/memory/__tests__/MemoryAuditLog.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import MemoryAuditLog from "../MemoryAuditLog";
import * as api from "@/lib/memory-api";

vi.mock("@/lib/memory-api");

const mkRow = (overrides = {}) => ({
  edge_id: "e1",
  source_node_id: "n1",
  target_node_id: "n2",
  rel_type: "HOLDS",
  valid_from: "2025-01-01",
  valid_to: null,
  invalidated_at: "2025-09-01",
  importance: 0.9,
  reasoning: "用户更正",
  source_label: "我",
  target_label: "茅台",
  ...overrides,
});

describe("MemoryAuditLog", () => {
  beforeEach(() => vi.resetAllMocks());

  it("loading 时渲染 Spin", () => {
    vi.mocked(api.fetchMemoryAudit).mockReturnValue(new Promise(() => {}));
    render(<MemoryAuditLog />);
    expect(document.querySelector(".ant-spin")).toBeTruthy();
  });

  it("audit 模式空数据渲染'memory 工作得不错'", async () => {
    vi.mocked(api.fetchMemoryAudit).mockResolvedValue({ edges: [] });
    render(<MemoryAuditLog />);
    await waitFor(() =>
      expect(screen.getByText(/暂无被纠正的记录/)).toBeTruthy(),
    );
  });

  it("audit 模式列出 invalidated edges", async () => {
    vi.mocked(api.fetchMemoryAudit).mockResolvedValue({
      edges: [mkRow({ edge_id: "e1" }), mkRow({ edge_id: "e2", target_label: "五粮液" })],
    });
    render(<MemoryAuditLog />);
    await waitFor(() => {
      expect(screen.getByText("茅台")).toBeTruthy();
      expect(screen.getByText("五粮液")).toBeTruthy();
    });
  });

  it("active 模式 + 一键否决调用 invalidateMemoryEdge", async () => {
    vi.mocked(api.fetchMemoryAudit).mockResolvedValue({ edges: [] });
    vi.mocked(api.fetchMemoryGraph).mockResolvedValue({
      nodes: [],
      edges: [mkRow({ edge_id: "e_active", invalidated_at: null, valid_to: null })] as never,
    });
    vi.mocked(api.invalidateMemoryEdge).mockResolvedValue({ ok: true });
    render(<MemoryAuditLog />);
    fireEvent.click(screen.getByTestId("toggle-active"));
    await waitFor(() => screen.getByTestId("invalidate-btn-e_active"));
    fireEvent.click(screen.getByTestId("invalidate-btn-e_active"));
    fireEvent.click(await screen.findByText("否决"));  // Popconfirm 的 OK
    await waitFor(() =>
      expect(api.invalidateMemoryEdge).toHaveBeenCalledWith("e_active"),
    );
  });
});
```

- [ ] **Step 3: 挂 page.tsx 第三 tab**

```tsx
// frontend/src/app/memory/page.tsx — 完整 items
{ key: "graph", label: "Graph", children: <MemoryGraph highlightEdgeId={highlightEdge} /> },
{ key: "timeline", label: "Timeline", children: <MemoryTimeline /> },
{ key: "audit", label: "Audit", children: <MemoryAuditLog /> },
```

- [ ] **Step 4: 跑 vitest + commit**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
pnpm vitest run src/components/memory/__tests__/MemoryAuditLog.test.tsx
```

预期 4 项 pass。

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
git add frontend/src/components/memory/MemoryAuditLog.tsx \
  frontend/src/components/memory/__tests__/MemoryAuditLog.test.tsx \
  frontend/src/app/memory/page.tsx
git commit -m "feat(c5-plan7b): MemoryAuditLog with one-click invalidate (issue #8 user loop)"
```

---

## Task 5: MemoryOnboardingModal.tsx — 首次 session 强 onboarding 弹窗

**Why this task:** **#8 算法深度补丁** 之 (b) 项。spec § 11 末尾 #8:"上线第一周用户问'你怎么监视我'"。强 onboarding 弹窗显式告知系统会记录什么 + 用户控制权 + 跳转 /memory。localStorage 标记不重复。

**Files:**
- Create: `frontend/src/components/memory/MemoryOnboardingModal.tsx`
- Create: `frontend/src/components/memory/__tests__/MemoryOnboardingModal.test.tsx`
- Modify: `frontend/src/App.tsx`(或 Layout 顶层)— 挂载 modal 一次性

- [ ] **Step 1: 写 MemoryOnboardingModal.tsx**

```tsx
// frontend/src/components/memory/MemoryOnboardingModal.tsx
import { useEffect, useState } from "react";
import { Modal, Button, Typography, List } from "antd";
import { useNavigate } from "react-router-dom";

const { Title, Paragraph, Text } = Typography;

const STORAGE_KEY = "memory_onboarding_seen_v1";

export function hasSeenOnboarding(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function markOnboardingSeen() {
  try {
    localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    /* localStorage disabled, accept re-prompt */
  }
}

export default function MemoryOnboardingModal() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (!hasSeenOnboarding()) {
      // 微延迟避免跟登录 modal 撞
      const t = setTimeout(() => setOpen(true), 800);
      return () => clearTimeout(t);
    }
  }, []);

  const close = () => {
    markOnboardingSeen();
    setOpen(false);
  };

  const goMemory = () => {
    markOnboardingSeen();
    setOpen(false);
    navigate("/memory");
  };

  return (
    <Modal
      open={open}
      onCancel={close}
      maskClosable={false}
      title="一件事:我会记住您的投资偏好和持仓"
      width={560}
      data-testid="memory-onboarding-modal"
      footer={[
        <Button key="memory" type="default" onClick={goMemory} data-testid="onboarding-go-memory">
          去 /memory 看看
        </Button>,
        <Button key="ok" type="primary" onClick={close} data-testid="onboarding-confirm">
          我知道了
        </Button>,
      ]}
    >
      <Paragraph>
        为了给您更贴合的研究建议,我会从您的对话中**自动**记录:
      </Paragraph>
      <List
        size="small"
        bordered
        dataSource={[
          "您的持仓 / 加减仓变动",
          "您对某只股 / 某行业的偏好与回避",
          "您表达的观点(看好 / 看空 / 中性)",
          "您研究过的标的与对比",
        ]}
        renderItem={(item) => <List.Item>{item}</List.Item>}
      />
      <Paragraph style={{ marginTop: 16 }}>
        这些信息**仅用于本会话**,不会跨用户共享。
      </Paragraph>
      <Paragraph>
        <Text strong>您随时可以:</Text>
      </Paragraph>
      <List
        size="small"
        dataSource={[
          "在 /memory 页查看所有记录(graph / timeline / audit 三视图)",
          "对任何 fact 一键否决(立即生效,不再影响 retrieval)",
          "看到我引用 memory 时,我会显式提示 [查看] 链接",
        ]}
        renderItem={(item) => <List.Item>{item}</List.Item>}
      />
    </Modal>
  );
}
```

- [ ] **Step 2: 写 vitest(3 项)**

```tsx
// frontend/src/components/memory/__tests__/MemoryOnboardingModal.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import MemoryOnboardingModal, {
  hasSeenOnboarding,
  markOnboardingSeen,
} from "../MemoryOnboardingModal";

const renderWithRouter = () =>
  render(
    <MemoryRouter>
      <MemoryOnboardingModal />
    </MemoryRouter>,
  );

describe("MemoryOnboardingModal", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("首次访问 800ms 后弹 modal", async () => {
    renderWithRouter();
    expect(screen.queryByTestId("memory-onboarding-modal")).toBeNull();
    act(() => vi.advanceTimersByTime(900));
    await waitFor(() => expect(screen.getByText(/我会记住您的投资偏好和持仓/)).toBeTruthy());
  });

  it("已 seen 时不弹", async () => {
    markOnboardingSeen();
    renderWithRouter();
    act(() => vi.advanceTimersByTime(2000));
    expect(screen.queryByText(/我会记住您的投资偏好/)).toBeNull();
    expect(hasSeenOnboarding()).toBe(true);
  });

  it("点'我知道了'后标记 seen + 关闭", async () => {
    renderWithRouter();
    act(() => vi.advanceTimersByTime(900));
    await waitFor(() => screen.getByTestId("onboarding-confirm"));
    fireEvent.click(screen.getByTestId("onboarding-confirm"));
    expect(hasSeenOnboarding()).toBe(true);
  });
});
```

- [ ] **Step 3: 挂载到 App / Layout 顶层**

打开 `frontend/src/App.tsx`(或 Layout 组件),在路由 outlet 同级一次性挂载:

```tsx
// frontend/src/App.tsx — 顶层一次
import MemoryOnboardingModal from "@/components/memory/MemoryOnboardingModal";

// JSX 顶层
<>
  <MemoryOnboardingModal />
  <Outlet />  {/* 或现有路由结构 */}
</>
```

注意:**仅登录态用户才挂**,挂载位置必须在 auth-guard 之后(避免 logout 状态弹无意义 onboarding)。具体看 `frontend/src/components/auth-guard/`,在 `<AuthGuard>` 内部挂。

- [ ] **Step 4: 跑 vitest + commit**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
pnpm vitest run src/components/memory/__tests__/MemoryOnboardingModal.test.tsx
```

预期 3 项 pass。

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
git add frontend/src/components/memory/MemoryOnboardingModal.tsx \
  frontend/src/components/memory/__tests__/MemoryOnboardingModal.test.tsx \
  frontend/src/App.tsx
git commit -m "feat(c5-plan7b): MemoryOnboardingModal first-session disclosure (issue #8a/b)"
```

---

## Task 6: Chat 内显式提及 memory 来源 — `[查看](#mem-{edge_id})` anchor

**Why this task:** **#8 算法深度补丁** 之 (a) 项。Agent 在 chat 内回复时,引用 memory 必须显式标注来源。前端 chat message renderer 识别 `[查看](#mem-{edge_id})` pattern,渲染成跳转 `/memory?highlight_edge={edge_id}` 的 link。Backend prompt 改造**不在 Plan 7B 范围**(归 Plan 4 的 archival_memory_search tool result formatter,Plan 4 已 ship 的 result template 加 `[查看](#mem-...)` 后缀;此处 Plan 7B 只 ship 前端识别)。

**Files:**
- Modify: `frontend/src/components/chat/TextMessage.tsx`
- Modify: `frontend/src/components/chat/__tests__/TextMessage.test.tsx`

- [ ] **Step 1: 读现有 TextMessage.tsx 看 markdown render 逻辑**

```bash
cat /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend/src/components/chat/TextMessage.tsx
```

预期已经用 `marked` 库 render markdown。本仓 marked 15.0.7 + react 19,marked 默认会把 `[查看](#mem-xxx)` render 成 `<a href="#mem-xxx">查看</a>`。我们要拦截 click 改导航。

- [ ] **Step 2: 改 TextMessage.tsx**

```tsx
// frontend/src/components/chat/TextMessage.tsx — 关键改动
import { useNavigate } from "react-router-dom";
// ... 原有 import

const MEM_LINK_RE = /^#mem-([a-f0-9-]+)$/i;

export default function TextMessage({ content }: { content: string }) {
  const navigate = useNavigate();
  // ... 原有 markdown render 逻辑

  // 在容器 onClick 上拦截 anchor click
  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.tagName === "A") {
      const href = target.getAttribute("href") ?? "";
      const m = href.match(MEM_LINK_RE);
      if (m) {
        e.preventDefault();
        const edgeId = m[1];
        navigate(`/memory?highlight_edge=${edgeId}`);
      }
    }
  };

  return (
    <div
      data-testid="text-message"
      onClick={handleClick}
      className="text-message"
      // ... 原有 markdown render 输出
      dangerouslySetInnerHTML={{ __html: rendered }}
    />
  );
}
```

注意:不要改其他 link 的行为(普通 http://, 正常 anchor);只拦截 `#mem-...` pattern。

如 `TextMessage.tsx` 已经用 React component tree 而非 `dangerouslySetInnerHTML`,改 marked custom renderer:

```tsx
import { marked, Renderer } from "marked";

const renderer = new Renderer();
const baseLink = renderer.link.bind(renderer);
renderer.link = function(href, title, text) {
  if (href && MEM_LINK_RE.test(href)) {
    const m = href.match(MEM_LINK_RE);
    return `<a href="${href}" data-mem-edge-id="${m![1]}" class="mem-link">${text}</a>`;
  }
  return baseLink(href, title, text);
};
marked.setOptions({ renderer });
```

并仍用 onClick 拦 `data-mem-edge-id`。

- [ ] **Step 3: 加 vitest case(原 file 已有 tests,加新 case)**

```tsx
// frontend/src/components/chat/__tests__/TextMessage.test.tsx — 加新 case
import { MemoryRouter, useLocation } from "react-router-dom";

// 在原 describe 末尾加:
it("点 [查看](#mem-xxx) link 跳转 /memory?highlight_edge=xxx", async () => {
  const LocationDisplay = () => {
    const loc = useLocation();
    return <div data-testid="loc">{loc.pathname + loc.search}</div>;
  };
  const { container } = render(
    <MemoryRouter initialEntries={["/chat"]}>
      <TextMessage content="基于您的偏好([查看](#mem-abc-123)),建议..." />
      <LocationDisplay />
    </MemoryRouter>,
  );
  const link = container.querySelector('a[href="#mem-abc-123"]') as HTMLAnchorElement;
  expect(link).toBeTruthy();
  fireEvent.click(link);
  await waitFor(() =>
    expect(screen.getByTestId("loc").textContent).toContain(
      "/memory?highlight_edge=abc-123",
    ),
  );
});

it("普通 http link 不被 mem link 拦截", () => {
  const { container } = render(
    <MemoryRouter>
      <TextMessage content="参考 [百度](https://baidu.com)" />
    </MemoryRouter>,
  );
  const link = container.querySelector('a[href="https://baidu.com"]') as HTMLAnchorElement;
  expect(link).toBeTruthy();
  // 不抛 navigation, 仍是普通 link
});
```

- [ ] **Step 4: 跑 vitest**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
pnpm vitest run src/components/chat/__tests__/TextMessage.test.tsx
```

预期原有 case + 2 个新 case 全 pass。

- [ ] **Step 5: commit**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
git add frontend/src/components/chat/TextMessage.tsx \
  frontend/src/components/chat/__tests__/TextMessage.test.tsx
git commit -m "feat(c5-plan7b): chat TextMessage [查看](#mem-id) anchor → /memory navigation (#8a)"
```

---

## Task 7: Backend `memory_email.py` — 月度 digest 邮件生成函数(不发送)

**Why this task:** **#8 算法深度补丁** 之 (c) 项。spec 要求"每月推一封'我们记得关于您的 5 件事,请确认'邮件"。Plan 7B ship 函数 stub:`generate_monthly_digest(user_id) -> str`,返 markdown body(含 5 条 top-importance current edge + 一键否决 link 回 /memory page)。**不 ship 实际发送**(SMTP / SendGrid 留 P3 hook,跟 Scale-2 用户回路一起做)。

**Files:**
- Create: `backend/app/services/memory_email.py`
- Create: `backend/tests/unit/services/test_memory_email.py`
- Create: `backend/tests/integration/services/test_memory_email_integration.py`

- [ ] **Step 1: 写 `memory_email.py`**

```python
# backend/app/services/memory_email.py
"""Monthly memory digest email body generator.

#8 算法深度补丁 (c): 每月推 "我们记得关于您的 5 件事,请确认" 邮件.
**Plan 7B 只 ship body 生成函数, 不 ship 实际发送 (留 P3 hook + Scale-2 用户回路一起做).**

P3 触发后, email worker 在 backend/app/tasks/memory_email_worker.py 调本函数 + SMTP/SendGrid 发.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.models import ChatMemoryEdge, ChatMemoryNode

if TYPE_CHECKING:
    pass


REL_TYPE_LABELS_ZH: dict[str, str] = {
    "HOLDS": "持仓",
    "WATCHES": "关注",
    "PREFERS": "偏好",
    "AVOIDS": "回避",
    "EXPRESSED_VIEW": "表态",
    "SOLD": "卖出",
    "STUDIED": "研究",
    "COMPARED": "对比",
    "BELONGS_TO": "属于",
    "HAS_CONCEPT": "含概念",
    "CORRELATED_WITH": "相关",
}

DEFAULT_TOP_N = 5
WEB_BASE_URL_DEFAULT = "https://app.local"  # 实际部署从 settings 读


async def fetch_top_edges_for_digest(
    session: AsyncSession,
    user_id: UUID,
    top_n: int = DEFAULT_TOP_N,
    window_days: int = 30,
) -> list[tuple[ChatMemoryEdge, str, str]]:
    """取 user 最近 window_days 内 importance DESC 前 top_n 条 current edge.

    Returns:
        [(edge, source_label, target_label), ...]
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    src = ChatMemoryNode.__table__.alias("src")
    tgt = ChatMemoryNode.__table__.alias("tgt")
    e = ChatMemoryEdge.__table__

    stmt = (
        select(
            ChatMemoryEdge,
            src.c.entity_label.label("src_label"),
            tgt.c.entity_label.label("tgt_label"),
        )
        .select_from(
            e.join(src, e.c.source_node_id == src.c.node_id)
             .join(tgt, e.c.target_node_id == tgt.c.node_id)
        )
        .where(e.c.user_id == user_id)
        .where(e.c.valid_to.is_(None))
        .where(e.c.invalidated_at.is_(None))
        .where(e.c.recorded_at >= cutoff)
        .order_by(e.c.importance.desc(), e.c.recorded_at.desc())
        .limit(top_n)
    )

    result = await session.execute(stmt)
    rows = result.all()
    return [(r[0], r.src_label, r.tgt_label) for r in rows]


def render_digest_markdown(
    rows: list[tuple[ChatMemoryEdge, str, str]],
    user_display_name: str,
    web_base_url: str = WEB_BASE_URL_DEFAULT,
) -> str:
    """Render markdown email body.

    Template:
        ## {name} 您好,我们最近一个月记下了关于您的 {n} 件事

        请花 30 秒确认 (任何不准确请一键否决):

        1. **{rel}**: {src} → {tgt} (importance {imp}, {date}) [一键否决]({invalidate_url})
        ...

        [查看完整 memory]({memory_url})
    """
    if not rows:
        return _empty_digest_template(user_display_name, web_base_url)

    lines: list[str] = [
        f"## {user_display_name} 您好,我们最近一个月记下了关于您的 {len(rows)} 件事",
        "",
        "请花 30 秒确认 (任何不准确请一键否决):",
        "",
    ]
    for i, (edge, src_label, tgt_label) in enumerate(rows, start=1):
        rel_zh = REL_TYPE_LABELS_ZH.get(edge.rel_type, edge.rel_type)
        date_str = (
            edge.valid_from.strftime("%Y-%m-%d")
            if edge.valid_from else "—"
        )
        invalidate_url = (
            f"{web_base_url}/memory?highlight_edge={edge.edge_id}&action=invalidate"
        )
        lines.append(
            f"{i}. **{rel_zh}**: {src_label} → {tgt_label} "
            f"(importance {edge.importance}, {date_str}) "
            f"[一键否决]({invalidate_url})"
        )
    lines.extend(
        [
            "",
            f"[查看完整 memory]({web_base_url}/memory)",
            "",
            "---",
            "如不希望再收到此邮件, 在 /memory 页底部关闭月度 digest.",
        ],
    )
    return "\n".join(lines)


def _empty_digest_template(user_display_name: str, web_base_url: str) -> str:
    return (
        f"## {user_display_name} 您好,这个月暂无新增 memory\n\n"
        f"看起来这个月您没怎么聊投资 — 之前的记录都还在 "
        f"[/memory]({web_base_url}/memory) 页。\n"
    )


async def generate_monthly_digest(
    session: AsyncSession,
    user_id: UUID,
    user_display_name: str = "用户",
    top_n: int = DEFAULT_TOP_N,
    window_days: int = 30,
    web_base_url: str = WEB_BASE_URL_DEFAULT,
) -> str:
    """Public entry: 拉数据 + 渲染 markdown body.

    P3 hook: email worker 调本函数后接 SMTP/SendGrid send.
    Plan 7B 只 ship 此函数, 不 ship send.
    """
    rows = await fetch_top_edges_for_digest(session, user_id, top_n, window_days)
    return render_digest_markdown(rows, user_display_name, web_base_url)
```

- [ ] **Step 2: 写 L0 unit test(纯函数:render_digest_markdown,不碰 DB)**

```python
# backend/tests/unit/services/test_memory_email.py
"""L0: render_digest_markdown 纯函数 unit test."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.memory_email import (
    _empty_digest_template,
    render_digest_markdown,
)


def _mk_edge(
    rel_type: str = "HOLDS",
    importance: float = 0.9,
    valid_from: datetime | None = None,
):
    return SimpleNamespace(
        edge_id=uuid4(),
        rel_type=rel_type,
        importance=importance,
        valid_from=valid_from or datetime(2025, 4, 15, tzinfo=timezone.utc),
    )


def test_render_empty_rows_uses_empty_template() -> None:
    body = render_digest_markdown([], "张先生")
    assert "暂无新增 memory" in body
    assert "张先生" in body
    assert "/memory" in body


def test_render_5_rows_lists_in_order() -> None:
    rows = [
        (_mk_edge("HOLDS"), "我", "茅台"),
        (_mk_edge("PREFERS"), "我", "白酒行业"),
        (_mk_edge("AVOIDS"), "我", "新能源"),
    ]
    body = render_digest_markdown(rows, "李四")
    assert "我们最近一个月记下了关于您的 3 件事" in body
    assert "**持仓**: 我 → 茅台" in body
    assert "**偏好**: 我 → 白酒行业" in body
    assert "**回避**: 我 → 新能源" in body
    # 验顺序
    pos_holds = body.index("持仓")
    pos_prefers = body.index("偏好")
    pos_avoids = body.index("回避")
    assert pos_holds < pos_prefers < pos_avoids


def test_render_includes_invalidate_url_per_row() -> None:
    edge = _mk_edge("HOLDS")
    rows = [(edge, "我", "茅台")]
    body = render_digest_markdown(rows, "用户", web_base_url="https://x.com")
    assert f"https://x.com/memory?highlight_edge={edge.edge_id}&action=invalidate" in body
    assert "[一键否决](" in body


def test_render_unknown_rel_type_falls_back_to_raw() -> None:
    rows = [(_mk_edge("UNKNOWN_REL"), "A", "B")]
    body = render_digest_markdown(rows, "用户")
    assert "**UNKNOWN_REL**: A → B" in body


def test_empty_template_links_to_memory() -> None:
    body = _empty_digest_template("用户", "https://x.com")
    assert "https://x.com/memory" in body
```

- [ ] **Step 3: 写 L1 integration test(real PG via pg_memory_fixture, 复用 § 6 契约 fixture)**

```python
# backend/tests/integration/services/test_memory_email_integration.py
"""L1: generate_monthly_digest 真 PG e2e."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode
from app.services.memory_email import generate_monthly_digest

pytestmark = pytest.mark.integration


async def _seed_user_with_edges(
    session: AsyncSession,
    user_id,
    n_edges: int,
    days_ago: int = 5,
) -> list[ChatMemoryEdge]:
    """Seed n_edges current HOLDS edges for user."""
    # 先建 User node + n_edges 个 Stock node + n_edges 个 episode
    user_node = ChatMemoryNode(
        user_id=user_id, entity_type="User", entity_label="我", properties={}
    )
    session.add(user_node)
    await session.flush()

    edges: list[ChatMemoryEdge] = []
    for i in range(n_edges):
        stock_node = ChatMemoryNode(
            user_id=user_id,
            entity_type="Stock",
            entity_label=f"股票{i}",
            properties={"ts_code": f"00000{i}.SZ"},
        )
        session.add(stock_node)
        episode = ChatMemoryEpisode(
            user_id=user_id,
            session_id=uuid4(),
            episode_index=i,
            user_message_text=f"我买了 股票{i}",
            agent_response_text="收到",
            source_kind="chat_turn",
        )
        session.add(episode)
        await session.flush()

        edge = ChatMemoryEdge(
            user_id=user_id,
            source_node_id=user_node.node_id,
            target_node_id=stock_node.node_id,
            rel_type="HOLDS",
            valid_from=datetime.now(timezone.utc) - timedelta(days=days_ago),
            valid_to=None,
            invalidated_at=None,
            source_episode_id=episode.episode_id,
            importance=0.9 - i * 0.01,  # 让顺序确定
            reasoning=f"reason {i}",
        )
        session.add(edge)
        edges.append(edge)
    await session.commit()
    return edges


async def test_generate_monthly_digest_returns_markdown_with_top_edges(
    pg_memory_fixture, async_session,
) -> None:
    """Plan 7B Task 7 — 真 PG seed → 生成 digest body 包含 top edges."""
    user_id = uuid4()
    await _seed_user_with_edges(async_session, user_id, n_edges=7)

    body = await generate_monthly_digest(
        async_session, user_id, user_display_name="测试用户", top_n=5
    )

    assert "测试用户 您好" in body
    assert "我们最近一个月记下了关于您的 5 件事" in body
    # 7 seed 但只取前 5
    assert body.count("**持仓**") == 5


async def test_generate_monthly_digest_excludes_invalidated_and_old_edges(
    pg_memory_fixture, async_session,
) -> None:
    """invalidated 和 30+ 天前的 edge 不应进 digest."""
    user_id = uuid4()
    await _seed_user_with_edges(async_session, user_id, n_edges=2, days_ago=2)

    # seed 一条 invalidated edge
    user_node = (await async_session.execute(
        ChatMemoryNode.__table__.select().where(
            ChatMemoryNode.user_id == user_id, ChatMemoryNode.entity_type == "User"
        )
    )).first()
    bad_stock = ChatMemoryNode(
        user_id=user_id, entity_type="Stock", entity_label="坏股", properties={}
    )
    async_session.add(bad_stock)
    bad_ep = ChatMemoryEpisode(
        user_id=user_id, session_id=uuid4(), episode_index=99,
        user_message_text="坏", agent_response_text="收",
        source_kind="chat_turn",
    )
    async_session.add(bad_ep)
    await async_session.flush()
    bad_edge = ChatMemoryEdge(
        user_id=user_id,
        source_node_id=user_node.node_id,
        target_node_id=bad_stock.node_id,
        rel_type="HOLDS",
        valid_from=datetime.now(timezone.utc) - timedelta(days=2),
        invalidated_at=datetime.now(timezone.utc),  # 已 invalidated
        source_episode_id=bad_ep.episode_id,
        importance=0.9,
    )
    async_session.add(bad_edge)
    await async_session.commit()

    body = await generate_monthly_digest(async_session, user_id, top_n=5)
    assert "坏股" not in body
    # 2 条 valid edge 都应出现
    assert body.count("**持仓**") == 2
```

注意:`pg_memory_fixture` + `async_session` 由 Plan 1 在 `backend/tests/conftest.py` 提供(契约 § 6)。

- [ ] **Step 4: 跑 backend test**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
unset all_proxy https_proxy http_proxy && \
  uv run pytest backend/tests/unit/services/test_memory_email.py -v
```

预期 5 项 L0 pass。

```bash
unset all_proxy https_proxy http_proxy && \
  uv run pytest backend/tests/integration/services/test_memory_email_integration.py -v
```

预期 2 项 L1 pass(依赖 Plan 1 的 pg_memory_fixture / Plan 1 的 4 PG 表 schema 已 ship)。

- [ ] **Step 5: commit**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
git add backend/app/services/memory_email.py \
  backend/tests/unit/services/test_memory_email.py \
  backend/tests/integration/services/test_memory_email_integration.py
git commit -m "feat(c5-plan7b): memory_email.generate_monthly_digest body generator (#8c, send is P3 hook)"
```

---

## Task 8: Playwright e2e + 知识卡 + ship 收束

**Why this task:** E2E 验三 tab 完整渲染 + Cytoscape 节点交互 + 一键否决 + onboarding modal 流程。写知识卡 + final review。

**Files:**
- Create: `frontend/playwright/memory.spec.ts`
- Create: `docs/claude-context/c5-plan7b-visualizations-onboarding-done.md`
- Modify: `CLAUDE.md` — 加 Plan 7B 索引(可选,留 Plan 8 总收束也行)

- [ ] **Step 1: 写 playwright e2e**

```ts
// frontend/playwright/memory.spec.ts
import { test, expect } from "@playwright/test";

test.describe("Memory page (Plan 7B)", () => {
  test.beforeEach(async ({ page }) => {
    // mock backend API (用 page.route, 避免依赖真 backend ship)
    await page.route("**/api/v0/memory/graph", async (route) =>
      route.fulfill({
        json: {
          nodes: [
            { node_id: "n1", entity_type: "User", entity_label: "我" },
            { node_id: "n2", entity_type: "Stock", entity_label: "茅台" },
          ],
          edges: [
            {
              edge_id: "e1",
              source_node_id: "n1",
              target_node_id: "n2",
              rel_type: "HOLDS",
              valid_from: "2025-01-01",
              valid_to: null,
              invalidated_at: null,
              importance: 0.9,
              reasoning: "重仓",
            },
          ],
        },
      }),
    );
    await page.route("**/api/v0/memory/timeline", async (route) =>
      route.fulfill({
        json: {
          edges: [
            {
              edge_id: "e1",
              source_node_id: "n1",
              target_node_id: "n2",
              rel_type: "HOLDS",
              valid_from: "2025-01-01",
              valid_to: null,
              invalidated_at: null,
              importance: 0.9,
              reasoning: null,
              source_label: "我",
              target_label: "茅台",
            },
          ],
        },
      }),
    );
    await page.route("**/api/v0/memory/audit", async (route) =>
      route.fulfill({
        json: {
          edges: [
            {
              edge_id: "e_inv",
              source_node_id: "n1",
              target_node_id: "n2",
              rel_type: "HOLDS",
              valid_from: "2024-08-01",
              valid_to: "2025-03-01",
              invalidated_at: "2025-09-01",
              importance: 0.9,
              reasoning: "用户更正",
              source_label: "我",
              target_label: "茅台 (旧)",
            },
          ],
        },
      }),
    );
    await page.route("**/api/v0/memory/edges/*/invalidate", async (route) =>
      route.fulfill({ json: { ok: true } }),
    );

    // 跳过 onboarding(已在 localStorage 标记)
    await page.addInitScript(() => {
      localStorage.setItem("memory_onboarding_seen_v1", "1");
    });
  });

  test("三 tab 全部渲染", async ({ page }) => {
    await page.goto("/memory");
    await expect(page.getByRole("heading", { name: "我的 Memory" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Graph" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Timeline" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Audit" })).toBeVisible();
  });

  test("Graph tab 渲染 cytoscape canvas", async ({ page }) => {
    await page.goto("/memory");
    await page.getByRole("tab", { name: "Graph" }).click();
    await expect(page.locator("canvas")).toBeVisible({ timeout: 5000 });
  });

  test("Timeline tab 渲染 bar 元素", async ({ page }) => {
    await page.goto("/memory");
    await page.getByRole("tab", { name: "Timeline" }).click();
    await expect(page.getByTestId("timeline-bar-e1")).toBeVisible();
    await expect(page.getByTestId("timeline-count")).toContainText("1 条");
  });

  test("Audit tab 一键否决流程", async ({ page }) => {
    await page.goto("/memory");
    await page.getByRole("tab", { name: "Audit" }).click();
    // 先看 invalidated 历史
    await expect(page.getByText("茅台 (旧)")).toBeVisible();
    // 切到 active 模式
    await page.getByTestId("toggle-active").click();
    // mock 已 set, 应该能看到 active edge 一键否决按钮
    await expect(page.getByTestId(/^invalidate-btn-/)).toBeVisible();
    await page.getByTestId(/^invalidate-btn-/).click();
    await page.getByText("否决").click();  // popconfirm
    // 期待 success message
    await expect(page.getByText(/已否决/)).toBeVisible({ timeout: 3000 });
  });

  test("Onboarding modal 首次访问弹出 + 标记 seen", async ({ page }) => {
    // 清掉 init script
    await page.context().clearCookies();
    await page.addInitScript(() => localStorage.clear());
    await page.goto("/");
    await expect(page.getByTestId("memory-onboarding-modal")).toBeVisible({
      timeout: 3000,
    });
    await page.getByTestId("onboarding-confirm").click();
    await expect(page.getByTestId("memory-onboarding-modal")).toBeHidden();

    // reload 不再弹
    await page.reload();
    await expect(page.getByTestId("memory-onboarding-modal")).toBeHidden({
      timeout: 2000,
    });
  });

  test("Chat 内 [查看](#mem-xxx) 链接跳转 /memory?highlight_edge", async ({ page }) => {
    // 此 case 需要 chat 页 ship + 真消息流; 留 manual dogfood 验, e2e 用 markdown render unit cover
    // 占位 — Plan 8 dogfood 阶段补充
    test.skip(true, "Dogfood 验, vitest 已 cover renderer 行为");
  });
});
```

- [ ] **Step 2: 跑 playwright(需 backend / frontend dev server)**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
pnpm playwright install --with-deps chromium  # 第一次跑装
pnpm playwright test playwright/memory.spec.ts
```

预期 5 项 e2e pass(1 项 skip)。

如 dev server 启动需要 backend mock,在 `playwright.config.ts` 看 `webServer` 配置;Plan 7A 应已设置 `pnpm dev` 配置。

- [ ] **Step 3: 写知识卡**

```markdown
<!-- docs/claude-context/c5-plan7b-visualizations-onboarding-done.md -->
---
name: c5-plan7b-visualizations-onboarding-done
description: C.5 Plan 7B (Frontend 三视图 + 用户心智 onboarding + 月度邮件 spec) ship — Cytoscape graph / Timeline / Audit + onboarding modal + 显式提及 + email body generator
type: project
---

C.5 Plan 7B (Frontend Visualizations + 用户心智 Onboarding + 月度邮件) ship — 2026-05-1X.

## ship 范围

### Frontend 三视图 (spec § 9)
- **MemoryGraph**: Cytoscape.js graph viz, 7 entity_type 颜色, 11 rel_type label, bi-temporal 状态视觉编码 (实线 current / 虚线 ended / 点线 invalidated), edge tap 弹 Drawer 详情
- **MemoryTimeline**: 横向时间轴 (纯 SVG/CSS, 无第三方 timeline 依赖), rel_type 选择 + entity 关键字筛 + bar tooltip
- **MemoryAuditLog**: antd Table 列 invalidated edge 历史 + Switch 切到 active edge 列表 + Popconfirm 一键否决

### #8 算法深度补丁 (spec § 11 末尾 #8) 完整覆盖
- (a) **Agent 显式提及来源**: chat TextMessage 识别 `[查看](#mem-{edge_id})` anchor → 跳转 `/memory?highlight_edge={edge_id}` + Cytoscape 高亮
- (b) **Onboarding modal**: 首次 session 强弹窗告知"我会记住您的投资偏好和持仓, 可随时在 /memory 删除", localStorage `memory_onboarding_seen_v1` 标记不重复
- (c) **月度邮件 spec**: `app/services/memory_email.generate_monthly_digest()` ship body 生成函数 + L0/L1 测试; **不 ship 实际发送** (留 P3 hook + Scale-2 用户回路一起做)

### 测试
- vitest 4 组件 16 项 pass
- Playwright 5 项 e2e pass (1 skip 留 dogfood)
- backend memory_email L0 5 + L1 2 项 pass

## 关键决策 (实施期撞实)

- **Cytoscape 选 cose layout**: dogfood 数据量 (单用户 ~50-200 edge) 下 cose force-directed 比 dagre / breadthfirst 更直观; 真上量后 (1000+ edge) 切 cola layout 增量 render
- **Timeline 不引第三方库**: 评估过 vis-timeline / react-calendar-timeline 都 200KB+, 单视图用浪费; 纯 SVG/CSS + dayjs 100 LoC 够用
- **一键否决限单 edge**: cascade invalidate (削 HOLDS 自动连带 EXPRESSED_VIEW) 留 P3 hook, 涉及 bi-temporal 推理复杂度
- **Onboarding 800ms 延迟弹**: 避免跟 auth-guard 登录 modal 撞重叠
- **`#mem-` anchor pattern 不破坏普通 link**: marked custom renderer 仅当 `^#mem-[a-f0-9-]+$` match 时改写, 其他 `#anchor` / `http://` 走原 marked 行为

## 跟 spec 决策对齐

- spec § 9 视图 1/2/3 全部 ship
- spec § 11 末尾 #8 (a)(b)(c) 三补丁全部覆盖
- spec § 11 末尾 #8 验证目标"用户调研 5 人首次 session 后 4/5 知道有 memory 系统": Plan 7B 提供机制 (modal + 显式提及), 实际调研留 dogfood 阶段验
- spec 月度邮件打开率 ≥ 30%: P3 实际发送时收集

## 关键文件 ref

- `frontend/src/components/memory/MemoryGraph.tsx` (+ styles)
- `frontend/src/components/memory/MemoryTimeline.tsx`
- `frontend/src/components/memory/MemoryAuditLog.tsx`
- `frontend/src/components/memory/MemoryOnboardingModal.tsx`
- `frontend/src/components/chat/TextMessage.tsx` (改造)
- `frontend/src/app/memory/page.tsx` (Plan 7A ship, 7B 挂三 tab)
- `backend/app/services/memory_email.py`
- `frontend/playwright/memory.spec.ts`

## P3 hook ref (留待 v1.x)

- 邮件实际发送: `backend/app/tasks/memory_email_worker.py` (Celery monthly cron) + SMTP/SendGrid client
- 跟 spec § 11 Scale-2 "用户回路 first-class" 补丁一起做
- Cascade invalidate: 削 HOLDS 时 LLM 判断是否连带相关 EXPRESSED_VIEW (看时间窗 + 语义关联)
```

- [ ] **Step 4: final review checklist**

```bash
# 1. 全 vitest pass
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
pnpm vitest run src/components/memory/ src/components/chat/__tests__/TextMessage.test.tsx

# 2. backend test pass
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
unset all_proxy https_proxy http_proxy && uv run pytest backend/tests/unit/services/test_memory_email.py backend/tests/integration/services/test_memory_email_integration.py -v

# 3. mypy strict
unset all_proxy https_proxy http_proxy && uv run mypy backend/app/services/memory_email.py

# 4. frontend build 通过
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
pnpm build 2>&1 | tail -10

# 5. 检查没有引入禁用的依赖
grep -r "vis-timeline\|react-calendar-timeline" frontend/package.json && echo "FAIL: 引入了禁用 timeline lib" || echo "OK"
```

- [ ] **Step 5: commit + ship**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
git add frontend/playwright/memory.spec.ts \
  docs/claude-context/c5-plan7b-visualizations-onboarding-done.md
git commit -m "test(c5-plan7b): playwright e2e + knowledge card for Plan 7B ship"
```

---

## Self-Review Checklist

### Spec § 9 /memory page UI 可视化部分 coverage

- [x] **视图 1 (Graph viz / Cytoscape.js)** — Task 2 ship: MemoryGraph.tsx, 7 entity_type 颜色, 11 rel_type label hover, bi-temporal 实线/虚线/点线 视觉编码, tap 弹详情 Drawer
- [x] **视图 2 (Timeline view)** — Task 3 ship: MemoryTimeline.tsx, 横轴 valid_from 排序, edge bar 颜色按 rel_type, hover Tooltip 显示完整 properties, 支持 rel_type / entity 关键字筛选
- [x] **视图 3 (Audit log)** — Task 4 ship: MemoryAuditLog.tsx, antd Table 列 invalidated_at IS NOT NULL 的 edge, 显示 invalidated_at + reasoning, Switch 切 active 模式 + 一键否决按钮
- [x] **数据接口** — 复用 Plan 7A ship 的 `fetchMemoryGraph / fetchMemoryTimeline / fetchMemoryAudit / invalidateMemoryEdge`,严守契约 § 10
- [x] **复用 PR #39 AppShell + Sidebar** — Plan 7A 已建 `/memory` 路由,Plan 7B 不重定义,只挂三 tab
- [x] **Cytoscape.js 选型理由** — 知识卡说明 cose layout 选择 + 上量后切 cola 的预案
- [x] **Read-only 起步** — Plan 7B 只 ship "一键否决"(单 edge invalidate),不 ship edit / cascade(留 P3)

### Spec § 11 末尾 #8 用户心智模型 + 信任危机 coverage

- [x] **(a) Agent 在 chat 内显式提及来源** — Task 6 ship: TextMessage.tsx 识别 `[查看](#mem-{edge_id})` → 跳转 `/memory?highlight_edge={edge_id}`,MemoryGraph 接收 highlight_edge 高亮 cytoscape edge
- [x] **(b) 首次 session 强 onboarding 弹窗** — Task 5 ship: MemoryOnboardingModal.tsx, "我会记住您的投资偏好和持仓,可随时在 /memory 删除", localStorage `memory_onboarding_seen_v1` 标记
- [x] **(c) 每月推一封'我们记得关于您的 5 件事,请确认'邮件** — Task 7 ship: backend `memory_email.generate_monthly_digest()` 函数返 markdown body 含 5 条 + 一键否决 link, **send 留 P3 hook**(Plan 7B 不 ship,跟 Scale-2 用户回路一起做)

### #8 验证目标对齐

- [x] **机制就位**: 三补丁的 frontend / backend 机制全部 ship
- [⏳] **5 人用户调研 4/5 知道 memory 系统** — 留 dogfood 阶段验,Plan 7B 提供机制
- [⏳] **月度邮件打开率 ≥ 30%** — 实际发送 P3 后才能收集

### 契约 § 1 frontend 路径合规

- [x] `frontend/src/app/memory/page.tsx` — Plan 7A ship,Plan 7B 挂三 tab
- [x] `frontend/src/components/memory/MemoryGraph.tsx` ✓
- [x] `frontend/src/components/memory/MemoryTimeline.tsx` ✓
- [x] `frontend/src/components/memory/MemoryAuditLog.tsx` ✓
- [x] `frontend/src/components/memory/MemoryOnboardingModal.tsx` ✓
- [x] `frontend/src/lib/memory-api.ts` — Plan 7A ship,Plan 7B 复用
- [x] 不引第三方 timeline 库(纯 SVG/CSS),不破坏现仓 stack

### 测试 coverage

- [x] L0 vitest: 4 组件 (MemoryGraph 5 + MemoryTimeline 4 + MemoryAuditLog 4 + MemoryOnboardingModal 3) = **16 项**
- [x] Chat TextMessage 加 2 项 case (mem link + 普通 link 不被拦)
- [x] Backend L0 unit: render_digest_markdown / _empty_digest_template / unknown rel fallback / invalidate_url present = **5 项**
- [x] Backend L1 integration: real PG seed → digest generated / invalidated edges 不进 digest = **2 项**
- [x] Playwright e2e: 三 tab 渲染 / Cytoscape canvas / Timeline bar / Audit 一键否决 / Onboarding 弹窗 + reload 不再弹 = **5 项**(1 项 skip 留 dogfood)
- [x] Smoke test: cytoscape import + render-not-throw = **2 项**

总计:30 项测试 ship。

### Plan 7B 不在范围验证(防 scope creep)

- [x] ❌ 邮件 service 实际发送 → P3 hook,知识卡明记 ref
- [x] ❌ Memory edge edit → P3 hook
- [x] ❌ Cascade invalidate → P3 hook
- [x] ❌ Routing eval / 50 golden case → Plan 8
- [x] ❌ /memory 路由 + 5 backend endpoint → Plan 7A 已 ship,Plan 7B 不重定义

### 工期对账

| Task | Wall time |
|---|---|
| Task 1 装依赖 + smoke | 0.2 天 |
| Task 2 MemoryGraph (cytoscape + drawer + 5 vitest) | 0.6 天 |
| Task 3 MemoryTimeline (SVG bar + filter + 4 vitest) | 0.4 天 |
| Task 4 MemoryAuditLog (table + invalidate + 4 vitest) | 0.3 天 |
| Task 5 MemoryOnboardingModal (modal + 3 vitest) | 0.2 天 |
| Task 6 Chat TextMessage 显式提及 (改造 + 2 vitest) | 0.3 天 |
| Task 7 memory_email backend (L0 + L1) | 0.3 天 |
| Task 8 Playwright e2e + 知识卡 | 0.2 天 |
| **合计** | **2.5 天** ✓ |

跟 spec § 13 的 "#8 用户心智 (显式提及 + onboarding + 邮件 spec) 0.5 天" 算法深度补丁部分对齐;另 2 天是 spec § 9 视图 1/2/3 (4 天 spec 估,Plan 7A 已 ship 1 天 backend API + 0.5 天路由,Plan 7B 实际 frontend 视图 2 天)。

---

## P3 Hook Ref

留待 v1.x 后续 Plan / 触发后 spec:

1. **邮件实际发送** (`memory_email_worker`)
   - 触发:Scale-2 "用户回路 first-class" 上线
   - 实施:Celery monthly cron + SMTP/SendGrid + unsubscribe 链接处理
   - 文件:`backend/app/tasks/memory_email_worker.py` + 接 `app/services/memory_email.generate_monthly_digest()`

2. **Memory edge edit** (改 edge 内容)
   - 触发:dogfood 反馈"否决太重,只是想改个数字"
   - 实施:涉及 bi-temporal 改写(原 edge invalidate + 新 edge insert with same valid_from)
   - 文件:`frontend/src/components/memory/MemoryEditModal.tsx` + backend `PATCH /api/v0/memory/edges/{edge_id}`

3. **Cascade invalidate**
   - 触发:dogfood 撞实"否决了 HOLDS 茅台,但 EXPRESSED_VIEW 茅台还在,不一致"
   - 实施:LLM 判断 cascade 候选 + 用户确认 UI
   - 文件:`backend/app/memory/cascade_resolver.py`

---

## Done Definition

- [ ] 8 task 全 commit
- [ ] vitest 16 项 + chat 2 项 + smoke 2 项 = 20 项 frontend test pass
- [ ] backend L0 5 项 + L1 2 项 = 7 项 backend test pass
- [ ] playwright 5 项 e2e pass(1 skip)
- [ ] frontend build 通过
- [ ] backend mypy strict 通过
- [ ] 知识卡 ship (`docs/claude-context/c5-plan7b-visualizations-onboarding-done.md`)
- [ ] (Plan 8 收束时) CLAUDE.md 加索引

**ship 完触发**:Plan 8 (Eval + Tests + Docs 收束)。
