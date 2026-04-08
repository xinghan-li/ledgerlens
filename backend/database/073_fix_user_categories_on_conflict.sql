-- ============================================
-- Migration 073: Fix ON CONFLICT for expression-based unique index
--
-- Problem: user_categories_user_parent_name_key is an expression-based
-- unique index: (user_id, COALESCE(parent_id, nil_uuid), name).
--
-- Both seed_user_default_categories and sync_system_categories_to_user use
-- `ON CONFLICT DO NOTHING` WITHOUT a conflict target. PostgreSQL's inference
-- engine can fail to match expression-based indexes when no target is given,
-- allowing the 23505 duplicate-key error to propagate instead of being
-- silently suppressed. This is worsened by the race condition where
-- concurrent API requests call both functions simultaneously for the same user.
--
-- Fix: replace `ON CONFLICT DO NOTHING` with an explicit conflict target that
-- matches the expression index exactly.
--
-- PREREQUISITES: 070 (current function definitions), 051 (index definition)
-- ============================================

BEGIN;

-- ============================================
-- 1. Fix seed_user_default_categories
--    (only seeds L1 since migration 070)
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

  -- Seed L1 only (locked copies of system L1 categories)
  v_sort := 0;
  FOR v_sys_l1 IN
    SELECT id, name, path FROM categories
    WHERE level = 1 AND is_active = TRUE
    ORDER BY name
  LOOP
    -- Explicit conflict target on the expression index prevents 23505 on
    -- concurrent calls (race condition) and when user already has a same-named
    -- category without a system_category_id link.
    INSERT INTO user_categories (
      user_id, parent_id, level, name, path,
      system_category_id, is_locked, sort_order
    ) VALUES (
      p_user_id, NULL, 1, v_sys_l1.name, v_sys_l1.path,
      v_sys_l1.id, TRUE, v_sort
    )
    ON CONFLICT (user_id, (COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid)), name)
    DO NOTHING;

    v_sort := v_sort + 10;
  END LOOP;
END;
$$;

COMMENT ON FUNCTION seed_user_default_categories(UUID) IS
  'Seeds a new user''s category tree from system L1 categories (locked). Idempotent; safe under concurrent calls.';

-- ============================================
-- 2. Fix sync_system_categories_to_user
--    (incremental sync of any new system L1s to existing users)
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

  -- Find current max sort_order among L1 so new ones go at the end
  SELECT COALESCE(MAX(sort_order), 0) INTO v_max_sort
  FROM user_categories
  WHERE user_id = p_user_id AND level = 1;

  -- For each active system L1 the user doesn't have yet (by system_category_id link)
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

    -- Explicit conflict target prevents 23505 when a same-named user category
    -- already exists without a system_category_id (e.g. user-created or
    -- orphaned from a renamed/deleted system category).
    INSERT INTO user_categories (
      user_id, parent_id, level, name, path,
      system_category_id, is_locked, sort_order
    ) VALUES (
      p_user_id, NULL, 1, v_sys_l1.name, v_sys_l1.path,
      v_sys_l1.id, TRUE, v_max_sort
    )
    ON CONFLICT (user_id, (COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid)), name)
    DO NOTHING;

    v_added := v_added + 1;
  END LOOP;

  -- Update names/paths for any renamed system L1s already linked to this user
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

COMMENT ON FUNCTION sync_system_categories_to_user(UUID) IS
  'Incrementally adds missing system L1 categories to an existing user. Called on each category tree load. Safe under concurrent calls.';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 073 completed: seed_user_default_categories and sync_system_categories_to_user updated with explicit ON CONFLICT targets to fix duplicate-key errors on expression-based unique index.';
END $$;
