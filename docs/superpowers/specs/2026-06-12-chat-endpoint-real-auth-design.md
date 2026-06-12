# Chat 端点接真 JWT 认证(C.6 wiring)设计

**Goal:** 让 `/api/v0/chat` 认前端本就在发的真 JWT,登录用户那一轮带真实 `user_id` → 跨会话记忆(#7 的 episode 写入)真正生效;无 token 时回退匿名,保持今天的行为。

**背景:** #7(PR #151)接通了「chat 轮末写 episode + 触发 Path B」,但浏览器实测发现 0 写入——根因:`/api/v0/chat` 用的是 `auth_helpers.get_current_user` 这个 **v0 匿名 stub**(每轮 `user.id="anonymous"`),而 `ChatMemoryEpisode.user_id` 是 NOT NULL FK,匿名写不进去,hook 正确跳过。结论:**记忆写入在真 auth 接进 chat 端点前是休眠的**。真 JWT 认证(`auth_router`:`/auth/login` `/auth/token` `/auth/me` + `get_current_user`)前后端早已完整存在,只差 chat 端点没接(`_coerce_user_uuid` 注释自承「C.6 接 JWT 后」是计划内的一步;除 chat/reports 外其它 router 都已用真 auth)。

## 决策

**改 1 个文件 `backend/app/router/auth_helpers.py`,chat.py 一行不动。**

`auth_helpers.get_current_user` 由「恒返回匿名」改为「委托真 `auth_router.get_current_user`(校验 JWT → `User | None`),有则返回真 User,无/无效 token 则回退 `_AnonUser(id="anonymous")`」。

```
登录(带有效 Bearer token)→ 真 User(真 UUID id)→ 那一轮真写 episode ✅
无 / 无效 token            → _AnonUser(id="anonymous")→ hook 照常跳过(= 今天行为,不变)
```

chat.py 通篇只读 `user.id`,匿名回退后 `.id` 仍合法,故 chat.py 无需改动。

## 影响面 / 兼容

- **chat.py 不动**;符号 `auth_helpers.get_current_user` 身份不变(仅换函数体 + 加 `Depends` 子依赖),故现有 chat 集成测试的 `app.dependency_overrides[get_current_user] = lambda: _StubUser()` 仍命中,匿名/stub 路径行为不变。
- 仅 chat 这一条;`reports.py` 及其它 router 不碰(它们要么已用 `get_current_user_required`,要么是独立决策)。

## 风险与缓解

1. **persona populate 对真用户激活**:`_maybe_populate_persona_on_session_start` 对匿名一直在 `UUID("anonymous")` 处抛错被吞(只 warn);真用户则首轮真跑 persona 蒸馏。这是预期功能激活,且该 hook best-effort / fail-safe(失败只 log 不阻塞 enqueue)。→ 浏览器端到端冒烟一轮确认。
2. **无 token 路径新增 `get_db` 子依赖**:真 `get_current_user` 依赖 `oauth2_scheme`(auto_error=False)+ `get_db`,即便无 token 也会注入 db。这是所有用真 auth 的端点早就在做的标准姿势,低风险。→ 跑全套 chat 测试确认不回归。

## 测试

- **单测** `auth_helpers.get_current_user` 回退逻辑:`real_user=<User>` 直通返回;`real_user=None` → `_AnonUser(id="anonymous")`。
- **回归**:全套 chat 集成测试(`test_chat_*`)必须全绿(匿名路径不变)。
- **浏览器 e2e**:登录用户(testuser,前端已持 token)发一轮 → PG 真出现一条 `source_kind=chat_turn` 且 `user_id=真UUID` 的 episode(就是 #7 一直追的 happy-path),且 Path B 抽取被触发。

## 被否备选

- **auth_router 新建 `get_current_user_optional` 再换 chat 依赖**:更分层,但要改测试 override 的 key、多碰文件,收益不大。
- **chat 改强制登录(`get_current_user_required`)**:会把匿名 UX + 一堆现有匿名假设测试全打挂。❌
