-- ============================================
-- 诊断 store_candidates 与 store_locations 的关系
-- 预期：已在 store_locations 匹配到的店（含 fuzzy 1-2 字母）不应出现在 store_candidates
-- ============================================

-- 1) store_candidates 总览：按 status、按 normalized_name 数量
SELECT '1_store_candidates_by_status' AS report;
SELECT status, COUNT(*) AS cnt
FROM store_candidates
GROUP BY status
ORDER BY status;

-- 2) 重复的 normalized_name（同一店名多条 candidate）
SELECT '2_duplicate_normalized_names' AS report;
SELECT normalized_name, COUNT(*) AS cnt, array_agg(id::text) AS candidate_ids
FROM store_candidates
WHERE status = 'pending'
GROUP BY normalized_name
HAVING COUNT(*) > 1
ORDER BY cnt DESC
LIMIT 30;

-- 3) 有 store_candidate 的 receipt，其 record_summaries 是否已有 store_location_id（不应同时存在）
--    若 summary 已有 store_location_id 说明该小票已匹配到 store_locations，不应再在 store_candidates
SELECT '3_receipts_with_candidate_but_has_location' AS report;
SELECT sc.id AS candidate_id, sc.receipt_id, sc.normalized_name,
       rs.store_chain_id, rs.store_location_id,
       sl.name AS location_name, sl.chain_name
FROM store_candidates sc
JOIN record_summaries rs ON rs.receipt_id = sc.receipt_id
LEFT JOIN store_locations sl ON sl.id = rs.store_location_id
WHERE rs.store_location_id IS NOT NULL
ORDER BY sc.created_at DESC
LIMIT 50;

-- 4) 数量汇总：有 candidate 且 summary 已有 store_location_id 的条数（这些本不该进 candidate）
SELECT '4_count_should_not_be_candidates' AS report;
SELECT COUNT(*) AS receipts_with_location_but_also_candidate
FROM store_candidates sc
JOIN record_summaries rs ON rs.receipt_id = sc.receipt_id
WHERE rs.store_location_id IS NOT NULL;

-- 5) store_candidates 中有 suggested_location_id 的（说明匹配到了建议门店，但仍被当成 candidate）
SELECT '5_candidates_with_suggested_location' AS report;
SELECT id, receipt_id, raw_name, normalized_name, suggested_chain_id, suggested_location_id, status, source
FROM store_candidates
WHERE suggested_location_id IS NOT NULL
ORDER BY created_at DESC
LIMIT 30;

-- 6) 按 source 统计 store_candidates
SELECT '6_candidates_by_source' AS report;
SELECT source, status, COUNT(*) AS cnt
FROM store_candidates
GROUP BY source, status
ORDER BY source, status;

-- 7) 有 receipt_id 的 candidate 中，对应 receipt 的 pipeline 与 run 的 _metadata 是否含 chain_id/location_id（抽样）
--    (需要 output_payload 里有 _metadata.chain_id / _metadata.location_id 时 categorizer 才不建 candidate)
SELECT '7_sample_run_metadata' AS report;
SELECT rpr.receipt_id, rpr.stage,
       rpr.output_payload->'_metadata'->>'chain_id' AS meta_chain_id,
       rpr.output_payload->'_metadata'->>'location_id' AS meta_location_id,
       rpr.output_payload->'_metadata'->'address_correction'->>'chain_id' AS addr_chain_id,
       rpr.output_payload->'_metadata'->'address_correction'->>'location_id' AS addr_location_id
FROM receipt_processing_runs rpr
WHERE rpr.receipt_id IN (SELECT receipt_id FROM store_candidates WHERE receipt_id IS NOT NULL LIMIT 20)
  AND rpr.status = 'pass'
ORDER BY rpr.receipt_id, rpr.created_at DESC;
