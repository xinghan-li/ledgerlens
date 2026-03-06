-- ============================================
-- Migration 015: categories 分类树（最终形态）
--
-- 已合并以下迁移（新库直接建到最终形态，无需再单独运行）：
--   021_simplify_categories.sql   → 删除 display_order/icon/color/product_count；normalized_name 改名为 name
--   028_categories_lowercase.sql  → name 和 path 全部小写
--
-- 本文件直接以最终字段建表，seed 数据直接使用小写。
-- ============================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- 1. categories 表（最终形态）
-- ============================================
CREATE TABLE categories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id UUID REFERENCES categories(id) ON DELETE CASCADE,

  level INT NOT NULL,
  name TEXT NOT NULL,     -- 小写，前端显示时做 title case
  path TEXT,              -- 小写，e.g. 'grocery/produce/fruit'

  description TEXT,
  is_system BOOLEAN DEFAULT TRUE,
  is_active BOOLEAN DEFAULT TRUE,

  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  CHECK (level >= 1 AND level <= 10),
  CHECK (parent_id IS NULL OR level > 1)
);

CREATE INDEX categories_parent_id_idx ON categories(parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX categories_level_idx ON categories(level);
CREATE INDEX categories_name_idx ON categories(name);
CREATE INDEX categories_path_idx ON categories(path);
CREATE INDEX categories_active_idx ON categories(is_active) WHERE is_active = TRUE;
CREATE INDEX categories_name_trgm_idx ON categories USING gin(name gin_trgm_ops);

CREATE TRIGGER categories_updated_at
  BEFORE UPDATE ON categories
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMENT ON TABLE categories IS 'Hierarchical category tree for product classification';
COMMENT ON COLUMN categories.name IS 'Category name (lowercase normalized; apply title case in frontend for display)';
COMMENT ON COLUMN categories.path IS 'Full path from root, lowercase, e.g. grocery/produce/fruit';

-- ============================================
-- 2. Seed：Level 1
-- ============================================
INSERT INTO categories (level, name, path) VALUES
  (1, 'grocery',       'grocery'),
  (1, 'household',     'household'),
  (1, 'personal care', 'personal care'),
  (1, 'pet supplies',  'pet supplies'),
  (1, 'health',        'health'),
  (1, 'other',         'other');

-- ============================================
-- 3. Seed：Level 2 — Grocery 子分类
-- ============================================
INSERT INTO categories (parent_id, level, name, path)
SELECT c.id, 2, sub.name, 'grocery/' || sub.name
FROM categories c
CROSS JOIN (VALUES
  ('produce'),
  ('dairy'),
  ('meat & seafood'),
  ('bakery'),
  ('frozen'),
  ('pantry'),
  ('beverages'),
  ('snacks'),
  ('deli')
) AS sub(name)
WHERE c.name = 'grocery' AND c.level = 1;

-- ============================================
-- 4. Seed：Level 2 — Household 子分类
-- ============================================
INSERT INTO categories (parent_id, level, name, path)
SELECT c.id, 2, sub.name, 'household/' || sub.name
FROM categories c
CROSS JOIN (VALUES
  ('cleaning'),
  ('paper products'),
  ('kitchen'),
  ('storage')
) AS sub(name)
WHERE c.name = 'household' AND c.level = 1;

-- ============================================
-- 5. Seed：Level 3 — Produce
-- ============================================
INSERT INTO categories (parent_id, level, name, path)
SELECT c.id, 3, sub.name, 'grocery/produce/' || sub.name
FROM categories c
CROSS JOIN (VALUES
  ('fruit'),
  ('vegetables'),
  ('salad & greens'),
  ('herbs')
) AS sub(name)
WHERE c.name = 'produce' AND c.level = 2;

-- ============================================
-- 6. Seed：Level 3 — Dairy
-- ============================================
INSERT INTO categories (parent_id, level, name, path)
SELECT c.id, 3, sub.name, 'grocery/dairy/' || sub.name
FROM categories c
CROSS JOIN (VALUES
  ('milk'),
  ('cheese'),
  ('yogurt'),
  ('butter & eggs'),
  ('cream')
) AS sub(name)
WHERE c.name = 'dairy' AND c.level = 2;

-- ============================================
-- 7. Seed：Level 3 — Meat & Seafood
-- ============================================
INSERT INTO categories (parent_id, level, name, path)
SELECT c.id, 3, sub.name, 'grocery/meat & seafood/' || sub.name
FROM categories c
CROSS JOIN (VALUES
  ('beef'),
  ('chicken'),
  ('pork'),
  ('fish'),
  ('seafood')
) AS sub(name)
WHERE c.name = 'meat & seafood' AND c.level = 2;

-- ============================================
-- 8. Seed：Level 3 — Frozen
-- ============================================
INSERT INTO categories (parent_id, level, name, path)
SELECT c.id, 3, sub.name, 'grocery/frozen/' || sub.name
FROM categories c
CROSS JOIN (VALUES
  ('frozen meals'),
  ('frozen vegetables'),
  ('frozen snacks'),
  ('ice cream')
) AS sub(name)
WHERE c.name = 'frozen' AND c.level = 2;

COMMIT;

DO $$
DECLARE
  total_count INT;
BEGIN
  SELECT COUNT(*) INTO total_count FROM categories;
  RAISE NOTICE 'Migration 015 completed: categories table (final schema, incl. 021+028). Total rows: %', total_count;
END $$;
