# 画图 charting skill + run_python 自动捕获/套主题 harness 设计

- 日期:2026-06-11
- 状态:设计定稿,待实施
- 关联:[代码解释器 run_python](2026-06-11-code-interpreter-tool-design.md) · 知识卡 `docs/claude-context/code-interpreter-run-python-done.md`

## 1. 背景:真浏览器实测抓出的失败

代码解释器 ship 后,**内联数据**画图(「把 [1,2,3] 和 [4,5,6] 画折线」)真浏览器验过能渲染。但**真实场景**是用户只说「查贵州茅台和五粮液的股价画柱状图对比」——数据得 agent 先调工具读到、再画。这条多轮工具链真浏览器实测**失败**:

- ✅ 模型正确查了数据(`compare_stocks` + `get_stock_quote`),也把真值串进了 run_python 代码(`prices=[241.3,197.0]`);
- ❌ `run_python` **连失败 3 次**(`stdout_invalid_json` ×2 + `non_zero_exit`):模型写了挺漂亮的 `make_subplots` 柱状图,但**结尾忘了 `print(json.dumps({result, figures:[fig.to_dict()]}))`**——沉浸在堆图表里把输出契约那步丢了;
- 结局:撞 12 步上限,退回纯文字表格,无图。

**根因**:弱模型(`deepseek-v4-flash`)写复杂图时不可靠地执行"print 契约";契约虽在 code 参数 description 里,但靠模型每次记得太脆。**模型依赖型的正确性是不可靠的**——既然如此,把"输出契约"和"固定风格"从模型身上挪进可信代码。

## 2. 两件东西

| | 角色 | 触发 | 不可靠时 |
|---|---|---|---|
| **harness**(run_python 执行器升级) | 地板/兜底,always-on | 每次 run_python 都生效 | 没 load skill、代码极简也能出一张 iOS 风格的图 |
| **charting skill**(方法论文本) | 天花板,锦上添花 | `load_skill('charting')` | 复杂图不翻车、配色更准、问题有解法 |

设计原则:**harness 保正确性下限,skill 提质量上限**。skill 不引入新工具名额(纯文本),不放 scripts/(画图是模型当场写,非预写脚本)。

## 3. harness:`execute_source` 升级为「自动捕获 + 自动套主题」

### 3.1 新契约(对模型)

模型只管:
- 把图赋给 `fig`(单张)或 `figures`(列表);结论赋给 `result`(可选);
- 数据自动以变量 `data`(dict)注入命名空间,**直接用**(不用 `json.load(sys.stdin)`);
- **不用 print、不用记 JSON 格式、不返回图片链接/markdown 图**。

### 3.2 执行流程

`execute_source(source, payload)`:
1. `scan_script_safety(source)` —— 扫**用户码**(`open`/`subprocess`/`os.popen`… 仍禁,不变);
2. 写用户码到 `workdir/user_code.py`;
3. 写**可信 wrapper** 到 `workdir/interp.py`(wrapper 不被扫描,可用 `exec`/`open`);
4. 跑 `interp.py`,stdin 仍喂 payload(向后兼容旧式读 stdin 的代码)。

wrapper 干的事(伪码):
```python
import sys, io, json, plotly.io as pio, plotly.graph_objects as go
pio.templates["ios"] = go.layout.Template(layout=<§4 iOS 主题>)
pio.templates.default = "ios"           # 用户建的图自动带主题

_ns = {"data": <payload>}               # data 注入命名空间
_buf, _real = io.StringIO(), sys.stdout
sys.stdout = _buf                        # 吞掉用户调试 print,不污染 stdout
try:
    exec(compile(open("user_code.py").read(), "user_code.py", "exec"), _ns)
finally:
    sys.stdout = _real

def _figd(f): return f if isinstance(f, dict) else f.to_dict()
figs = _ns.get("figures")
if figs is None and "fig" in _ns: figs = [_ns["fig"]]
result = _ns.get("result")
# 三重兜底:命名空间没图 → 回退解析被吞 stdout 里旧式 print(json.dumps(...))
if not figs:
    parsed = _last_json_with_figures(_buf.getvalue())
    if parsed: figs, result = parsed.get("figures"), result or parsed.get("result")
print(json.dumps({"result": result, "figures": [_figd(f) for f in (figs or [])],
                  "stdout": _buf.getvalue()[:500]}, default=str))
```

