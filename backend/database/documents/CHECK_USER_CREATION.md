# 新用户创建机制说明

## 🎯 问题

之前的数据库设计中，`users` 表引用了 `auth.users`，但**没有自动创建机制**：

```sql
create table users (
  id uuid primary key references auth.users(id) on delete cascade,
  user_class text default 'free',  -- 默认值
  ...
);
```

**问题：**
- 在 Supabase Dashboard 创建新用户 → 只创建 `auth.users` 记录
- `public.users` 表**不会**自动创建对应记录
- 导致后端请求失败（外键约束错误）

## ✅ 解决方案

### Migration 013: 自动创建用户触发器

运行 `013_auto_create_user_on_signup.sql` 后：

```
新用户在 Supabase Auth 注册
         ↓
auth.users 表插入新记录
         ↓
触发器: on_auth_user_created
         ↓
自动在 public.users 创建记录
         ├─ user_class: 'free' (默认)
         ├─ status: 'active' (默认)
         └─ email: 从 auth.users 复制
```

## 📋 功能说明

### 1. 自动创建默认用户

**触发时机：** 每当新用户在 Supabase Auth 注册时

**默认值：**
```json
{
  "user_class": "free",      // 免费用户
  "status": "active",        // 激活状态
  "email": "user@email.com"  // 从 auth.users 复制
}
```

### 2. 处理重复情况

如果 `users` 记录已存在（例如用户删除后重新注册），触发器会：
- 更新邮箱（如果变化）
- 更新 `updated_at` 时间戳
- 不会报错

### 3. 回填历史用户

Migration 会自动检查并回填：
- 查找 `auth.users` 中存在但 `public.users` 中不存在的用户
- 自动创建缺失的记录
- 使用默认值 `user_class='free'`

## 🧪 如何测试

### 方法 1: Supabase Dashboard

1. 登录 Supabase Dashboard
2. 进入 **Authentication → Users**
3. 点击 **"Add user" → "Create new user"**
4. 输入邮箱和密码
5. 创建用户

**验证：**
```sql
-- 检查新用户是否自动创建
SELECT 
    au.id,
    au.email as auth_email,
    u.email as user_email,
    u.user_class,
    u.status
FROM auth.users au
LEFT JOIN public.users u ON au.id = u.id
ORDER BY au.created_at DESC
LIMIT 5;
```

**预期结果：**
- ✅ 每个 `auth.users` 都有对应的 `public.users` 记录
- ✅ 新用户的 `user_class` 是 `'free'`
- ✅ 新用户的 `status` 是 `'active'`

### 方法 2: Magic Link 注册（前端）

当用户通过前端的 Magic Link 注册时：

```typescript
// 用户第一次使用 Magic Link 登录
await supabase.auth.signInWithOtp({ email: 'newuser@example.com' })

// Supabase 自动：
// 1. 创建 auth.users 记录
// 2. 触发 on_auth_user_created
// 3. 自动创建 public.users 记录（user_class='free'）
```

## 👑 如何设置管理员

### 普通用户升级为管理员

```sql
-- 升级为 admin
UPDATE users 
SET user_class = 'admin' 
WHERE email = 'admin@example.com';

-- 升级为 super_admin
UPDATE users 
SET user_class = 'super_admin' 
WHERE email = 'superadmin@example.com';
```

### 用户等级说明

```
super_admin → 最高权限（你自己）
admin       → 管理员权限
premium     → 付费用户
free        → 免费用户（默认）
```

## 🔍 验证 Migration 是否成功

### 检查触发器是否存在

```sql
SELECT 
    trigger_name,
    event_manipulation,
    event_object_table,
    action_statement
FROM information_schema.triggers
WHERE trigger_name = 'on_auth_user_created';
```

**预期结果：**
```
trigger_name        | on_auth_user_created
event_manipulation  | INSERT
event_object_table  | users (in auth schema)
action_statement    | EXECUTE FUNCTION handle_new_user()
```

### 检查所有用户是否同步

```sql
-- 应该返回 0（所有 auth 用户都有对应的 public.users 记录）
SELECT COUNT(*) as missing_users
FROM auth.users au
LEFT JOIN public.users u ON au.id = u.id
WHERE u.id IS NULL;
```

## 📝 回答你的问题

### Q1: 新建的用户都是普通用户吗？

**A: ✅ 是的！** 

运行 Migration 013 后，所有新用户默认：
- `user_class = 'free'` （免费用户）
- `status = 'active'` （激活状态）

### Q2: 在 Supabase 创建新用户，users 表会自动多一个人吗？

**A: ✅ 会的！**

运行 Migration 013 后，触发器会自动处理：
```
Supabase Dashboard 创建用户
    ↓
auth.users 插入记录
    ↓
触发器自动执行
    ↓
public.users 自动创建记录（user_class='free'）
```

### Q3: 如何运行这个 Migration？

**步骤：**

1. 登录 **Supabase Dashboard**
2. 进入 **Database → SQL Editor**
3. 复制 `013_auto_create_user_on_signup.sql` 的内容
4. 粘贴并点击 **Run**
5. 查看输出，确认成功

**预期输出：**
```
NOTICE: Migration 013 completed successfully.
NOTICE: Auth users count: 1
NOTICE: Public users count: 1
NOTICE: ✓ All auth users have corresponding user records
```

## 🚀 后续步骤

1. **立即运行** Migration 013
2. **测试创建新用户**（Supabase Dashboard）
3. **验证** users 表是否自动创建记录
4. **设置管理员**（如果需要其他管理员用户）

## 🔐 安全提示

- ⚠️ **不要直接在 Supabase Dashboard 修改 `auth.users`**
- ✅ **使用 Supabase 提供的 API 创建用户**
- ✅ **通过 SQL 修改 `public.users` 的权限/等级**

## 📚 相关文件

- Migration 文件: `backend/database/013_auto_create_user_on_signup.sql`
- Users 表定义: `backend/database/001_schema_v2.sql`（第 64-80 行）
- User 等级更新: `backend/database/004_update_user_class.sql`
