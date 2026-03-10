-- ============================================
-- Migration 064: User Category Tree Restructure
--
-- 重构分类系统：系统 L1 固定 + 用户自建 L2+ 树
--
-- Changes:
--   1. user_categories: 增加 sort_order, is_locked 列
--   2. record_items: 增加 user_category_id 列 (用户展示用)
--   3. 新建 seed_user_default_categories(p_user_id) 函数
--   4. 新建 resolve_system_to_user_category(p_user_id, p_system_category_id) 函数
--   5. 更新 handle_new_user() 触发器：新用户注册后自动 seed 分类
--   6. 更新 record_items_enriched 视图：增加用户分类信息
--   7. RLS policies for user_categories and user_item_category_overrides
--
-- PREREQUISITES: 051 (user_categories), 062 (handle_new_user), 017 (record_items_enriched)
-- ============================================

BEGIN;

-- ============================================
-- 1. user_categories: 新增 sort_order, is_locked
-- ============================================
ALTER TABLE user_categories
  ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS is_locked BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN user_categories.sort_order IS 'User-defined display order among siblings (0 = default).';
COMMENT ON COLUMN user_categories.is_locked IS 'Locked categories (L1 copies from system) cannot be renamed or deleted by users.';

-- 索引：用户分类树查询时按 path 排序，sort_order 辅助
CREATE INDEX IF NOT EXISTS user_categories_user_sort_idx
  ON user_categories (user_id, sort_order);

