# Harness Board · M3 设计文档(增量 spec)

## § 0 元信息与范围

- **基线**:M2 已 ship([2026-05-07-harness-board-m2-design.md](2026-05-07-harness-board-m2-design.md),PR #31,tag `harness-board-m2`)
- **本期范围**:M2 ship 后第三期增量(spec § 9.1 第三行 = `/decisions` route + decision_extractor + filter UI)+ M2 final review 沉淀 2 件 follow-up(test infra fixture / M1 test mypy 清债)
- **不在本期**:B Kanban `[XX]` dim prefix(M2 polish PR);`LayerSummary.id` cast 收紧(M2 polish);决策 `state: deprecated` 自动 detect(留 M3.x);URL filter state 同步(留 M3.x)
- **工期估算**:1.3 天 wall time(spec § 9.1 M3 1 天 + (b)+(c) follow-up 0.3 天,memory `feedback_estimate_in_claude_code_walltime`)
- **测试目标**:M2 47 项 + M3 增量 ~12 项 = ~59 项 PASS,mypy strict 含 test files 全清洁

---

## § 1 痛点动机:M2 ship 后撞到的问题

M2 D/B 视图 + 编辑模式跑起来后,作为 portfolio 工具还差三个闭环:

1. **决策追溯断片** — 8 个 spec + 30+ memory 文件里散着大量"决策一/决策二"段(每段都按业界 alternatives + tradeoff + 量化评估四件套写),但分散在文件里没有索引页。求职面试讲技术决策时翻不到 quick reference,简历叙事也缺一个"决策清单"页。
2. **note 不能就地 capture** — D 视图编辑模式只能 toggle wip / lit / todo,不能就地写"为什么这么改"。所有决策的 note 都得写在 git commit message 里,事后翻 git log 比翻 dashboard 重。
3. **测试技术债累计** — M2 server tests 共享 `backend/data/board.db`,靠 inline cleanup `__clear__` 维持隔离,fragile;M1 test files 8 处 mypy strict 报错(返回类型缺 `-> None`、`list` 缺 type arg),M3 加 ~12 测试时正好一并清。

---

## § 2 决策一:M3 scope 框定

**问题陈述**:M3 该做什么?

**业界 alternatives**:无固定参照(self-built dev meta-tool);备选以 spec § 9.1 + M2 final review 沉淀的笛卡尔积:

| 候选 | 描述 |
|---|---|
| A 严格 § 9.1 三件 | `/decisions` route + decision_extractor + filter UI |
| **B § 9.1 + (b) test fixture + (c) M1 mypy 清债(选用)** | + test infra 升级(顺手) |
| C § 9.1 + 全部 4 follow-up | + (a) Kanban `[XX]` dim prefix + (d) LayerSummary cast 收紧 |
| D § 9.1 三件 only,余 follow-up 各自 polish PR | 严格 scope,每事一 PR |

**Tradeoff**:

| 候选 | 优 | 劣 |
|---|---|---|
| A 严格 § 9.1 | 工期最省(1 天) | M3 加 ~12 server tests,继续用 M2 inline cleanup 模式 fragile;M1 mypy 老债不动 |
| **B + (b)(c)** | M3 加 server tests 时 fixture 已就位,~10 处复用;M1 mypy debt 顺手清 | + 0.3 天 |
| C + (a)(d) | 一并清债 | (a) Kanban prefix 是 M2 polish,放 M3 主线污染 scope;(d) LayerSummary cast 跟 M3 主线无关 |
| D 严格 + 多 polish PR | scope 最干净 | 浪费 M3 ship 时机;polish PR 容易拖 |

**量化评估**:
- **工期边际成本**:B 比 A 多 0.3 天,主要在 (b) `conftest.py` 写 autouse fixture + 改 ~5 个 server test files
- **测试可读性**:M2 server tests 含 inline `__clear__` 模式 4 处;B 后零 inline cleanup,fixture 自动隔离
- **mypy 绿率**:M1 残留 8 strict errors 全在 test files;B 加 `-> None` 注解 + `list[T]` type args 即清

**选用 B**(brainstorming Q1)。

---

## § 3 决策二:decision_extractor 数据来源 + layer derive 复杂度

**问题陈述**:决策从哪来?layer 字段(spec § 7.4 mockup 显示 `[06 GUARD]`)如何 derive?

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| A 仅扫 spec sections | 9 个 spec 文件 `^## § \d+ 决策\d+:.*` 段;~12 项 |
| **B spec + memory frontmatter(选用)** | A + memory `*.md` frontmatter(`type=feedback\|project`);layer 用 `dimensions.yaml.keywords` 反向归类;~47 项 |
| C B + frontmatter convention 升级 | + memory 35+ 文件手填 `layer: ...` + `state: ...` |

**Tradeoff**:

| 候选 | 优 | 劣 |
|---|---|---|
| A 仅 spec | 实现最简(扫 1 类源) | 数量 ~12 偏少,filter UI 价值低;memory 大量决策(35+ feedback)被埋没 |
| **B spec + memory 关键字归类** | 数量 ~47 符合 spec § 9.1 anchor "30-50 项";复用 dimensions.yaml.keywords 字段无新数据;layer 命中率 ~80% | layer 边界 case 落 META(eg `Skills bundle` 含 "Skills" → prompt_context 但语义跨 layer);M3 用 note 编辑模式手补 |
| C frontmatter convention | layer 准确率 ~95% | 35+ 文件手填工期翻倍;不符合 1.3 天 wall time |

**量化评估**:
- **代码量**:A 扫 1 类源 ~30 LoC;B 加 memory frontmatter 解析 + 关键字归类 ~50 LoC;C 同 B + 35 文件手填(LoC 不增但人工时大)
- **layer 命中率**(基于 dimensions.yaml.keywords 8 dim 各 2-4 关键字):
  - spec section 内 keyword 密度高 → A 命中 ~90%
  - memory frontmatter description 短(< 100 字符)→ B 命中 ~70-80%(剩 META 兜底)
- **决策数量 anchor**:spec § 9.1 "预计 30-50 项";A 12 不达标,B 47 达标,C 47 同 B

**state 字段处理**(三方案统一):全部默认 `active`,`deprecated` detection 留 M3.x。M3 ship 时所有决策都是 active,filter state chip 仍 render 但 deprecated 列表为空。

**选用 B**(brainstorming Q2)。

### § 3.1 layer 关键字归类算法

```python
def classify_layer(text: str, main_dims: list[DimensionConfig]) -> str:
    """从 description+name 文本里 keyword scan 8 dim,返回最多匹配的 dim id。
    无匹配返 'META'。"""
    scores: dict[str, int] = {}
    for d in main_dims:
        for kw in d.keywords:
            if kw.lower() in text.lower():
                scores[d.id] = scores.get(d.id, 0) + 1
    if not scores:
        return "META"
    return max(scores.items(), key=lambda x: x[1])[0]
```

### § 3.2 version derive 规则

- spec 文件:filename regex `\d{4}-\d{2}-\d{2}-(v\d+\.\d+(?:\.\d+)?|M\d+)-` 提取(eg `2026-05-05-v0.8.5-...md` → `v0.8.5`,`2026-05-07-harness-board-m2-design.md` → `M2`)
- memory `project_v(\d+\.\d+)_*.md`:filename regex 提取(eg `project_v0.8.5_architecture_landed.md` → `v0.8.5`)
- memory `feedback_*.md`:**无 version 模式**,落 `unversioned`
- 无匹配 → `unknown`

---

## § 4 决策三:`decision_note` 表 schema + 写入语义

**问题陈述**:用户备注怎么记?

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| **A 平行 capability_override pattern(选用)** | `decision_note(decision_id PK, note TEXT, set_at TEXT)`;upsert + DELETE;single row per decision |
| B 通用 user_note(target_type, target_id, ...) | 服务多类型(decision + 未来 capability + ...) |

**Tradeoff**:

| 候选 | 优 | 劣 |
|---|---|---|
| **A** | YAGNI;capability 当前不用 note;同 M2 OverrideRepo 模式 1:1 复用代码与心智 | 未来若给 capability 也加 note 需新表 / 改名;但 spec § 4.2 明确"M2 reason 字段已存,M3 不加 capability note" |
| B 通用表 | 1 表服务多用例 | 多态字段(target_type ENUM 强校验)增复杂;decision 是当前唯一 user 主动写的字段 |

**选用 A**(brainstorming Q3a)。

### § 4.1 完整 schema

```sql
CREATE TABLE IF NOT EXISTS decision_note (
  decision_id TEXT PRIMARY KEY,         -- 12 字 sha256(version + layer + title)[:12]
  note TEXT NOT NULL DEFAULT '',
  set_at TEXT NOT NULL
);
```

### § 4.2 DecisionNoteRepo 接口

```python
class DecisionNoteRepo:
    def __init__(self, conn: sqlite3.Connection): ...
    def get_all(self) -> dict[str, str]:
        """返回 {decision_id: note}"""
    def upsert(self, decision_id: str, note: str, set_at: str | None = None) -> None: ...
    def delete(self, decision_id: str) -> None: ...
```

跟 M2 OverrideRepo 1:1 镜像,只换字段名 + 表名。

---

## § 5 决策四:filter 数据流

**问题陈述**:用户多选 layer / state / 关键字时,如何 render?

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| **A Server render 全部 + client JS filter(选用)** | 一次 GET /decisions 拿全部 ~47 卡 HTML,JS toggle `display: none` |
| B Server render + filter form submit | 每次 filter 改 → POST → server 重 render 子集 |
| C SPA(Vue/React) | 拒绝 |

**Tradeoff**:

| 候选 | 优 | 劣 |
|---|---|---|
| **A** | spec § 7.4 明确"无 server roundtrip";~47 卡 HTML ~30KB,首屏 OK;JS filter 即时无延迟 | client JS ~30 LoC(scan cards 设 display);data-attr 多挂(layer/state/title text) |
| B 重 render | 无 client JS | filter 改一次 = 1 次 GET,延迟 ~50-200ms;不符合 spec |
| C SPA | 现代前端范式 | 跟 dashboard 极简手写风格冲突,htmx vendored 哲学违背 |

**选用 A**(brainstorming Q3b)— spec 明文约束。

### § 5.1 数据流细节

- Server `GET /decisions` → render `decisions.html`,每张 card 含 `data-layer="04"` `data-state="active"` `data-text="<lower-case title + why>"` 属性
- Client JS 监听:
  - layer chip click → toggle `.active` class → 收集所有 active layer chip values → scan cards,卡 layer ∈ active layers OR active layers 为空 → 显示
  - state chip 同
  - keyword `<input>` `oninput` → scan cards,`data-text` 含 keyword → 显示
- 三种 filter AND 关系(layer + state + keyword 同时满足才显示)

---

## § 6 决策五:filter UI 形态

**问题陈述**:UI 元素怎么呈现 filter 多选?

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| **A chip 多选 + keyword input(选用)** | 8 dim chip + META + state 2 chip + 1 keyword input;点击 chip toggle `.active` class |
| B `<input type="checkbox">` 列 | 列出 9 + 2 + input,checkbox 原生 |
| C URL query 双向同步 | `?layer=04,06&state=active&q=router`;state 持久化 |

**Tradeoff**:

| 候选 | 优 | 劣 |
|---|---|---|
| **A** | 跟 dashboard chip 三态 lit/wip/todo 视觉风格一致;手写 CSS ~10 行 | URL state 不持久化(刷页 reset filter) |
| B checkbox | 浏览器原生,无 JS | 视觉重,跟 chip-heavy dashboard 风格冲突 |
| C URL 同步 | 链接可分享 + 刷页保留 filter | 增 URL parsing + JS 同步逻辑 ~20 行;M3 主用例(dogfood)无分享需求 |

**选用 A**(brainstorming Q3c);URL 同步留 M3.x。

---

## § 7 决策六:nav entry 形态

**问题陈述**:`/decisions` 入口在哪?

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| **A D/B/决策 三 tab(选用)** | 现 `_d_b_toggle.html` 改名 `_view_toggle.html`,加第三 tab → `/decisions` |
| B Hero 加 link | `<a href="/decisions">查看决策</a>` |
| C 仅 URL 直接访问 | 无 nav |

**选用 A**(brainstorming Q3d):决策视图跟 capability matrix(D/B)是平行视图,共享 tab nav 是自然结构。

### § 7.1 active 状态判定

`_view_toggle.html` 接 `active_view: "d" | "b" | "decisions"`:
- `GET /` 时 server 传 `active_view = view_mode`(d 或 b)
- `GET /decisions` 时 server 传 `active_view = "decisions"`

模板:

```html
<nav class="view-toggle">
  <a href="/?view=d" class="{% if active_view == 'd' %}active{% endif %}">D 维度</a>
  <a href="/?view=b" class="{% if active_view == 'b' %}active{% endif %}">B Kanban</a>
  <a href="/decisions" class="{% if active_view == 'decisions' %}active{% endif %}">决策</a>
</nav>
```

---

## § 8 决策七:decision_extractor 模块结构

**问题陈述**:模块拆几个文件?

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| **A 单文件 `decision_extractor.py`(选用)** | ~80 LoC,内含 spec scan + memory scan + 合并 + ID 计算 |
| B 两 collector | `spec_collector.py` + `memory_collector.py` + `extractor.py` 合并 |
| C 多 inner func | 1 文件 + 内部函数细分 |

**选用 A**(brainstorming Q3e):
- M3 工期 1 天,单文件 ~80 LoC 容易 hold + review
- M3.x 拆分如有需要(eg M4 加 git log collector / commit message collector,两 collector 才有意义)

---

## § 9 路径配置:memory_path

**问题陈述**:memory 文件不在 repo,在 `~/.claude/projects/<escaped-project-path>/memory/`。dashboard 怎么找?

**solution**:三层 fallback,优先级从高到低:

1. **env var override**:`HARNESS_MEMORY_PATH=/abs/path` 优先
2. **auto-detect**:`Path.home() / ".claude" / "projects" / ("-" + str(PROJECT_ROOT).replace("/", "-")) / "memory"`(基于 Claude memory escape 规则)
3. **fallback**:目录不存在 → memory_extractor 部分跳过 + UI 顶部显示 warning banner "memory 路径未找到,仅显示 spec 决策 ~12 项"

### § 9.1 实现细节

```python
def resolve_memory_path() -> Path | None:
    env = os.environ.get("HARNESS_MEMORY_PATH")
    if env:
        return Path(env)
    auto = Path.home() / ".claude" / "projects" / ("-" + str(PROJECT_ROOT).replace("/", "-")) / "memory"
    if auto.exists():
        return auto
    return None
```

- 启动时跑一次,server.py 缓存 `MEMORY_PATH` 模块级常量
- 单元测试通过 `monkeypatch.setenv("HARNESS_MEMORY_PATH", str(tmp_path))` 注入

---

## § 10 5 层架构增量

| 层 | M2 现状 | M3 增量 |
|---|---|---|
| **Source** | dimensions.yaml + capabilities.yaml | 无 yaml 变化;新增 `MEMORY_PATH` 启动时 resolve |
| **Derive** | path_router + capability_resolver + snapshot_builder + app_shell_stat | + `decision_extractor.py`;types.py 加 `Decision` dataclass + ID 计算 helper |
| **State** | SnapshotRepo + OverrideRepo | + `DecisionNoteRepo`;db.py SCHEMA 加 `decision_note` 表 |
| **Server** | GET /(?view=d\|b)+ /healthz + /capability/.../edit + POST /override + POST /refresh + /static | + `GET /decisions`;+ `POST /decisions/{id}/note`;+ `DELETE /decisions/{id}/note` |
| **UI** | base/main/_hero/_d_view/_b_view/_d_b_toggle/_app_shell/_capability_chip/_edit_select | + `decisions.html`(主 page);+ `_decision_card.html`;+ `_decision_filter.html`;+ `decisions-filter.js`(~30 LoC);改 `_d_b_toggle.html` → `_view_toggle.html`(加第三 tab + active_view 参数);改 `style.css`(decision-card / filter-chip 等) |

---

## § 11 视图布局

### § 11.1 三 tab nav

```
┌──────────┬──────────┬────────┐
│ D 维度    │ B Kanban │ 决策   │
└──────────┴──────────┴────────┘
```

active tab 下边框 lit-fg color(沿用 M2 `.view-toggle a.active` 样式)。

### § 11.2 /decisions page 布局

```
┌─────────────────────────────────────────────────────┐
│ Hero(沿用 M1)— "今天没在做任何 capability ..."  │  ← 共用
├─────────────────────────────────────────────────────┤
│ [D 维度] [B Kanban] [决策]  ← active                │  ← _view_toggle.html
├─────────────────────────────────────────────────────┤
│ Filter:                                              │  ← _decision_filter.html
│ [01 提示][02 工具][03 编排][04 记忆][05 RAG]        │
│ [06 护栏][07 评测][08 成本][META]                    │
│ [active][deprecated]   关键字: [_______________]    │
├─────────────────────────────────────────────────────┤
│ 2026-05-05 · v0.8.5 · [06 护栏]                      │  ← _decision_card.html
│ Constrained LLM Router(plan_id 4 选 1)             │
│   Why: prompt 漂移与 schema 软约束教训              │
│   refs: 2026-05-05-v0.8.5-constrained-router.md     │
│   note: [_________________________](inline edit)    │
├─────────────────────────────────────────────────────┤
│ ... 更多决策(server render ~47 卡)               │
└─────────────────────────────────────────────────────┘
│ App Shell 第 9 行(沿用 M2)                         │  ← 共用
└─────────────────────────────────────────────────────┘
```

### § 11.3 单决策卡格式(`_decision_card.html`)

```html
<article class="decision-card"
         data-layer="{{ d.layer }}"
         data-state="{{ d.state }}"
         data-text="{{ (d.title + ' ' + d.why)|lower }}">
  <header class="decision-head">
    <span class="decision-date">{{ d.date }}</span>
    <span class="decision-version">{{ d.version }}</span>
    <span class="decision-layer">[{{ d.layer }}]</span>
  </header>
  <h3 class="decision-title">{{ d.title }}</h3>
  <p class="decision-why"><strong>Why:</strong> {{ d.why }}</p>
  <p class="decision-refs">
    refs:
    {% for ref in d.refs %}<code>{{ ref }}</code>{% endfor %}
  </p>
  <form class="decision-note"
        hx-post="/decisions/{{ d.id }}/note"
        hx-target="this"
        hx-swap="outerHTML">
    <input name="note" value="{{ note_lookup.get(d.id, '') }}" placeholder="(用户备注)">
    <button type="submit">保存</button>
  </form>
</article>
```

### § 11.4 filter UI(`_decision_filter.html`)

```html
<section class="decision-filter">
  <div class="filter-group">
    {% for dim in main_dims %}
      <button class="filter-chip filter-layer" data-value="{{ dim.id }}">
        {{ dim.number }} {{ dim.name_cn }}
      </button>
    {% endfor %}
    <button class="filter-chip filter-layer" data-value="META">META</button>
  </div>
  <div class="filter-group">
    <button class="filter-chip filter-state" data-value="active">active</button>
    <button class="filter-chip filter-state" data-value="deprecated">deprecated</button>
  </div>
  <div class="filter-group">
    <input class="filter-keyword" type="text" placeholder="关键字搜索...">
  </div>
</section>
```

`decisions-filter.js`(~30 LoC):click chip → toggle `.active` class → scan all `.decision-card`,根据 active layer chip values + active state chip values + keyword 同时 match → 显示;否则 `display: none`。

---

## § 12 工程组成

### § 12.1 新增文件

```
dashboard/
├── derive/
│   ├── decision_extractor.py        # 新(~80 LoC)
│   └── types.py                     # 改:加 Decision dataclass
├── state/
│   ├── repositories.py              # 改:加 DecisionNoteRepo
│   └── db.py                        # 改:SCHEMA 加 decision_note 表
├── templates/
│   ├── decisions.html               # 新:主 page
│   ├── _decision_card.html          # 新
│   ├── _decision_filter.html        # 新
│   ├── _view_toggle.html            # 改名自 _d_b_toggle.html + 加第三 tab
│   ├── main.html                    # 改:_d_b_toggle 改 _view_toggle
│   └── base.html                    # 不动
├── static/
│   ├── decisions-filter.js          # 新(~30 LoC)
│   └── style.css                    # 改:加 .decision-card / .filter-chip / .filter-keyword 等
├── server.py                        # 改:加 3 routes + memory_path resolve
└── tests/
    ├── derive/
    │   └── test_decision_extractor.py   # 新
    ├── state/
    │   └── test_decision_note_repo.py   # 新
    └── server/
        ├── conftest.py                  # 新:autouse fixture monkeypatch DB_PATH 到 tmp_path(只 server/ scope)
        └── test_decisions_endpoint.py   # 新
```

### § 12.2 不新增依赖

M3 复用 M2 的 jinja2 + sqlite3(stdlib)+ htmx vendored,无 npm,无新 pyproject 依赖。`hashlib`(stdlib)用于 sha256 ID。`os.environ` + `pathlib.Path`(stdlib)用于 memory_path resolve。

---

## § 13 API 列表

| Method | Path | 作用 | 返回 |
|---|---|---|---|
| GET | `/` | D/B 主视图(M1+M2) | HTML |
| GET | `/healthz` | 健康检查 | JSON |
| GET | `/capability/{id}/edit` | edit dropdown(M2) | HTML 片段 |
| POST | `/capability/{id}/override` | upsert override(M2) | HTML 片段 |
| POST | `/refresh` | invalidate snapshot(M2) | 302 |
| **GET** | **`/decisions`** | **决策列表 page**(全部 ~47 卡 + filter UI) | **HTML** |
| **POST** | **`/decisions/{decision_id}/note`** | **upsert note(form `note`)** | **HTML 片段(新 form)** |
| **DELETE** | **`/decisions/{decision_id}/note`** | **clear note** | **HTML 片段(空 form)** |
| GET | `/static/*` | 静态资源 | css / js |

---

## § 14 测试增量

### § 14.1 新增 ~12 项

```
dashboard/tests/
├── conftest.py                            # 新:autouse fixture
├── derive/test_decision_extractor.py      # 5 项
│   ├── test_extract_from_specs_basic
│   ├── test_extract_from_memory_frontmatter
│   ├── test_layer_keyword_classification
│   ├── test_decision_id_stable
│   └── test_extract_all_merges_and_sorts
├── state/test_decision_note_repo.py       # 4 项
│   ├── test_empty_returns_empty_dict
│   ├── test_upsert_then_get
│   ├── test_delete_clears
│   └── test_multi_decision_isolation
└── server/test_decisions_endpoint.py      # 4 项
    ├── test_get_decisions_renders_cards
    ├── test_get_decisions_active_tab
    ├── test_post_decision_note
    └── test_delete_decision_note
```

加上 `conftest.py` autouse fixture 改造,M2 server tests inline cleanup 全部撤销(简化 ~5 处)。

### § 14.2 conftest.py fixture(M3 follow-up b)

```python
import pytest
from pathlib import Path

@pytest.fixture(autouse=True)
def isolated_dashboard_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """每个 server test 用独立 sqlite,不污染 backend/data/board.db。"""
    monkeypatch.setattr("dashboard.server.DB_PATH", tmp_path / "board.db")
```

**位置**:放 `dashboard/tests/server/conftest.py`(只 server/ scope 生效),不放 `dashboard/tests/conftest.py`(否则 derive/state tests 也会触发,无害但范围过大)。

### § 14.3 M1 test mypy 清债(M3 follow-up c)

修以下 8 处 strict 报错:
- `tests/derive/test_path_router.py`:`fixture` 缺 `tuple[list, list]` → `tuple[list[DimensionConfig], list[DimensionConfig]]`
- `tests/derive/test_snapshot_builder.py:10/25/31/36/43`:测试函数加 `-> None`
- 其他类似,全部加 return annotation

---

## § 15 Ship 标准(spec § 9.1 M3 + follow-up)

verify 跑通 7 条:

1. ✅ `make board` 切 D/B/决策 三 tab,active class 正确高亮
2. ✅ `/decisions` page 显示 ~30-50 项决策(memory + spec 合并)+ time-desc 排序
3. ✅ layer chip + state chip 多选 filter 工作(client-side 显隐)
4. ✅ keyword input 实时 filter
5. ✅ 决策卡 note 输入框 + 保存按钮:点击保存 htmx swap → 重 render form 含已存值;关浏览器再开 note 仍在(sqlite 持久化)
6. ✅ Server tests 全 用 `conftest.py` fixture,`backend/data/board.db` 不被测试污染(运行 pytest 后该文件 mtime 不变)
7. ✅ `mypy strict dashboard/`(含 test files)全 PASS;`pytest dashboard/tests/`  ~59 项 PASS

---

## § 16 工期 + 风险

### § 16.1 工期估算

1.3 天 wall time(memory `feedback_estimate_in_claude_code_walltime`)。任务大致:

| 子项 | 估时 |
|---|---|
| decision_note 表 + DecisionNoteRepo + 4 测试 | 1h |
| Decision dataclass + types.py | 0.5h |
| decision_extractor: spec scan + memory scan + 合并 + ID + 5 测试 | 3h |
| memory_path resolve + env override | 0.5h |
| `_view_toggle.html` 改名 + active_view 参数 + main.html 引用 | 0.5h |
| GET /decisions route + decisions.html + _decision_card.html | 1.5h |
| _decision_filter.html + decisions-filter.js + filter CSS | 1.5h |
| POST/DELETE /decisions/{id}/note + 2 测试 | 1h |
| GET /decisions test + active tab 测试 | 0.5h |
| **(b)** conftest.py autouse fixture + M2 inline cleanup 撤销 | 0.5h |
| **(c)** M1 test mypy 清债 | 0.3h |
| 整体 E2E smoke + commit + tag | 0.5h |

合计 ~10.8h ≈ 1.3 天(buffer 0.5h)。

### § 16.2 风险

| 风险 | 概率 | 缓解 |
|---|---|---|
| **memory_path auto-detect 公式错** | 中 | spec § 9.1 实现给了 escape 公式;启动时 print(MEMORY_PATH) log,user 看到错可设 env var 修;test 用 monkeypatch 注入 |
| **layer 关键字归类命中率低于预期** | 中 | M3 ship 时 `python -c "from dashboard.derive.decision_extractor import extract_all; print(每 layer count)"` smoke;< 70% 命中再加 keyword 到 dimensions.yaml |
| **决策稳定 ID hash 碰撞** | 极低 | sha256[:12] 12 字 hex = 48 bit space,~ 47 项决策碰撞概率忽略 |
| **client JS filter 在 ~50 卡时性能** | 极低 | 一次 scan 47 卡 setProperty <5ms,无问题;若 M4 决策超过 200 项再加 debounce |
| **conftest.py fixture 范围过广破坏 M2 测试** | 低 | autouse 仅在 server tests 命名空间生效(`tests/server/conftest.py` 而非 `tests/conftest.py`);M2 server tests 失去 inline cleanup 后必须依赖 fixture,如不工作会立即 fail |
| **decision_note htmx swap 跟 form structure 兼容** | 低 | M2 chip swap 已 spike;form 同模式;test 验证 hx-target=this + hx-swap=outerHTML |

---

## § 17 范围边界 / YAGNI

### § 17.1 在范围内 ✓

- `/decisions` route + decisions.html
- decision_extractor(spec sections + memory frontmatter,layer 关键字归类)
- DecisionNoteRepo + decision_note 表 + 持久化
- filter UI(layer chip 9 + state chip 2 + keyword input + client JS)
- 三 tab nav(D / B / 决策)+ active_view 参数
- memory_path resolve(env var + auto-detect + fallback)
- conftest.py autouse fixture(test infra 升级)
- M1 test files mypy 清债

### § 17.2 不在范围 ✗(显式排除,防滑动)

- ❌ `state: deprecated` 自动 detection(留 M3.x;用户可在 note 字段手填"已废弃")
- ❌ URL filter state 同步(`?layer=04,06`)— 留 M3.x
- ❌ 决策稳定 ID 跨版本变更追踪(M3 ID = sha256 同 input → 同 output;input 变 → 新决策卡)
- ❌ 决策来自 git log / commit message — 留 M4
- ❌ B Kanban `[XX]` dim prefix(M2 polish PR)
- ❌ `LayerSummary.id` cast 收紧(M2 polish PR)
- ❌ memory frontmatter convention 升级(强制加 `layer: ...` 字段)— 留 M3.x 视 layer 命中率决定
- ❌ 决策 link 到 GitHub commit / PR — 留 M4
- ❌ 决策 export(markdown / pdf / csv)— YAGNI

---

## § 18 实施引用

实施时按 [docs/superpowers/plans/](../plans/) 下产出的 M3 plan 跑(下一步 brainstorming → writing-plans skill 会写)。
