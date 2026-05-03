# Backend Legacy 模块清单 + v1.x 演进计划

本文档列出 backend 里跟 v0.8.x 主路径(`app/services/*` 复数 / `app/agents/*` / `app/orchestration/*` / `app/tools/*` / `app/kb/*`)并存的 legacy 模块, 以及未来演进计划。

## 开发规则

- **新功能优先 import `app/services/*`(复数)主线**
- 不要给 legacy 模块加新功能
- legacy 模块仅作 v0.8.x 主路径的"基础设施"使用

## Legacy 模块清单

| 模块 | 用途 | 当前依赖方 | v1.x 演进计划 |
|---|---|---|---|
| `app/core/database.py` | SQLAlchemy `Base` + `engine` + `get_db` + `SessionLocal` | router 13 个 + `app_main` + 多个 service | v1.1.0 改 Postgres + tenant_id, 保留位置 |
| `app/core/security.py` | OAuth/JWT helper | `auth_router` | v1.1.1 OAuth 升级时重写 |
| `app/core/redis_client.py` | Redis cache wrapper | `research_router` | v1.1.1 Redis 缓存升级时扩 |
| `app/config/llm_config.py` | LLM 配置 + `get_config` | `services/openai_client`(v0.8.x 主路径)+ 多个 router | v0.8.x 主路径仍在用, 不变 |
| `app/config/industry_config.py` | 行业配置 | `news_router` / `news_collection_service` | legacy, v0.8.x 不用 |
| `app/config/stock_mapping.py` | 股票名 → 代码映射 | `deep_research_v2`(legacy) | legacy, 可能被新 tools 替代 |
| `app/models/user.py` | User ORM | router(`auth` / `database` / `memory` / `attachment` / `knowledge` / `session`) | v1.1.0 加 tenant_id 列 |
| `app/models/chat.py` | ChatMessage / ChatSession / LongTermMemory / ChatAttachment ORM | router(`session` / `attachment` / `memory`)+ `memory_service` | v1.1.0 加 tenant_id 列 |
| `app/models/knowledge.py` | Document / KnowledgeBase ORM | `knowledge_router` | v1.1.0 加 tenant_id 列 |
| `app/models/news.py` | BiddingInfo / IndustryNews / NewsCollectionTask ORM | `news_collection_service` | legacy(BiddingInfo 不再用), v1.x 评估砍 |
| `app/models/industry_data.py` | CompanyData / IndustryStats / PolicyData ORM | `seed_industry_data` script | legacy, v1.x 评估砍 |
| `app/models/research.py` | ResearchCheckpoint ORM | `checkpoint_service` | legacy(v0.8.x 不用 checkpoint), v1.x 评估砍 |
| `app/service/checkpoint_service.py` | LangGraph checkpoint 持久化 | (待 grep 看是否被 agents 用) | v0.8.x 主路径用 SqliteSaver, 这个 service 可能 unused |
| `app/service/scheduler_service.py` | 调度任务 | (待 grep) | v0.8.3 持仓预警可能复用其调度框架, 否则 legacy |
| `app/service/news_collection_service.py` | 新闻采集 batch | (待 grep) | legacy, v0.8.x 用 Bocha 实时 |
| `app/service/memory_service.py` | LongTermMemory CRUD | `memory_router` | v0.8.4 Memory 子系统 v1 实施时合并到 `app/services/memory_*` |
| `app/service/mock_bocha_service.py` | Mock Bocha API | (历史) | v0.6 真接 Bocha 后已 deprecated, 可删 |
| `app/service/mock_tushare_service.py` | Mock tushare API | `app/tools/get_financials.py` / `get_stock_quote.py`(try/except guard) | v0.8.3 真接 tushare 后 deprecated |
| `app/service/deep_research_v2/*` | 上一代 research subgraph | (legacy 替代品 = `app/orchestration/research_*`) | legacy, v1.x 可整删 |

## 边界

本文档只列**当前** legacy 状态; v0.8.3 / v0.8.4 / v0.8.5 / v1.1 实施时按"演进计划"列分阶段迁移。
