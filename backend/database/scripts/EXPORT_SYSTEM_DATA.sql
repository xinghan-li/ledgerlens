-- ============================================================
-- EXPORT_SYSTEM_DATA.sql
-- 在 DEV 数据库里运行，把每个 SELECT 的结果复制出来
-- 然后去 IMPORT_SYSTEM_DATA.sql 里替换对应的占位符
-- ============================================================
-- 顺序必须严格按照外键依赖：
--   1. store_chains（无依赖）
--   2. categories（自引用 parent_id，按 level 排序保证父先于子）
--   3. store_locations（依赖 store_chains）
--   4. product_categorization_rules（依赖 categories + store_chains）
--   5. prompt_binding（依赖 prompt_library，已由 seed 文件建好）
-- ============================================================

-- ── 1. store_chains ──────────────────────────────────────────
SELECT id, name, normalized_name, aliases, is_active, created_at, updated_at
FROM store_chains
ORDER BY created_at;

-- ── 2. categories（必须按 level 升序，确保父节点先插入）───────
SELECT id, parent_id, level, name, path, description, is_system, is_active, created_at, updated_at
FROM categories
ORDER BY level ASC, created_at ASC;

-- ── 3. store_locations ───────────────────────────────────────
SELECT id, chain_id, name, address_line1, address_line2,
       city, state, zip_code, country_code,
       latitude, longitude, chain_name, phone,
       is_active, created_at, updated_at
FROM store_locations
ORDER BY created_at;

-- ── 4. product_categorization_rules ──────────────────────────
SELECT id, normalized_name, original_examples, store_chain_id,
       category_id, match_type, similarity_threshold,
       source, priority, times_matched, last_matched_at,
       created_by, created_at, updated_at
FROM product_categorization_rules
ORDER BY created_at;

-- ── 5. prompt_binding（检查 dev 里是否有超出 seed 的额外数据）
SELECT id, prompt_key, library_id, scope, chain_id, location_id, priority, is_active, created_at, updated_at
FROM prompt_binding
ORDER BY scope, priority;
