# 实施计划:verl RL 工具界面对齐 MCP(A + stub)

> 2026-06-27。目标:让 RL rollout(verl,Path B)看到的工具界面 == SFT 采轨/生产(Path A,MCP chat_tools),
> 消除 train/serve skew。方案 A(进程内调同一份 MCP 工具定义)+ stub(重依赖辅助工具占位)。
> 依据:`docs/research/2026-06-27-cross-family-distill-and-tool-alignment.md`。

## 决策回顾(已定)

- **A 方案**:verl tool_server 不经 MCP 子进程,而是**进程内复用同一份 MCP 工具定义**(`_load_tool_registry("chat_tools")` 的 TOOL_DEF + handle),单一源不漂。
- **stub**:reward 必需的数据工具走真实 handle;重依赖辅助工具(memory_search/kb_search/web_search/get_news/get_portfolio_positions,需 Milvus/PG/Bocha)**保留 TOOL_DEF 但 handle 换 stub**(返"训练环境不可用"占位)——界面对齐、依赖可控。
- **②(SFT 数据重渲染)已验证无需额外工作**:qwen3 `apply_chat_template` 原生把 reasoning_content→`<think>`、OpenAI tool_calls→Hermes `<tool_call>`。

## 任务(按依赖)

### T1 — as_of 改 per-call(并发安全)【必做,最关键】
**问题**:`_as_of.eval_as_of()` 只读 `CHAT_TOOLS_AS_OF` env;verl tool_server 单进程并发处理多题,用全局 env 注入会串题。
**改**:`app/mcp_server/_as_of.py` 加 `contextvars.ContextVar`:
```python
import contextvars
_ASOF_VAR: contextvars.ContextVar[str | None] = contextvars.ContextVar("eval_as_of", default=None)
def eval_as_of() -> str | None:
    v = _ASOF_VAR.get()
    if v: return v
    e = os.getenv(ENV, "").strip()
    return e or None
def set_eval_as_of(as_of: str | None): _ASOF_VAR.set(as_of)
```
**向后兼容**:生产/SFT 采轨仍走 env(contextvar 默认 None → fallback env)→ 行为不变。verl 走 contextvar。
**验证**:并发两协程各 set 不同 as_of,各自 eval_as_of() 互不串(contextvar 是 task-local)。

### T2 — verl tool_server 改用 MCP registry(in-process)
**改** `eval/question_gen/verl_bridge/tool_server.py`(+ 可能新 `mcp_tool_box.py`):
- 用 `from app.mcp_server.server import _load_tool_registry; reg = _load_tool_registry("chat_tools")` 拿 `{name: module}`。
- `GET /tools` → `[mod.TOOL_DEF ... ]`(转 verl schema 格式,同现 schemas() 的 schema_for_llm 形状)。
- `POST /sessions/{sid}/exec`:
  1. `set_eval_as_of(req.as_of)`(T1)
  2. `result = await reg[req.tool].handle(req.args)` —— 但 stub 工具走 stub(T3)
  3. 适配 `list[TextContent]` → dict(抽 `json.loads(textcontent.text)`,现 ToolBox 返 dict,verl 侧已有解析)。
- run_python 仍走 CodeInterpreterTool(沙箱),不在 MCP registry 里 → 单独注册(现 ToolBox 已有,保留这一件)。
**注**:保留现有 HTTP 端点契约(/tools /sessions /exec),verl 侧 http_tool_proxy 不用改。

### T3 — stub 重依赖工具
- 列出 chat_tools profile 里需 Milvus/PG/Bocha 的:`memory_search` `kb_search` `web_search` `get_news` `get_portfolio_positions`(+ 复核 `read_cached_result`/`load_skill`/`run_skill_script`/`memory_write` 等非数据工具)。
- 对这些:**保留 TOOL_DEF**(界面在),`handle` 换 stub → 返 `{"note":"该工具在 RL 训练环境为占位,无结果"}`(或空 items)。
- 实现:tool_server 建一个 `STUB_TOOLS = {...}`,exec 时若 name 在 STUB 走 stub,否则走真 handle。
**取舍记录**:这几个非 reward 必需;stub 保界面、避重依赖。模型 SFT 见过它们,RL 仍可调到(返空),不报错即可。