-- ============================================
-- 2. record_items: 新增 user_category_id
-- ============================================
ALTER TABLE record_items
  ADD COLUMN IF NOT EXISTS user_category_id UUID REFERENCES user_categories(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS record_items_user_category_id_idx
  ON record_items (user_category_id);

CREATE INDEX IF NOT EXISTS record_items_user_ucategory_idx
  ON record_items (user_id, user_category_id);

COMMENT ON COLUMN record_items.user_category_id IS 'Per-user category (user_categories.id). Used for UI display and user-facing analytics. May differ from category_id (system).';

-- ============================================
-- 3. seed_user_default_categories(p_user_id)
--    将系统 L1 + L2 + L3 seed 到用户分类树
--    L1: is_locked=true (不可改名/删除)
--    L2+: is_locked=false (用户可改)
-- ============================================
CREATE OR REPLACE FUNCTION seed_user_default_categories(p_user_id UUID)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_sys_l1 RECORD;
  v_sys_l2 RECORD;
  v_sys_l3 RECORD;
  v_user_l1_id UUID;
  v_user_l2_id UUID;
  v_sort INT;
BEGIN
  -- Skip if user already has categories (idempotent)
  IF EXISTS (SELECT 1 FROM user_categories WHERE user_id = p_user_id LIMIT 1) THEN
    RETURN;
  END IF;

  -- Seed L1 (locked copies of system categories)
  v_sort := 0;
  FOR v_sys_l1 IN
    SELECT id, name, path FROM categories
    WHERE level = 1 AND is_active = TRUE
    ORDER BY name
  LOOP
    INSERT INTO user_categories (
      user_id, parent_id, level, name, path,
      system_category_id, is_locked, sort_order
    ) VALUES (
      p_user_id, NULL, 1, v_sys_l1.name, v_sys_l1.path,
      v_sys_l1.id, TRUE, v_sort
    )
    ON CONFLICT DO NOTHING
    RETURNING id INTO v_user_l1_id;

    IF v_user_l1_id IS NULL THEN
      SELECT id INTO v_user_l1_id
      FROM user_categories
      WHERE user_id = p_user_id AND system_category_id = v_sys_l1.id;
    END IF;

    v_sort := v_sort + 10;

    -- Seed L2 under this L1
    FOR v_sys_l2 IN
      SELECT id, name, path FROM categories
      WHERE parent_id = v_sys_l1.id AND level = 2 AND is_active = TRUE
      ORDER BY name
    LOOP
      INSERT INTO user_categories (
        user_id, parent_id, level, name, path,
        system_category_id, is_locked, sort_order
      ) VALUES (
        p_user_id, v_user_l1_id, 2, v_sys_l2.name, v_sys_l2.path,
        v_sys_l2.id, FALSE, 0
      )
      ON CONFLICT DO NOTHING
      RETURNING id INTO v_user_l2_id;

      IF v_user_l2_id IS NULL THEN
        SELECT id INTO v_user_l2_id
        FROM user_categories
        WHERE user_id = p_user_id AND system_category_id = v_sys_l2.id;
      END IF;

      -- Seed L3 under this L2
      FOR v_sys_l3 IN
        SELECT id, name, path FROM categories
        WHERE parent_id = v_sys_l2.id AND level = 3 AND is_active = TRUE
        ORDER BY name
      LOOP
        INSERT INTO user_categories (
          user_id, parent_id, level, name, path,
          system_category_id, is_locked, sort_order
        ) VALUES (
          p_user_id, v_user_l2_id, 3, v_sys_l3.name, v_sys_l3.path,
          v_sys_l3.id, FALSE, 0
        )
        ON CONFLICT DO NOTHING;
      END LOOP;
    END LOOP;
  END LOOP;
END;
$$;

COMMENT ON FUNCTION seed_user_default_categories(UUID) IS
  'Seeds a new user''s category tree from system categories (L1 locked, L2+ editable). Idempotent.';

-- ============================================
-- 4. resolve_system_to_user_category(p_user_id, p_system_category_id)
--    Maps a system category_id to the user's corresponding user_category_id.
--    Falls back up the hierarchy if no direct match. Returns NULL only if user has no categories.
-- ============================================
CREATE OR REPLACE FUNCTION resolve_system_to_user_category(
  p_user_id UUID,
  p_system_category_id UUID
)
RETURNS UUID
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_user_cat_id UUID;
  v_sys_parent_id UUID;
  v_current_sys_id UUID;
  v_depth INT := 0;
BEGIN
  IF p_system_category_id IS NULL OR p_user_id IS NULL THEN
    RETURN NULL;
  END IF;

  v_current_sys_id := p_system_category_id;

  -- Walk up the system category tree until we find a matching user_category
  WHILE v_depth < 10 LOOP
    -- Try exact match at current level
    SELECT id INTO v_user_cat_id
    FROM user_categories
    WHERE user_id = p_user_id
      AND system_category_id = v_current_sys_id
    LIMIT 1;

    IF v_user_cat_id IS NOT NULL THEN
      RETURN v_user_cat_id;
    END IF;

    -- No match: walk up to parent
    SELECT parent_id INTO v_sys_parent_id
    FROM categories
    WHERE id = v_current_sys_id;

    IF v_sys_parent_id IS NULL THEN
      EXIT; -- Already at L1 with no match
    END IF;

    v_current_sys_id := v_sys_parent_id;
    v_depth := v_depth + 1;
  END LOOP;

  -- Last resort: return the user's first L1 category
  SELECT id INTO v_user_cat_id
  FROM user_categories
  WHERE user_id = p_user_id AND level = 1
  ORDER BY sort_order, name
  LIMIT 1;

  RETURN v_user_cat_id;
END;
$$;

COMMENT ON FUNCTION resolve_system_to_user_category(UUID, UUID) IS
  'Maps system category_id to user''s user_category_id. Walks up hierarchy to find nearest match.';

-- ============================================
-- 5. resolve_user_categories_for_receipt(p_receipt_id)
--    One-shot: fill user_category_id for all record_items in a receipt
--    that have category_id but no user_category_id yet.
-- ============================================
CREATE OR REPLACE FUNCTION resolve_user_categories_for_receipt(p_receipt_id UUID)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_updated INT := 0;
BEGIN
  UPDATE record_items ri
  SET user_category_id = resolve_system_to_user_category(ri.user_id, ri.category_id)
  WHERE ri.receipt_id = p_receipt_id
    AND ri.category_id IS NOT NULL
    AND ri.user_category_id IS NULL;

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated;
END;
$$;

COMMENT ON FUNCTION resolve_user_categories_for_receipt(UUID) IS
  'Fills user_category_id for all uncategorized items in a receipt using the resolve function.';

-- ============================================
-- 5b. handle_new_user(): 新用户注册后 seed 分类
-- ============================================
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.users (
    id, email, user_class, status, created_at, updated_at
  )
  VALUES (
    NEW.id, NEW.email, 0, 'active', NOW(), NOW()
  )
  ON CONFLICT (id) DO UPDATE
  SET email = EXCLUDED.email, updated_at = NOW();

  -- Seed default category tree for new user
  PERFORM seed_user_default_categories(NEW.id);

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================
-- 6. 更新 record_items_enriched 视图：增加用户分类信息
--    必须 DROP 再 CREATE，因为新增列改变了列顺序/名称，
--    CREATE OR REPLACE VIEW 不允许这种变更。
-- ============================================
DROP VIEW IF EXISTS record_items_enriched;
CREATE VIEW record_items_enriched AS
SELECT
  ri.id,
  ri.receipt_id,
  ri.user_id,
  ri.product_name AS raw_product_name,
  p.normalized_name AS product_normalized_name,
  p.size_quantity AS product_size_quantity,
  p.size_unit AS product_size_unit,
  p.package_type AS product_package_type,
  -- System categories (for admin analytics)
  c1.name AS category_l1,
  c2.name AS category_l2,
  c3.name AS category_l3,
  COALESCE(ri.category_id, p.category_id) AS category_id,
  -- User categories (for user-facing display)
  ri.user_category_id,
  uc.name AS user_category_name,
  uc.path AS user_category_path,
  uc.level AS user_category_level,
  -- User category hierarchy
  uc_parent.name AS user_category_parent_name,
  uc_l1.name AS user_category_l1_name,
  ri.quantity,
  ri.unit,
  ri.unit_price,
  ri.line_total,
  ri.on_sale,
  ri.discount_amount,
  ri.category_source,
  rs.store_chain_id,
  rs.store_location_id,
  sc.name AS store_chain_name,
  sl.name AS store_location_name,
  rs.receipt_date,
  ri.created_at
FROM record_items ri
LEFT JOIN products p ON ri.product_id = p.id
LEFT JOIN categories c3 ON COALESCE(ri.category_id, p.category_id) = c3.id
LEFT JOIN categories c2 ON c3.parent_id = c2.id
LEFT JOIN categories c1 ON c2.parent_id = c1.id
LEFT JOIN user_categories uc ON ri.user_category_id = uc.id
LEFT JOIN user_categories uc_parent ON uc.parent_id = uc_parent.id
LEFT JOIN user_categories uc_l1 ON (
  CASE
    WHEN uc.level = 1 THEN uc.id
    WHEN uc.level = 2 THEN uc.parent_id
    ELSE uc_parent.parent_id
  END
) = uc_l1.id
LEFT JOIN receipt_status r ON ri.receipt_id = r.id
LEFT JOIN record_summaries rs ON r.id = rs.receipt_id
LEFT JOIN store_chains sc ON rs.store_chain_id = sc.id
LEFT JOIN store_locations sl ON rs.store_location_id = sl.id;

COMMENT ON VIEW record_items_enriched IS 'Enriched record_items with product, system category, user category, and store info.';

-- ============================================
-- 7. RLS Policies for user_categories
-- ============================================
ALTER TABLE public.user_categories ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_categories_own"
  ON public.user_categories FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "user_categories_admin_read_all"
  ON public.user_categories FOR SELECT
  USING (public.is_admin());

-- ============================================
-- 8. RLS Policies for user_item_category_overrides
-- ============================================
ALTER TABLE public.user_item_category_overrides ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_item_category_overrides_own"
  ON public.user_item_category_overrides FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "user_item_category_overrides_admin_read_all"
  ON public.user_item_category_overrides FOR SELECT
  USING (public.is_admin());

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 064 completed: user_categories (sort_order, is_locked) + record_items (user_category_id) + seed/resolve functions + handle_new_user updated + record_items_enriched view updated + RLS policies added.';
END $$;
