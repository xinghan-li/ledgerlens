-- ============================================
-- 清空所有小票相关记录（保留 users, store_chains, store_locations, products, categories 等）
-- ============================================
-- 用途：改过 schema/逻辑后，历史小票数据不一致时，一次性删掉所有小票链路数据。
-- 执行后：receipt_status / record_summaries / record_items / receipt_processing_runs 全空；
--         api_calls.receipt_id、store_candidates.receipt_id 置空；
--         classification_review 中 source_record_item_id 会因 record_items 被删而置空（ON DELETE SET NULL）。
--
-- 在 Supabase SQL Editor 中执行前请确认无误。
-- ============================================

BEGIN;

-- 1. 解除对 receipt_status 的引用（这些表没有 ON DELETE CASCADE）
UPDATE api_calls SET receipt_id = NULL WHERE receipt_id IS NOT NULL;
UPDATE store_candidates SET receipt_id = NULL WHERE receipt_id IS NOT NULL;

-- 2. 删除所有小票主表；级联会删掉：
--    - receipt_processing_runs
--    - record_summaries
--    - record_items
DELETE FROM receipt_status;

-- classification_review：source_record_item_id 引用 record_items，为 ON DELETE SET NULL，
-- 上面删除 record_items 后会自动置空，无需单独处理。
-- 若希望连 classification_review 的待审核行也清空，可取消下面注释：
-- DELETE FROM classification_review;

COMMIT;

-- 可选：查看当前行数
-- SELECT 'receipt_status' AS tbl, COUNT(*) FROM receipt_status
-- UNION ALL SELECT 'record_summaries', COUNT(*) FROM record_summaries
-- UNION ALL SELECT 'record_items', COUNT(*) FROM record_items
-- UNION ALL SELECT 'receipt_processing_runs', COUNT(*) FROM receipt_processing_runs;
