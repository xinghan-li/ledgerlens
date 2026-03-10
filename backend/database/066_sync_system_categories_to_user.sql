-- ============================================
-- Migration 066: sync_system_categories_to_user function
--
-- Problem: seed_user_default_categories is idempotent (skips if user already
-- has categories). When admin adds new system L1 categories, existing users
-- never receive them.
--
-- Solution: A new function that incrementally syncs any missing system L1
-- (and their L2/L3 children) to an existing user's category tree.
--
-- PREREQUISITES: 064 (user_categories with is_locked, seed function)
-- ============================================

BEGIN;

CREATE OR REPLACE FUNCTION sync_system_categories_to_user(p_user_id UUID)
RETURNS INT
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
    ON CONFLICT DO NOTHING
    RETURNING id INTO v_user_l1_id;

    IF v_user_l1_id IS NULL THEN
      SELECT id INTO v_user_l1_id
      FROM user_categories
      WHERE user_id = p_user_id AND system_category_id = v_sys_l1.id;
    END IF;

    IF v_user_l1_id IS NOT NULL THEN
      v_added := v_added + 1;

      -- Also seed L2 children under this new L1
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

        IF v_user_l2_id IS NOT NULL THEN
          v_added := v_added + 1;

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

            v_added := v_added + 1;
          END LOOP;
        END IF;
      END LOOP;
    END IF;
  END LOOP;

  RETURN v_added;
END;
$$;

COMMENT ON FUNCTION sync_system_categories_to_user(UUID) IS
  'Incrementally adds any missing system L1 categories (and their L2/L3) to an existing user. Called on each category tree load.';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 066 completed: sync_system_categories_to_user function created.';
END $$;
