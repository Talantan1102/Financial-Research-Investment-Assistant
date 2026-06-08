# Smoke Results — qwen/DashScope 原生 function calling 能力实测

**日期:** 2026-06-05  
**模型:** deepseek-v4-flash  
**脚本:** `backend/scripts/smoke_native_tools.py`  
**阶段:** Phase 0 — 门控 Phase 1 `LLMService.stream_step` 实现

---

## 结果表

| item | result | detail |
|---|---|---|
| 1 native tool_calls | PASS | finish_reason=tool_calls, calls=['get_stock_quote', 'get_news'] |
| 2 stream delta 拼接 | PASS | finish=tool_calls, assembled={0: ('get_stock_quote', {'ts_code': '600519.SH'})} |
| 3 parallel calls | PASS | n_calls=2: ['get_stock_quote', 'get_news'] |
| 4 thinking 形态 | PASS | reasoning_content=present(absent=不做 reasoning 折叠区,非失败) |
| 5 stream usage | PASS | prompt=358 |
| 6 隐式缓存命中 | PASS | cached_tokens=1280(0/None=隐式缓存未命中,记录但非阻塞) |
| 7 tool_choice=none | PASS | finish=stop, content_len=126 |
| 8 瘦 schema 行为 | PASS | calls=['get_stock_quote', 'get_stock_quote', 'get_news', 'get_news'](观察模型对瘦 schema 工具的调用行为) |

---

## 裁决

### 全部 PASS — 无阻塞项

所有 8 项均 PASS，Phase 1 `LLMService.stream_step` 实现可正常推进。以下是各项的决策映射：

| item | 裁决 |
|---|---|
| 1 native tool_calls | PASS — 主路径可用。`finish_reason=tool_calls` + `message.tool_calls` 均正确返回，stream_step 可直接依赖此路径。|
| 2 stream delta 拼接 | PASS — 主路径可用。流式 delta 拼接逻辑（按 index 累积 arguments）验证正确，stream_step 可按此模式实现。|
| 3 parallel calls | PASS — 主路径可用。单轮多工具并行调用（n_calls=2）正常，stream_step 无需额外处理。|
| 4 thinking 形态 | PASS，`reasoning_content=present`。模型支持 thinking 输出。当前 Phase 1 不做 reasoning 折叠区 UI，`reasoning_content` 字段静默忽略即可；后续如需折叠区可接回。|
| 5 stream usage | PASS — 主路径可用。`stream_options={"include_usage": True}` 在末尾 chunk 正确返回 usage，token 计数/成本记录可用。|
| 6 隐式缓存命中 | PASS，`cached_tokens=1280`。隐式缓存在本次测试中命中。缓存命中率指标继续记录，口径以 `prompt_tokens_details.cached_tokens` 为准，注意该字段非所有模型版本均保证存在（None 视为未命中，非错误）。|
| 7 tool_choice=none | PASS — 主路径可用。收尾圈（非工具轮）传 `tool_choice="none"` 可正确阻止工具调用，stream_step 在纯文本生成轮可安全使用此参数。|
| 8 瘦 schema 行为 | PASS（观察性）。模型面对瘦 schema 工具（`compare_stocks`，无参数声明）时，未调用该工具，而是重复调用了 `get_stock_quote` 和 `get_news` 各两次（共 4 次调用）。结论：**模型会回避参数信息不足的工具**，`compare_stocks` 类工具若无完整 schema 将被绕过。Phase 1 中所有注册工具须提供完整参数声明。|
