-- ============================================
-- 合并 store_chain（如 T&T US + Canada）后的数据扫描
-- 用途：检查孤儿引用、T&T 相关小票/商品/规则、门店地址是否完整
-- ============================================

-- ---------------------------------------------------------------------------
-- 1. 孤儿 store_chain_id：引用了已不存在的 chain（合并时若先删 chain 再改引用会失败，但可能部分表已改、部分未改）
-- ---------------------------------------------------------------------------
SELECT 'record_summaries' AS tbl, rs.id, rs.receipt_id, rs.store_chain_id AS orphan_chain_id, rs.store_name
FROM record_summaries rs
LEFT JOIN store_chains sc ON sc.id = rs.store_chain_id
WHERE rs.store_chain_id IS NOT NULL AND sc.id IS NULL
LIMIT 100;

SELECT 'products' AS tbl, p.id, p.normalized_name, p.store_chain_id AS orphan_chain_id
FROM products p
LEFT JOIN store_chains sc ON sc.id = p.store_chain_id
WHERE p.store_chain_id IS NOT NULL AND sc.id IS NULL
LIMIT 100;

SELECT 'product_categorization_rules' AS tbl, r.id, r.normalized_name, r.store_chain_id AS orphan_chain_id
FROM product_categorization_rules r
LEFT JOIN store_chains sc ON sc.id = r.store_chain_id
WHERE r.store_chain_id IS NOT NULL AND sc.id IS NULL
LIMIT 100;

SELECT 'classification_review' AS tbl, cr.id, cr.raw_product_name, cr.store_chain_id AS orphan_chain_id
FROM classification_review cr
LEFT JOIN store_chains sc ON sc.id = cr.store_chain_id
WHERE cr.store_chain_id IS NOT NULL AND sc.id IS NULL
LIMIT 100;

SELECT 'store_candidates' AS tbl, c.id, c.raw_name, c.suggested_chain_id AS orphan_chain_id
FROM store_candidates c
LEFT JOIN store_chains sc ON sc.id = c.suggested_chain_id
WHERE c.suggested_chain_id IS NOT NULL AND sc.id IS NULL
LIMIT 100;

-- ---------------------------------------------------------------------------
-- 2. 当前 T&T 连锁（合并后应只剩一条）
-- ---------------------------------------------------------------------------
SELECT id, name, normalized_name, aliases, is_active
FROM store_chains
WHERE (name ILIKE '%T&T%' OR normalized_name ILIKE '%t&t%' OR normalized_name ILIKE '%tnt%')
ORDER BY name;

-- ---------------------------------------------------------------------------
-- 3. 小票：已关联到 T&T chain 的数量 + 未关联但 store_name 像 T&T 的（应被 backfill 覆盖）
-- ---------------------------------------------------------------------------
-- 3a 已关联到 T&T 的 record_summaries 数量（按 store_name 看是否有 US/Canada 字样）
SELECT
  sc.id AS chain_id,
  sc.name AS chain_name,
  COUNT(rs.id) AS receipt_count,
  COUNT(CASE WHEN rs.store_name ILIKE '%US%' OR rs.store_name ILIKE '%USA%' OR rs.store_name ILIKE '%Lynnwood%' THEN 1 END) AS like_us,
  COUNT(CASE WHEN rs.store_name ILIKE '%Canada%' OR rs.store_name ILIKE '%Canada%' OR rs.store_name ILIKE '%Osaka%' OR rs.store_name ILIKE '%BC%' THEN 1 END) AS like_canada
FROM store_chains sc
LEFT JOIN record_summaries rs ON rs.store_chain_id = sc.id
WHERE sc.name ILIKE '%T&T%' OR sc.normalized_name ILIKE '%t&t%'
GROUP BY sc.id, sc.name;

-- 3b 未关联 chain 但 store_name 像 T&T 的（backfill 会把这些挂到合并后的 T&T chain）
SELECT rs.id, rs.receipt_id, rs.store_name, rs.store_chain_id
FROM record_summaries rs
WHERE rs.store_chain_id IS NULL
  AND (rs.store_name ILIKE '%T&T%' OR rs.store_name ILIKE '%TNT%' OR rs.store_name ILIKE '%t&t%')
ORDER BY rs.created_at DESC
LIMIT 50;

-- ---------------------------------------------------------------------------
-- 4. 该 T&T chain 下的 store_locations（合并后应同时包含美加地址，否则地址匹配会缺加拿大店）
-- ---------------------------------------------------------------------------
SELECT sl.id, sl.chain_id, sl.name AS location_name, sl.city, sl.state, sl.country_code
FROM store_locations sl
JOIN store_chains sc ON sc.id = sl.chain_id
WHERE sc.name ILIKE '%T&T%' OR sc.normalized_name ILIKE '%t&t%'
ORDER BY sl.country_code, sl.state, sl.name;

-- ---------------------------------------------------------------------------
-- 5. 该 T&T chain 下的 product_categorization_rules 与 products 数量
-- ---------------------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM product_categorization_rules r JOIN store_chains sc ON sc.id = r.store_chain_id WHERE sc.name ILIKE '%T&T%' OR sc.normalized_name ILIKE '%t&t%') AS rules_for_tnt,
  (SELECT COUNT(*) FROM products p JOIN store_chains sc ON sc.id = p.store_chain_id WHERE sc.name ILIKE '%T&T%' OR sc.normalized_name ILIKE '%t&t%') AS products_for_tnt;

-- ---------------------------------------------------------------------------
-- 6. 汇总：各表引用当前所有 store_chains 的情况（无孤儿时均为 0）
-- ---------------------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM record_summaries rs LEFT JOIN store_chains sc ON sc.id = rs.store_chain_id WHERE rs.store_chain_id IS NOT NULL AND sc.id IS NULL) AS orphan_in_record_summaries,
  (SELECT COUNT(*) FROM products p LEFT JOIN store_chains sc ON sc.id = p.store_chain_id WHERE p.store_chain_id IS NOT NULL AND sc.id IS NULL) AS orphan_in_products,
  (SELECT COUNT(*) FROM product_categorization_rules r LEFT JOIN store_chains sc ON sc.id = r.store_chain_id WHERE r.store_chain_id IS NOT NULL AND sc.id IS NULL) AS orphan_in_rules,
  (SELECT COUNT(*) FROM classification_review cr LEFT JOIN store_chains sc ON sc.id = cr.store_chain_id WHERE cr.store_chain_id IS NOT NULL AND sc.id IS NULL) AS orphan_in_classification_review,
  (SELECT COUNT(*) FROM store_candidates c LEFT JOIN store_chains sc ON sc.id = c.suggested_chain_id WHERE c.suggested_chain_id IS NOT NULL AND sc.id IS NULL) AS orphan_in_store_candidates;
