-- ============================================
-- Migration 015: Add hierarchical categories table
-- ============================================
-- NOTE: Structure simplified by migration 021 (drops display_order, icon, color,
--       product_count; renames normalized_name→name, drops display name).
--
-- Purpose: Replace flat category_l1/l2/l3 columns with flexible tree structure
--
-- Benefits:
-- 1. Unlimited depth (not limited to 3 levels)
-- 2. Easy to add/remove categories
-- 3. Supports user-defined categories in future
-- 4. Consistent categorization across stores
--
-- IMPORTANT: Run this BEFORE 016 (products catalog)
-- ============================================

BEGIN;

-- Enable pg_trgm extension for fuzzy text search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- 1. Create categories table (tree structure)
-- ============================================
CREATE TABLE categories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id UUID REFERENCES categories(id) ON DELETE CASCADE,
  
  -- Category info
  level INT NOT NULL,             -- 1, 2, 3, 4...
  name TEXT NOT NULL,             -- Display name
  normalized_name TEXT NOT NULL,  -- Lowercase for matching
  
  -- Hierarchy path (for efficient queries)
  path TEXT,                      -- e.g., 'Grocery/Produce/Fruit'
  
  -- Display and ordering
  display_order INT DEFAULT 0,
  icon TEXT,                      -- Icon name or emoji
  color TEXT,                     -- Hex color for UI
  
  -- Metadata
  description TEXT,
  is_system BOOLEAN DEFAULT TRUE, -- System categories vs user-defined
  is_active BOOLEAN DEFAULT TRUE,
  
  -- Statistics (updated by triggers/jobs)
  product_count INT DEFAULT 0,
  
  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- Constraints
  CHECK (level >= 1 AND level <= 10),
  CHECK (parent_id IS NULL OR level > 1)
);

