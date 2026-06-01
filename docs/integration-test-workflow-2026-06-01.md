# 浏览器端到端联调 Workflow（2026-06-01）

目标：像真实用户一样在浏览器里用鼠标键盘跑通三块功能 —— **记忆手动增删改查 / 持仓监控 / 知识库增删**。

本机（Windows，Intel i7-10700）准备状态见文末「环境就绪清单」。执行需先起全栈。

---

## 0. 起栈顺序（Docker 就绪 + .env 填好 DASHSCOPE_API_KEY 后）

```powershell
# 1. 起依赖容器（compose 会自动 merge docker-compose.override.yml → PG 用 apache/age）
cd D:\mys\Financial-Research-Investment-Assistant
docker compose up -d postgres redis etcd minio milvus
# 等 PG/Milvus healthy（docker compose ps 看 health）

# 2. 起后端（仓库根，load_dotenv 从这里找 .env）
uv run uvicorn app.app_main:app --port 8000 --app-dir backend
#   验证：curl http://127.0.0.1:8000/health  → 期望 200

# 3. 起前端（另一个终端）
cd frontend ; npm run dev          # vite → http://localhost:5173

# 4. 浏览器打开 http://localhost:5173 → 注册/登录拿 JWT
```

**关键依赖核对**
- 记忆图谱需 AGE：override 已把 PG 换 `apache/age:PG15_latest`；起栈后验 `CREATE EXTENSION age` 成功（app_main lifespan log「C.5 memory SQL migration applied」而非 skipped）。
- KB 上传需 embedding（qwen，需 DASHSCOPE）+ PDF 解析（已设 `PDF_PARSER_MODE=pdfplumber` 绕开本机坏掉的 mineru/torch）。
- 记忆/画像新增、mock tushare 行情都依赖 DASHSCOPE。

---

## 1. 登录（前置）

| 步 | 操作 | 期望 |
|---|---|---|
| 1 | 访问 `/` → 重定向 `/login` | 登录页 |
| 2 | 无账号则点「注册」→ 填用户名/密码 → 提交 | 注册成功，落 PG `users` 表 |
| 3 | 登录 | 拿到 JWT，存 localStorage；跳 `/chat` |

> 校验点（曾是 bug #94/#98）：登录后刷新页面不掉登录态；各页请求头带 `Authorization: Bearer`。

---

## 2. 记忆 手动增删改查（/memory → 画像 tab）✅ 完整可测

UI：`MemoryPersona`，两区「你声明的 / agent 观察到的」，元素带 `data-testid`。

| 步 | 操作（鼠标键盘） | 期望 | 校验 |
|---|---|---|---|
| 增 | 进 `/memory`，默认「画像」tab → 点「+ 手动添加一条」→ 输入「风险偏好稳健」→ 点「保存」 | toast「已添加」；「你声明的」区出现新条 | `POST` persona add；刷新后仍在（落 PG） |
| 查 | 观察两区列表 | user_declared / agent_inferred 分区渲染 | `fetchPersona` 200 |
| 改 | 新条上点 ✏️ → 改文本 → 点 ✓ | 文本更新；若是 agent 条改后会「迁到你的声明区」并高亮 | `updatePersonaItem` |
| 删 | 点 🗑️ → Popconfirm「确认」 | toast「已删除」；条目消失 | `deletePersonaItem`；刷新不复现 |
| 其它读视图 | 切「图谱」「时间线」「历史」tab | 图谱（AGE 数据）、时间线、审计日志正常渲染 | graph/timeline/audit 三端点 200；**若 AGE 没装好图谱会空 → 回到起栈核对** |
| 软删 | 图谱 tab 选一条 edge → invalidate | edge 失效（bi-temporal） | `POST /memory/edges/{id}/invalidate` |

---

## 3. 持仓监控（/portfolio + /monitoring）⚠️ 创建路径断裂 — 需先决策

**联调发现的缺口（读代码即得，未跑已知）：**
- `/portfolio` 页 **只读**（仅 `listPositions()`）；无新增/编辑/删除 UI。
- `/monitoring/config` 客户 CRUD **v1.0 已退役**：「添加客户」弹窗点确定只 `message.error("客户管理接口已在 v1.0 中退役")`；删除同样报错。全局配置/阈值**仅前端生效**（重启丢）。
- 迁移提示原文：「监控标的改由『持仓』页管理」——但持仓页没有录入 UI。
- ⇒ **真实用户无法在浏览器里新增监控标的。** 只有后端 `POST /portfolio/onboarding` / `/portfolio/trades` 能灌仓位（前端未 wire）。

