-- ============================================
-- 查询某日期的所有小票（用于排查重复）
-- 用法：把下面的 '2026-02-02' 改成你要查的日期
-- ============================================

-- 1) 2026-02-02 的所有小票：receipt_status id、上传时间、file_hash、小票上的门店/金额
SELECT
  rs.id AS receipt_id,
  r.uploaded_at,
  r.created_at,
  r.current_status,
  r.file_hash,
  s.store_name,
  s.receipt_date,
  s.total,
  s.subtotal,
  s.tax
FROM receipt_status r
JOIN record_summaries s ON s.receipt_id = r.id
WHERE s.receipt_date = '2026-02-02'
ORDER BY r.uploaded_at;

-- 2) 若上面有两条且 file_hash 相同 → 说明同一文件被记了两次（理论上唯一约束会拦，除非当时 file_hash 为空）
-- 3) 若 file_hash 不同或都为空 → 可能是上传了两次（两张图或同图传了两次且当时未算 hash）