-- Indexes
CREATE INDEX categories_parent_id_idx ON categories(parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX categories_level_idx ON categories(level);
CREATE INDEX categories_normalized_name_idx ON categories(normalized_name);
CREATE INDEX categories_path_idx ON categories(path);
CREATE INDEX categories_active_idx ON categories(is_active) WHERE is_active = TRUE;

-- Text search
CREATE INDEX categories_name_trgm_idx ON categories USING gin(name gin_trgm_ops);

-- Trigger
CREATE TRIGGER categories_updated_at 
  BEFORE UPDATE ON categories
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Comments
COMMENT ON TABLE categories IS 'Hierarchical category tree for flexible product classification';
COMMENT ON COLUMN categories.level IS 'Depth in tree (1=root, 2=child of root, etc.)';
COMMENT ON COLUMN categories.path IS 'Full path from root for efficient ancestor queries';
COMMENT ON COLUMN categories.is_system IS 'TRUE for system categories, FALSE for user-defined';
COMMENT ON COLUMN categories.product_count IS 'Number of products in this category (includes descendants)';

-- ============================================
-- 2. Seed initial categories
-- ============================================

-- Level 1: Top categories
INSERT INTO categories (level, name, normalized_name, path, display_order, icon) VALUES
  (1, 'Grocery', 'grocery', 'Grocery', 1, '🛒'),
  (1, 'Household', 'household', 'Household', 2, '🏠'),
  (1, 'Personal Care', 'personal care', 'Personal Care', 3, '💄'),
  (1, 'Pet Supplies', 'pet supplies', 'Pet Supplies', 4, '🐾'),
  (1, 'Health', 'health', 'Health', 5, '💊'),
  (1, 'Other', 'other', 'Other', 99, '📦');

-- Level 2: Grocery subcategories
INSERT INTO categories (parent_id, level, name, normalized_name, path, display_order)
SELECT 
  c.id,
  2,
  subcategory.name,
  subcategory.normalized_name,
  'Grocery/' || subcategory.name,
  subcategory.display_order
FROM categories c
CROSS JOIN (VALUES
  ('Produce', 'produce', 1),
  ('Dairy', 'dairy', 2),
  ('Meat & Seafood', 'meat & seafood', 3),
  ('Bakery', 'bakery', 4),
  ('Frozen', 'frozen', 5),
  ('Pantry', 'pantry', 6),
  ('Beverages', 'beverages', 7),
  ('Snacks', 'snacks', 8),
  ('Deli', 'deli', 9)
) AS subcategory(name, normalized_name, display_order)
WHERE c.name = 'Grocery' AND c.level = 1;

-- Level 3: Produce subcategories
INSERT INTO categories (parent_id, level, name, normalized_name, path, display_order)
SELECT 
  c.id,
  3,
  subcategory.name,
  subcategory.normalized_name,
  'Grocery/Produce/' || subcategory.name,
  subcategory.display_order
FROM categories c
CROSS JOIN (VALUES
  ('Fruit', 'fruit', 1),
  ('Vegetables', 'vegetables', 2),
  ('Salad & Greens', 'salad & greens', 3),
  ('Herbs', 'herbs', 4)
) AS subcategory(name, normalized_name, display_order)
WHERE c.name = 'Produce' AND c.level = 2;

-- Level 3: Dairy subcategories
INSERT INTO categories (parent_id, level, name, normalized_name, path, display_order)
SELECT 
  c.id,
  3,
  subcategory.name,
  subcategory.normalized_name,
  'Grocery/Dairy/' || subcategory.name,
  subcategory.display_order
FROM categories c
CROSS JOIN (VALUES
  ('Milk', 'milk', 1),
  ('Cheese', 'cheese', 2),
  ('Yogurt', 'yogurt', 3),
  ('Butter & Eggs', 'butter & eggs', 4),
  ('Cream', 'cream', 5)
) AS subcategory(name, normalized_name, display_order)
WHERE c.name = 'Dairy' AND c.level = 2;

-- Level 3: Meat & Seafood subcategories
INSERT INTO categories (parent_id, level, name, normalized_name, path, display_order)
SELECT 
  c.id,
  3,
  subcategory.name,
  subcategory.normalized_name,
  'Grocery/Meat & Seafood/' || subcategory.name,
  subcategory.display_order
FROM categories c
CROSS JOIN (VALUES
  ('Beef', 'beef', 1),
  ('Chicken', 'chicken', 2),
  ('Pork', 'pork', 3),
  ('Fish', 'fish', 4),
  ('Seafood', 'seafood', 5)
) AS subcategory(name, normalized_name, display_order)
WHERE c.name = 'Meat & Seafood' AND c.level = 2;

-- Level 2: Household subcategories
INSERT INTO categories (parent_id, level, name, normalized_name, path, display_order)
SELECT 
  c.id,
  2,
  subcategory.name,
  subcategory.normalized_name,
  'Household/' || subcategory.name,
  subcategory.display_order
FROM categories c
CROSS JOIN (VALUES
  ('Cleaning', 'cleaning', 1),
  ('Paper Products', 'paper products', 2),
  ('Kitchen', 'kitchen', 3),
  ('Storage', 'storage', 4)
) AS subcategory(name, normalized_name, display_order)
WHERE c.name = 'Household' AND c.level = 1;

-- ============================================
-- 3. Create migration helper table
-- ============================================
-- Map old flat categories to new tree structure
CREATE TABLE category_migration_mapping (
  old_l1 TEXT,
  old_l2 TEXT,
  old_l3 TEXT,
  new_category_id UUID REFERENCES categories(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (old_l1, old_l2, old_l3)
);

-- Populate mapping for existing categories
INSERT INTO category_migration_mapping (old_l1, old_l2, old_l3, new_category_id)
SELECT 
  'Grocery' as old_l1,
  'Produce' as old_l2,
  'Fruit' as old_l3,
  id as new_category_id
FROM categories 
WHERE path = 'Grocery/Produce/Fruit';

INSERT INTO category_migration_mapping (old_l1, old_l2, old_l3, new_category_id)
SELECT 
  'Grocery' as old_l1,
  'Produce' as old_l2,
  'Vegetables' as old_l3,
  id as new_category_id
FROM categories 
WHERE path = 'Grocery/Produce/Vegetables';

INSERT INTO category_migration_mapping (old_l1, old_l2, old_l3, new_category_id)
SELECT 
  'Grocery' as old_l1,
  'Dairy' as old_l2,
  'Milk' as old_l3,
  id as new_category_id
FROM categories 
WHERE path = 'Grocery/Dairy/Milk';

INSERT INTO category_migration_mapping (old_l1, old_l2, old_l3, new_category_id)
SELECT 
  'Grocery' as old_l1,
  'Dairy' as old_l2,
  'Cheese' as old_l3,
  id as new_category_id
FROM categories 
WHERE path = 'Grocery/Dairy/Cheese';

-- Add more mappings as needed...

COMMENT ON TABLE category_migration_mapping IS 'Mapping from old flat categories to new tree structure for data migration';

-- ============================================
-- 4. Keep old columns for backward compatibility
-- ============================================
-- DO NOT DROP category_l1/l2/l3 columns from receipt_items yet
-- They will be deprecated gradually after backfill

-- Verification
DO $$
DECLARE
  category_count INTEGER;
  l1_count INTEGER;
  l2_count INTEGER;
  l3_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO category_count FROM categories;
  SELECT COUNT(*) INTO l1_count FROM categories WHERE level = 1;
  SELECT COUNT(*) INTO l2_count FROM categories WHERE level = 2;
  SELECT COUNT(*) INTO l3_count FROM categories WHERE level = 3;
  
  RAISE NOTICE 'Migration 015 completed successfully.';
  RAISE NOTICE 'Created % total categories', category_count;
  RAISE NOTICE '  Level 1 (top): % categories', l1_count;
  RAISE NOTICE '  Level 2: % categories', l2_count;
  RAISE NOTICE '  Level 3: % categories', l3_count;
END $$;

COMMIT;

-- ============================================
-- Helper queries
-- ============================================

-- View category tree
-- SELECT 
--   REPEAT('  ', level - 1) || name as category_tree,
--   level,
--   path
-- FROM categories
-- ORDER BY path;

-- Get all descendants of a category
-- WITH RECURSIVE category_tree AS (
--   SELECT id, parent_id, name, path, level
--   FROM categories
--   WHERE id = 'some-uuid'  -- Parent category
--   
--   UNION ALL
--   
--   SELECT c.id, c.parent_id, c.name, c.path, c.level
--   FROM categories c
--   INNER JOIN category_tree ct ON c.parent_id = ct.id
-- )
-- SELECT * FROM category_tree;
