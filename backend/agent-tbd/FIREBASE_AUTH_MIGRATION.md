# Supabase Auth → Firebase Auth 迁移说明

## 已完成的代码改动

- **前端**：登录改为 Firebase Email Link（`sendSignInLinkToEmail`），回调页 `/auth/callback` 用 `signInWithEmailLink` 完成登录；Dashboard/Admin 等用 `onAuthStateChanged` + `getIdToken()` 调用后端 API；middleware 不再校验 session（由各 layout 负责）。
- **后端**：优先校验 Firebase ID token，通过 `firebase_uid` 在 `public.users` 中查找或创建用户，返回内部 `user_id`；未配置 Firebase 或 token 非 Firebase 时回退到原有 Supabase JWT 校验。
- **数据库**：迁移 `042_firebase_uid_and_drop_auth_fk.sql` 为 `users` 表增加 `firebase_uid`，并去掉对 `auth.users` 的外键，以便仅用 Firebase 的新用户插入。

## 你需要做的

### 1. Firebase Console

- 在 **Authentication → Settings → Authorized domains** 中加入你实际使用的域名（如 `localhost`、ngrok 域名、生产域名）。否则邮件里的登录链接会报错。
- （可选）在 **Authentication → Templates** 中调整邮件链接有效期等。

### 2. 前端环境变量（`frontend/.env.local`）

从 Firebase Console → Project settings → General → Your apps → 选择/创建 Web 应用，复制：

- `NEXT_PUBLIC_FIREBASE_API_KEY`
- `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`（如 `ledgerlens-484819.firebaseapp.com`）
- `NEXT_PUBLIC_FIREBASE_PROJECT_ID`（如 `ledgerlens-484819`）
- `NEXT_PUBLIC_FIREBASE_APP_ID`

### 3. 后端环境变量（`backend/.env`）

- `FIREBASE_SERVICE_ACCOUNT_PATH`：指向 Firebase 服务账号 JSON 的**绝对路径**（即你下载的 `ledgerlens-484819-firebase-adminsdk-....json`）。  
  或使用已有的 `GOOGLE_APPLICATION_CREDENTIALS` 指向同一文件，后端会优先用 `FIREBASE_SERVICE_ACCOUNT_PATH`，没有则用 `GOOGLE_APPLICATION_CREDENTIALS`。

### 4. 数据库迁移

在 Supabase SQL Editor（或你的 Postgres 客户端）中执行：

- `backend/database/042_firebase_uid_and_drop_auth_fk.sql`

若你的库里 `users.id` 的外键名不是 `users_id_fkey`，先执行 `\d users`（或查看表定义）确认约束名，再把迁移里的 `users_id_fkey` 改成实际名称后执行。

### 5. 安装依赖

- 前端：`cd frontend && npm install`（已加入 `firebase`）
- 后端：`pip install -r requirements.txt`（已加入 `firebase-admin`）

### 6. 现有用户（可选）

- 现有 Supabase 用户在**首次用 Firebase 登录**时，后端会按**邮箱**（先精确再忽略大小写）在 `users` 中查找并写入 `firebase_uid`，之后即按 Firebase 正常使用。
- 若希望保留 Supabase 登录一段时间，可不删 Supabase 配置；后端会先试 Firebase，失败再试 Supabase JWT。

### 7. 若已用同一邮箱登录却出现「新用户、小票没了、Data Analysis Unauthorized」

说明首次 Firebase 登录时邮箱匹配失败（例如大小写不一致），后端新建了一个用户，旧小票还在「旧 user_id」下。一次性修复：

1. 在 Supabase **SQL Editor** 里查两个用户（替换成你的邮箱）：
   ```sql
   SELECT id, email, firebase_uid,
          (SELECT COUNT(*) FROM record_summaries r WHERE r.user_id = u.id) AS receipt_count
   FROM users u
   WHERE LOWER(TRIM(email)) = LOWER('xinghan.sde@gmail.com');
   ```
2. 记下：**有 receipt_count 的那个**是旧用户（`old_id`），**有 firebase_uid 且 receipt_count=0** 的是这次新建的（`new_id`），以及旧用户对应的 `firebase_uid` 若为空，需要把当前 Firebase UID 绑到旧用户上。
3. 当前 Firebase UID：在第一步的查询结果里，**新用户**那一行的 `firebase_uid` 就是（或从 Firebase Console → Authentication → Users 里该邮箱用户的 **User UID** 复制）。
4. 把 Firebase 绑到旧用户、解绑新用户（替换下面的 UUID 和 Firebase UID）：
   ```sql
   UPDATE users SET firebase_uid = NULL WHERE id = '新用户UUID';
   UPDATE users SET firebase_uid = '当前Firebase的UID' WHERE id = '旧用户UUID';
   ```
5. 执行完后**退出登录再重新用邮件链接登录**，应会命中旧用户，小票和 Data Analysis 恢复正常。

## 登录流程（当前）

1. 用户打开登录页，输入邮箱，前端调用 `sendSignInLinkToEmail`，Firebase 发邮件。
2. 用户点邮件中的链接，打开 `/auth/callback?oobCode=...`，前端用 `signInWithEmailLink` 完成登录并跳转 `/dashboard`。
3. 前端请求 API 时在 Header 中带 `Authorization: Bearer <Firebase ID token>`，后端验证 token 后按 `firebase_uid` 查/建用户并返回内部 `user_id`。

## 未迁移或可后续处理的

- **dev-login**（`/dev-login?access_token=...`）：目前仍依赖后端签发 JWT；若需用 Firebase，可改为后端签发 Firebase 自定义 token，前端 `signInWithCustomToken`。
- **auth-debug**、**test-upload** 等如仍引用 Supabase Auth，可后续改为使用 Firebase 或移除。
