-- ============================================
-- 检查 receipt_summaries 表的结构和数据
-- ============================================
-- 在 Supabase SQL Editor 中运行此脚本
-- ============================================

-- 1. 检查表是否存在
SELECT EXISTS (
    SELECT FROM information_schema.tables 
    WHERE table_schema = 'public' 
    AND table_name = 'receipt_summaries'
) as table_exists;

-- 2. 获取表结构（所有列）
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default,
    character_maximum_length
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'receipt_summaries'
ORDER BY ordinal_position;

-- 3. 获取所有索引
SELECT 
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = 'receipt_summaries'
ORDER BY indexname;

-- 4. 获取约束
SELECT 
    conname as constraint_name,
    contype as constraint_type,
    pg_get_constraintdef(oid) as definition
FROM pg_constraint
WHERE conrelid = 'receipt_summaries'::regclass
ORDER BY conname;

-- 5. 检查数据量
SELECT COUNT(*) as total_records FROM receipt_summaries;

-- 6. 检查有多少记录有 store_name 和 store_chain_id
SELECT 
    COUNT(*) as total,
    COUNT(store_name) as with_store_name,
    COUNT(store_chain_id) as with_store_chain_id,
    COUNT(*) - COUNT(store_name) as null_store_name,
    COUNT(*) - COUNT(store_chain_id) as null_store_chain_id
FROM receipt_summaries;

-- 7. 查看几条数据示例
SELECT 
    id,
    receipt_id,
    user_id,
    store_name,
    store_chain_id,
    store_location_id,
    subtotal,
    tax,
    total,
    currency,
    receipt_date,
    created_at
FROM receipt_summaries
ORDER BY created_at DESC
LIMIT 5;

-- 8. 检查 receipt_items 表是否存在
SELECT EXISTS (
    SELECT FROM information_schema.tables 
    WHERE table_schema = 'public' 
    AND table_name = 'receipt_items'
) as receipt_items_exists;

-- 9. 如果 receipt_items 存在，检查数据量
SELECT COUNT(*) as receipt_items_count FROM receipt_items;

-- 10. 对比：有多少 receipts 在 receipt_summaries 中
SELECT 
    (SELECT COUNT(DISTINCT id) FROM receipts) as total_receipts,
    (SELECT COUNT(*) FROM receipt_summaries) as receipts_in_summaries,
    (SELECT COUNT(DISTINCT receipt_id) FROM receipt_items) as receipts_with_items;
