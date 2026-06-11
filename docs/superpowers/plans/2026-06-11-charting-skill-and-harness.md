# charting skill + run_python harness 实施计划

> 配套 spec:`docs/superpowers/specs/2026-06-11-charting-skill-and-harness-design.md`。本计划由 orchestrator 直接实现(env 含 WSL+真浏览器,subagent 跑不顺),每步带测试,最后真浏览器重验。

**Goal:** run_python 执行器自动捕获 `fig/figures/result` + 自动套 iOS plotly 主题(模型不用记 print 契约),并加一个 charting 方法论技能;修掉多轮「查数据→画图」失败。

**Tech Stack:** Python(execute_source wrapper / plotly template)、pytest、SKILL.md 文本。

---

## 文件结构

**新建:**
- `backend/app/skills/plotly_theme.py` — iOS plotly Template(纯数据,被 wrapper 注入)
- `backend/claude_skills/charting/SKILL.md` — 画图方法论技能
- `backend/tests/unit/skills/test_execute_source_harness.py` — harness 捕获/兜底/套主题 L0

**修改:**
- `backend/app/skills/skill_executor.py` — `execute_source` 升级为 wrapper 模式(自动捕获+套主题+data 注入+三重兜底)
- `backend/app/chatloop/code_interpreter_tool.py` — `code`/`data` 参数 description 改成新契约(赋 fig/figures/result,别 print)
- `backend/app/chatloop/tool_docs.py` — run_python `doc` 正文同步新契约 + 指向 charting skill
- `backend/tests/unit/skills/test_execute_source.py` — 既有用例改成新契约
- `backend/tests/integration/test_code_interpreter_e2e.py` — e2e 改新契约 + 验主题
- `backend/tests/unit/chatloop/test_code_interpreter_tool.py` — 出参不变(仍 {result,figures,...}),确认兼容

---

## Task 1: iOS plotly 主题常量

**Files:** Create `backend/app/skills/plotly_theme.py`

- [ ] 写一个返回 plotly Template **纯 dict**(不 import plotly,避免 executor 进程强依赖;wrapper 在子进程里 import plotly 时用这个 dict 构造 Template):
```python
"""iOS Calm plotly 主题 —— code interpreter 固定画图风格(spec § 4)。
纯 dict,不在此 import plotly;子进程 wrapper 用它构造 go.layout.Template。"""
from __future__ import annotations

IOS_FONT = (
    "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', system-ui, sans-serif"
)
IOS_COLORWAY = ["#5E5CE6", "#00C7BE", "#FF9500", "#AF52DE", "#34C759", "#FF2D55"]

def ios_template_layout() -> dict:
    axis = dict(gridcolor="#F0F0F2", zerolinecolor="#E5E5EA", linecolor="#D1D1D6",
                tickfont=dict(color="#1D1D1F", size=12), title=dict(font=dict(color="#1D1D1F")))
    return dict(
        colorway=IOS_COLORWAY,
        font=dict(family=IOS_FONT, color="#1D1D1F", size=13),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        xaxis=axis, yaxis=axis,
        title=dict(x=0.0, xanchor="left", font=dict(size=17, color="#1D1D1F")),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=56, r=24, t=48, b=48),
        colorscale=dict(sequential=[[0, "#E8E8FB"], [1, "#5E5CE6"]]),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#E5E5EA",
                        font=dict(family=IOS_FONT, color="#1D1D1F")),
    )
```
- [ ] 提交。

## Task 2: execute_source → wrapper 模式

**Files:** Modify `skill_executor.py`; Test `test_execute_source_harness.py`

- [ ] 先写失败测试(真子进程,需 plotly):
  - `data` 注入:`code="result = data['x'] + data['y']"`,payload `{x:1,y:2}` → `stdout_json["result"]==3`
  - 赋 `fig`:`code` 建一个 `fig=go.Figure(...)` → `stdout_json["figures"]` 长度 1 且含 `data`/`layout`
  - 赋 `figures` 列表 → 长度匹配
  - 旧式 `print(json.dumps({"figures":[fig.to_dict()]}))` 不赋变量 → 兜底解析出 1 图
  - 用户 `print("debug")` → 不破坏(stdout_json 仍合法,debug 不在顶层)
  - 主题:某图 `figures[0]["layout"]["template"]` 非空(套了 ios)
  - 安全不变:`code="open('/etc/passwd')"` → `safety_scan_rejected`
