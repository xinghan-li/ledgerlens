-- ============================================
-- Migration 028: Categories - 全部小写
-- ============================================
-- Purpose: 统一 name 和 path 为小写，避免大小写重复（如 Grocery vs grocery）
-- Run after: 021, 025
-- ============================================

BEGIN;

UPDATE categories SET name = lower(name) WHERE name IS NOT NULL;
UPDATE categories SET path = lower(path) WHERE path IS NOT NULL;

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 028 completed: categories name and path normalized to lowercase';
END $$;
