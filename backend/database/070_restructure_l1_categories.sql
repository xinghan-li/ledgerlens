-- ============================================
-- Migration 070: Restructure system L1 categories
--
-- New architecture: system/admin only manages L1. Users build L2+ themselves.
--
-- Steps:
--   1. Promote all L2/L3 category_id references to their L1 parent
--   2. Deactivate all L2/L3 system categories
--   3. Rename existing L1s: grocery→groceries, household→household supplies, health→medical
--   4. Add 11 new L1 categories
--   5. Update seed_user_default_categories to only seed L1 (no more L2/L3)
--   6. Sync new L1s to all existing users' user_categories
--
-- PREREQUISITES: 069 (latest), 064 (seed/sync functions), 015 (categories)
-- ============================================

BEGIN;

-- ============================================
-- 1. Promote all L2/L3 category_id references to their L1 parent
--    Walk up the tree to find L1 ancestor for each L2/L3 category
-- ============================================

-- Build a temp mapping: category_id → L1 ancestor id
CREATE TEMP TABLE _cat_to_l1 AS
WITH RECURSIVE ancestors AS (
  -- Start from every category
  SELECT id AS original_id, id, parent_id, level
  FROM categories
  UNION ALL
  SELECT a.original_id, c.id, c.parent_id, c.level
  FROM ancestors a
  JOIN categories c ON c.id = a.parent_id
  WHERE a.level > 1
)
SELECT original_id, id AS l1_id
FROM ancestors
WHERE level = 1;

-- Update record_items: promote L2/L3 → L1
UPDATE record_items
SET category_id = m.l1_id
FROM _cat_to_l1 m
WHERE record_items.category_id = m.original_id
  AND m.original_id != m.l1_id;

-- Update products: promote L2/L3 → L1
UPDATE products
SET category_id = m.l1_id
FROM _cat_to_l1 m
WHERE products.category_id = m.original_id
  AND m.original_id != m.l1_id;

-- Update product_categorization_rules: promote L2/L3 → L1
UPDATE product_categorization_rules
SET category_id = m.l1_id
FROM _cat_to_l1 m
WHERE product_categorization_rules.category_id = m.original_id
  AND m.original_id != m.l1_id;

-- Update classification_review: promote L2/L3 → L1
UPDATE classification_review
SET category_id = m.l1_id
FROM _cat_to_l1 m
WHERE classification_review.category_id = m.original_id
  AND m.original_id != m.l1_id;

DROP TABLE _cat_to_l1;

-- ============================================
-- 2. Deactivate all L2/L3 system categories
-- ============================================
UPDATE categories SET is_active = FALSE WHERE level > 1;

-- ============================================
-- 3. Rename existing L1 categories
-- ============================================
UPDATE categories SET name = 'groceries',          path = 'groceries'          WHERE name = 'grocery'   AND level = 1;
UPDATE categories SET name = 'household supplies', path = 'household supplies' WHERE name = 'household' AND level = 1;
UPDATE categories SET name = 'medical',            path = 'medical'            WHERE name = 'health'    AND level = 1;
-- personal care, pet supplies, other — keep as-is

-- ============================================
-- 4. Add 11 new L1 categories
-- ============================================
INSERT INTO categories (level, name, path, is_system, is_active)
VALUES
  (1, 'snacks & beverages',  'snacks & beverages',  TRUE, TRUE),
  (1, 'restaurants',         'restaurants',          TRUE, TRUE),
  (1, 'home & furniture',    'home & furniture',     TRUE, TRUE),
  (1, 'electronics',         'electronics',          TRUE, TRUE),
  (1, 'clothing & apparel',  'clothing & apparel',   TRUE, TRUE),
  (1, 'transportation',      'transportation',       TRUE, TRUE),
  (1, 'education & office',  'education & office',   TRUE, TRUE),
  (1, 'entertainment',       'entertainment',        TRUE, TRUE),
  (1, 'services & fees',     'services & fees',      TRUE, TRUE),
  (1, 'childcare',           'childcare',            TRUE, TRUE),
  (1, 'garden',              'garden',               TRUE, TRUE)