- [ ] 跑挂。
- [ ] 改 `execute_source`:scan 用户码 → 写 `user_code.py` → 写 wrapper `interp.py`(见 spec § 3.2,wrapper 字符串里 `pio.templates.default='ios'` 用 Task 1 的 dict;捕获 stdout;命名空间抓 fig/figures/result;三重兜底;`json.dumps(default=str)`)。注意:wrapper 通过 `exec(compile(open('user_code.py').read(),...))` 跑用户码,`data` 经 `_ns={"data": payload}` 注入(不再只靠 stdin;stdin 仍喂兼容旧码)。
- [ ] 跑过 + 既有 `tests/unit/skills` 回归。
- [ ] 提交。

## Task 3: 契约文案同步(tool + tool_docs)

**Files:** Modify `code_interpreter_tool.py`、`tool_docs.py`;Test `test_code_interpreter_tool.py`

- [ ] `CodeInterpreterArgs.code` 的 Field description 改成新契约:
  > 完整 Python 脚本。数据在变量 `data`(dict)里,直接用。把图赋给 `fig`(单张)或 `figures`(列表的 plotly Figure),结论赋给 `result`。**不要 print、不要返回图片链接**——执行器自动序列化并套统一主题。例:`import plotly.graph_objects as go; fig=go.Figure(); fig.add_bar(x=data['names'], y=data['vals'])`。硬约束:用 plotly;无网络/无文件;复杂图先 load_skill('charting')。
- [ ] `tool_docs.py` 的 run_python `doc` 正文同步(参数/示例改新契约;末尾加"画复杂图/要统一风格 → 先 load_skill('charting')")。brief 不变(≤80)。
- [ ] 既有 `test_code_interpreter_tool.py` 仍绿(出参 {result,figures,stderr,elapsed_s} 不变;Fake backend 返回的 stdout_json 结构不变)。
- [ ] 提交。

## Task 4: 既有 e2e/execute_source 用例迁新契约

**Files:** Modify `test_execute_source.py`、`test_code_interpreter_e2e.py`

- [ ] `test_execute_source.py`:原 `print(json.dumps({...}))` 用例保留一条验**兜底**;新增/改写主路径为赋变量 `result=`。断言 stdout_json 形状不变(`{result,figures,...}`)。
- [ ] e2e:plotly 用例改成 `fig=px.line(...)`(不 print),断言 `out["figures"]` 长度 1 + `figures[0]["layout"]["template"]` 套了 ios;断网用例不变。
- [ ] 跑过(真子进程 + plotly)。
- [ ] 提交。

## Task 5: charting skill

**Files:** Create `backend/claude_skills/charting/SKILL.md`

- [ ] 按 spec § 5 写:frontmatter(name/description 触发判据/version)+ 写法契约 + iOS 风格速查(色板+红涨绿跌)+ 问题解法目录(多系列/时序/饼/热力/直方/双轴/子图 各最小范式 + CJK/下采样/空数据/数值格式化/标签防重叠 各一条)+ 图类型样板。
- [ ] 验证自动进 L1:`SkillLoader(skills_root=CHAT_SKILLS_ROOT).load_l1()` 含 charting;`load_skill('charting')` 返回全文。加一条 L0 断言(`test_charting_skill_listed`)。
- [ ] 提交。

## Task 6: 真浏览器重验(收尾闸)

- [ ] 重启 worker(它被 SIGTERM 了);确认 backend/frontend/PG/Redis 在。
- [ ] 浏览器新对话发「查一下贵州茅台和五粮液的最新股价,画个柱状图对比」。
- [ ] DOM 验:`svg.main-svg` > 0、`scatterTraces`/bar trace > 0、图带 iOS 配色;截图存证。
- [ ] 若仍失败 → 看 Redis 流 run_python 的 code/error,迭代。

## Task 7: git 收尾

- [ ] 当前工作区在用户的 `design/chat-subagent-dispatch` 分支 → 本次提交落此处后,worktree cherry-pick 到 `feat/code-interpreter-run-python` + push 更新 PR #143(不动用户分支/工作树);design 上的重复提交连同之前两笔一起,留给用户确认清理。

---

## 自审清单
- [ ] `cd backend && pytest tests/unit/skills tests/unit/chatloop tests/integration/test_code_interpreter_e2e.py -q` 全绿
- [ ] ruff(改动文件)+ 浏览器重验出图(iOS 主题)
