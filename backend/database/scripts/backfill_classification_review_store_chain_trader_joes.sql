-- ============================================
-- 一次性：将 classification_review 的 store_chain_id 设为 Trader Joe's
-- ============================================
-- 执行前可先查：SELECT id, name, normalized_name FROM store_chains WHERE normalized_name = 'trader joe''s' OR name ILIKE 'Trader Joe%';
-- ============================================

UPDATE classification_review
SET store_chain_id = (
  SELECT id FROM store_chains
  WHERE normalized_name = 'trader joe''s'
     OR name ILIKE 'Trader Joe%'
  LIMIT 1
)
WHERE (
  SELECT id FROM store_chains
  WHERE normalized_name = 'trader joe''s'
     OR name ILIKE 'Trader Joe%'
  LIMIT 1
) IS NOT NULL;

-- 查看影响行数（可选）
-- SELECT COUNT(*) FROM classification_review WHERE store_chain_id = (SELECT id FROM store_chains WHERE normalized_name = 'trader joe''s' LIMIT 1);
