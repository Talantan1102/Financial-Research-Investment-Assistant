-- C.5 Cross-session memory schema migration.
-- Spec: docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md § 2
-- Plan: docs/superpowers/plans/2026-05-11-c5-plan1a-storage-foundation.md
--
-- Idempotent: 安全多次运行(IF NOT EXISTS / DROP-and-recreate-when-needed pattern)。
-- 应用时机: app_main.lifespan create_all() 之后, 或 tests fixture 应用一次。

-- ===========================================================================
-- 1. partial index for unextracted episodes(spec § 2 行 158-159)
-- ===========================================================================

CREATE INDEX IF NOT EXISTS idx_episodes_unextracted
  ON chat_memory_episodes(user_id)
  WHERE extracted_at IS NULL;

-- ===========================================================================
-- 2. GENERATED tsvector + GIN index on nodes(spec § 2 行 173-180)
-- ===========================================================================
-- 注: GENERATED column 加在 ALTER TABLE 时, 不能用 IF NOT EXISTS for column;
-- 用 DO block 检查 column 不存在再 ADD.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'chat_memory_nodes' AND column_name = 'search_vector'
  ) THEN
    ALTER TABLE chat_memory_nodes
      ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(search_tokens, ''))
      ) STORED;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_nodes_search_gin
  ON chat_memory_nodes USING GIN(search_vector);

-- ===========================================================================
-- 3. GENERATED tsvector + GIN index on edges(spec § 2 行 205-208 + 215)
-- ===========================================================================

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'chat_memory_edges' AND column_name = 'search_vector'
  ) THEN
    ALTER TABLE chat_memory_edges
      ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(search_tokens, ''))
      ) STORED;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_edges_search_gin
  ON chat_memory_edges USING GIN(search_vector);

-- ===========================================================================
-- 4. Partial index for "current snapshot"(spec § 2 行 217-220)
--    高频 query: 当前持仓 / 偏好(valid_to IS NULL AND invalidated_at IS NULL)
-- ===========================================================================

CREATE INDEX IF NOT EXISTS idx_edges_current_snapshot
  ON chat_memory_edges(user_id, source_node_id, target_node_id)
  WHERE valid_to IS NULL AND invalidated_at IS NULL;

-- ===========================================================================
-- 5. 时间区间复合索引(spec § 2 行 222-224)
-- ===========================================================================

CREATE INDEX IF NOT EXISTS idx_edges_valid_range
  ON chat_memory_edges(user_id, valid_from, valid_to);

-- ===========================================================================
-- 6. AGE 扩展加载 + 'chat_memory' 图 + 7 vlabel + 11 elabel
--    (spec § 2 行 274-302)
--    若 AGE 不可用, 用 DO block 把全部 AGE 命令包起来, exception swallow.
--    L1 fixture 探测, 真不可用时 skip 测试。
-- ===========================================================================

DO $age$ BEGIN
  -- 加载 AGE 扩展
  CREATE EXTENSION IF NOT EXISTS age;
  LOAD 'age';
  -- AGE 要求 search_path 含 ag_catalog
  PERFORM set_config('search_path', 'ag_catalog,"$user",public', false);

  -- 创建图(若不存在)
  IF NOT EXISTS (
    SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'chat_memory'
  ) THEN
    PERFORM ag_catalog.create_graph('chat_memory');
  END IF;

  -- 7 vlabel(create_vlabel 内部已有"已存在则跳过"语义, 但保险用 EXCEPTION 包裹)
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'User'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Stock'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Industry'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Sector'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Metric'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Strategy'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Concept'); EXCEPTION WHEN OTHERS THEN NULL; END;

  -- 11 elabel
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'HOLDS'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'WATCHES'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'PREFERS'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'AVOIDS'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'EXPRESSED_VIEW'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'SOLD'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'STUDIED'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'COMPARED'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'BELONGS_TO'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'HAS_CONCEPT'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'CORRELATED_WITH'); EXCEPTION WHEN OTHERS THEN NULL; END;

EXCEPTION WHEN undefined_file OR undefined_object OR feature_not_supported THEN
  -- AGE 扩展未编译进 PG / 镜像不带 AGE → silent skip(测试 fixture 单独 verify)
  RAISE NOTICE 'AGE extension not available; skipping graph setup';
END $age$;
