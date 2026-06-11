# Chat 记忆写入接线设计(2026-06-11)

## 背景

跨会话记忆(C.5)的架构早已 ship(MemGPT 分层 + Zep 双时态图谱杂交:核心块 / 档案 /
图谱三层;Path A 自管写入 + Path B 异步抽取 + 读管线 + 画像注入)。但**写入侧从未接进
live 聊天循环**:

- `HierarchicalMemory.write_episode`(记一轮对话进库,供后续抽取)在 live 路径**零调用**
  (只有 2 个集成测试用),`chat_runner` 轮次收尾不写 episode。
- 异步抽取的 Celery 任务 `app.tasks.memory.extract_session_episodes_async`(内部跑
  `PathBRunner.run_for_session`:扫未抽取 episode → `cross_turn_grouper` 分组 → LLM 抽事实
  → 写 PG edges + Milvus → `mark_extracted`)**已造好,但无任何 live 触发点、也不在 beat 调度**。

后果:Path B 抽取没有原料、从不运行(对话流评估卡片实测「生产 Path B 抽取从未工作」);
`memory_write` 的 `archival_insert` 因无 episode 可挂而恒返「指导错误」(本设计**不**解此项,
见「显式不做」)。核心块 `core_append/core_replace` 不依赖 episode,现已可用。

## 目标与范围

让记忆**从对话自动积累**:每轮对话写成 episode,触发已建好的异步抽取,事实落库后下次
对话可被 `memory_search` / 画像注入召回。

**只做「甲」(后台消化对话成记忆)**,缺口精确是两根线:① 轮末写 episode;② 触发抽取任务。

## 关键决策:per-turn 即时触发(A1)

抽取触发节奏有两条路,本设计选 **A1(per-turn 即时)**,用户在知悉取舍后拍板:

- **A1 选定**:轮末写完 episode 立刻 fire-and-forget 触发 `extract_session_episodes_async`。
  聊完几秒内记忆消化好;接线最简;复用现成任务。
- **取舍(明确记录)**:`cross_turn_grouper` 的设计意图是在**会话边界**把整段会话的相邻轮
  合成「对话块」,抽**跨轮事实**(「我刚买了」→「买什么」→「茅台 500 股」分散 3 轮 →
  合成一条)。per-turn 触发下,慢节奏聊天时每轮只有 1 个未抽取 episode、分组退化为单轮,
  **跨轮事实抓不到**。**缓解**:触发是异步的,连续快聊、worker 滞后时,`run_for_session`
  会把当时所有未抽取 episode 一起 group,自然退化成批量——所以 A1 在「聊得快」时仍能抓到
  部分跨轮事实,只有「慢悠悠一轮一轮」才是纯单轮抽取。
- **未来切换路径(架构不动,只改触发点)**:若以后嫌单轮抽取质量/调用数,把触发从「轮末」
  改到「会话边界」即可——扩现有 `chat_stale_scanner`(每 60s beat)发现「有未抽取 episode 且
  空闲 ≥30min」的会话 → 触发 `extract_session_episodes_async(session_id, "idle_30min")`
  (`idle_30min` 是现成 trigger 档)。本设计不实施这条,仅留作已知演进方向。

**不依赖 #8(AGE)**:`archival_memory_insert` 同时写 AGE + Milvus,AGE 失败被 SAVEPOINT 兜住
(`age_sync` 的毒事务防护,无扩展环境照常)。故抽取出的事实照落 PG + 向量库、检索可用,
仅「图谱遍历」(`memory_search scope='graph'`)降级——与本设计正交。

## 改动点

### 1. 轮末写 episode(`backend/app/tasks/chat_runner.py`)

`run_chat_async` 的 finally 中 `_finalize` 之后,新增一个守卫块,**仅在干净成功轮**执行:

- 条件:`not cancelled_by_user and loop_error is None and final_state is not None
  and user_id 非 None/"anonymous" and emitted_text.strip()`(取消/报错/匿名/空回复轮**不写**)。