### T4 — trace/DB 解耦核查
- 核查数据工具 handle() 是否硬依赖 PG(TraceService 等)。预期:工具层只用 tushare,trace 在 chatloop 层(不在 handle)→ 应无需 PG。若某 handle 触 PG,stub 或惰性化。
- 起 tool_server 时**不连 PG/Milvus**(只 tushare + 沙箱),确认数据工具全绿。

### T5 — 验证(逐闸)
1. **schema 对齐**:`GET /tools` 返回的工具名集 == SFT 采轨用过的(get_financial_statements/get_market_indicators/get_daily/search_tools/trade_cal/get_stock_quote/run_python + stub 们)。
2. **as_of 并发隔离**:并发 exec 两题不同 as_of,各自财报/快照返回对应期(无串题)。
3. **逐工具 exec**:对 reward 必需工具各跑一发(真 tushare),返真实数据 + as_of 钉对(类似已做的 ToolBox 验证表,但走 MCP registry)。
4. **端到端 smoke**:verl 2-step rollout,日志出现 `get_financial_statements`/`search_tools`,reward 非零(对比 D3 旧 smoke)。

## 风险
- **R1**:contextvar 跨 async 边界传播——确保 `set_eval_as_of` 与 `handle` 在同一 task(FastAPI handler 内顺序 await,OK)。
- **R2**:`_load_tool_registry` 导入 chat_tools 全部模块时,某些模块 import 即拉重依赖(Milvus client 等)→ 可能 import 期就炸。缓解:stub 模块改成"不 import 重依赖的轻量 TOOL_DEF 源",或 import 失败兜底只取 TOOL_DEF。**起手先实测 `_load_tool_registry("chat_tools")` 在纯 tushare env 能否 import 通**(冒烟第一步)。
- **R3**:search_tools 依赖完整工具注册表做检索——确认它在 registry 内、检索目标是同一份 registry。
- **R4**:verl env vs backend deps——tool_server 跑在 fria env(有 backend deps),verl 经 HTTP 调,**不在 verl env 里装 backend**(沿用 D3 隔离)。

## 不做(out of scope)
- 真上 memory/kb/web(全量)——本计划 stub。
- SFT 数据重渲染脚本——②已由 qwen3 模板原生解决。
- RFT 同家重采——用户已砍。

## 起手第一步
**先冒烟 R2**:在 fria env 跑 `_load_tool_registry("chat_tools")`,看哪些模块 import 即炸/拉重依赖 → 决定 T3 stub 的 import 处理方式。这一步定了,T1/T2/T3 才好写。

---

## 2026-06-27 R2 冒烟结果(已跑)

✅ **`_load_tool_registry("chat_tools")` 在纯 fria env 干净加载,13 工具无 import 崩溃**:
`get_stock_quote / get_financial_statements / get_market_indicators / get_corporate_actions /
get_news / web_search / kb_search / compare_stocks / get_daily / get_index_daily /
get_fund_nav / get_sector_daily / trade_cal`。**重依赖(Milvus/PG/Bocha)惰性**,import 不拉 → R2 大幅缓解,**T3 只需在 handle() 调用层 stub,不必处理 import 期崩溃**。

**计划修正(重要)**:这 13 个是 MCP chat_tools profile,**不含** `search_tools`/`run_python`/`memory_search`/`get_portfolio_positions`——那些由 SFT采轨的 `build_real_hub`(`eval/tool_selection/_live.py`)另加。所以:
- **完整 SFT 工具面 = 13 MCP chat_tools + build_real_hub 的 {run_python, search_tools, memory_search, memory_write, get_portfolio_positions, read_cached_result, load_skill...}**。
- **T2 工具来源修正**:registry = `_load_tool_registry("chat_tools")` ∪ build_real_hub 里的轻量工具(run_python 已在 ToolBox;**search_tools 必接**,它 SFT 用了 1264 次,是渐进披露核心,且是 registry 上的 meta 检索、无重依赖)。
- **T3 stub 目标(handle 层)**:`get_news`/`web_search`(Bocha)、`kb_search`/`memory_search`(Milvus)、`get_portfolio_positions`(PG)、memory_write/load_skill 等非数据工具。
- **真实 handle(reward 必需)**:get_financial_statements / get_market_indicators / get_daily / get_stock_quote / compare_stocks / get_corporate_actions / get_index_daily / get_fund_nav / get_sector_daily / trade_cal / run_python / search_tools。

**下一步**:T1(as_of contextvar,隔离安全)先做 → 再 T2(tool_server 接 registry+build_real_hub 轻量工具)→ T3 stub → T5 验证。
