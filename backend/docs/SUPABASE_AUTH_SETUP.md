# Supabase Auth 设置指南

本文档说明如何设置 Supabase Auth 并获取 JWT token 用于 API 测试。

## 一、在 Supabase Dashboard 上的操作

### 1. 获取 JWT Secret

**重要**：Supabase 现在使用新的 JWT 密钥系统。你需要获取 **Legacy JWT Secret**（共享密钥）。

#### 步骤 1：从 Authentication 页面导航到 Project Settings

1. **查看左侧边栏**
   - 你现在在 **Authentication** > **Users** 页面
   - 在左侧边栏中，向下滚动到最底部
   - 找到 **Project Settings**（带齿轮图标 ⚙️，通常在边栏最底部）

2. **点击 Project Settings**
   - 这会打开项目设置页面
   - 左侧会显示设置菜单（如 General, API, Database, Auth 等）

#### 步骤 2：进入 API 设置

1. **在 Project Settings 页面中**
   - 查看左侧设置菜单
   - 找到并点击 **API** 选项
   - 或者直接访问：`https://app.supabase.com/project/YOUR_PROJECT_ID/settings/api`

2. **你会进入 API 设置页面**
   - 这个页面显示 API 相关的配置

#### 步骤 3：找到 JWT Keys 标签页

1. **在 API 设置页面中**
   - 查看页面顶部的标签页（如 "General", "JWT Keys" 等）
   - 找到并点击 **JWT Keys** 标签页

2. **你会看到两个标签**：
   - **JWT Signing Keys** - 新的 ECC 密钥系统（当前激活，显示 ECC (P-256) 密钥）
   - **Legacy JWT Secret** - 旧的 HS256 共享密钥 ← **点击这个标签**

#### 步骤 4：复制 Legacy JWT Secret

1. 点击 **Legacy JWT Secret** 标签页
2. 你会看到一个长字符串（类似：`your-super-secret-jwt-token-with-at-least-32-characters-long`）
3. 点击复制按钮或手动复制整个字符串

**注意**：
- 如果你看不到 "Legacy JWT Secret" 标签页，说明你的项目已经迁移到新的密钥系统
- 在这种情况下，我们需要更新代码以支持新的 ECC 密钥
- 如果 Legacy JWT Secret 存在但显示为 "PREVIOUS KEY"（之前的密钥），你仍然可以使用它来验证旧的 token，但新生成的 token 可能使用新的 ECC 密钥

### 2. 配置环境变量

将 JWT Secret 添加到你的 `.env` 文件中：

```bash
# 在 backend/.env 文件中添加
SUPABASE_JWT_SECRET=your-super-secret-jwt-token-with-at-least-32-characters-long
```

### 3. 确保 Auth 已启用（可选，用于测试）

这一步是可选的，主要用于测试用户注册功能。如果你已经有测试用户（如 `xinghan.sde@gmail.com`），可以**跳过这一步**。

1. **在 Supabase Dashboard 中**
   - 你现在应该在 **Authentication** 部分（左侧边栏）
   - 在 **Authentication** 下，找到 **CONFIGURATION** 部分
   - 点击 **Sign In / Providers**

2. **在 Sign In / Providers 页面中**
   - 找到 **Email** 部分
   - 确保 **Enable Email Signup** 开关是打开的（如果需要邮箱注册）
   - 检查 **Confirm email** 设置：
     - 如果打开：用户注册后需要确认邮箱才能登录
     - 如果关闭：用户注册后可以直接登录（适合测试）

3. **保存设置**（如果有更改）

**重要提示**：
- 如果你已经有测试用户，**可以完全跳过这一步**
- 这一步主要用于新用户注册，不影响 JWT token 的获取和使用
- 你已经有了用户 `xinghan.sde@gmail.com`，所以可以直接进入下一步

## 二、如何获取 JWT Token（重要！）

**现在你已经配置好了 JWT Secret，接下来需要获取 JWT token 来测试 API。**

JWT token 是通过用户登录获得的，不是从 Dashboard 直接复制的。

### 方法 1：使用 Supabase Dashboard（最简单）

1. 在 Supabase Dashboard 中，进入 **Authentication** > **Users**
2. 找到或创建一个测试用户
3. 点击用户，查看详情
4. 在用户详情页面，你可以看到用户的 UUID（这就是 `user_id`）
5. **注意**：Dashboard 不直接显示 JWT token，你需要使用方法 2 或 3

### 方法 2：使用 Supabase JavaScript Client（推荐用于前端测试）

如果你有前端应用，可以使用 Supabase JavaScript client：

