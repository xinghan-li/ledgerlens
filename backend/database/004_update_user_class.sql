-- ============================================
-- Update user_class to support new classes: super_admin, admin, premium, free
-- ============================================

-- Drop the old check constraint
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_user_class_check;

-- Add new check constraint with updated values
ALTER TABLE users ADD CONSTRAINT users_user_class_check 
  CHECK (user_class IN ('super_admin', 'admin', 'premium', 'free'));

-- Update comment
COMMENT ON COLUMN users.user_class IS 'User class: super_admin, admin, premium, free';

-- Note: Existing 'enterprise' users will need to be manually updated
-- If you have existing 'enterprise' users, run this first:
-- UPDATE users SET user_class = 'premium' WHERE user_class = 'enterprise';
