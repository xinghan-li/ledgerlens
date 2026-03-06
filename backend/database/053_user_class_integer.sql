-- ============================================
-- Migration 053: user_class TEXT → SMALLINT (numeric tiers)
--
-- Tier mapping: 0=free, 2=premium, 7=admin, 9=super_admin.
-- New users default to 0.
-- ============================================

BEGIN;

-- 1. Add new column
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS user_class_new smallint NOT NULL DEFAULT 0;

-- 2. Drop old constraint and column, rename new column
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_user_class_check;
ALTER TABLE public.users DROP COLUMN IF EXISTS user_class;
ALTER TABLE public.users RENAME COLUMN user_class_new TO user_class;

-- 3. Default and constraint
ALTER TABLE public.users ALTER COLUMN user_class SET DEFAULT 0;
ALTER TABLE public.users ADD CONSTRAINT users_user_class_range
  CHECK (user_class >= 0 AND user_class <= 99);

COMMENT ON COLUMN public.users.user_class IS 'User tier: 0=free, 2=premium, 7=admin, 9=super_admin. Higher = more privilege.';

-- 4. Trigger: new signups get user_class = 0
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

-- 5. RLS: is_admin() for integer user_class
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.users
    WHERE id = auth.uid() AND user_class IN (9, 7)
  );
$$;

COMMENT ON FUNCTION public.is_admin() IS 'True if current user is super_admin (9) or admin (7).';

-- 6. Policy: admin/super_admin may update any user (e.g. user_class for User Management)
DROP POLICY IF EXISTS "users_admin_update" ON public.users;
CREATE POLICY "users_admin_update"
  ON public.users FOR UPDATE
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 053 completed: user_class is now smallint (0=free, 2=premium, 7=admin, 9=super_admin). New users default 0.';
END $$;