- 数据:`user_message`(初始 state)、`agent_response = "".join(emitted_tokens)`(= `_finalize`
  用的 `emitted_text`)、`session_id`、`user_id`。
- `episode_index`:该 session 现有 episode 数(`max(episode_index)+1`,首轮 0;DB 有唯一约束
  `(session_id, episode_index)`)。新增 `HierarchicalMemory.next_episode_index(session_id)`
  helper(一条 `SELECT max+1` 查询)。
- 调 `singletons.memory.write_episode(user_id, session_id, episode_index, user_message,
  agent_response, source_kind="chat_turn")`。
- **fail-soft**:整块包 try/except,失败只 `logger.warning`,**绝不影响已给用户的回复**
  (回复早已 emit + 持久化,本块是纯副作用)。

### 2. 触发抽取(同块,episode 写成功后)

- fire-and-forget:`extract_session_episodes_async.delay(session_id, "post_turn")`(经现有
  `_enqueue_*` 风格的薄封装,便于测试 patch `.delay`)。
- 同样 fail-soft。

### 3. 新增 trigger 档(`backend/app/tasks/memory.py`)

`_VALID_TRIGGER_REASONS` 现为 `{session_closed, idle_30min, new_session_started}`(全会话边界)。
加 `"post_turn"`。`run_for_session` 主流程不变(扫→group→window→extract→insert→mark);
per-turn 触发时通常扫到 1 个新 episode(快聊时自然批量)。

## 数据流

用户聊一轮 → 回复照常秒回(写 episode 在回复+持久化之后,不加聊天延迟)→ 写 episode
(extracted_at=NULL)→ fire-and-forget 入队抽取 → 后台 Celery:`run_for_session` 扫未抽取 →
`group_episodes` → 5-turn 窗口 → LLM 抽事实 →(`skip_gate` 过滤闲聊)→ 写 PG edges + Milvus
(AGE 缺则 SAVEPOINT 跳过)→ `mark_extracted`。下次对话 `memory_search`/画像注入召回。

## 失败 / 幂等 / 防噪

- **fail-soft**:episode 写入/触发失败不破坏聊天轮次(回复与持久化先于本块、已完成)。
- **幂等**:`mark_extracted` 保证重复触发不重抽;并发同 session 任务在单用户顺序聊天下基本
  无重叠(用户等回复才发下一轮),罕见重叠由 `mark_extracted` + `failure_matrix` 收口。
- **防噪**:`skip_gate` 过滤闲聊不进记忆(已有,不改)。

## 测试(WSL fria-venv;不碰真实 LLM / 不进 Path B 内部抽取)

- 干净成功轮后 `write_episode` 被调,断言入参:user_message / agent_response(= emitted_text)/
  session_id / `episode_index` 递增。
- **不写**的分支:cancelled / loop_error / 匿名 user_id / 空回复 —— 各断言 `write_episode` 未被调。
- **fail-soft**:`memory.write_episode` 抛错时,聊天轮次的终止事件/持久化不受影响(断言无异常逃逸)。
- 触发:`extract_session_episodes_async.delay` 被 fire-and-forget 调用且参数为
  `(session_id, "post_turn")`(patch `.delay`)。
- `_VALID_TRIGGER_REASONS` 接受 `"post_turn"`(扩断言);未知档仍 raise。

## 显式不做

- **乙(during-turn `archival_insert`)**:agent 半路主动记结构化事实仍返指导错误(需轮首占位
  episode 的时序设计);本设计不解,核心块 `core_append` 暂顶。留后续。
- **#8 生产 AGE**:基础设施(生产 PG 无 AGE 扩展),与本设计正交,不动。
- **会话边界触发**:见「未来切换路径」,本设计不实施。
- 不改 `cross_turn_grouper` / `PathBRunner` / `skip_gate` 内部逻辑(复用现成)。
