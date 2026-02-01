-- ============================================
-- Add file_hash column to receipts table for duplicate detection
-- ============================================

-- Add file_hash column
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS file_hash TEXT;

-- Create index for fast lookup
CREATE INDEX IF NOT EXISTS receipts_file_hash_idx ON receipts(file_hash);

-- Create unique index per user to prevent duplicate uploads
-- This allows same file to be uploaded by different users, but prevents same user from uploading same file twice
CREATE UNIQUE INDEX IF NOT EXISTS receipts_user_file_hash_idx ON receipts(user_id, file_hash) WHERE file_hash IS NOT NULL;

-- Add comment
COMMENT ON COLUMN receipts.file_hash IS 'SHA256 hash of the uploaded file for duplicate detection';
