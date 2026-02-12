# LedgerLens Frontend

智能小票识别系统前端 - 基于 Next.js 15 App Router

## 技术栈

- **框架**: Next.js 15 (App Router)
- **UI**: React 19 + TypeScript
- **样式**: Tailwind CSS
- **认证**: Supabase Auth (Magic Link)
- **部署**: Vercel (推荐)

## 快速开始

### 1. 安装依赖

```bash
npm install
```

### 2. 配置环境变量

复制 `.env.local.example` 到 `.env.local` 并填写配置：

```bash
cp .env.local.example .env.local
```

编辑 `.env.local`：

```env
# Supabase 配置（从 Supabase Dashboard 获取）
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key-here

# 后端 API URL
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 3. 启动开发服务器

```bash
npm run dev
```

访问 [http://localhost:3000](http://localhost:3000)

## 项目结构

```
frontend/
├── app/                      # Next.js App Router
│   ├── layout.tsx           # 根布局
│   ├── page.tsx             # 首页
│   ├── globals.css          # 全局样式
│   ├── login/               # 登录页面
│   ├── dashboard/           # 主控制台（受保护）
│   ├── auth/
│   │   └── callback/        # OAuth 回调处理
│   └── about/               # 关于页面
├── lib/
│   └── supabase.ts          # Supabase 客户端配置
├── components/              # React 组件（未来扩展）
├── public/                  # 静态资源
└── middleware.ts            # Next.js 中间件（路由保护）
```

## 功能特性

### ✅ 已实现

- 🔐 **Magic Link 登录**
  - 邮箱 OTP 认证
  - 无需密码，安全快捷
  - 自动 session 管理

- 🛡️ **路由保护**
  - Middleware 自动保护 `/dashboard`
  - 未登录自动重定向

- 📤 **小票上传**
  - 拖拽/点击上传
  - 自动调用后端 API
  - JWT Token 认证

### 🚧 开发中

- 📊 小票列表展示
- 🔍 数据详情查看
- 📈 统计报表
- 🎨 更多 UI 优化

## 认证流程

### Magic Link 登录流程

```
1. 用户输入邮箱 → /login
2. 前端调用 supabase.auth.signInWithOtp()
3. Supabase 发送登录邮件
4. 用户点击邮件链接 → /auth/callback?code=xxx
5. 回调处理: exchangeCodeForSession()
6. 重定向到 /dashboard
```

### API 认证

Dashboard 自动从 Supabase Session 获取 JWT Token，所有 API 请求都会在 Header 中携带：

```
Authorization: Bearer <jwt_token>
```

后端通过 Supabase JWT 验证用户身份。

## 开发指南

### 运行测试

```bash
npm run build      # 构建生产版本
npm run lint       # 代码检查
```

### 环境要求

- Node.js >= 18.17
- npm >= 9.0

### 常见问题

**Q: 登录后无法访问 Dashboard？**

A: 检查：
1. 环境变量是否正确配置
2. Supabase Redirect URLs 是否包含 `http://localhost:3000/auth/callback`
3. 浏览器 Console 是否有错误

**Q: API 调用失败？**

A: 检查：
1. `NEXT_PUBLIC_API_URL` 是否正确
2. 后端服务是否运行
3. JWT Token 是否有效（Dashboard 可查看）

**Q: 未收到登录邮件？**

A: 检查：
1. 垃圾邮件文件夹
2. Supabase Email Templates 配置
3. Email Rate Limiting（开发环境限制）

## 部署

### Vercel 部署（推荐）

1. 推送代码到 GitHub
2. 在 Vercel 导入项目
3. 配置环境变量（同 `.env.local`）
4. 自动部署完成

记得在 Supabase 添加生产环境的 Redirect URL：

```
https://your-domain.vercel.app/auth/callback
```

### 其他平台

支持任何支持 Next.js 的平台：
- Netlify
- Cloudflare Pages
- 自建服务器

## 后续开发计划

- [ ] 完善 Dashboard UI
- [ ] 添加小票列表和详情页
- [ ] 实现搜索和筛选
- [ ] 数据导出功能
- [ ] 移动端适配
- [ ] 暗黑模式

## 贡献

欢迎提交 Issue 和 PR！

## License

MIT
