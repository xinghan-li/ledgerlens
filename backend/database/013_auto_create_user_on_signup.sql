-- ============================================
-- Migration 013: 用户自动创建 + Firebase Auth 支持 + 注册编号
--
-- 已合并以下迁移（新库直接建到最终形态，无需再单独运行）：
--   042_firebase_uid_and_drop_auth_fk.sql   → users.firebase_uid; DROP FK to auth.users
--   047_users_registration_no_and_username.sql → users.registration_no 序列; user_name 唯一索引
-- ============================================

BEGIN;

-- ============================================
-- 1. 触发器：新用户注册时自动创建 users 行
-- ============================================
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.users (
    id, email, user_class, status, created_at, updated_at
  )
  VALUES (
    NEW.id, NEW.email, 'free', 'active', NOW(), NOW()
  )
  ON CONFLICT (id) DO UPDATE
  SET email = EXCLUDED.email, updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW
  EXECUTE FUNCTION handle_new_user();

-- 回填：补全已有 auth.users 但无 users 记录的情况
INSERT INTO public.users (id, email, user_class, status, created_at, updated_at)
SELECT au.id, au.email, 'free', 'active', au.created_at, NOW()
FROM auth.users au
LEFT JOIN public.users u ON au.id = u.id
WHERE u.id IS NULL
ON CONFLICT (id) DO NOTHING;

-- ============================================
-- 2. Firebase Auth 支持（来自 042）
--    - 增加 firebase_uid 列
--    - 删除 users.id 对 auth.users 的 FK（Firebase 用户无 auth.users 行）
-- ============================================
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS firebase_uid TEXT UNIQUE;

CREATE UNIQUE INDEX IF NOT EXISTS users_firebase_uid_key
  ON users (firebase_uid) WHERE firebase_uid IS NOT NULL;

COMMENT ON COLUMN users.firebase_uid IS 'Firebase Auth UID. Set when user signs in with Firebase.';

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_id_fkey;

COMMENT ON TABLE users IS 'User profile. id: internal UUID. firebase_uid: set for Firebase-authenticated users.';

-- ============================================
-- 3. 注册编号 + user_name 唯一（来自 047）
-- ============================================
CREATE SEQUENCE IF NOT EXISTS users_registration_no_seq
  START WITH 1
  INCREMENT BY 1
  NO MINVALUE
  MAXVALUE 999999999
  CACHE 1;

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS registration_no INTEGER;

-- 回填现有用户
WITH ordered AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY created_at ASC, id::text) AS rn
  FROM users
)
UPDATE users u
SET registration_no = ordered.rn
FROM ordered
WHERE u.id = ordered.id AND u.registration_no IS NULL;

ALTER TABLE users
  ALTER COLUMN registration_no SET DEFAULT nextval('users_registration_no_seq');
ALTER TABLE users
  ALTER COLUMN registration_no SET NOT NULL;

SELECT setval(
  'users_registration_no_seq',
  COALESCE((SELECT MAX(registration_no) FROM users), 0) + 1
);

CREATE UNIQUE INDEX IF NOT EXISTS users_registration_no_key ON users (registration_no);
COMMENT ON COLUMN users.registration_no IS '9-digit registration order (1=first user). Display zero-padded as 000000001.';

CREATE UNIQUE INDEX IF NOT EXISTS users_user_name_key
  ON users (user_name) WHERE user_name IS NOT NULL AND user_name <> '';
COMMENT ON COLUMN users.user_name IS 'User-chosen unique display name. Set from frontend.';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 013 completed: handle_new_user trigger; firebase_uid; FK dropped; registration_no; user_name unique';
END $$;
