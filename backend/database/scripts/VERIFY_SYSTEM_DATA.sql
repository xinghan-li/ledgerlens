-- ============================================================
-- VERIFY_SYSTEM_DATA.sql
-- 在 production 和 dev 都跑，对比行数
-- ============================================================

SELECT '1_store_chains'                AS table_name, COUNT(*) AS rows FROM store_chains
UNION ALL
SELECT '2_categories',                              COUNT(*)         FROM categories
UNION ALL
SELECT '3_store_locations',                         COUNT(*)         FROM store_locations
UNION ALL
SELECT '4_product_categorization_rules',            COUNT(*)         FROM product_categorization_rules
UNION ALL
SELECT '5_prompt_binding',                          COUNT(*)         FROM prompt_binding
UNION ALL
SELECT '6_prompt_library',                          COUNT(*)         FROM prompt_library
ORDER BY table_name;

-- 分类树层级分布（dev/prod 应一致）
SELECT level, COUNT(*) AS count
FROM categories
GROUP BY level
ORDER BY level;

-- store_chains 列表
SELECT name, normalized_name, is_active FROM store_chains ORDER BY name;

-- store_locations 数量（按 chain 分组）
SELECT sc.name AS chain, COUNT(sl.id) AS location_count
FROM store_locations sl
JOIN store_chains sc ON sl.chain_id = sc.id
GROUP BY sc.name
ORDER BY sc.name;

-- categorization_rules 数量（按 source 分组）
SELECT source, match_type, COUNT(*) AS count
FROM product_categorization_rules
GROUP BY source, match_type
ORDER BY source, match_type;
