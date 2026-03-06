-- âš ï¸ DEPRECATED - å·²åˆå¹¶åˆ° 001_schema_v2.sql
-- å†…å®¹ï¼šreceipt_status.file_hash åˆ— + ç´¢å¼•
-- æ–°åº“è¯·å‹¿å•ç‹¬è¿è¡Œæœ¬æ–‡ä»¶ã€‚
-- ============================================
-- ============================================
-- Add file_hash column to receipt_status table for duplicate detection
-- ============================================

-- Add file_hash column
ALTER TABLE receipt_status ADD COLUMN IF NOT EXISTS file_hash TEXT;

-- Create index for fast lookup
CREATE INDEX IF NOT EXISTS receipt_status_file_hash_idx ON receipt_status(file_hash);

-- Create unique index per user to prevent duplicate uploads
CREATE UNIQUE INDEX IF NOT EXISTS receipt_status_user_file_hash_idx ON receipt_status(user_id, file_hash) WHERE file_hash IS NOT NULL;

-- Add comment
COMMENT ON COLUMN receipt_status.file_hash IS 'SHA256 hash of the uploaded file for duplicate detection';

