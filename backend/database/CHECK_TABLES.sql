-- ============================================
-- Check which tables exist in your database
-- ============================================
-- Run this in Supabase SQL Editor to see what you have
-- ============================================

SELECT 
  table_name,
  CASE 
    WHEN table_name IN ('users', 'receipts', 'receipt_processing_runs', 'store_chains', 'store_locations') 
      THEN '✅ Core (Migration 001)'
    WHEN table_name IN ('receipt_summaries', 'receipt_items') 
      THEN '📦 Migration 012'
    WHEN table_name = 'brands' 
      THEN '⚠️ Deprecated (014, run 020 to drop)'
    WHEN table_name = 'categories' 
      THEN '🗂️ Migration 015'
    WHEN table_name = 'products' 
      THEN '📦 Migration 016'
    WHEN table_name = 'price_snapshots' 
      THEN '💰 Migration 018'
    ELSE '❓ Other'
  END as migration,
  pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) as size
FROM information_schema.tables 
WHERE table_schema = 'public' 
  AND table_type = 'BASE TABLE'
ORDER BY table_name;
