-- ============================================
-- Migration 051: user_categories + user_item_category_overrides
--
-- 注意：本文件原来还包含 record_items.category_source ADD COLUMN 操作，
-- 该列已合并到 012_add_receipt_items_and_summaries.sql（建表时直接包含）。
--
-- 本文件现在只创建两个新表：
--   - user_categories（用户自定义分类树）
--   - user_item_category_overrides（用户逐条覆盖分类）
--
-- PREREQUISITES: 012 (record_items, users), 015 (categories)
-- ============================================

BEGIN;

-- ============================================
-- 1. user_categories（每用户自定义分类树）
-- ============================================
CREATE TABLE IF NOT EXISTS user_categories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  parent_id UUID REFERENCES user_categories(id) ON DELETE CASCADE,
  level INT NOT NULL CHECK (level >= 1 AND level <= 10),
  name TEXT NOT NULL,
  path TEXT,
  system_category_id UUID REFERENCES categories(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  CHECK (parent_id IS NULL OR level > 1)
);

CREATE INDEX IF NOT EXISTS user_categories_user_id_idx ON user_categories(user_id);
CREATE INDEX IF NOT EXISTS user_categories_parent_id_idx ON user_categories(parent_id) WHERE parent_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS user_categories_user_parent_name_key
  ON user_categories (user_id, COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), name);

CREATE TRIGGER user_categories_updated_at
  BEFORE UPDATE ON user_categories
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMENT ON TABLE user_categories IS 'Per-user custom category tree (e.g. Weekend Treats). Overrides may reference this or system categories.';
COMMENT ON COLUMN user_categories.system_category_id IS 'Optional: map this user category to a system category for aggregated analytics.';

-- ============================================
-- 2. user_item_category_overrides（每用户对每条记录的分类覆盖）
-- ============================================
CREATE TABLE IF NOT EXISTS user_item_category_overrides (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  record_item_id UUID NOT NULL REFERENCES record_items(id) ON DELETE CASCADE,
  category_id UUID REFERENCES categories(id) ON DELETE CASCADE,
  user_category_id UUID REFERENCES user_categories(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT user_item_category_overrides_one_target
    CHECK (
      (category_id IS NOT NULL AND user_category_id IS NULL) OR
      (category_id IS NULL AND user_category_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS user_item_category_overrides_user_item_key
  ON user_item_category_overrides (user_id, record_item_id);

CREATE INDEX IF NOT EXISTS user_item_category_overrides_user_id_idx ON user_item_category_overrides(user_id);
CREATE INDEX IF NOT EXISTS user_item_category_overrides_record_item_id_idx ON user_item_category_overrides(record_item_id);

CREATE TRIGGER user_item_category_overrides_updated_at
  BEFORE UPDATE ON user_item_category_overrides
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMENT ON TABLE user_item_category_overrides IS 'Per-user category override per receipt line item. Display: if override exists use it, else use record_items.category_id.';
COMMENT ON COLUMN user_item_category_overrides.category_id IS 'System category (categories.id) when user chose a system category.';
COMMENT ON COLUMN user_item_category_overrides.user_category_id IS 'User-defined category (user_categories.id) when user chose their own category.';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 051 completed: user_categories + user_item_category_overrides created (record_items.category_source already in 012)';
END $$;
