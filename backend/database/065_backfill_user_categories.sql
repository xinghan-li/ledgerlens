-- ============================================
-- Migration 065: Backfill user categories for existing users
--
-- 1. Seed user_categories for all existing users who have none
-- 2. Backfill record_items.user_category_id using resolve function
--
-- PREREQUISITES: 064 (seed/resolve functions, user_category_id column)
-- ============================================

BEGIN;

-- ============================================
-- 1. Seed default categories for all existing users
-- ============================================
DO $$
DECLARE
  v_user RECORD;
  v_seeded INT := 0;
BEGIN
  FOR v_user IN
    SELECT id FROM users
    WHERE id NOT IN (SELECT DISTINCT user_id FROM user_categories)
  LOOP
    PERFORM seed_user_default_categories(v_user.id);
    v_seeded := v_seeded + 1;
  END LOOP;
  RAISE NOTICE 'Seeded categories for % existing users', v_seeded;
END $$;

-- ============================================
-- 2. Backfill user_category_id for all existing record_items
-- ============================================
DO $$
DECLARE
  v_receipt RECORD;
  v_total_updated INT := 0;
  v_updated INT;
BEGIN
  FOR v_receipt IN
    SELECT DISTINCT receipt_id
    FROM record_items
    WHERE category_id IS NOT NULL AND user_category_id IS NULL
  LOOP
    v_updated := resolve_user_categories_for_receipt(v_receipt.receipt_id);
    v_total_updated := v_total_updated + v_updated;
  END LOOP;
  RAISE NOTICE 'Backfilled user_category_id for % record_items', v_total_updated;
END $$;

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 065 completed: existing users seeded + record_items.user_category_id backfilled.';
END $$;
