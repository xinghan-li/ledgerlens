-- ============================================================
-- GENERATE_INSERT_SQL.sql
-- 在 DEV 数据库 SQL Editor 里运行
-- 把每段输出的 INSERT SQL 复制到 production SQL Editor 里执行
-- 顺序：store_chains → categories → store_locations
--        → product_categorization_rules → prompt_binding
-- ============================================================


-- ── 1. store_chains ──────────────────────────────────────────
SELECT
  'INSERT INTO store_chains (id, name, normalized_name, aliases, is_active, created_at, updated_at) VALUES ('
  || quote_literal(id::text) || ', '
  || quote_literal(name) || ', '
  || quote_literal(normalized_name) || ', '
  || quote_literal(aliases::text) || '::text[], '
  || is_active || ', '
  || quote_literal(created_at::text) || ', '
  || quote_literal(updated_at::text)
  || ') ON CONFLICT (id) DO NOTHING;'
FROM store_chains
ORDER BY created_at;


-- ── 2. categories（level 升序，保证父节点先于子节点插入）──────
SELECT
  'INSERT INTO categories (id, parent_id, level, name, path, description, is_system, is_active, created_at, updated_at) VALUES ('
  || quote_literal(id::text) || ', '
  || COALESCE(quote_literal(parent_id::text), 'NULL') || ', '
  || level || ', '
  || quote_literal(name) || ', '
  || COALESCE(quote_literal(path), 'NULL') || ', '
  || COALESCE(quote_literal(description), 'NULL') || ', '
  || is_system || ', '
  || is_active || ', '
  || quote_literal(created_at::text) || ', '
  || quote_literal(updated_at::text)
  || ') ON CONFLICT (id) DO NOTHING;'
FROM categories
ORDER BY level ASC, created_at ASC;


-- ── 3. store_locations ───────────────────────────────────────
SELECT
  'INSERT INTO store_locations (id, chain_id, name, address_line1, address_line2, city, state, zip_code, country_code, latitude, longitude, chain_name, phone, is_active, created_at, updated_at) VALUES ('
  || quote_literal(id::text) || ', '
  || quote_literal(chain_id::text) || ', '
  || quote_literal(name) || ', '
  || COALESCE(quote_literal(address_line1), 'NULL') || ', '
  || COALESCE(quote_literal(address_line2), 'NULL') || ', '
  || COALESCE(quote_literal(city), 'NULL') || ', '
  || COALESCE(quote_literal(state), 'NULL') || ', '
  || COALESCE(quote_literal(zip_code), 'NULL') || ', '
  || COALESCE(quote_literal(country_code), 'NULL') || ', '
  || COALESCE(latitude::text, 'NULL') || ', '
  || COALESCE(longitude::text, 'NULL') || ', '
  || COALESCE(quote_literal(chain_name), 'NULL') || ', '
  || COALESCE(quote_literal(phone), 'NULL') || ', '
  || is_active || ', '
  || quote_literal(created_at::text) || ', '
  || quote_literal(updated_at::text)
  || ') ON CONFLICT (id) DO NOTHING;'
FROM store_locations
ORDER BY created_at;


-- ── 4. product_categorization_rules ──────────────────────────
SELECT
  'INSERT INTO product_categorization_rules (id, normalized_name, original_examples, store_chain_id, category_id, match_type, similarity_threshold, source, priority, times_matched, last_matched_at, created_by, created_at, updated_at) VALUES ('
  || quote_literal(id::text) || ', '
  || quote_literal(normalized_name) || ', '
  || COALESCE(quote_literal(original_examples::text) || '::text[]', 'NULL') || ', '
  || COALESCE(quote_literal(store_chain_id::text), 'NULL') || ', '
  || quote_literal(category_id::text) || ', '
  || quote_literal(match_type) || ', '
  || similarity_threshold || ', '
  || quote_literal(source) || ', '
  || priority || ', '
  || times_matched || ', '
  || COALESCE(quote_literal(last_matched_at::text), 'NULL') || ', '
  || 'NULL' || ', '  -- created_by: production 无用户，设 NULL
  || quote_literal(created_at::text) || ', '
  || quote_literal(updated_at::text)
  || ') ON CONFLICT (id) DO NOTHING;'
FROM product_categorization_rules
ORDER BY created_at;


-- ── 5. prompt_binding ────────────────────────────────────────
-- 注意：library_id UUID 在 dev/prod 不同（seed 各自生成），
-- 用子查询通过 prompt_key 在 production 里找到对应的 library_id
SELECT
  'INSERT INTO prompt_binding (id, prompt_key, library_id, scope, chain_id, location_id, priority, is_active, created_at, updated_at) VALUES ('
  || quote_literal(id::text) || ', '
  || quote_literal(prompt_key) || ', '
  || '(SELECT id FROM prompt_library WHERE key = ' || quote_literal(prompt_key) || ' LIMIT 1), '
  || quote_literal(scope) || ', '
  || COALESCE(quote_literal(chain_id::text), 'NULL') || ', '
  || COALESCE(quote_literal(location_id::text), 'NULL') || ', '
  || priority || ', '
  || is_active || ', '
  || quote_literal(created_at::text) || ', '
  || quote_literal(updated_at::text)
  || ') ON CONFLICT (id) DO NOTHING;'
FROM prompt_binding
ORDER BY scope, priority;
