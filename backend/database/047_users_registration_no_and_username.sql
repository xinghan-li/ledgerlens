-- ============================================
-- Migration 047: registration_no + user_name unique
-- ============================================
-- 1. registration_no: 9-digit number = Nth registered user (1, 2, 3, ...), display as 000000001.
-- 2. user_name: existing column; add unique constraint for display/greeting (frontend can set).
--
-- Run after: 046
-- ============================================

BEGIN;

-- Sequence for registration order (1, 2, 3, ... up to 999999999)
CREATE SEQUENCE IF NOT EXISTS users_registration_no_seq
  START WITH 1
  INCREMENT BY 1
  NO MINVALUE
  MAXVALUE 999999999
  CACHE 1;

-- Add registration_no (nullable first for backfill)
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS registration_no INTEGER;

-- Backfill existing users by created_at order
WITH ordered AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY created_at ASC, id::text) AS rn
  FROM users
)
UPDATE users u
SET registration_no = ordered.rn
FROM ordered
WHERE u.id = ordered.id AND u.registration_no IS NULL;

-- Set default for new rows and make non-null
ALTER TABLE users
  ALTER COLUMN registration_no SET DEFAULT nextval('users_registration_no_seq');
ALTER TABLE users
  ALTER COLUMN registration_no SET NOT NULL;

-- Advance sequence past existing max so next insert gets correct number
SELECT setval(
  'users_registration_no_seq',
  COALESCE((SELECT MAX(registration_no) FROM users), 0) + 1
);

-- Unique 9-digit registration number
CREATE UNIQUE INDEX IF NOT EXISTS users_registration_no_key ON users (registration_no);
COMMENT ON COLUMN users.registration_no IS '9-digit registration order (1=first user). Display zero-padded as 000000001.';

-- user_name: unique for display/greeting (existing column)
CREATE UNIQUE INDEX IF NOT EXISTS users_user_name_key
  ON users (user_name) WHERE user_name IS NOT NULL AND user_name <> '';
COMMENT ON COLUMN users.user_name IS 'User-chosen unique display name for greeting and feedback. Set from frontend.';

COMMIT;