ON CONFLICT DO NOTHING;

-- ============================================
-- 5. Update seed_user_default_categories: only seed L1 (no L2/L3)
-- ============================================
CREATE OR REPLACE FUNCTION seed_user_default_categories(p_user_id UUID)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_sys_l1 RECORD;
  v_sort INT;
BEGIN
  -- Skip if user already has categories (idempotent)
  IF EXISTS (SELECT 1 FROM user_categories WHERE user_id = p_user_id LIMIT 1) THEN
    RETURN;
  END IF;

  -- Seed L1 only (locked copies of system categories)
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
    ON CONFLICT DO NOTHING;

    v_sort := v_sort + 10;
  END LOOP;
END;
$$;

-- ============================================
-- 6. Update sync_system_categories_to_user: only sync L1 (no L2/L3)
-- ============================================
CREATE OR REPLACE FUNCTION sync_system_categories_to_user(p_user_id UUID)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_sys_l1 RECORD;
  v_added INT := 0;
  v_max_sort INT;
BEGIN
  -- If user has no categories at all, do a full seed instead
  IF NOT EXISTS (SELECT 1 FROM user_categories WHERE user_id = p_user_id LIMIT 1) THEN
    PERFORM seed_user_default_categories(p_user_id);
    SELECT COUNT(*) INTO v_added FROM user_categories WHERE user_id = p_user_id;
    RETURN v_added;
  END IF;

  -- Find the current max sort_order among L1 so new ones go at the end
  SELECT COALESCE(MAX(sort_order), 0) INTO v_max_sort
  FROM user_categories
  WHERE user_id = p_user_id AND level = 1;

  -- For each active system L1 that the user doesn't have yet
  FOR v_sys_l1 IN
    SELECT id, name, path
    FROM categories
    WHERE level = 1 AND is_active = TRUE
      AND id NOT IN (
        SELECT system_category_id FROM user_categories
        WHERE user_id = p_user_id AND system_category_id IS NOT NULL
      )
    ORDER BY name
  LOOP
    v_max_sort := v_max_sort + 10;

    INSERT INTO user_categories (
      user_id, parent_id, level, name, path,
      system_category_id, is_locked, sort_order
    ) VALUES (
      p_user_id, NULL, 1, v_sys_l1.name, v_sys_l1.path,
      v_sys_l1.id, TRUE, v_max_sort
    )
    ON CONFLICT DO NOTHING;

    v_added := v_added + 1;
  END LOOP;

  -- Also update renamed L1s in user_categories (if system_category_id matches but name differs)
  UPDATE user_categories uc
  SET name = c.name, path = c.path
  FROM categories c
  WHERE uc.system_category_id = c.id
    AND uc.is_locked = TRUE
    AND uc.level = 1
    AND (uc.name != c.name OR uc.path != c.path);

  RETURN v_added;
END;
$$;

-- ============================================
-- 7. Backfill: sync new + renamed L1s to ALL existing users
-- ============================================
DO $$
DECLARE
  v_user RECORD;
  v_synced INT := 0;
  v_total_added INT := 0;
  v_added INT;
BEGIN
  FOR v_user IN
    SELECT DISTINCT user_id AS id FROM user_categories
  LOOP
    v_added := sync_system_categories_to_user(v_user.id);
    v_total_added := v_total_added + v_added;
    v_synced := v_synced + 1;
  END LOOP;
  RAISE NOTICE 'Synced L1 categories to % existing users, added % total new user_categories', v_synced, v_total_added;
END $$;

COMMIT;

DO $$
DECLARE
  v_l1_count INT;
BEGIN
  SELECT COUNT(*) INTO v_l1_count FROM categories WHERE level = 1 AND is_active = TRUE;
  RAISE NOTICE 'Migration 070 completed: % active L1 categories. L2/L3 deactivated. All users synced.', v_l1_count;
END $$;
