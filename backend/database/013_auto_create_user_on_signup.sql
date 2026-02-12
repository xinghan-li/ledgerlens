-- ============================================
-- Migration 013: Auto-create user record on signup
-- ============================================
-- Purpose: Automatically create a record in the public.users table
-- when a new user signs up via Supabase Auth (auth.users)
--
-- This ensures:
-- 1. Every auth.users record has a corresponding users record
-- 2. New users get default values (user_class='free', status='active')
-- 3. No manual intervention needed when users sign up
-- ============================================

BEGIN;

-- ============================================
-- 1. Create trigger function to handle new user signup
-- ============================================
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    -- Insert a new record into public.users table
    -- with default values when a new auth user is created
    INSERT INTO public.users (
        id,
        email,
        user_class,
        status,
        created_at,
        updated_at
    )
    VALUES (
        NEW.id,                    -- Same UUID as auth.users
        NEW.email,                 -- Copy email from auth.users
        'free',                    -- Default user class
        'active',                  -- Default status
        NOW(),
        NOW()
    )
    -- Handle case where user already exists (e.g., re-signup after deletion)
    ON CONFLICT (id) DO UPDATE
    SET
        email = EXCLUDED.email,
        updated_at = NOW();
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================
-- 2. Create trigger on auth.users
-- ============================================
-- Drop existing trigger if it exists
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;

-- Create trigger that fires after a new user is inserted
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION handle_new_user();

-- ============================================
-- 3. Backfill existing auth.users without corresponding users record
-- ============================================
-- This handles cases where auth.users already exist but users records don't
INSERT INTO public.users (id, email, user_class, status, created_at, updated_at)
SELECT 
    au.id,
    au.email,
    'free' as user_class,
    'active' as status,
    au.created_at,
    NOW() as updated_at
FROM auth.users au
LEFT JOIN public.users u ON au.id = u.id
WHERE u.id IS NULL
ON CONFLICT (id) DO NOTHING;

-- ============================================
-- 4. Verification
-- ============================================
DO $$
DECLARE
    auth_count INTEGER;
    user_count INTEGER;
BEGIN
    -- Count auth.users
    SELECT COUNT(*) INTO auth_count FROM auth.users;
    
    -- Count public.users
    SELECT COUNT(*) INTO user_count FROM public.users;
    
    RAISE NOTICE 'Migration 013 completed successfully.';
    RAISE NOTICE 'Auth users count: %', auth_count;
    RAISE NOTICE 'Public users count: %', user_count;
    
    IF auth_count = user_count THEN
        RAISE NOTICE '✓ All auth users have corresponding user records';
    ELSE
        RAISE WARNING '⚠ Mismatch: % auth users but % public users', auth_count, user_count;
    END IF;
END $$;

COMMIT;

-- ============================================
-- Testing the trigger (optional, run manually)
-- ============================================
-- To test, create a new user in Supabase Dashboard:
-- 1. Go to Authentication → Users
-- 2. Click "Add user" → "Create new user"
-- 3. Enter email and password
-- 4. Check public.users table - should have new record with user_class='free'

-- Verification query:
-- SELECT 
--     au.id,
--     au.email as auth_email,
--     au.created_at as auth_created,
--     u.email as user_email,
--     u.user_class,
--     u.status
-- FROM auth.users au
-- LEFT JOIN public.users u ON au.id = u.id
-- ORDER BY au.created_at DESC
-- LIMIT 10;

-- ============================================
-- How to manually set a user as admin (if needed)
-- ============================================
-- UPDATE users 
-- SET user_class = 'admin' 
-- WHERE email = 'admin@example.com';

-- Or for super_admin:
-- UPDATE users 
-- SET user_class = 'super_admin' 
-- WHERE email = 'superadmin@example.com';
