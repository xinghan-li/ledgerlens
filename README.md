# LedgerLens 智能小票识别系统

基于 AI 的智能收据识别和管理平台

## 🏗️ 项目结构

```
LedgerLens/
├── backend/          # Python FastAPI 后端
│   ├── app/         # 应用代码
│   ├── tests/       # 测试文件
│   └── README.md    # 后端文档
│
├── frontend/        # Next.js React 前端
│   ├── app/        # App Router 页面
│   ├── lib/        # 工具库
│   ├── TODO.md     # 配置待办事项
│   └── README.md   # 前端文档
│
└── input/          # 测试小票样本
```

---

## 🚀 快速开始

### 后端启动

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python run_backend.py
```

后端运行在: **http://localhost:8000**

详细文档: `backend/README.md`

---

### 前端启动

```bash
cd frontend
npm install
npm run dev
```

前端运行在: **http://localhost:3001**

详细文档: `frontend/README.md`

**⚠️ 首次使用前**，请按照 `frontend/TODO.md` 完成配置！

---

## 🌐 部署架构

### 生产环境

| 服务 | 平台 | 地址 |
|---|---|---|
| 前端 | Vercel (production 分支) | https://ledgerlens.net |
| 后端 | GCP Cloud Run | `https://xxxx-uc.a.run.app` |
| 数据库 | Supabase (production project) | `pwbgiszbsercdtsjfjmy.supabase.co` |

### 分支与部署对应关系

```
main        → Vercel Preview (ledgerlens-git-main-xinghans-projects-2327145c.vercel.app)
production  → Vercel Production (ledgerlens.net)
```

**更新生产环境流程：**
1. 在 `main` 上开发和测试
2. 测试通过后：`git checkout production && git merge main && git push origin production`
3. Vercel 自动重新部署 `ledgerlens.net`

---

## 🔧 本地后端 + Preview 前端调试

当需要用**真实登录**测试前后端交互时，使用 Preview URL + ngrok。

**Preview URL 使用本地后端（ngrok），Production URL 始终使用 Cloud Run，互不干扰。**

### 环境变量配置（已在 Vercel 中配置好）

| 环境 | `NEXT_PUBLIC_API_URL` |
|---|---|
| Production | Cloud Run URL |
| Preview | `https://ledgerlens-be.ngrok-free.app` |

### 调试步骤

**第一步：启动 ngrok（暴露本地后端）**

```powershell
ngrok http 8000 --hostname=ledgerlens-be.ngrok-free.app
```

**第二步：启动本地后端**

```powershell
cd backend
python run_backend.py
```

**第三步：打开 Preview URL 测试**

```
https://ledgerlens-git-main-xinghans-projects-2327145c.vercel.app
```

用邮箱登录，此时请求走 ngrok → `localhost:8000` → dev Supabase。

### 注意事项

- `localhost:3000`（本地前端）也自动用 `localhost:8000`，不需要 ngrok
- `ledgerlens.net`（生产）始终用 Cloud Run，本地跑不跑后端**没有任何影响**
- Preview URL 已加入 Firebase Authorized Domains，可以正常登录

---

## 📦 技术栈

### 后端

- **框架**: FastAPI (Python)
- **OCR**: Google Document AI
- **LLM**: Google Gemini
- **数据库**: Supabase (PostgreSQL)
- **认证**: JWT (Supabase Auth)

### 前端

- **框架**: Next.js 15 (App Router)
- **UI**: React 19 + TypeScript
- **样式**: Tailwind CSS
- **认证**: Supabase Auth (Magic Link)

---

## ✨ 功能特性

### ✅ 已实现

- 🤖 **AI 小票识别**
  - Google Document AI OCR
  - 多商店规则引擎（Costco, Trader Joe's, T&T 等）
  - LLM 增强解析
  - 坐标验证和数学检查

- 🔐 **用户认证**
  - Magic Link 无密码登录
  - JWT Token 认证
  - 基于角色的权限控制
  - API 速率限制

- 📤 **小票管理**
  - 文件上传（JPG, PNG, PDF）
  - 自动处理流程
  - 数据库存储

### 🚧 开发中

- 📊 前端 Dashboard UI
- 🔍 小票列表和详情页
- 📈 统计分析功能
- 🎨 更多 UI 优化

---

## 📚 文档索引

### 主要文档

- **[FRONTEND_IMPLEMENTATION_SUMMARY.md](./FRONTEND_IMPLEMENTATION_SUMMARY.md)** - 前端实现总结
- **[backend/README.md](./backend/README.md)** - 后端文档
- **[frontend/README.md](./frontend/README.md)** - 前端文档
- **[frontend/TODO.md](./frontend/TODO.md)** - 前端配置待办事项

### 技术文档

- **[backend/RATE_LIMITER_SETUP.md](./backend/RATE_LIMITER_SETUP.md)** - API 速率限制
- **[backend/development_log/](./backend/development_log/)** - 开发日志
- **[backend/app/processors/validation/](./backend/app/processors/validation/)** - 小票处理模块文档

---

## 🎯 支持的商店

- ✅ Costco (US Digital, US Physical, CA Digital)
- ✅ Trader Joe's
- ✅ T&T Supermarket
- ✅ 99 Ranch Market
- ✅ Island Gourmet Markets
- 🚧 更多商店持续添加中...

---

## 🛠️ 开发工具

### API 测试

```bash
# 健康检查
curl http://localhost:8000/health

# 上传小票（需要 JWT）
curl -X POST http://localhost:8000/api/receipt/workflow \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "file=@receipt.jpg"
```

### 数据库

- Supabase Dashboard: https://app.supabase.com
- 本地数据: 见后端配置

---

## 📝 开发日志

查看每日开发进展:

- `backend/development_log/2026-02-10_log.md` - 最新日志
- `backend/development_log/2026-01-31_log.md`
- `backend/development_log/2026-01-26_log.md`

---

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

---

## 📄 License

MIT License

---

## 📧 联系方式

如有问题或建议，欢迎提交 Issue！

---

**开始使用:**

1. 启动后端: `cd backend && python run_backend.py`
2. 启动前端: `cd frontend && npm run dev`
3. 配置前端: 按照 `frontend/TODO.md` 完成 Supabase 配置
4. 访问: http://localhost:3001
5. 开始使用 LedgerLens! 🎉
