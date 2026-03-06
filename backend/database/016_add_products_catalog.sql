-- ============================================
-- Migration 016: products 商品目录（最终形态）
--
-- 已合并以下迁移（新库直接建到最终形态，无需再单独运行）：
--   020_drop_brands_table.sql                         → 新库从未建 brands，直接无 brand_id
--   022_simplify_products.sql                         → 删除 variant_type/is_organic/aliases 等冗余列
--   027_size_quantity_unit_package.sql (products 部分) → size 拆分为 size_quantity/size_unit/package_type
--   029_size_quantity_2dec_and_products_store_chain.sql → size_quantity NUMERIC(12,2)；加 store_chain_id；唯一索引
--
-- PREREQUISITES: 015 (categories)
-- ============================================

BEGIN;

CREATE TABLE products (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  normalized_name TEXT NOT NULL,

  -- 商品规格（来自 027+029）
  size_quantity NUMERIC(12,2),
  size_unit TEXT,
  package_type TEXT,

  -- 关联门店（来自 029）
  store_chain_id UUID REFERENCES store_chains(id) ON DELETE SET NULL,

  category_id UUID REFERENCES categories(id) ON DELETE SET NULL,

  usage_count INT DEFAULT 0,
  last_seen_date DATE,

  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 索引
CREATE INDEX products_normalized_name_idx ON products(normalized_name);
CREATE INDEX products_category_idx ON products(category_id) WHERE category_id IS NOT NULL;
CREATE INDEX products_usage_count_idx ON products(usage_count DESC);
CREATE INDEX products_last_seen_idx ON products(last_seen_date DESC NULLS LAST);
CREATE INDEX products_store_chain_id_idx ON products(store_chain_id) WHERE store_chain_id IS NOT NULL;
CREATE INDEX products_normalized_name_trgm_idx ON products USING gin(normalized_name gin_trgm_ops);

-- 唯一索引：NULL store_chain_id 统一视为同一 bucket（来自 029）
CREATE UNIQUE INDEX products_unique_key ON products (
  normalized_name,
  COALESCE(size_quantity::text, ''),
  COALESCE(size_unit, ''),
  COALESCE(package_type, ''),
  COALESCE(store_chain_id, '00000000-0000-0000-0000-000000000000'::uuid)
);

CREATE TRIGGER products_updated_at
  BEFORE UPDATE ON products
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMENT ON TABLE products IS 'Unified product catalog for cross-receipt aggregation';
COMMENT ON COLUMN products.normalized_name IS 'Normalized product name (lowercase, singular) for matching';
COMMENT ON COLUMN products.size_quantity IS 'Numeric quantity, 2 decimal places (e.g. 3.50)';
COMMENT ON COLUMN products.size_unit IS 'Unit of measure (oz, ml, lb, ct, etc.)';
COMMENT ON COLUMN products.package_type IS 'Package type (bottle, box, bag, jar, can, etc.)';
COMMENT ON COLUMN products.store_chain_id IS 'Store chain for this product; NULL = global/legacy';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 016 completed: products table (final schema, incl. 020+022+027+029)';
END $$;
