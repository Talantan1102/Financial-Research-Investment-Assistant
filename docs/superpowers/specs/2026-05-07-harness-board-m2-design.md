# Harness Board · M2 设计文档(增量 spec)

## § 0 元信息与范围

- **基线**:M1 已 ship([2026-05-07-harness-board-design.md](2026-05-07-harness-board-design.md) § 9.1 第一行,PR #29,tag `harness-board-m1`)
- **本期范围**:M1 ship 后的第二期增量(spec § 9.1 第二行 + M1 final review 沉淀的 2 个 follow-up)
- **不在本期**:`/decisions` route + decision_extractor + `spec_section/memory_frontmatter` 死分支测试覆盖(留 M3,届时 decision_extractor 自然会用到这两类 derive_rule)
- **工期估算**:1.5 天 wall time(每天 4-5h Claude Code 投入,memory `feedback_estimate_in_claude_code_walltime`)
- **测试目标**:M1 28 项 + M2 增量 ~12 项 = ~40 项 PASS,mypy strict 仍清洁

---

## § 1 痛点动机:M1 ship 后撞到的问题

M1 跑起来之后,作为日用 dev meta-tool 还差三个闭环:

1. **看不到"我现在在做啥"** — D 视图全是 lit/todo,wip 列空,因为 M1 没暴露编辑模式,无法手填"我在做这条" 信号。Hero "今天没在做任何 capability — 从 todo 挑一个?" 的提示空转。
2. **lit 35 / todo 27 总览感薄弱** — D 视图按 8 维切片,看不到"还有多少件没做",看不到 portfolio 缺口的优先级感。需要 Kanban 三列(Todo / Doing / Done)的"剩余仓库"视角。
3. **App Shell 看不见** — spec § 5.3 设计了第 9 行 mini stat,M1 没实现,前端/Auth/Database/Connectors 工程完整性维度被压成 0。

### 1.1 M1 final review 沉淀的 2 个 non-blocker(本期一并清)

- **(c) GET handler 写副作用** — `_get_or_build_snapshot` lazy build inside GET / 违反 HTTP 语义。M1 已 stub Makefile `board-refresh` target,M2 必接 POST /refresh 闭环。
- **(b) Storage 边界 `dict[str, Any]` 收紧** — `SnapshotRepo.save / get_latest` 用 `dict[str, Any]`,模板侧 `snap["layers"]` / `c["status"]` 全靠肉眼。M2 加 `capability_override` 新表正是收紧 storage layer 的好时机,加 `SnapshotDict` TypedDict 一并做掉。

---

## § 2 决策一:M2 scope 框定

**问题陈述**:M2 该做什么?

**业界 alternatives**:无固定参照(本工具是 self-built dev meta-tool,不存在外部 SaaS 同类对标);备选方案以 spec § 9.1 + M1 review 沉淀的笛卡尔积:

| 候选 | 描述 |
|---|---|
| A 严格 § 9.1 三件 | B Kanban + 编辑模式 + 09 App Shell mini stat |
| B § 9.1 三件 + (c) POST /refresh | + 闭环 M1 已 stub 的 Makefile target |
| **C § 9.1 三件 + (c) + (b) TypedDict 收紧(选用)** | + 顺手做 storage 边界类型化 |
| D § 9.1 三件 + 全部 3 follow-up | + 死分支也带测试覆盖 |

**Tradeoff**:

| 候选 | 优 | 劣 |
|---|---|---|
| A 严格 § 9.1 | 工期最省(1-1.5 天) | M1 stub 的 Makefile target 死路;模板/storage 类型不安全继续累 |
| B + POST /refresh | M1 闭环 | 类型债拖到 M3 |
| **C + (b)(c)** | M2 加新表本来就动 storage 边界,顺手收紧成本极低;模板字典访问获得 mypy 保护 | + 0.3-0.5 天 |
| D + 全部 follow-up | 全部清 | spec_section/memory_frontmatter 在 M3 decision_extractor 自然会用,M2 加 fixture 测试是早动 |

**量化评估**:
- **工期边际成本**:C 比 A 多 0.3-0.5 天,主要在 SnapshotDict TypedDict + 模板字段类型化(~ 10 处访问)
- **bug 暴露率**:M1 SnapshotRepo 用 `dict[str, Any]`,模板侧任何 typo(如 `c["staus"]`)都不会被 mypy 抓;C 改为 TypedDict 后这类 bug 在 mypy 阶段拦截
- **闭环完整度**:A 留下 board-refresh 死链;C 完整闭环

**选用 C**(brainstorming Q1):scope = `§ 9.1 三件 + (b) TypedDict + (c) POST /refresh`。

---

## § 3 决策二:capability_override 表 schema + 写入语义

**问题陈述**:override 表怎么记?spec § 4.2 只说 `(capability_id, status, reason, set_at)` 四列,没说"用户清除 override"如何记。

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| **A single row per capability(选用)** | 表加 `UNIQUE(capability_id)`;set 是 upsert;clear 是 DELETE |
| B append-only history | 每次操作 INSERT 一行(包括 clear 写 `status=NULL`);读 `ORDER BY set_at DESC LIMIT 1` |

**Tradeoff**:

| 候选 | 优 | 劣 |
|---|---|---|
| **A single row** | 表 ≤ 62 行,代码 ~30 行;读快,索引天然(主键就是 capability_id) | override 修改无 history;回滚靠用户重新 toggle |
| B append-only | 保留审计 trail;支持 history view UI | 表行数累加;读需 `ORDER BY` + `LIMIT`;每次 clear 写一行 status=NULL 半语义 |

**量化评估**:
- **代码量**:A ~30 行(`UPSERT INTO ... ON CONFLICT(capability_id) DO UPDATE`);B ~50 行(query + tombstone 处理)
- **读性能**:A 主键直查 O(log N);B `ORDER BY set_at DESC LIMIT 1` 需 covering index 才不退化
- **dev 工具语义**:个人 portfolio 项目无审计 trail 需求,git log 已经记录代码变化

**选用 A**(brainstorming Q2):single row per capability,upsert + DELETE 清。

### § 3.1 完整 schema

```sql
CREATE TABLE IF NOT EXISTS capability_override (
  capability_id TEXT PRIMARY KEY,           -- 例 "memory.long_term_memory"
  status TEXT NOT NULL,                      -- "lit" | "wip" | "todo"
  reason TEXT NOT NULL DEFAULT '',           -- 选填,UI 默认空
  set_at TEXT NOT NULL                       -- ISO 8601 datetime
);
```

`reason DEFAULT ''` 让前端不填时落空字符串,简化 NULL handling。

### § 3.2 OverrideRepo 接口

```python
class OverrideRepo:
    def __init__(self, conn: sqlite3.Connection): ...
    def get_all(self) -> dict[str, CapabilityStatus]:
        """返回 {capability_id: status},喂给 build_snapshot(overrides=...)"""
    def upsert(self, capability_id: str, status: CapabilityStatus,
               reason: str = "", set_at: str | None = None) -> None: ...
    def delete(self, capability_id: str) -> None: ...
```

`get_all()` 返回的形状直接对接 `capability_resolver.resolve_all(overrides=...)`,无需中间转换。

---

## § 4 决策三:edit mode UX 形态

**问题陈述**:用户怎么编辑 chip 状态?

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| **A 原生 `<select>` 4 选 1 + htmx swap(选用)** | 点 chip → 模板用 htmx swap 渲染 `<select>` → 选完 `hx-post` |
| B 直接 cycle | 点击循环 lit→wip→todo→clear→derived,无 popup |
| C hover panel + reason input | 鼠标悬停显示 4 mini button + 备注框 |

**Tradeoff**:

| 候选 | 优 | 劣 |
|---|---|---|
| **A 原生 select** | 浏览器 native,无 JS,所有状态显式可见;reason 字段写选填 input | 多一次 click(open select + select option);需 4 选 1 包含 "clear override" |
| B cycle | 单击操作 | 不直观,误点不知当前状态;无显式 "clear override" 入口 |
| C hover panel | 一次操作完所有字段 | hover 在 mobile 失效;dev 工具不需要 reason 那么严肃 |

**量化评估**:
- **代码复杂度**:A htmx 一行 `hx-get="/capability/{id}/edit"` swap select,B 需要 cycle 逻辑 + state 跟踪,C 需 hover JS + modal CSS
- **可发现性**:A select 4 个选项一眼可见(force-lit / set-wip / force-todo / clear);B 隐式 cycle 不发现 clear;C hover 需要鼠标停留
- **mobile 兼容**:A/B 兼容,C 不兼容(macOS 主用,但仍是减分项)

**选用 A**(brainstorming Q3a):chip 点击 → htmx swap 出 `<select>` → 选完 POST。

### § 4.1 交互细节

```
[点击 chip]                     [select 弹出]                  [select 后]
┌──────────────┐  hx-get →  ┌────────────────────────┐  hx-post →  ┌────────────┐
│ ✅ Memory     │            │ <select>                │             │ 🟠 Memory   │
│ checkpoint   │            │   force-lit             │             │ checkpoint │
└──────────────┘            │   set-wip               │             └────────────┘
                            │   force-todo            │
                            │   clear override        │
                            │ </select>               │
                            └────────────────────────┘
```

**4 选 1 语义** —— 所有 `status` field 走同一 POST endpoint,前端区分:
- `force-lit` / `set-wip` / `force-todo`:body `status=lit|wip|todo` → upsert
- `clear override`:body `status=__clear__` → DELETE

也可以用 HTTP DELETE 走单独 route,但 jinja 表单原生不支持 DELETE method,htmx 需 `hx-delete`。统一 POST + sentinel 简化模板。

### § 4.2 reason 字段

UI **不显示 reason 输入框**(M2 简化)。OverrideRepo.upsert 接受 `reason=""` default,行内自动填 "via UI"(set_at 标 ISO timestamp 已经够追溯)。如果未来有需求,M3 加 expandable 详情面板填 reason。

---

## § 5 决策四:stale ✏️ 视觉标记

**问题陈述**:override 写入后,UI 怎么区分"派生命中" vs "手填"?

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| **A 加 ✏️ emoji 标记(选用)** | chip 上 `{% if c.derived_status != c.status %}✏️{% endif %}` |
| B 不标记 | spec § 4.2 默认,override 跟 derived 视觉一致 |

**选用 A**(brainstorming Q3b):
- **Why**:半年后回来一眼看出哪些是手填,哪些是真派生命中
- **实施成本**:1 行 jinja conditional,CSS `.stale-mark { font-size: 9px; opacity: 0.7; }` 5 行
- **不混淆**:✏️ 跟现有 ✅ / 🟠 / ⬜ 视觉区别清晰,叠加显示(eg `✅✏️` = "派生说 lit + 手填覆盖也是 lit",`✏️🟠` = "派生说 todo 但手填 wip")

---

## § 6 决策五:App Shell 第 9 行 mini stat 公式

**问题陈述**:spec § 5.3 留白"file count / loc / capability hit ratio,实施时按 derive_rule 决定"。M2 必须填。

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| **A `<file count>` 显示(选用)** | path_router 反向归类,数 6 项各命中多少文件;eg `Frontend: 47 files` |
| B `<file_exists>` bool | 6 项各做单点 file_exists,显示 ✅/⬜;eg `Frontend: ✅` |
| C `<lit/total>` ratio | 6 项各按 capability 计 lit/total,跟 8 维一致 |

**Tradeoff**:

| 候选 | 优 | 劣 |
|---|---|---|
| **A file count** | 反映"该应用层有多丰富",对个人 portfolio 项目 useful;实施直接 `glob(path)` count | 单维数字,无 progress 感 |
| B bool | 简单,易 mock | 信息量低(只能看 0/1) |
| C ratio | 跟 D 视图视觉一致 | App Shell 没有 capability 列表,要现做 6 套 sub-capability,YAGNI |

**量化评估**:
- **实施量**:A 一个新 derive 模块 ~20 行(loop App Shell items, glob count);B 复用 file_exists 1 行;C 需另起 60+ App Shell capability YAML
- **信息密度**:A "47 files"瞬间看到模块体量;B 只能看 0/1;C 跟 D 视图重复
- **个人 portfolio 价值**:A 瞬间显示"前端 47 文件 / 鉴权 8 / 数据库 5",对简历叙事有用

**选用 A**(brainstorming Q3c):file count via path_router 反向归类。

### § 6.1 derive 模块

新模块 `dashboard/derive/app_shell_stat.py`:

```python
def compute_app_shell_stat(
    project_root: Path,
    app_shell: list[DimensionConfig],   # 来自 load_dimensions()[1]
) -> list[AppShellItem]:
    """返回 6 项 (id, name_cn, file_count) 列表。"""
    out = []
    for d in app_shell:
        count = 0
        for glob_pat in d.paths:
            count += sum(1 for fp in glob(str(project_root / glob_pat), recursive=True)
                         if Path(fp).is_file())
        out.append(AppShellItem(id=d.id, name_cn=d.name_cn, file_count=count))
    return out
```

`AppShellItem` 加在 `dashboard/derive/types.py`。

---

## § 7 决策六:POST /refresh 触发条件

**问题陈述**:override 写入后,前端怎么及时反映新状态?

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| A 仅手动 | 仅 `make board-refresh` curl POST /refresh |
| **B override 写自动 invalidate + 显式 POST 强制(选用)** | override 写时 DELETE FROM derived_snapshot;POST /refresh 也 invalidate |
| C 都做(同 B) | 跟 B 实质相同 |

**选用 B**(brainstorming Q3d):
- **Why**:override 写入必须立即影响下次 GET / 渲染,不然新设的 wip 看不到。invalidate snapshot cache 是最简单的 cache busting,跟 M1 lazy-build 模式一致。
- **数据流**:`POST /capability/{id}/override` → `OverrideRepo.upsert` + `SnapshotRepo.invalidate()` (DELETE FROM derived_snapshot) + 返回新 chip HTML 给 htmx swap;**chip 立即 swap 对用户可见**;同时 cache 已 invalidate,下次完整 GET / 会重 build 含新 override 的 snapshot。
- **POST /refresh 仍保留** — 仅 invalidate snapshot,302 to `/`。用于代码改了但 override 没动的场景(eg 加新文件需要 path_router 重 scan)。

### § 7.1 关键不变量

- `derived_snapshot.payload` 永远是"已 apply override"的最终态(M1 已经支持 overrides 参数,M2 喂进去即可)
- override 写 → 必 invalidate snapshot → 下次 GET / 重 build
- POST /refresh = 显式 invalidate,跟 override 写共享同一 invalidate 函数,无 dead code

---

## § 8 决策七:`SnapshotDict` TypedDict 收紧

**问题陈述**:M1 `SnapshotRepo.save(payload: dict[str, Any])` / `get_latest() -> dict[str, Any] | None` 是 storage 边界 untyped。模板侧 `snap["layers"]` / `c["status"]` 任何 typo 不会被 mypy 抓。

### § 8.1 TypedDict 定义(`dashboard/derive/types.py`)

```python
class CapabilityDict(TypedDict):
    id: str
    dimension: DimensionId
    name_cn: str
    name_en: str
    status: CapabilityStatus
    derived_status: CapabilityStatus

class LayerSummaryDict(TypedDict):
    id: DimensionId
    number: str
    name_cn: str
    name_en: str
    lit: int
    wip: int
    todo: int
    total: int
    capabilities: list[CapabilityDict]

class SnapshotDict(TypedDict):
    refreshed_at: str
    layers: list[LayerSummaryDict]
    total_lit: int
    total_wip: int
    total_todo: int
    total: int
```

### § 8.2 收紧后的 storage 接口

```python
class SnapshotRepo:
    def save(self, refreshed_at: str, payload: SnapshotDict) -> None: ...
    def get_latest(self) -> SnapshotDict | None: ...
    def invalidate(self) -> None: ...     # 新增,M2 用,DELETE FROM derived_snapshot
```

### § 8.3 影响面

- `Snapshot.to_dict()` 返回 `SnapshotDict`(`from typing import cast` 一次或显式构造)
- `_get_or_build_snapshot()` 返回 `SnapshotDict`
- `index` view 把 `snap: SnapshotDict` 传给 jinja(jinja 仍按字典访问,但 Python 侧 mypy 已守好)
- 模板侧 typo(eg `{{ c.staus }}`)不会被 mypy 抓 — Jinja 是动态字符串,这是 known limitation。但模板 Pydantic 数据进出已经被收紧。

---

## § 9 5 层架构增量

| 层 | M1 现状 | M2 增量 |
|---|---|---|
| **Source** | `dimensions.yaml` + `capabilities.yaml` | 无变化 |
| **Derive** | `path_router` + `capability_resolver` + `snapshot_builder` | + `app_shell_stat.py`;`build_snapshot()` 接受 overrides 参数(M1 已有,M2 喂数据);`types.py` 加 `SnapshotDict` / `AppShellItem` |
| **State** | `SnapshotRepo`(全量替换) | + `OverrideRepo`(upsert / delete / get_all);`SnapshotRepo` 加 `.invalidate()`;types 收紧到 `SnapshotDict` |
| **Server** | `GET /` + `GET /healthz` + Mount /static | + `GET /?view=d|b`;+ `POST /capability/{id}/override`;+ `GET /capability/{id}/edit`(htmx swap select);+ `POST /refresh` |
| **UI** | `base.html` + `main.html` + `_hero.html` + `_d_view.html` + `style.css` + htmx vendor | + `_b_view.html`(Kanban 三列);+ `_d_b_toggle.html`(Tab nav);+ `_app_shell.html`(第 9 行);+ `_capability_chip.html`(抽出 chip 渲染,htmx swap 重用);+ `_edit_select.html`(htmx swap source);改 `_d_view.html`(stale ✏️ + chip click htmx attrs);改 `style.css`(Kanban / app-shell / stale / select / view-toggle 样式) |

---

## § 10 视图布局

### § 10.1 D/B Tab toggle

```html
<nav class="view-toggle">
  <a href="/?view=d" class="{% if view_mode == 'd' %}active{% endif %}">D 维度</a>
  <a href="/?view=b" class="{% if view_mode == 'b' %}active{% endif %}">B Kanban</a>
</nav>
```

URL 决定 view,服务端渲染 `_d_view.html` 或 `_b_view.html`。无 JS state。

### § 10.2 B Kanban 视图

三列:Todo (todo count) / Doing (wip count) / Done (lit count)。Done 列默认折叠,显示计数 + `+ 展开`,点击展开完整列表。

```
┌───────────────┬───────────────┬───────────────┐
│ Todo (27)     │ Doing (0)     │ Done (35)     │
├───────────────┼───────────────┼───────────────┤
│ [04] Sem.. ✏️ │ (列空)         │ + 展开         │
│ [04] L-term  │               │               │
│ [01] Ver..   │               │               │
│ ...           │               │               │
└───────────────┴───────────────┴───────────────┘
```

每张卡 = `[XX] capability_中文 ✏️?`。XX 是 dim number(01-08)。点击卡片同 D 视图触发 htmx select。

### § 10.3 09 App Shell 第 9 行

布局接在 D 或 B 视图下方,**虚线边框、灰调、单行**:

```
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
  09 App Shell  │ 前端: 47   后端: 32   鉴权: 8
                │ 数据库: 5  连接器: 12  部署: 9
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
```

不进 62 计数,**只是工程完整性 reminder**(spec § 5.3 决议)。

---

## § 11 工程组成

### § 11.1 新增文件

```
dashboard/
├── derive/
│   ├── app_shell_stat.py            # 新
│   └── types.py                     # 改:加 SnapshotDict / AppShellItem TypedDict
├── state/
│   ├── repositories.py              # 改:加 OverrideRepo + SnapshotRepo.invalidate
│   └── db.py                        # 改:SCHEMA 加 capability_override 表
├── templates/
│   ├── _b_view.html                 # 新:Kanban 3 列
│   ├── _d_b_toggle.html             # 新:Tab nav
│   ├── _app_shell.html              # 新:第 9 行
│   ├── _capability_chip.html        # 新:抽出 chip 渲染(给 htmx swap 重用)
│   ├── _edit_select.html            # 新:edit dropdown(htmx swap source)
│   ├── _d_view.html                 # 改:stale ✏️ + chip htmx attrs
│   ├── base.html                    # 改:Tab nav 引用
│   └── main.html                    # 改:渲染 view_mode 动态 partial + app_shell
├── static/
│   └── style.css                    # 改:加 .kanban-* / .app-shell-* / .stale-mark / .edit-select / .view-toggle
├── server.py                        # 改:加 3 routes + view_mode query
└── tests/
    ├── derive/
    │   ├── test_app_shell_stat.py   # 新(3 项)
    │   └── test_snapshot_builder.py # 改(+1 SnapshotDict round-trip)
    ├── state/
    │   └── test_override_repo.py    # 新(4 项)
    └── server/
        └── test_main_endpoint.py    # 改(+4 项)
```

### § 11.2 不新增依赖

M2 复用 M1 的 jinja2 + sqlite3(stdlib)+ htmx vendored,无 npm,无新 pyproject 依赖。

---

## § 12 API 列表

| Method | Path | 作用 | 返回 |
|---|---|---|---|
| GET | `/?view=d\|b` | 主视图(d default) | HTML(D 或 B 视图 + Hero + 第 9 行) |
| GET | `/healthz` | 健康检查 | `{"ok": true}` |
| GET | `/capability/{id}/edit` | edit dropdown(htmx swap source) | `<select>` HTML(4 选 1) |
| POST | `/capability/{id}/override` | upsert override(form `status` + 选填 `reason`)或 sentinel `status=__clear__` | 新 chip HTML(htmx swap target = 原 chip) |
| POST | `/refresh` | 显式 invalidate snapshot | 302 to `/?view=...` |
| GET | `/static/*` | 静态资源 | css / js |

POST endpoints 用 form-encoded(htmx 默认),不 JSON。

---

## § 13 测试增量

### § 13.1 新增 ~10 项

```
dashboard/tests/
├── state/test_override_repo.py            # 4 项
│   ├── test_empty_returns_empty_dict
│   ├── test_upsert_then_get
│   ├── test_delete_clears
│   └── test_multi_capability_isolation
├── derive/test_app_shell_stat.py          # 3 项
│   ├── test_basic_file_count
│   ├── test_empty_dir_zero
│   └── test_glob_no_match_zero
├── server/test_main_endpoint.py           # 加 4 项
│   ├── test_index_view_b_renders_kanban
│   ├── test_post_override_invalidates_and_swaps
│   ├── test_post_override_clear_sentinel
│   └── test_post_refresh_invalidates_and_redirects
└── derive/test_snapshot_builder.py        # 加 1 项
    └── test_snapshot_to_dict_satisfies_typed_dict
```

### § 13.2 测试方法

- `OverrideRepo` 测试用 `tmp_path` 起 sqlite,跟 M1 `test_repositories.py` 同模式
- `app_shell_stat` 测试用 `tmp_path` 造假 file tree + mock `DimensionConfig`,无 real fs scan
- server 测试用 starlette TestClient,继承 M1 模式;`test_post_override_invalidates_and_swaps` 验证 (a) sqlite 里 override row 写入 (b) `derived_snapshot` 表行数 = 0(被 invalidate)(c) HTML response 是 chip outerHTML(含新 status class)
- TypedDict 测试用 `cast(SnapshotDict, snap.to_dict())` + assert 字段都在,verify 类型 round-trip

### § 13.3 mypy 不放松

新加文件全 strict;TypedDict 收紧后模板 view 函数必须显式 return `SnapshotDict`,不能 `dict`。

---

## § 14 Ship 标准(spec § 9.1 M2 落地)

verify 跑通 6 条:

1. ✅ `make board` 浏览器开,有 D/B Tab
2. ✅ 切到 B,看到 Kanban 三列(Todo 27 / Doing 0 / Done 35 折叠)
3. ✅ 点击 chip,弹 select 4 选 1,选 wip,chip 立即变 🟠 + ✏️
4. ✅ 关浏览器再开,wip 仍在(sqlite 持久化)
5. ✅ 第 9 行显示 `09 App Shell · 前端: N · 后端: N · ... · 部署: N`
6. ✅ `make board-refresh` 触发 POST /refresh,curl 返 302 + 重 build
7. ✅ `mypy dashboard/` strict 全 PASS;`pytest dashboard/tests/` 38+ PASS

---

## § 15 工期 + 风险

### § 15.1 工期估算

1.5 天 wall time(memory `feedback_estimate_in_claude_code_walltime`,每天 4-5h Claude Code 投入)。任务大致:

| 子项 | 估时 |
|---|---|
| capability_override 表 + OverrideRepo + 测试 | 2h |
| SnapshotDict TypedDict + 收紧 storage | 2h |
| app_shell_stat 模块 + 测试 | 1.5h |
| `_b_view.html` + Kanban CSS | 2h |
| `_d_b_toggle.html` + view_mode query 路由 | 1h |
| edit mode htmx(`/capability/{id}/edit` + POST + chip swap) | 2.5h |
| stale ✏️ 标记 + chip rerender 模板抽出 | 1h |
| POST /refresh + invalidate hook | 0.5h |
| `_app_shell.html` + 第 9 行 CSS | 0.5h |
| 整体 E2E smoke + tests | 1h |

合计 ~14h ≈ 1.5 天(buffer 0.5h)。

### § 15.2 风险

| 风险 | 概率 | 缓解 |
|---|---|---|
| **htmx swap target 错** | 中 | 每 chip 用 capability_id 做唯一 anchor `id="cap-{c.id|replace('.','-')}"`;`hx-target="#cap-{...}"` 显式;不依赖 closest |
| **TypedDict 跟 Snapshot dataclass 双源** | 中 | dataclass `to_dict` 用 `cast(SnapshotDict, ...)`;变更必须同步两处。memory `feedback_third_party_plugin_defaults` 提示先 spike;mypy strict 会抓 mismatch |
| **`__clear__` sentinel 跟 force-* 在同一 endpoint 混乱** | 低 | server 显式 `if status == "__clear__":` 分支;test 单独 case |
| **Kanban Done 列折叠默认值持久化?** | 低 | M2 不持久化(刷页恢复折叠态)。若用户反馈再 M3 加 localStorage |
| **path_router glob 反向归类性能** | 低 | 项目 ~ 1000 文件量级,6 次 glob ≤ 100ms,无需 cache |
| **override 写跟 GET / 并发** | 极低 | 个人 dev 工具单进程,`with conn:` 事务自然 serialize |

---

## § 16 范围边界 / YAGNI

### § 16.1 在范围内 ✓

- B Kanban 三列(Todo/Doing/Done 折叠)
- 编辑模式:chip 点击 → select → upsert override
- override 持久化 (sqlite single row per capability)
- stale ✏️ 视觉标记(派生 ≠ override)
- 09 App Shell 第 9 行 mini stat (file count 公式)
- POST /refresh 显式刷新闭环
- `SnapshotDict` TypedDict 收紧 storage 边界

### § 16.2 不在范围 ✗(显式排除,防滑动)

- ❌ B Kanban 拖拽切列(htmx + sortable.js v3 候选)
- ❌ override 历史 / undo / redo(留 M3 视需求)
- ❌ override reason input UI(M2 reason 字段存"via UI",M3 视需求)
- ❌ wip due date / timer
- ❌ Done 列折叠态持久化(刷页恢复)
- ❌ `/decisions` route + decision_extractor(留 M3)
- ❌ `spec_section` / `memory_frontmatter` derive_rule fixture 测试覆盖(留 M3,届时 decision_extractor 自然会用到)
- ❌ 多用户 / auth(本工具单用户 portfolio 用,无 viewer/editor 角色)
- ❌ 编辑模式 toggle(无 viewer 角色,默认即可编辑)
- ❌ 外网公开(localhost:8910 only,不 deploy)

---

## § 17 实施引用

实施时按 [docs/superpowers/plans/](../plans/) 下产出的 M2 plan 跑(下一步 brainstorming → writing-plans skill 会写)。