**可测的部分（读路径）：**
| 步 | 操作 | 期望 |
|---|---|---|
| 灌数据（API，非 UI） | `POST /portfolio/onboarding` 录入初始持仓（如 600519.SH） | 落 PG positions |
| 查 | 浏览器进 `/portfolio` | 表格显示持仓：代码/名称/数量/均价/盈亏/行情/静默 |
| 监控页 | 进 `/monitoring` | 告警列表渲染（需先有 detection cycle 产出，可手动触发 Celery task） |
| 告警详情 | 点一条告警 → `/monitoring/:cid/alert/:aid` | 详情渲染 |

**给用户的决策**（联调发现，需你定）：持仓监控的「增」要不要补？两条路：
- (A) 前端补 onboarding/trades 录入 UI（让真实用户能加仓位）。
- (B) 暂只联调读路径，创建走 API 灌数据。

---

## 4. 知识库 增删（/knowledge）✅ 完整可测

UI：`KnowledgePage`，完整 CRUD。

| 步 | 操作（鼠标键盘） | 期望 | 校验 |
|---|---|---|---|
| 增-库 | 进 `/knowledge` → 点「创建知识库」→ 填名称/描述 → 提交 | toast「知识库创建成功」；卡片出现 | `createKnowledgeBase` |
| 改-库 | 卡片上 ✏️ → 改名 → 保存 | toast「更新成功」 | `updateKnowledgeBase` |
| 进库 | 点卡片 | 进详情，文档列表（空态） | `fetchKnowledgeBase` |
| 增-文档 | 点「上传文档」→ 选一个 .txt/.md（避开大 PDF 先验通路）→ | 上传 modal；状态 待处理→处理中→已完成（3s 轮询） | `uploadDocument`；embedding 落 Milvus（需 DASHSCOPE） |
| 查-切片 | 文档「已完成」后点 👁 查看切片 | 抽屉显示 chunks | chunks 端点 |
| 删-文档 | 文档行 🗑️ → Popconfirm | toast「文档删除成功」；消失 | `deleteDocument` |
| 删-库 | 返回列表 → 卡片 🗑️ → Popconfirm | toast「知识库删除成功」 | `deleteKnowledgeBase` |

> 先用小 .txt 验证 上传→切块→embedding→完成 全链路，再试 PDF（pdfplumber 路径）。

---

## 5. 执行记录（2026-06-01 实测）

环境：本机 Windows 起全栈（PG=apache→postgres:15-alpine via daocloud / Redis / Milvus 容器 + uvicorn:8000 + vite:5183），testuser 注册登录成功。

### 记忆（/memory 画像 tab）— 核心 CRUD 全通过
| 操作 | 结果 |
|---|---|
| 增（+手动添加一条 → 保存） | ✅ PASS — "已添加"，落 PG，刷新仍在 |
| 改（✏️ 内联编辑 → ✓） | ✅ PASS — 文本更新 |
| 删（🗑️ → Popconfirm 确认） | ✅ PASS — "已删除"，回空态 |
| 查（列表/空态渲染） | ✅ PASS |
| 图谱 tab | ❌ **BUG**：点开后渲染器冻结（Cytoscape；`/memory/graph` 后端返 200，故为前端渲染卡死） |

### 持仓监控（/portfolio + /monitoring）
| 操作 | 结果 |
|---|---|
| /portfolio 读（持仓表格） | ✅ PASS — 列/计数/分页/监控中标记齐全；UTF-8 中文正常（中国平安经 curl UTF-8 灌入显示正确） |
| 增持仓（UI） | ⚠️ 无 UI — 只能经 API `POST /portfolio/onboarding`（已确认契约缺口） |
| /monitoring 告警页 | ❌ **BUG**：死循环狂刷 `GET /api/monitoring/signals?limit=50`（前端 useEffect 无限重取）→ 渲染器冻结 |
| /monitoring/config 客户 CRUD | ⚠️ v1.0 已退役（点添加只弹错误，预期） |

### 知识库（/knowledge）
| 操作 | 结果 |
|---|---|
| 创建知识库（UI 弹窗 → 创建） | ✅ PASS — "知识库创建成功" |
| 删除知识库（卡片 🗑️ → Popconfirm 确定） | ✅ PASS — 回空态 |
| 删除文档（API DELETE） | ✅ PASS — 204；UI 删除受"文档卡 pending 持续轮询"拖累 |
| **上传文档（增-文档）** | ❌ **重大 BUG**：`process_document` 后台任务 import 遗留 `app.service.docmind_service` → `ModuleNotFoundError: alibabacloud_docmind_api20220711`（未声明依赖）→ 文档永久卡 "待处理"，**错误不向用户暴露**（违反 fail-loud）。与 KB 设计的 pdfplumber/mineru 切块路径不符 |
| 创建弹窗 | ⚠️ minor：创建成功后弹窗未自动关闭 |
| 文档时间戳 | ⚠️ minor：详情页显示 "8 小时前"（TZ 偏移 bug；KB 卡片用 dayjs fromNow 正常显示"分钟前"） |

