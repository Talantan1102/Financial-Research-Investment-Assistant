# Chat 子系统用户隔离 设计

**Goal:** 把聊天子系统(会话列表/CRUD、轮次、升级)的访问控制补齐到与 reports/memory 同一标准——强制真 JWT 登录 + 所有查询按 `user.id` 过滤 + 资源归属校验——堵住"任何人(乃至不登录)都能读/改/删所有人聊天会话"的跨用户泄露。

## 背景 / 问题(已实证)

- `curl GET /api/v0/chats`(**无 token**)直接返回全部会话 → 不登录即可读所有人聊天。
- `chats.py` 5 个端点**零 auth 依赖**:`list_for_user("anonymous")` 硬编码、`create_session(user_id="anonymous")` 硬编码、`get/rename/delete` 拿任意 `session_id` 即可操作(IDOR,可删他人会话)。
- `chat.py`(轮次)#156 后是 optional auth + `"anonymous"` 兜底;`escalate.py` 硬编码 anonymous。
- 数据层:所有现存会话 `user_id IS NULL`(共享池),即便改码,老数据仍无归属。
- 对照:reports/memory/portfolio/knowledge 等 router **已正确隔离**(`get_current_user_required` + `filter(user_id==user.id)` + 归属校验)。本设计照搬该范式,不发明新机制。

## 决策(已与用户确认)

1. **匿名不能再聊天**:聊天端点改 `get_current_user_required`(无/无效 token → 401),与 reports/memory 一致。
2. **清掉老 NULL 用户会话**:`user_id IS NULL` 的 chat_sessions 连同级联子表删除。
3. 顺序:稳定真 auth 后端就绪(#156 已合入 main)→ 后端三 router 加隔离 → 数据清理 → 两用户验证。
4. **前端不改**:auth store 存读链已对(`token` key 一致)、`chatApi` 每请求拼 `Authorization`;之前的"匿名轮"是环境抽风(后端 stub↔真auth 反复切),非前端 bug。

## 设计(按文件)

### `backend/app/router/chats.py`(主修)
5 个端点统一注入 `user: User = Depends(get_current_user_required)`(从 `auth_router` 导入,与 reports.py 同):
- `list_chats` → `repo.list_for_user(str(user.id))`(传真 UUID 字符串,不再 `"anonymous"`)。
- `create_chat` → `repo.create_session(user_id=str(user.id), title=...)`。
- `get_chat` / `rename_chat` / `delete_chat` → 先 `repo.get_session(session_id)`,再**归属校验**:`if s.user_id != user.id: raise HTTPException(404)`(用 404 不暴露存在性,与 reports.py 的 403 取舍二选一,本设计用 404 防枚举)。校验通过才继续。

### `backend/app/router/chat.py`(轮次端点)
- `POST /api/v0/chat`、`/cancel`、`/steer`、`/retry`、`/stream`:`user` 依赖由 optional `get_current_user` 改 `get_current_user_required`(匿名禁聊)。
- 落 user message + 建 chat_task 前,**校验会话归属**(`req.session_id` 对应 session 的 `user_id == user.id`,否则 404)。
- 删除 `_coerce_user_uuid`/`"anonymous"` 兜底分支(`user.id` 此后恒真 UUID;retry 的 `old_task.user_id else "anonymous"` 改为要求 `old_task.user_id == user.id`)。
- `_maybe_populate_persona_on_session_start`:`user.id` 此后恒真 UUID,删匿名容错分支。

### `backend/app/router/escalate.py`
- 端点注入 `get_current_user_required`;`user_id="anonymous"`(L125)改真 `user.id` + 会话归属校验。

### 数据清理(一次性脚本)
删 `user_id IS NULL` 的会话及级联(顺序按 FK,子先父后):
`chat_memory_episodes`(WHERE session_id IN 该批)→ `chat_messages` → `chat_tasks` → `chat_sessions`。
脚本走 fria-venv + 真 PG,删前打印计数,事务内执行。

## 错误处理 / 边界

- 无/无效 token → 401(`get_current_user_required` 既有行为)。
- 访问/改/删非己会话 → 404(不区分"不存在"与"非己",防资源枚举)。
- 已登录但 `user.id` 解析异常 → 由 `get_current_user_required` 兜(返回真 User 才进 handler)。

## 测试

- **单元/集成**(照搬现有 chat 集成测试骨架,`dependency_overrides[get_current_user_required]` 注入 user A / user B):
  - 无 token → `GET /api/v0/chats` 返 401(回归:不再返全量)。
  - user A 建会话 → A 的 list 含之、B 的 list 不含(隔离)。
  - user B `GET/PUT/DELETE /chats/{A的id}` → 404(IDOR 堵死)。
  - 轮次端点无 token → 401。
- **数据清理**:脚本对一个临时 NULL 会话验证删除 + 级联不留孤儿。
- **浏览器 e2e(稳定真 auth 后端 + 两个账号)**:A 登录只见 A 的;B 登录只见 B 的;不登录进不去。

## 不在本设计范围

- 前端代码(已确认无 bug)。
- 老 NULL 会话之外的历史数据迁移(直接清,不迁)。
- reports/memory 等已隔离 router(无需改)。