```javascript
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  'YOUR_SUPABASE_URL',
  'YOUR_SUPABASE_ANON_KEY'
)

// 登录
const { data, error } = await supabase.auth.signInWithPassword({
  email: 'user@example.com',
  password: 'password'
})

if (data.session) {
  const token = data.session.access_token
  console.log('JWT Token:', token)
  // 使用这个 token 作为 Authorization header: "Bearer <token>"
}
```

### 方法 3：使用 Python 脚本（推荐用于后端测试）

创建一个测试脚本来获取 token：

```python
# backend/get_jwt_token.py
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_anon_key = os.getenv("SUPABASE_ANON_KEY")

# 创建 Supabase client
supabase = create_client(supabase_url, supabase_anon_key)

# 登录（使用邮箱和密码）
email = "test@example.com"
password = "your-password"

response = supabase.auth.sign_in_with_password({
    "email": email,
    "password": password
})

if response.session:
    token = response.session.access_token
    print(f"JWT Token: {token}")
    print(f"\n使用方式:")
    print(f'curl -H "Authorization: Bearer {token}" http://localhost:8000/api/auth/test-token')
else:
    print("登录失败")
```

运行脚本：

```bash
cd backend
python get_jwt_token.py
```

### 方法 4：使用 Swagger UI（用于 API 测试）

1. 启动后端服务器：`uvicorn app.main:app --reload`
2. 打开 Swagger UI：`http://localhost:8000/docs`
3. 点击右上角的 **Authorize** 按钮
4. 在 **Value** 字段中输入：`Bearer <your-jwt-token>`
5. 点击 **Authorize**
6. 现在所有需要认证的 API 都会自动使用这个 token

**注意**：你需要先使用方法 2 或 3 获取 token，然后在这里使用。

## 三、测试认证

### 1. 测试认证端点

使用 curl：

```bash
# 先获取 token（使用方法 3）
TOKEN="your-jwt-token-here"

# 测试认证
curl -X GET "http://localhost:8000/api/auth/test-token" \
  -H "Authorization: Bearer $TOKEN"
```

如果成功，你会看到：

```json
{
  "success": true,
  "message": "Authentication successful",
  "user_id": "user-uuid-here"
}
```

### 2. 测试受保护的 API

```bash
# 测试 workflow 端点
curl -X POST "http://localhost:8000/api/receipt/workflow" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@receipt.jpg"
```

### 3. 测试未认证的请求

```bash
# 不提供 token，应该返回 401
curl -X GET "http://localhost:8000/api/auth/test-token"
```

应该返回：

```json
{
  "detail": "Authorization header is required"
}
```

## 四、创建测试用户

### 方法 1：使用 Supabase Dashboard

1. 进入 **Authentication** > **Users**
2. 点击 **Add User** > **Create new user**
3. 输入邮箱和密码
4. 点击 **Create User**

### 方法 2：使用 Supabase API

```python
# backend/create_test_user.py
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# 使用 service role key 来创建用户（需要管理员权限）
supabase = create_client(supabase_url, supabase_service_role_key)

# 创建用户
response = supabase.auth.admin.create_user({
    "email": "test@example.com",
    "password": "test-password-123",
    "email_confirm": True  # 自动确认邮箱
})

if response.user:
    print(f"用户创建成功: {response.user.id}")
    print(f"邮箱: {response.user.email}")
else:
    print("用户创建失败")
```

## 五、常见问题

### Q1: 如何知道 token 是否过期？

JWT token 通常有 1 小时的过期时间。如果 token 过期，你会收到 `401 Unauthorized` 错误，错误信息是 `"Token has expired"`。

解决方法：重新登录获取新 token。

### Q2: 如何在 Swagger UI 中测试？

1. 获取 JWT token（使用方法 2 或 3）
2. 打开 Swagger UI：`http://localhost:8000/docs`
3. 点击右上角的 **Authorize** 按钮
4. 输入：`Bearer <your-token>`
5. 点击 **Authorize**
6. 现在所有 API 调用都会自动包含这个 token

### Q3: 如何刷新 token？

Supabase 的 refresh token 机制是自动的。如果你使用 Supabase client，它会自动刷新。如果使用手动 JWT，你需要重新登录获取新 token。

### Q4: 如何查看 token 的内容（不验证）？

你可以使用 [jwt.io](https://jwt.io) 来解码 token（不验证签名）。只需要粘贴 token，就能看到 payload 内容，包括 `user_id`（在 `sub` 字段中）。

## 六、安全注意事项

1. **永远不要**将 JWT Secret 提交到 Git
2. **永远不要**在前端代码中暴露 JWT Secret
3. JWT Secret 应该只存在于服务器端的 `.env` 文件中
4. 使用 `SUPABASE_ANON_KEY` 在前端，使用 `SUPABASE_JWT_SECRET` 在后端验证
5. 定期轮换 JWT Secret（在 Supabase Dashboard > Settings > API 中）

---

*最后更新：2026-01-31*
