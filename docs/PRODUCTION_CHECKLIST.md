# LedgerLens 生产部署完整清单

> 目标：把 ledgerlens.net 部署为公网可用的 Web App
> 技术栈：Next.js (Vercel) + FastAPI (GCP Cloud Run) + Supabase (Production) + Firebase Auth

---

## 架构总览

```
ledgerlens.net
    ↓
[Vercel] → Next.js 前端（免费 Hobby Plan，自带 CDN + SSL）
    ↓ HTTPS API 请求
[GCP Cloud Run] → FastAPI 后端（Docker 容器，自动扩缩容，按量计费）
    ↓
[Supabase - Production Project] → PostgreSQL 数据库
[Firebase - 同 GCP 项目] → 用户认证
[Google Document AI] → OCR
[OpenAI / Gemini API] → LLM 处理
```

---

## Git 分支策略

```
main          ← 日常开发（当前在这里）
production    ← 生产分支，push 触发自动部署
feature/*     ← 功能开发，合并到 main
```

**发布流程**：`feature/xxx` → merge 到 `main`（开发迭代）→ `main` merge 到 `production`（发布上线）

---

## 日常：每次 production 更新都重新部署后端

> 你改完代码、想让线上后端跑最新版本时，按下面选一种做即可。

### 方案 A：自动部署（推荐，一次配好以后就 3 步）

**前提**：已按下方「首次配置 CI」做过一次。

每次要更新后端时：

1. 在本地确保当前在 `main` 且已提交所有改动：
   ```bash
   git checkout main
   git status   # 确认没有未提交的修改
   ```

2. 切到 `production` 并合并 `main`：
   ```bash
   git checkout production
   git pull origin production
   git merge main
   ```

3. 推送到 GitHub，触发自动部署：
   ```bash
   git push origin production
   ```

4. 打开 **GitHub → Actions**，看 `Deploy Backend to Cloud Run` 是否变绿；约 3～5 分钟后到 **GCP Cloud Run → Revisions** 会多一个新版本，流量会切到新版本。

---

### 方案 B：手动部署（未配 CI 或临时用）

在**项目根目录**（能看到 `backend` 文件夹的那一层）打开终端，依次执行：

```bash
# 1. 登录 GCP（未登录时按提示在浏览器里登录）
gcloud auth login
gcloud config set project ledgerlens-484819
gcloud auth configure-docker gcr.io

# 2. 构建并推送镜像
docker build -t gcr.io/ledgerlens-484819/ledgerlens-backend:latest ./backend
docker push gcr.io/ledgerlens-484819/ledgerlens-backend:latest

# 3. 让 Cloud Run 使用新镜像
gcloud run deploy ledgerlens-backend --image gcr.io/ledgerlens-484819/ledgerlens-backend:latest --region us-central1 --platform managed
```

执行完后 Cloud Run 会多一个新 revision，即已更新后端。

---

### 首次配置 CI（方案 A 只需做一次）

1. **在 GCP 建一个给 CI 用的 Service Account**  
   - 打开 [GCP Console → IAM → Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts?project=ledgerlens-484819)  
   - 创建账号，名字如 `github-actions-deploy`  
   - 赋予角色：**Cloud Run Admin**、**Storage Admin**（或 **Artifact Registry 写入**，若用 GCR 则需 **Storage Object Admin** 等可 push 镜像的权限）

2. **给该 SA 创建并下载 JSON 密钥**  
   - 在该 Service Account 的「密钥」里创建密钥 → JSON → 下载

3. **把 JSON 内容放进 GitHub Secrets**  
   - 打开 GitHub 仓库 → **Settings → Secrets and variables → Actions**  
   - **New repository secret**，名字填 **`GCP_SA_KEY`**，值粘贴整个 JSON 文件内容，保存

4. **确认仓库里已有 workflow 文件**  
   - 路径：`.github/workflows/deploy-backend.yml`  
   - 内容是：push 到 `production` 时构建并部署后端（见 PHASE 7）

之后每次按「方案 A」的 3 步 push 到 `production`，后端就会自动重新部署。

---

## PHASE 1：Supabase Production 数据库

### 1.1 新建 Supabase 项目
- [ ] 去 supabase.com → New Project，命名 `ledgerlens-production`
- [ ] 选 Region（建议 `us-west-1` 或离用户最近的）
- [ ] 记录新项目的：`Project URL`、`anon key`、`service_role key`、`JWT secret`（Settings → API）

