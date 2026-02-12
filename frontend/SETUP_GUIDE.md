# LedgerLens Frontend 配置指南

## ✅ 已完成的工作

前端已经搭建完成并成功运行！包括：

1. ✅ Next.js 15 + React 19 + TypeScript 项目结构
2. ✅ Tailwind CSS 配置和样式
3. ✅ Supabase Auth 集成（Magic Link）
4. ✅ 登录页面 + 回调处理
5. ✅ Dashboard（受保护路由）
6. ✅ 中间件路由保护
7. ✅ API 调用集成（连接后端）

**开发服务器已启动：** http://localhost:3000

---

## 📋 你需要完成的配置（TODO）

### 1️⃣ 配置环境变量

**文件**: `frontend/.env.local`

需要创建这个文件并填入以下信息（从 Supabase Dashboard 获取）：

```env
# Supabase 配置
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key-here

# 后端 API（可选，默认 localhost:8000）
NEXT_PUBLIC_API_URL=http://localhost:8000
```

#### 如何获取 Supabase 配置：

1. 登录 [Supabase Dashboard](https://app.supabase.com)
2. 选择你的项目
3. 点击左侧 **Settings** → **API**
4. 复制以下信息：
   - **Project URL** → `NEXT_PUBLIC_SUPABASE_URL`
   - **anon public** key → `NEXT_PUBLIC_SUPABASE_ANON_KEY`

参考文件 `frontend/.env.local.example` 查看格式。

---

### 2️⃣ 在 Supabase 配置 Redirect URLs

**步骤**：

1. 在 Supabase Dashboard 中，进入 **Authentication** → **URL Configuration**
2. 在 **Redirect URLs** 中添加：
   ```
   http://localhost:3000/auth/callback
   ```
3. 如果将来部署到生产环境，还需添加：
   ```
   https://your-domain.com/auth/callback
   ```

这样 Magic Link 登录后才能正确重定向回应用。

---

### 3️⃣ 测试 Magic Link 登录

配置完成后，测试流程：

1. 访问 http://localhost:3001
2. 点击"登录"按钮
3. 输入邮箱地址
4. 检查邮箱，点击登录链接
5. 自动跳转到 Dashboard
6. 在 Dashboard 可以看到用户信息和 JWT Token

**注意事项**：

- 开发环境 Supabase 有邮件发送速率限制
- 如未收到邮件，检查垃圾邮件文件夹
- 可以在 Supabase Dashboard → Authentication → Logs 查看邮件发送日志

---

### 4️⃣ 连接后端 API（可选）

如果后端服务运行在 `localhost:8000`，无需配置。

如果后端在其他地址，修改 `.env.local` 中的：

```env
NEXT_PUBLIC_API_URL=https://your-backend-api.com
```

---

## 🎨 前端设计草稿集成

当前前端已经实现了基础功能：

- ✅ 登录页面（Magic Link）
- ✅ Dashboard 基础布局
- ✅ 小票上传功能（调用后端 API）
- ✅ 用户信息展示

**下一步**：根据你的设计草稿，我们可以继续实现：

- 📊 小票列表展示
- 🔍 详情查看页面
- 📈 数据统计和报表
- 🎨 UI 美化和优化
- 📱 移动端适配

**准备好设计稿后，随时发给我！**

---

## 🛠️ 开发命令

```bash
# 启动开发服务器
npm run dev

# 构建生产版本
npm run build

# 运行生产版本
npm run start

# 代码检查
npm run lint
```

---

## 📁 项目结构说明

```
frontend/
├── app/                      # Next.js App Router
│   ├── page.tsx             # 首页
│   ├── layout.tsx           # 根布局
│   ├── globals.css          # 全局样式
│   ├── login/               # 登录页面
│   │   └── page.tsx
│   ├── dashboard/           # 主控制台（需要登录）
│   │   └── page.tsx
│   ├── auth/
│   │   └── callback/        # OAuth 回调处理
│   │       └── route.ts
│   └── about/               # 关于页面
│       └── page.tsx
├── lib/
│   └── supabase.ts          # Supabase 客户端配置
├── components/              # React 组件（未来扩展）
├── middleware.ts            # 路由保护中间件
└── .env.local               # 环境变量（你需要创建）
```

---

## 🚨 常见问题

### Q: 启动失败或样式不显示？

A: 删除缓存重新启动：

```bash
rm -rf .next
npm run dev
```

### Q: 登录后无法访问 Dashboard？

A: 检查：

1. `.env.local` 配置是否正确
2. Supabase Redirect URLs 是否添加
3. 浏览器控制台是否有错误

### Q: API 调用失败？

A: 检查：

1. 后端服务是否运行
2. `NEXT_PUBLIC_API_URL` 是否正确
3. JWT Token 是否有效（Dashboard 可查看）

---

## 📝 下一步计划

- [ ] 创建 `.env.local` 配置文件
- [ ] 在 Supabase 配置 Redirect URLs
- [ ] 测试 Magic Link 登录流程
- [ ] 准备前端设计草稿
- [ ] 继续开发更多功能页面

**一切准备就绪！开始使用吧！🚀**
