# 新用户登录后 401 / “Session updated. Please try again.” 诊断

**现象**：新注册用户登录后，页面显示 “Session updated. Please try again.”，F12 里大量接口返回 `401 (Unauthorized)`（如 `/api/auth/me`、`/api/categories`、`/api/receipt/list`、`/api/analytics/...`），仪表盘一直处于 Loading。

**原因（最可能）**：  
后端用 **Firebase ID Token** 校验通过后，会调用 `get_or_create_user_id(firebase_uid, email)` 在 Supabase `public.users` 里按 `firebase_uid` 查找用户，找不到则按邮箱关联老用户或 **插入新用户**。  
若这一步失败（例如插入被 RLS 拒绝），后端不会返回 `user_id`，请求最终以 401 结束；前端收到 401 后展示 “Session updated. Please try again.”，且所有依赖鉴权的接口都 401，导致一直 Loading。

**常见根因**：  
生产环境（如 Cloud Run）**未配置 `SUPABASE_SERVICE_ROLE_KEY`**，后端退化为使用 `SUPABASE_ANON_KEY`。用 anon key 访问 Supabase 时受 RLS 限制，通常 **不允许** 向 `public.users` 插入新行，导致 `get_or_create_user_id` 在插入时抛错，鉴权失败 → 401。

**处理步骤**：

1. **确认生产环境已配置 Service Role Key**  
   在 Cloud Run（或当前部署环境）的环境变量 / Secret Manager 中设置：
   - `SUPABASE_SERVICE_ROLE_KEY` = Supabase 项目 Settings → API → `service_role` key  
   设置后需重新部署后端，确保进程读到新环境变量。

2. **临时补救（已有 Firebase 用户、尚未进 Supabase）**  
   在**本地**或能访问生产 DB 的机器上，配置好同一 Supabase 的 `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY` 以及 Firebase 的 `FIREBASE_SERVICE_ACCOUNT_JSON`（或 `FIREBASE_SERVICE_ACCOUNT_PATH`），然后执行：
   ```bash
   python -m backend.scripts.sync_firebase_users_to_supabase
   ```
   脚本会把 Firebase Auth 中的用户同步到 Supabase `public.users`（按 `firebase_uid` 查找或创建）。同步完成后，新用户再访问时会被“找到”而不是“插入”，即使之前 RLS 导致插入失败，此时也会正常通过鉴权。

3. **验证**  
   - 新用户再次登录并进入仪表盘，F12 中 `/api/auth/me` 等应返回 200。  
   - 若仍 401，查看后端日志中 “Firebase get_or_create_user_id failed” 或 “User creation/lookup failed” 的详细堆栈，根据报错再查 Supabase RLS / 表结构 / 权限。

**2026-03-09 更新：生产日志真实报错**

生产日志显示：`Firebase get_or_create_user_id failed: invalid input syntax for type smallint: "free"`。  
原因：迁移 053 已将 `users.user_class` 改为 `smallint`（0=free, 2=premium, 7=admin, 9=super_admin），但数据库里的触发器函数 `handle_new_user()` 若被迁移 013 覆盖过，会向 `user_class` 插入字符串 `'free'`，导致类型错误。该触发器在 **auth.users 有 INSERT 时** 会向 `public.users` 插入一行；Firebase 用户虽不经过 auth.users，但若曾先跑 053 再跑 013，或存在 Supabase Auth 注册路径，就会触发到旧版 `handle_new_user()`。

**处理**：在 Supabase SQL 编辑器中执行迁移 `062_fix_handle_new_user_user_class_smallint.sql`（或其中 `CREATE OR REPLACE FUNCTION public.handle_new_user() ... VALUES (..., 0, 'active', ...)` 部分），确保 `handle_new_user()` 写入的是整数 `0` 而非 `'free'`。执行后新用户创建应不再报错。

---

**代码与行为简述**：

- `backend/app/services/auth/jwt_auth.py`：先验证 Firebase token，再调用 `get_or_create_user_id`；若此处抛错或返回 `None`，会记录日志并返回 401。
- `backend/app/services/auth/firebase_auth.py`：`get_or_create_user_id` 会先按 `firebase_uid` 查 `users`，再按邮箱关联，最后 **insert** 新用户；insert 需后端使用 service role 才能绕过 RLS。
- `backend/app/services/database/supabase_client.py`：`_get_client()` 使用 `settings.supabase_service_role_key or settings.supabase_anon_key`；未配置 service role 时即为 anon，RLS 会拦截插入。

**前端**：  
“Session updated. Please try again.” 由收到 401 后的 `sessionRefreshedHint` 触发（见 `frontend/app/dashboard/page.tsx`），用于提示用户会话刷新/失败后重试。根本解决仍需后端鉴权成功（即上述 1/2）。