### 1.2 按顺序跑所有迁移 SQL（在 SQL Editor 里执行）
- [ ] `001_schema_v2.sql`
- [ ] `010_update_costco_lynnwood_address.sql`
- [ ] `012_add_receipt_items_and_summaries.sql`
- [ ] `013_auto_create_user_on_signup.sql`
- [ ] `015_add_categories_tree.sql`
- [ ] `016_add_products_catalog.sql`
- [ ] `017_link_receipt_items_to_products.sql`
- [ ] `018_add_price_snapshots.sql`
- [ ] `019_add_categorization_rules.sql`
- [ ] `023_seed_prompt_library.sql`（非 deprecated 版本）
- [ ] `023_prompt_library_and_binding.sql`
- [ ] `025_add_classification_review.sql`
- [ ] `030_increment_product_usage_rpc.sql`
- [ ] `034_fix_milk_and_soup_dumplings_rules.sql`
- [ ] `044_rls_policies.sql`
- [ ] `045_receipt_workflow_steps.sql`
- [ ] `046_user_strikes_and_lock.sql`
- [ ] `051_category_source_and_user_categories.sql`
- [ ] 跳过 `deprecated/` 和 `scripts/` 目录

### 1.3 迁移系统级数据（从 dev 项目导出再导入）
- [ ] `categories` 表（分类体系）
- [ ] `prompt_library` 表（LLM prompts）
- [ ] `categorization_rules` 表（分类规则）
- [ ] `store_locations` 表（门店信息）
- [ ] **不迁移**：`receipts`、`record_summaries`、`record_items`、`users`（生产从零开始）
- [ ] 导出方式：Supabase Dashboard → Table Editor → 导出 CSV → 导入新项目（或用 supabase CLI `db dump`）

---

## PHASE 2：准备 Production 环境变量

> 原则：secrets 绝不进 Git，绝不硬编码在代码里

### 2.1 后端 Production 环境变量（存入 GCP Secret Manager）

```
# 数据库 - 使用 production Supabase 项目的值
SUPABASE_URL=https://新项目.supabase.co
SUPABASE_ANON_KEY=新项目的anon key
SUPABASE_SERVICE_ROLE_KEY=新项目的service role key
SUPABASE_JWT_SECRET=新项目的JWT secret

# GCP
GCP_PROJECT_ID=ledgerlens-484819
DOCUMENTAI_ENDPOINT=（保持不变）

# AI APIs
OPENAI_API_KEY=（保持不变）
OPENAI_MODEL=gpt-4o-mini
OPENAI_ESCALATION_MODEL=gpt-5.1
GEMINI_API_KEY=（保持不变）
GEMINI_MODEL=gemini-2.5-flash
GEMINI_ESCALATION_MODEL=gemini-3.1-pro-preview

# 应用配置 - 改为 production 模式
ENV=production
ALLOW_DUPLICATE_FOR_DEBUG=false
ENABLE_DEBUG_LOGS=false
LOG_LEVEL=warning

# CORS - 改为 production 前端域名
CORS_ORIGINS=https://ledgerlens.net,https://www.ledgerlens.net

# 以下在 production 不需要
# TEST_USER_ID=（删除）
```

### 2.2 GCP Service Account Key 的处理（重要！）

- [ ] **不要**把 `.json` key 文件打包进 Docker 镜像
- [ ] 把 Firebase SA JSON 内容存入 GCP Secret Manager，key 名为 `FIREBASE_SERVICE_ACCOUNT_JSON`
- [ ] 修改 `config.py` 支持从环境变量读取 SA JSON（而不是文件路径）
- [ ] `GOOGLE_APPLICATION_CREDENTIALS` 也改为 Secret Manager 注入的方式

### 2.3 前端 Production 环境变量（存入 Vercel Dashboard）

```
# Firebase - public keys，和 dev 一样（同一 Firebase 项目）
NEXT_PUBLIC_FIREBASE_API_KEY=（不变）
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=（不变）
NEXT_PUBLIC_FIREBASE_PROJECT_ID=（不变）
NEXT_PUBLIC_FIREBASE_APP_ID=（不变）
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=（不变）
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=（不变）
NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=（不变）

# Supabase - 改为 production 项目的值
NEXT_PUBLIC_SUPABASE_URL=新项目URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=新项目anon key

# 后端 API - 改为 GCP Cloud Run 地址（第四步完成后填入）
NEXT_PUBLIC_API_URL=https://你的cloud-run-url.run.app
```

