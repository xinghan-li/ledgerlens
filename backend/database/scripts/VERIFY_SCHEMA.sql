-- ============================================================
-- VERIFY_SCHEMA.sql
-- 在 dev 和 production 两个数据库上分别运行，对比输出结果
-- 结果应完全一致（除了 row counts 部分，dev 有历史数据会更多）
-- ============================================================


-- ============================================================
-- SECTION 1: 所有表是否存在（应返回 19 行）
-- ============================================================
SELECT
  table_name,
  (SELECT COUNT(*) FROM information_schema.columns c
   WHERE c.table_schema = 'public' AND c.table_name = t.table_name) AS column_count
FROM information_schema.tables t
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
ORDER BY table_name;


-- ============================================================
-- SECTION 2: 所有函数是否存在
-- ============================================================
SELECT
  routine_name,
  routine_type
FROM information_schema.routines
WHERE routine_schema = 'public'
ORDER BY routine_name;


-- ============================================================
-- SECTION 3: 所有触发器是否存在
-- ============================================================
SELECT
  trigger_name,
  event_object_table,
  event_manipulation,
  action_timing
FROM information_schema.triggers
WHERE trigger_schema = 'public'
ORDER BY event_object_table, trigger_name;


-- ============================================================
-- SECTION 4: 所有索引（数量应一致）
-- ============================================================
SELECT
  tablename,
  indexname
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;


-- ============================================================
-- SECTION 5: 系统级数据行数
-- （dev 的小票数据更多是正常的，但系统表应一致）
-- ============================================================
SELECT 'categories'               AS tbl, COUNT(*) AS rows FROM categories
UNION ALL
SELECT 'store_chains',                     COUNT(*)         FROM store_chains
UNION ALL
SELECT 'store_locations',                  COUNT(*)         FROM store_locations
UNION ALL
SELECT 'prompt_library',                   COUNT(*)         FROM prompt_library
UNION ALL
SELECT 'prompt_binding',                   COUNT(*)         FROM prompt_binding
UNION ALL
SELECT 'product_categorization_rules',     COUNT(*)         FROM product_categorization_rules
-- 下面是用户 & 小票数据，prod 应为 0，dev 有历史数据
UNION ALL
SELECT '── users (prod=0 is ok)',          COUNT(*)         FROM users
UNION ALL
SELECT '── receipts (prod=0 is ok)',       COUNT(*)         FROM receipt_status
ORDER BY tbl;


-- ============================================================
-- SECTION 6: RLS 是否启用（所有业务表都应为 true）
-- ============================================================
SELECT
  relname AS table_name,
  relrowsecurity AS rls_enabled,
  relforcerowsecurity AS rls_forced
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relkind = 'r'
ORDER BY relname;


-- ============================================================
-- SECTION 7: categories 树结构快照（dev/prod 应完全一致）
-- ============================================================
SELECT
  id,
  name,
  parent_id,
  level,
  path
FROM categories
ORDER BY level, path, name;


-- ============================================================
-- SECTION 8: prompt_library 快照（dev/prod 应完全一致）
-- ============================================================
SELECT
  category,
  key,
  content_role,
  LEFT(content, 60) AS content_preview
FROM prompt_library
ORDER BY category, key;
