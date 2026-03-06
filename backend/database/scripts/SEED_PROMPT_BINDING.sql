-- ============================================================
-- SEED_PROMPT_BINDING.sql
-- 在 PRODUCTION 数据库 SQL Editor 里运行
-- 前提：prompt_library 已有 9 条数据
-- ============================================================

BEGIN;

-- 1. receipt_parse 用例（6 条 prompt 拼在一起）
INSERT INTO prompt_binding (prompt_key, library_id, scope, chain_id, location_id, priority, is_active)
SELECT
  'receipt_parse',
  id,
  'default',
  NULL,
  NULL,
  CASE key
    WHEN 'receipt_parse_base'          THEN 10
    WHEN 'package_price_discount'      THEN 20
    WHEN 'deposit_and_fee'             THEN 20
    WHEN 'membership_card'             THEN 20
    WHEN 'receipt_parse_user_template' THEN 5
    WHEN 'receipt_parse_schema'        THEN 5
    ELSE 50
  END,
  TRUE
FROM prompt_library
WHERE key IN (
  'receipt_parse_base',
  'package_price_discount',
  'deposit_and_fee',
  'membership_card',
  'receipt_parse_user_template',
  'receipt_parse_schema'
)
AND is_active = TRUE;

-- 2. classification
INSERT INTO prompt_binding (prompt_key, library_id, scope, chain_id, location_id, priority, is_active)
SELECT 'classification', id, 'default', NULL, NULL, 10, TRUE
FROM prompt_library
WHERE key = 'classification' AND is_active = TRUE;

-- 3. debug_ocr cascade
INSERT INTO prompt_binding (prompt_key, library_id, scope, priority, is_active)
SELECT 'receipt_parse_debug_ocr', id, 'default', 10, TRUE
FROM prompt_library
WHERE key = 'receipt_parse_debug_ocr' AND is_active = TRUE;

-- 4. debug_vision cascade
INSERT INTO prompt_binding (prompt_key, library_id, scope, priority, is_active)
SELECT 'receipt_parse_debug_vision', id, 'default', 10, TRUE
FROM prompt_library
WHERE key = 'receipt_parse_debug_vision' AND is_active = TRUE;

COMMIT;

-- 验证
SELECT prompt_key, scope, priority, is_active
FROM prompt_binding
ORDER BY prompt_key, priority;
