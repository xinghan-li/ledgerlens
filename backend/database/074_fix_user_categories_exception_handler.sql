-- ============================================
-- Migration 074: Fix 23505 using EXCEPTION WHEN unique_violation
--
-- Problem: Migration 073 used explicit ON CONFLICT conflict targets, but
-- PostgreSQL's conflict inference for expression-based indexes is unreliable.
-- The unique index is:
--   (user_id, COALESCE(parent_id, nil_uuid), name)
-- This is an *expression* index, not a simple column index. PostgreSQL cannot
-- always infer it as a conflict target, so ON CONFLICT ... DO NOTHING
-- still throws 23505 in concurrent or edge-case scenarios.
--
-- Fix: Replace ON CONFLICT with PL/pgSQL EXCEPTION WHEN unique_violation.
-- This is the most reliable approach for expression-based unique indexes.
-- Each INSERT is wrapped in a BEGIN...EXCEPTION block that silently ignores
-- duplicate key violations (23505), making the functions truly idempotent
-- under any concurrency level.
--
-- PREREQUISITES: 073 (or 070)
-- ============================================

BEGIN;

-- ============================================
-- 1. seed_user_default_categories
--    Called for brand-new users (no categories yet).
-- ============================================
CREATE OR REPLACE FUNCTION seed_user_default_categories(p_user_id UUID)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_sys_l1 RECORD;
  v_sort   INT := 0;
BEGIN
  -- Skip entirely if user already has categories (fast idempotent guard)
  IF EXISTS (SELECT 1 FROM user_categories WHERE user_id = p_user_id LIMIT 1) THEN
    RETURN;
  END IF;

  FOR v_sys_l1 IN
    SELECT id, name, path FROM categories
    WHERE level = 1 AND is_active = TRUE
    ORDER BY name
  LOOP
    BEGIN
      INSERT INTO user_categories (
        user_id, parent_id, level, name, path,
        system_category_id, is_locked, sort_order
      ) VALUES (
        p_user_id, NULL, 1, v_sys_l1.name, v_sys_l1.path,
        v_sys_l1.id, TRUE, v_sort
      );
    EXCEPTION WHEN unique_violation THEN
      NULL; -- row already exists (concurrent insert or re-run), safe to ignore
    END;

    v_sort := v_sort + 10;
  END LOOP;
END;
$$;

COMMENT ON FUNCTION seed_user_default_categories(UUID) IS
  'Seeds a new user''s category tree from active system L1 categories (locked). '
  'Idempotent and safe under concurrent calls via EXCEPTION WHEN unique_violation.';

-- ============================================
-- 2. sync_system_categories_to_user
--    Called on every category tree load to add any new system L1s.
-- ============================================
CREATE OR REPLACE FUNCTION sync_system_categories_to_user(p_user_id UUID)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_sys_l1   RECORD;
  v_added    INT := 0;
  v_max_sort INT;
BEGIN
  -- If user has no categories at all, delegate to full seed
  IF NOT EXISTS (SELECT 1 FROM user_categories WHERE user_id = p_user_id LIMIT 1) THEN
    PERFORM seed_user_default_categories(p_user_id);
    SELECT COUNT(*) INTO v_added FROM user_categories WHERE user_id = p_user_id;
    RETURN v_added;
  END IF;

  -- Place new L1s after the current highest sort_order
  SELECT COALESCE(MAX(sort_order), 0) INTO v_max_sort
  FROM user_categories
  WHERE user_id = p_user_id AND level = 1;

  -- Only process system L1s not yet linked to this user
  FOR v_sys_l1 IN
    SELECT id, name, path
    FROM categories
    WHERE level = 1 AND is_active = TRUE
      AND id NOT IN (
        SELECT system_category_id
        FROM user_categories
        WHERE user_id = p_user_id AND system_category_id IS NOT NULL
      )
    ORDER BY name
  LOOP
    v_max_sort := v_max_sort + 10;

    BEGIN
      INSERT INTO user_categories (
        user_id, parent_id, level, name, path,
        system_category_id, is_locked, sort_order
      ) VALUES (
        p_user_id, NULL, 1, v_sys_l1.name, v_sys_l1.path,
        v_sys_l1.id, TRUE, v_max_sort
      );
      v_added := v_added + 1;
    EXCEPTION WHEN unique_violation THEN
      NULL; -- name collision with an existing user category, skip silently
    END;
  END LOOP;

  -- Propagate renames: update name/path in user_categories when system L1 was renamed
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
  'Incrementally adds missing system L1 categories to an existing user. '
  'Safe under concurrent calls via EXCEPTION WHEN unique_violation.';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 074 completed: seed_user_default_categories and '
               'sync_system_categories_to_user now use EXCEPTION WHEN unique_violation '
               'instead of ON CONFLICT, permanently fixing 23505 on expression-based indexes.';
END $$;
