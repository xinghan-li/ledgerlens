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
