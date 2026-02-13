-- ============================================
-- Migration 021: Simplify categories table (MVP)
-- ============================================
-- Purpose: Remove unnecessary columns from categories, keep only MVP essentials.
--
-- Supersedes: Migration 015 (categories table structure)
-- Run after: 015, 016, 017, 018, 019, 020
--
-- 保留字段 | Kept:
--   id, parent_id, path, name(原normalized_name), description,
--   is_system, is_active, created_at, updated_at
--
-- 删除字段 | Removed (data discarded):
--   name(display)   - 可用 normalized_name title case 复现
--   display_order   - 前端可控制排序
--   icon            - UI 层 concern
--   color           - UI 层 concern
--   product_count   - 提前优化，MVP 不需要
-- ============================================

BEGIN;

-- 0. Drop views that depend on categories columns
DROP VIEW IF EXISTS receipt_items_enriched;

-- 1. Drop display name column (content can be reproduced from normalized_name via title case)
ALTER TABLE categories DROP COLUMN IF EXISTS name;

-- 2. Rename normalized_name to name (single source for category name)
ALTER TABLE categories RENAME COLUMN normalized_name TO name;

-- 3. Drop columns
ALTER TABLE categories DROP COLUMN IF EXISTS display_order;
ALTER TABLE categories DROP COLUMN IF EXISTS icon;
ALTER TABLE categories DROP COLUMN IF EXISTS color;
ALTER TABLE categories DROP COLUMN IF EXISTS product_count;

-- 4. Recreate indexes (old name/normalized_name indexes were dropped/renamed)
DROP INDEX IF EXISTS categories_normalized_name_idx;
CREATE INDEX categories_name_idx ON categories(name);
CREATE INDEX categories_name_trgm_idx ON categories USING gin(name gin_trgm_ops);

-- 5. Update comments
COMMENT ON COLUMN categories.name IS 'Category name (lowercase normalized, apply title case in frontend for display)';

-- 6. Recreate receipt_items_enriched (depends on categories.name)
CREATE OR REPLACE VIEW receipt_items_enriched AS
SELECT 
  ri.id,
  ri.receipt_id,
  ri.user_id,
  ri.product_name as raw_product_name,
  p.normalized_name as product_normalized_name,
  p.size as product_size,
  p.unit_type as product_unit_type,
  c1.name as category_l1,
  c2.name as category_l2,
  c3.name as category_l3,
  COALESCE(ri.category_id, p.category_id) as category_id,
  ri.quantity,
  ri.unit,
  ri.unit_price,
  ri.line_total,
  ri.on_sale,
  ri.discount_amount,
  rs.store_chain_id,
  rs.store_location_id,
  sc.name as store_chain_name,
  sl.name as store_location_name,
  rs.receipt_date,
  ri.created_at
FROM receipt_items ri
LEFT JOIN products p ON ri.product_id = p.id
LEFT JOIN categories c3 ON COALESCE(ri.category_id, p.category_id) = c3.id
LEFT JOIN categories c2 ON c3.parent_id = c2.id
LEFT JOIN categories c1 ON c2.parent_id = c1.id
LEFT JOIN receipts r ON ri.receipt_id = r.id
LEFT JOIN receipt_summaries rs ON r.id = rs.receipt_id
LEFT JOIN store_chains sc ON rs.store_chain_id = sc.id
LEFT JOIN store_locations sl ON rs.store_location_id = sl.id;

COMMENT ON VIEW receipt_items_enriched IS 'Enriched view of receipt_items with product, category, and store information';

COMMIT;

-- Verification
DO $$
BEGIN
  RAISE NOTICE 'Migration 021 completed: categories table simplified';
END $$;