---

## PHASE 3：Docker 化后端

### 3.1 创建 Dockerfile（在 `backend/` 目录下）

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY config/ ./config/

# Cloud Run 默认监听 8080
ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] 创建 `backend/Dockerfile`
- [ ] 创建 `backend/.dockerignore`（排除 `.env`、`keys/`、`service_account/`、`__pycache__`、`tests/`）
- [ ] 本地构建测试：`docker build -t ledgerlens-backend ./backend`
- [ ] 本地运行测试：`docker run -p 8080:8080 --env-file backend/.env ledgerlens-backend`

---

## PHASE 4：GCP Cloud Run 部署后端

### 4.1 GCP 准备
- [ ] GCP Console → 确认项目 `ledgerlens-484819` 已启用以下 API：
  - Cloud Run API
  - Container Registry API（或 Artifact Registry API）
  - Secret Manager API
- [ ] 安装 `gcloud` CLI（如未安装）：`gcloud auth login`

### 4.2 Secret Manager 配置
- [ ] 把所有后端 secrets 一条一条存入 Secret Manager（GCP Console → Security → Secret Manager）
- [ ] 或用 CLI：`echo -n "值" | gcloud secrets create SECRET_NAME --data-file=-`

### 4.3 首次手动部署
```bash
# 构建并推送镜像
docker build -t gcr.io/ledgerlens-484819/backend:v1 ./backend
docker push gcr.io/ledgerlens-484819/backend:v1

# 创建 Cloud Run 服务
gcloud run deploy ledgerlens-backend \
  --image gcr.io/ledgerlens-484819/backend:v1 \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 512Mi \
  --min-instances 0 \
  --max-instances 10 \
  --set-secrets="SUPABASE_URL=SUPABASE_URL:latest,..."
```

- [ ] 首次部署成功，记录 Cloud Run 服务 URL（`https://ledgerlens-backend-xxx.run.app`）
- [ ] 测试后端 health check：`GET https://你的url.run.app/health`

---

## PHASE 5：Vercel 部署前端

### 5.1 连接 GitHub
- [ ] 去 vercel.com → New Project → Import from GitHub → 选 `LedgerLens` 仓库
- [ ] Root Directory 设为 `frontend`
- [ ] Framework Preset 选 `Next.js`
- [ ] **Production Branch** 设为 `production`

### 5.2 配置环境变量
- [ ] 在 Vercel Dashboard → Settings → Environment Variables 里添加 2.3 节中所有变量
- [ ] 确保 `NEXT_PUBLIC_API_URL` 指向 Cloud Run 地址

### 5.3 首次部署
- [ ] 点击 Deploy，确认构建成功
- [ ] 访问 Vercel 给的临时域名（`xxx.vercel.app`），测试前端能正常运行
- [ ] 测试登录、上传小票等核心功能 end-to-end

---

## PHASE 6：域名绑定

### 6.1 前端域名（Vercel）
- [ ] Vercel Dashboard → 项目 → Settings → Domains
- [ ] 添加 `ledgerlens.net` 和 `www.ledgerlens.net`
- [ ] 按 Vercel 提示在域名注册商处添加 DNS 记录（通常是 A 记录或 CNAME）
- [ ] 等待 DNS 生效（几分钟到几小时），Vercel 自动申请 SSL 证书

### 6.2 后端域名（可选）
- [ ] 可配置 `api.ledgerlens.net` 指向 Cloud Run（Cloud Run → 自定义域名）
- [ ] 初期可以直接用 `*.run.app` 地址，前端 `NEXT_PUBLIC_API_URL` 指向它即可
- [ ] 配置后记得更新 Vercel 里的 `NEXT_PUBLIC_API_URL` 环境变量

---

## PHASE 7：GitHub Actions CI/CD（自动部署）

### 7.1 创建 GitHub Actions workflow
- [ ] 创建 `.github/workflows/deploy-production.yml`

