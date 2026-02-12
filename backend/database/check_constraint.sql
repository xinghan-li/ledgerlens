-- ============================================
-- Check receipts table constraint definition
-- ============================================
-- Run this in Supabase SQL Editor to check constraint

-- 1. Check constraint definition
SELECT 
    conname AS constraint_name,
    pg_get_constraintdef(oid) AS constraint_definition
FROM pg_constraint
WHERE conrelid = 'receipts'::regclass
AND conname = 'receipts_current_stage_check';

-- 2. Check all constraints on receipts table
SELECT 
    conname AS constraint_name,
    contype AS constraint_type,
    pg_get_constraintdef(oid) AS constraint_definition
FROM pg_constraint
WHERE conrelid = 'receipts'::regclass
ORDER BY contype, conname;

-- 3. Check receipts table structure
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'receipts'
AND table_schema = 'public'
ORDER BY ordinal_position;

-- Expected constraint definition:
-- CHECK (current_stage IN ('ocr', 'llm_primary', 'llm_fallback', 'manual'))
