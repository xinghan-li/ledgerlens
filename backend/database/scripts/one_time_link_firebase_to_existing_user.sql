-- 一次性：把「同邮箱的新 Firebase 用户」的 firebase_uid 绑到「旧用户」上，并清掉新用户的 firebase_uid
-- 使用场景：同一邮箱先用 Supabase 登录过，后改用 Firebase 登录时误建了新用户，导致旧用户 firebase_uid 仍为空
-- 使用前请把下面两处改成你的实际值：
--   your_email@example.com  → 你的邮箱（与 Firebase 一致）
--   7981c0a1-6017-4a8c-b551-3fb4118cd798  → 旧用户 id（表里 firebase_uid 为空、且有小票的那一行）

DO $$
DECLARE
  v_email     text := 'xinghan.sde@gmail.com';
  v_old_id    uuid := '7981c0a1-6017-4a8c-b551-3fb4118cd798';
  v_firebase  text;
  v_new_id    uuid;
BEGIN
  -- 找到「同邮箱且已有 firebase_uid」的那一行（即误建的新用户）
  SELECT id, firebase_uid INTO v_new_id, v_firebase
  FROM users
  WHERE LOWER(TRIM(email)) = LOWER(TRIM(v_email))
    AND firebase_uid IS NOT NULL
  LIMIT 1;

  IF v_firebase IS NULL THEN
    RAISE NOTICE '未找到同邮箱且 firebase_uid 非空的用户，可能已修复或邮箱不对。';
    RETURN;
  END IF;

  -- 把新用户的 firebase_uid 清空，避免唯一约束冲突
  UPDATE users SET firebase_uid = NULL WHERE id = v_new_id;
  -- 把该 firebase_uid 写到旧用户上
  UPDATE users SET firebase_uid = v_firebase WHERE id = v_old_id;

  RAISE NOTICE '已把 firebase_uid 从 % 移到旧用户 %', v_new_id, v_old_id;
END $$;