```yaml
name: Deploy to Production

on:
  push:
    branches:
      - production

jobs:
  deploy-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Authenticate to GCP
        uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}

      - name: Configure Docker for GCR
        run: gcloud auth configure-docker

      - name: Build and Push Docker Image
        run: |
          docker build -t gcr.io/ledgerlens-484819/backend:${{ github.sha }} ./backend
          docker push gcr.io/ledgerlens-484819/backend:${{ github.sha }}

      - name: Deploy to Cloud Run
        run: |
          gcloud run deploy ledgerlens-backend \
            --image gcr.io/ledgerlens-484819/backend:${{ github.sha }} \
            --region us-central1 \
            --platform managed \
            --allow-unauthenticated \
            --set-secrets="SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_ANON_KEY=SUPABASE_ANON_KEY:latest,SUPABASE_SERVICE_ROLE_KEY=SUPABASE_SERVICE_ROLE_KEY:latest,SUPABASE_JWT_SECRET=SUPABASE_JWT_SECRET:latest,OPENAI_API_KEY=OPENAI_API_KEY:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,FIREBASE_SERVICE_ACCOUNT_JSON=FIREBASE_SERVICE_ACCOUNT_JSON:latest,GCP_PROJECT_ID=GCP_PROJECT_ID:latest,DOCUMENTAI_ENDPOINT=DOCUMENTAI_ENDPOINT:latest"
```

### 7.2 配置 GitHub Secrets
- [ ] GitHub Repo → Settings → Secrets → Actions，添加：
  - `GCP_SA_KEY`：一个专用于 CI/CD 的 GCP Service Account JSON（需要 `Cloud Run Admin` + `Storage Admin` + `Container Registry` 权限）

### 7.3 Vercel 自动部署（前端）
- [ ] Vercel 连 GitHub 后自动处理，push 到 `production` 分支即触发前端构建
- [ ] 无需额外配置

### 7.4 发布流程验证
- [ ] 在 `main` 分支做一个小改动
- [ ] `git merge main production` 并 push
- [ ] 观察 GitHub Actions 是否自动触发
- [ ] 观察 Cloud Run 是否更新到新版本
- [ ] 观察 Vercel 是否自动构建

---

## PHASE 8：生产安全检查（上线前必做）

### CORS
- [ ] 后端 `CORS_ORIGINS` 仅包含 `https://ledgerlens.net` 和 `https://www.ledgerlens.net`
- [ ] 不包含 `localhost`、`*`、ngrok 地址

### HTTPS
- [ ] 前端全站 HTTPS（Vercel 自动处理）
- [ ] 后端 Cloud Run 自带 HTTPS

### Debug / 日志
- [ ] `ENV=production`
- [ ] `ALLOW_DUPLICATE_FOR_DEBUG=false`
- [ ] `ENABLE_DEBUG_LOGS=false`
- [ ] `LOG_LEVEL=warning`
- [ ] `config.py` 里的 `[DEBUG]` print 语句关闭（在 production 模式下跳过）

### Secrets 安全
- [ ] `.env`、`.json` key 文件已加入 `.gitignore`
- [ ] Git 历史中没有泄露过 secrets（如有，需要 rotate 所有 key）
- [ ] 所有 production secrets 仅存在于 GCP Secret Manager 和 Vercel Environment Variables

### Admin 账户
- [ ] 确认 `admin` / `super_admin` 名单仅包含可信账号

### 限流
- [ ] 当前为单实例内存限流；Cloud Run 多实例时需迁移到 Redis 或 Upstash

---

## API Keys & Credentials 存放位置汇总

| Secret | 存放位置 | 备注 |
|--------|----------|------|
| Supabase keys | GCP Secret Manager | 后端用 |
| OpenAI / Gemini API keys | GCP Secret Manager | 后端用 |
| Firebase SA JSON | GCP Secret Manager | 后端用（不进镜像）|
| GCP Document AI credentials | GCP Workload Identity 或 Secret Manager | 后端用 |
| `NEXT_PUBLIC_*` Firebase keys | Vercel Environment Variables | 前端用（public，可见）|
| Supabase anon key | Vercel Environment Variables | 前端用 |
| GCP_SA_KEY（CI/CD 专用） | GitHub Secrets | 仅 Actions 用 |
| 本地开发 `.env` | 本地文件系统 | **绝不提交 Git** |

---

*本清单创建于 2026-03-05，涵盖从 dev 到 production 的完整部署流程。*