### 3.3 三重兜底(覆盖各种写法)
1. 命名空间有 `figures`/`fig` → 用它(新契约,主路径);
2. 没有 → 解析被吞 stdout 里**最后一个含 `figures` 的合法 JSON**(旧式 `print(json.dumps(...))` 代码仍可用);
3. 都没有 → 空 figures(诚实,LLM 看到 `charts_rendered:0` 可自纠)。

### 3.4 安全不变
- 用户码仍过 AST 扫描(harness 不放松任何禁项);wrapper 是我生成的可信代码,它用 `exec`/`open` 不经扫描——只扫用户码,用户码里这些仍禁。
- `_SANDBOX_THREAD_ENV`(OpenBLAS 单线程)、rlimit、断网、workdir 一律不变。

## 4. iOS plotly 主题(固定风格,harness 自动套)

注册成 `pio.templates['ios']` 并设默认,每张图继承。`fig.to_dict()` 会把主题**内联进 layout.template**,前端 plotly 直接渲染(前端不需知道 'ios' 这个名)。

| 维度 | 值 |
|---|---|
| colorway(序列轮色) | `#5E5CE6` 靛(主) · `#00C7BE` 薄荷 · `#FF9500` 橙 · `#AF52DE` 紫 · `#34C759` 绿 · `#FF2D55` 粉红 |
| 背景 | `paper_bgcolor`/`plot_bgcolor` 均 `#FFFFFF` |
| 网格/轴线 | grid `#F0F0F2` · zeroline `#E5E5EA` · axis line `#D1D1D6` |
| 字体 | `-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", system-ui, sans-serif` · 色 `#1D1D1F` · 13px |
| 标题/图例 | 标题左对齐;图例横排、置底;hover 圆角白卡 |
| 边距 | `l56 r24 t48 b48` |
| 顺序色阶 | `#E8E8FB → #5E5CE6` |

**红涨绿跌**(`#FF3B30`/`#34C759`):数据语义、按图而定,harness 套不了 → 由 charting skill 教模型在涨跌场景显式用。中文字体浏览器渲染,无 matplotlib 乱码坑。

## 5. charting skill(`backend/claude_skills/charting/SKILL.md`)

纯文本,新目录自动进 L1 清单(SkillLoader 扫描发现,无需手工注册)。

- **frontmatter**:`name: charting`;`description` 含触发判据(用户要图/趋势/对比/分布/占比/画一下 时 load_skill('charting'));
- **写法契约**:赋 `fig`/`figures`/`result`;数据在 `data` 变量;别 print、别返回图片链接;
- **固定风格速查**:§4 色板 + 何时用哪个色 + 红涨绿跌规矩;
- **问题解法目录**(用户明确要的"遇到各种问题怎么解"):多系列对比 / 时间序列 / 占比饼图 / 相关性热力 / 分布直方 / 双轴 / 子图——各一段最小可改范式;另:CJK 不乱码、大数据下采样、空数据兜底、数值格式化(¥/%/万亿)、横标签防重叠 各一条坑;
- **图类型范式**:line/bar/pie/scatter/box/heatmap/candlestick 各一小段样板。

## 6. 测试 + 收尾

- **L0**(harness wrapper,Fake 不起真子进程的纯逻辑 + 真子进程 e2e):赋 `figures` → 序列化;赋 `fig` → 单图;忘赋但旧式 `print(json.dumps)` → 兜底解析出图;用户 `print` 调试 → 不污染 stdout;每图带 ios 模板(layout.template 非空);`data` 注入命名空间可用;空 → figures=[]。
- **既有 run_python 测试**:契约变了,改成赋 fig/figures 而非 print;e2e 跑真 plotly。
- **charting skill**:文档完整性 + 触发 eval(≥3 该 load 的 query)。
- **真浏览器重验**(收尾闸):重跑「查贵州茅台和五粮液股价画柱状图对比」这条多轮工具 case,看到一张 **iOS 主题的柱状图真渲染出来**才算过。

## 7. 范围外
- 红涨绿跌的 harness 强制(数据语义,留给 skill);K 线/复杂金融图模板化(skill 给范式即可);深度研报 pipeline 复用本主题(留 follow-up);图跨 reload 持久化(沿用既有 follow-up)。
