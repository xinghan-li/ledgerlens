-- ============================================
-- Migration 062: Fix handle_new_user() to use user_class = 0 (smallint)
--
-- Problem: If 013 was applied after 053, handle_new_user() was overwritten with
--   user_class = 'free' (text). Column user_class is smallint after 053, so
--   INSERT fails with: invalid input syntax for type smallint: "free"
-- Fix: Ensure handle_new_user() inserts 0 (integer) for user_class.
-- ============================================

BEGIN;

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
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 062 completed: handle_new_user() now uses user_class = 0 (smallint).';
END $$;
