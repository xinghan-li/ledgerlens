# API 认证实现总结

## ✅ 已完成的工作

### 1. JWT 认证模块
- ✅ 创建 `backend/app/services/auth/jwt_auth.py`
- ✅ 实现 `get_current_user()` - 验证 JWT token 并返回 user_id
- ✅ 实现 `get_current_user_optional()` - 可选认证（用于公开端点）

### 2. 配置更新
- ✅ 在 `config.py` 中添加 `supabase_jwt_secret` 配置
- ✅ 在 `requirements.txt` 中添加 `PyJWT>=2.8.0`

### 3. API 端点更新
- ✅ `/api/receipt/workflow` - 添加认证要求
- ✅ `/api/receipt/workflow-bulk` - 添加认证要求
- ✅ `/api/auth/test-token` - 新增测试端点

### 4. 工作流更新
- ✅ `process_receipt_workflow()` - 已支持 `user_id` 参数
- ✅ `process_bulk_receipts()` - 已更新以接受并传递 `user_id`

### 5. 文档和工具
- ✅ 创建 `docs/SUPABASE_AUTH_SETUP.md` - 详细设置指南
- ✅ 创建 `get_jwt_token.py` - 测试脚本

---

## 📋 你需要做的事情

### 步骤 1：在 Supabase Dashboard 上获取 JWT Secret

1. 登录 [Supabase Dashboard](https://app.supabase.com)
2. 选择你的项目
3. 进入 **Settings** > **API**
4. 找到 **JWT Secret** 字段
5. 复制这个 secret

### 步骤 2：配置环境变量

在 `backend/.env` 文件中添加：

```bash
SUPABASE_JWT_SECRET=your-super-secret-jwt-token-here
```

### 步骤 3：安装依赖

```bash
cd backend
pip install PyJWT>=2.8.0
```

### 步骤 4：创建测试用户（如果还没有）

在 Supabase Dashboard：
1. 进入 **Authentication** > **Users**
2. 点击 **Add User** > **Create new user**
3. 输入邮箱和密码
4. 点击 **Create User**

### 步骤 5：获取 JWT Token

运行测试脚本：

```bash
cd backend
python get_jwt_token.py
```

输入你的邮箱和密码，脚本会输出 JWT token。

### 步骤 6：测试认证

#### 方法 A：使用 Swagger UI（推荐）

1. 启动后端：`uvicorn app.main:app --reload`
2. 打开 `http://localhost:8000/docs`
3. 点击右上角的 **Authorize** 按钮
4. 输入：`Bearer <your-jwt-token>`
5. 点击 **Authorize**
6. 现在可以测试所有需要认证的 API

#### 方法 B：使用 curl

```bash
# 测试认证端点
curl -X GET "http://localhost:8000/api/auth/test-token" \
  -H "Authorization: Bearer <your-jwt-token>"

# 测试 workflow 端点
curl -X POST "http://localhost:8000/api/receipt/workflow" \
  -H "Authorization: Bearer <your-jwt-token>" \
  -F "file=@receipt.jpg"
```

---

## 🔒 受保护的端点

以下端点现在需要认证：

- ✅ `POST /api/receipt/workflow` - 单个收据处理
- ✅ `POST /api/receipt/workflow-bulk` - 批量收据处理
- ✅ `GET /api/auth/test-token` - 认证测试端点

以下端点**不需要**认证（公开端点）：

- ✅ `GET /health` - 健康检查
- ✅ `POST /api/receipt/goog-ocr` - Google OCR（仅 OCR，不保存）
- ✅ `POST /api/receipt/goog-ocr-dai` - Document AI（仅 OCR，不保存）
- ✅ `POST /api/receipt/amzn-ocr` - AWS Textract（仅 OCR，不保存）
- ✅ `POST /api/receipt/openai-llm` - OpenAI LLM（仅处理，不保存）
- ✅ `POST /api/receipt/gemini-llm` - Gemini LLM（仅处理，不保存）

---

## 🧪 测试流程

### 1. 测试未认证请求（应该失败）

```bash
curl -X GET "http://localhost:8000/api/auth/test-token"
```

**预期结果**：`401 Unauthorized`

### 2. 测试认证请求（应该成功）

```bash
# 先获取 token
python get_jwt_token.py

# 使用 token 测试
curl -X GET "http://localhost:8000/api/auth/test-token" \
  -H "Authorization: Bearer <token>"
```

**预期结果**：
```json
{
  "success": true,
  "message": "Authentication successful",
  "user_id": "user-uuid-here"
}
```

### 3. 测试 workflow 端点

```bash
curl -X POST "http://localhost:8000/api/receipt/workflow" \
  -H "Authorization: Bearer <token>" \
  -F "file=@receipt.jpg"
```

**预期结果**：正常的处理结果

---

## 📝 常见问题

### Q: 如何知道 token 是否过期？

A: 如果 token 过期，你会收到 `401 Unauthorized` 错误，错误信息是 `"Token has expired"`。解决方法：重新运行 `get_jwt_token.py` 获取新 token。

### Q: 可以在 Swagger UI 中测试吗？

A: 可以！这是最方便的方法：
1. 获取 JWT token
2. 打开 Swagger UI
3. 点击 **Authorize** 按钮
4. 输入 `Bearer <token>`
5. 所有 API 调用都会自动包含这个 token

### Q: token 有效期是多久？

A: Supabase 的 JWT token 默认有效期是 1 小时。过期后需要重新登录获取新 token。

### Q: 如何查看 token 的内容？

A: 你可以使用 [jwt.io](https://jwt.io) 来解码 token（不验证签名）。只需要粘贴 token，就能看到 payload 内容，包括 `user_id`（在 `sub` 字段中）。

---

## 🚀 下一步

完成认证设置后，你可以继续实现：

1. **使用量限制**（下一步）
   - 在 `users` 表添加 `monthly_quota_used` 字段
   - 在每次上传前检查配额

2. **Rate Limiting**（下一步）
   - 使用 `slowapi` 库
   - IP 级别限制：10 requests/minute
   - 用户级别限制：根据 user_class 设置不同限制

---

*最后更新：2026-01-31*
