-- ============================================
-- 按条件清空部分小票记录（不删全部）
-- ============================================
-- 用途：测试时只删「最近上传的 N 条」或「某一天上传的」小票，保留其他数据。
-- 执行前：在下面「步骤 0」里二选一，改 N 或改日期，然后执行整个脚本。
--
-- 在 Supabase SQL Editor 中执行。
-- ============================================

BEGIN;

-- ========== 步骤 0：选择要删哪些 receipt（二选一，只保留一个取消注释） ==========

-- 方式 A：只删「最近上传的 N 条」（例如刚上传的 3 条）
CREATE TEMP TABLE receipt_ids_to_wipe AS
SELECT id FROM receipt_status
ORDER BY uploaded_at DESC NULLS LAST
LIMIT 3;   -- 改成你要删的条数，例如 3、5、10

-- 方式 B：只删「某一天上传的」小票（按 UTC 日期）。用这个时请注释掉上面「方式 A」整段。
-- CREATE TEMP TABLE receipt_ids_to_wipe AS
-- SELECT id FROM receipt_status
-- WHERE (uploaded_at AT TIME ZONE 'UTC')::date = '2026-02-18';   -- 改成你要删的日期

-- 可选：先看会删多少条
-- SELECT COUNT(*) AS receipts_to_wipe FROM receipt_ids_to_wipe;

-- 1. 解除对 receipt_status 的引用
UPDATE api_calls SET receipt_id = NULL WHERE receipt_id IN (SELECT id FROM receipt_ids_to_wipe);
UPDATE store_candidates SET receipt_id = NULL WHERE receipt_id IN (SELECT id FROM receipt_ids_to_wipe);

-- 2. 按 receipt 删子表（顺序：先子后主）
DELETE FROM record_items WHERE receipt_id IN (SELECT id FROM receipt_ids_to_wipe);
DELETE FROM record_summaries WHERE receipt_id IN (SELECT id FROM receipt_ids_to_wipe);
DELETE FROM receipt_processing_runs WHERE receipt_id IN (SELECT id FROM receipt_ids_to_wipe);
DELETE FROM receipt_status WHERE id IN (SELECT id FROM receipt_ids_to_wipe);

COMMIT;

-- 可选：执行后查看剩余条数
-- SELECT 'receipt_status' AS tbl, COUNT(*) FROM receipt_status
-- UNION ALL SELECT 'record_summaries', COUNT(*) FROM record_summaries
-- UNION ALL SELECT 'record_items', COUNT(*) FROM record_items;