### Windows 环境问题（非产品逻辑 bug，但阻碍本机完整运行；项目本在 Mac/Linux 跑）
- `psycopg cannot use ProactorEventLoop`：psycopg3 异步连接池要 SelectorEventLoop → LangGraph 聊天 checkpointer 受影响。
- `greenlet DLL load failed`：SQLAlchemy 异步 session 缺 greenlet C 扩展 DLL（缺 MSVC redist 同根）→ 异步 SQLAlchemy 端点报错。
- `No module named 'resource'`：resource 是 Unix-only → chat graph 构建失败，/chat 返 503。
- torch/transformers DLL：mineru PDF 解析本机跑不起（已用 PDF_PARSER_MODE=pdfplumber 规避，但 KB 实际走 docmind 路径，见上）。

### 结论（含复核修正）
- **记忆增删改查**：✅ 核心 CRUD（画像 tab）全部通过。
- **知识库增删**：✅ 库的增/删通过；文档上传原断裂 → **已修复**（见下）。
- **持仓监控**：✅ 持仓读路径通过；⚠️ 增持仓无 UI。

### ⚠️ 复核修正：2 个"前端冻结 bug"是误报
最初报告 /monitoring 死循环冻结、/memory 图谱冻结。按调试纪律精确复核后**推翻**：
- 精确测速 /monitoring signals = **2 次/10秒**（正好 5s 轮询，非死循环）；清掉多余浏览器 tab 后 /monitoring 与 /memory 图谱均**正常渲染**。
- 真因：联调时累积了多个**后台轮询的废 tab** + GIF 录制 → **Chrome 扩展过载** → 截图超时，被误判为"页面死循环/冻结"。
- 教训：浏览器自动化要**用完即关 tab**；测速率不能用 `tail` 混历史。

### ✅ 真 bug 修复：KB 文档上传（backend/app/router/knowledge_router.py）
- **根因**：`process_document` 后台任务 import 遗留 `app.service.docmind_service` → 依赖未声明的 `alibabacloud_docmind_api20220711` → ModuleNotFoundError → 文档永久卡 "pending" 且不报错。
- **修复**：重写 `process_document` 走本地管线 —— `_extract_text`（txt/code 直读 / pdf 走 pdfplumber / docx 走 python-docx）→ `_chunk_text`（段落感知切块）→ `build_embedding_service_from_env()`（qwen 1024d）→ `MilvusService.insert_documents`（写 `kb_{kb_id}`，与 get_document_chunks 对齐）；错误写入 `doc.error_message`（fail-loud）。
- **附带环境修复**：后端进程继承了 `all_proxy=socks5://127.0.0.1:7897`，dashscope（阿里云国内直连）走它需 PySocks 报 `InvalidSchema: Missing dependencies for SOCKS support`。后端以**清空代理 env**（NO_PROXY=*）重启即解（后端出站全是 localhost 服务 + 国内 aliyun，不需代理）。
- **端到端验证**：浏览器 UI 上传后文档 `已完成 · 1 个切片`，查看切片抽屉显示正确中文内容；修复前那笔显示 `处理失败 + 错误信息`（证明 fail-loud 生效）。chunks API 返回 content 正确。

### Windows 环境问题（非产品逻辑 bug，项目本在 Mac/Linux 跑）
- `psycopg cannot use ProactorEventLoop`（聊天 checkpointer）/ `greenlet DLL load failed`（异步 SQLAlchemy 端点）/ `No module named 'resource'`（/chat 503）/ torch DLL（mineru，已用 pdfplumber 规避）。
- 这些不影响本次三块功能的同步 REST 路径（记忆 CRUD / 持仓读 / KB 增删改）。

---

## 环境就绪清单（2026-06-01 已备）
- ✅ 前端依赖 `node_modules`（vite 就位，411 包）
- ✅ `.env`（仓库根）：JWT 随机密钥已填、PG/Redis/Milvus 本地默认、mock 模式、`PDF_PARSER_MODE=pdfplumber`。**待填 `DASHSCOPE_API_KEY`**
- ✅ `docker-compose.override.yml`：PG → `apache/age:PG15_latest`
- ✅ 浏览器扩展已连
- ⏳ Docker Desktop（用户安装中）
