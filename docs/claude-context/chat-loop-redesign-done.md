---
title: Chat Loop 重设计总卡
type: project
date: 2026-06-05
---

# Chat Loop 重设计:裸 while 工具调用循环(2026-06-05 ship)

**结论**:chat 模式 agent 从 LangGraph supervisor 六节点单程图重设计为裸 Python while 工具调用循环,新包 `backend/app/chatloop/`(loop / state / context / gates / tool_hub / events 六文件)2026-06-05 设计定稿。核心决策:单 LLM(planner/responder 合并)+ 原生 function calling + 四道终止闸(自然停/硬迭代上限/预算/回合边界)+ 打转检测(签名集指纹)+ 烧签名(同签名失败三次封堵)；窗口四区(稳定前缀吃 KV-cache / 历史区 / 本 turn 轨迹区 / 尾部动态区)；工具渐进披露(核心 6 完整 schema + 延迟 8 瘦条目 + search_tools 按需文档)；记忆六件套合并为 memory_search / memory_write 双工具,注入分类器收口唯一写入入口；技能图回环退役，变为 load_skill 工具 + 循环天然承载(活跃技能方法论不降级)；升级信号工具 offer_deep_research + 熔断收尾(tool_choice="none" 代码强制)；steering 插话走 Redis List 而非 pub/sub(turn 内 LPUSH/RPOP,不可丢)；turn 原子语义(取消 = partial 仅展示非恢复点 / 重试 = 整 turn 从头重跑 / checkpoint 彻底退役)。

## Why

**七个设计缺口驱动重设**:现状单程图"planner → 路由 → 工具批执行 → responder"在七处无法对齐工业事实标准——① 够不着"查了 A 才知道要查 B"的依赖型多跳;② 无预算闸(按 token/金额封顶的硬停);③ 上下文管理只有超阈值压缩,无检索式选择;④ 模型推理过程无真实流式(direct_response 路径靠补发 hack 假装流式);⑤ 打断只有取消整轮,无"插话并入改方向"(steering);⑥ 无审批门 hook;⑦ 工具报错只能 responder 道歉,无自纠回路。

**三轮 20 路对抗核查调研裁决**:上下文工程 8 路 / 周边接线 7 路 / 技能接线 5 路专项调研,结论沉淀为看板三份研报《Chat 模式 Agent Loop·怎么做》《Agent Loop 上下文工程·怎么做》《Agent Loop 周边接线·怎么做》,设计每处偏离工业主流均有可溯源的 trade-off 标注。

**用户骨架选型 = 裸 while**:三方案对比(裸 while / LangGraph 双节点回环 / 事件溯源 reducer)× 三镜头(可行性 / 研报对齐 / 作品价值),用户选定裸 while 纯正派——控制流百分之百自有。LangGraph 退出 chat 路径的核心依据是 turn 原子语义("中间圈检查点无消费者"):重试 = 整 turn 重跑 → 每圈 checkpoint 失去用处,反过来坐实裸 while 合理性;生产 worker 路径本来就是 `checkpointer=None`(半接通状态)。

**窗口四区铁律**:三路调研全票指出"动态状态不进前缀"——每圈变一字 = 从那字起缓存全废。预算/步数等状态进尾部动态区(每圈只 miss 最小一段,同时是召回最强位)。稳定前缀吃 DashScope 隐式 KV-cache 折扣(实测续片约两折)。

**记忆路由节点退役的理由**:router 节点的"智能"全部活在 kb_search / memory_search 这对互斥 description 里("公开市场信息" vs "用户个人的持仓/偏好/历史说过的话");description 是一等设计物,路由节点变成冗余控制流。

**steering 用 Redis List 不用 pub/sub**:worker 在流式输出的几秒里不在监听,pub/sub 会丢;插话不可丢,cancel 可丢(用户会再按)——两路信号不同可靠性要求,分用两种原语。

## How to apply

**改 chat 行为找 `backend/app/chatloop/`**:loop.py = 编排壳(唯一有副作用);gates.py / context.py / state.py = 纯函数核,L0 直测不需任何 runtime,闸判定/窗口组装/状态折叠全可独立验证。

**新工具 / 新数据源**:走 MCP + tool_docs 瘦条目进延迟组,不扩核心组;增长纪律——数据源配工具名额,方法论进技能(约 100 token 元数据),计算进技能脚本(零名额)。

**技能集在 `backend/claude_skills/`**(7 个):load_skill 工具触发后 SKILL.md 全文进窗口;活跃技能方法论常驻不降级;切换技能后旧方法论才降,降级时硬规则条款保留原文 + 加"历史方法论勿重新执行"标记。

**评测目标**:工具选择专项(该调时调/不该调时弃权双指标 + memory/kb 分桶混淆)+ 技能触发离线 eval(每技能 ≥3 条金标准 query + 近似负例,`--live` 参数烧真 LLM)+ chatloop cassette 三条主路径重录(SUTOutput 的 tool_calls 从台账抽,非旧 plan)。

**实施分期骨架**:0 冒烟测试 8 项(任何循环代码动工前的闸,8 项含 qwen 原生 function calling 确认 / 流式 usage / tool_choice="none" / 缓存命中 cached_tokens 回包)→ 1 stream_step 扩展 → 2 chatloop 核心 L0 全绿 → 3 ToolHub(MCP + in-process + 渐进披露)→ 4 传输替换(切换点)→ 5 前端适配 → 6 评测收束 → 7 退役清理(删 chat_graph.py / nodes.py 三节点 / planner/responder chat 路径 / LangGraph checkpoint 接线)。

**已知留口**:

| 留口 | 触发条件 | 当前处置 |
|---|---|---|
| reasoning 折叠区 | qwen thinking 模式下工具轮 reasoning 回传约束待验 | 冒烟测试项 ④ 前置 |
| 脚本大输出写缓存 | run_skill_script 大输出强制走 ToolResultCache | 设计已定,实施期落 |
| 技能两层化逃生口 | 技能数量 ≥15 或工具选错率抬头 | 配置写死,按需开关 |
| episode_id_resolver | archival_insert 的 episode_id 暂指导错误 | 遗留自 C.5,chat loop 重设计不引入新依赖 |
| 打转语义环 | 精确指纹漏语义等价调用 | 上限闸 + 预算闸兜底,诚实标注 |

**关键教训**:cassette 真录抓出 StreamAssembler 空串覆盖 bug(qwen 续片 `name=""` 非 null,现有拼接逻辑用非空判断覆盖了有效 name)——mock 测试无法复现协议细节,真 API cassette 录制是不可替代的回归面。"spec 谈某接口行为必须先录 cassette 核实,不能只看文档"。

相关:[[v0.9-chat-c1c2-architecture]] [[c5-cross-session-memory-done]] [[conv-agent-evaluation-methods]]
