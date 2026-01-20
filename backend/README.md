# Receipt OCR Backend

基于 FastAPI 的最小化收据 OCR 后端，使用 Google Cloud Vision API 和 Supabase。

## 功能特性

- 接收收据图片上传（JPEG/PNG）
- 使用 Google Cloud Vision API 进行文档文本检测（OCR）
- 将 OCR 结果和元数据存储到 Supabase（PostgreSQL）
- 返回提取的文本内容

## 项目结构

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 应用和路由
│   ├── config.py            # 配置管理（Pydantic）
│   ├── vision_client.py     # Google Cloud Vision 客户端
│   ├── supabase_client.py   # Supabase 客户端
│   └── models.py            # Pydantic 数据模型
├── tests/
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## 安装和设置

### 1. 创建虚拟环境

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env.example` 到 `.env` 并填写实际值：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# Google Cloud Platform
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/vision-service-account.json
GCP_PROJECT_ID=your-gcp-project-id

# Google Document AI (可选，用于 /api/receipt/g-document-ai 端点)
# 从 Document AI processor 详情页复制 endpoint URL
DOCUMENTAI_ENDPOINT=https://us-documentai.googleapis.com/v1/projects/YOUR_PROJECT/locations/us/processors/YOUR_PROCESSOR_ID:process
# 或者直接指定 processor name
# DOCUMENTAI_PROCESSOR_NAME=projects/YOUR_PROJECT_ID/locations/us/processors/YOUR_PROCESSOR_ID

# OpenAI Configuration (用于 /api/receipt/llm-process 端点)
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-4o-mini  # 可选，默认 gpt-4o-mini，可改为 gpt-4o, gpt-4-turbo 等

# Supabase
SUPABASE_URL=https://YOUR-PROJECT.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY

# Application
ENV=local
LOG_LEVEL=info

# Test User ID (for development only)
# 注意：这个 user_id 必须在 Supabase auth.users 表中存在
# 在 Supabase Dashboard > Authentication > Users 中创建一个测试用户，然后复制其 UUID
TEST_USER_ID=your-test-user-uuid-here
```

**重要提示：** `TEST_USER_ID` 是必需的，因为 `receipts` 表有外键约束，要求 `user_id` 必须存在于 `auth.users` 表中。

**如何获取测试用户 ID：**
1. 登录 Supabase Dashboard
2. 进入 **Authentication > Users**
3. 创建一个测试用户（或使用现有用户）
4. 复制用户的 **UUID**
5. 将 UUID 填入 `.env` 文件的 `TEST_USER_ID`

### 4. 设置 Supabase 数据库

在 Supabase SQL 编辑器中执行以下 SQL 创建表：

```sql
CREATE TABLE IF NOT EXISTS receipts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT,
  filename TEXT NOT NULL,
  raw_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 5. 获取 Google Cloud 服务账号密钥

1. 在 Google Cloud Console 中创建服务账号
2. 授予 `Cloud Vision API User` 角色
3. 下载 JSON 密钥文件
4. 将文件路径填入 `.env` 中的 `GOOGLE_APPLICATION_CREDENTIALS`

## 运行服务器

```bash
uvicorn app.main:app --reload --port 8000
```

服务器将在 `http://127.0.0.1:8000` 启动。

API 文档可在 `http://127.0.0.1:8000/docs` 查看。

## API 端点

### 健康检查

```bash
GET /health
```

响应：
```json
{
  "status": "ok"
}
```

### Google Document AI 解析收据

使用 Google Document AI Expense Parser 解析收据（不保存到数据库）：

```bash
POST /api/receipt/g-document-ai
```

**请求：**
- Content-Type: `multipart/form-data`
- 参数：`file` (图片文件，JPEG 或 PNG)

**响应：**
返回 Document AI 提取的完整结构化数据

**示例（curl）：**
```bash
curl -X POST "http://127.0.0.1:8000/api/receipt/g-document-ai" \
  -F "file=@/path/to/receipt.jpg"
```

**配置要求：**
- 在 `.env` 文件中设置 `DOCUMENTAI_ENDPOINT` 或 `DOCUMENTAI_PROCESSOR_NAME`
- 需要 Google Cloud 服务账号密钥文件（`GOOGLE_APPLICATION_CREDENTIALS`）

### OCR 收据

```bash
POST /api/receipts/ocr
```

**请求：**
- Content-Type: `multipart/form-data`
- 参数：`file` (图片文件，JPEG 或 PNG)

**响应：**
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "filename": "receipt.jpg",
  "text": "提取的 OCR 文本内容..."
}
```

**示例（curl）：**

```bash
curl -X POST "http://127.0.0.1:8000/api/receipts/ocr" \
  -F "file=@/path/to/receipt.jpg"
```

**示例（Python）：**

```python
import requests

url = "http://127.0.0.1:8000/api/receipts/ocr"
with open("receipt.jpg", "rb") as f:
    files = {"file": f}
    response = requests.post(url, files=files)
    print(response.json())
```

## 限制

- 仅支持 JPEG 和 PNG 格式
- 文件大小限制：5MB
- 当前未实现用户认证（`user_id` 为 `None`）

## 技术栈

- **FastAPI**: Web 框架
- **Uvicorn**: ASGI 服务器
- **Google Cloud Vision API**: OCR 服务
- **Google Cloud Document AI**: 结构化文档解析
- **OpenAI API**: LLM 结构化重建和验证
- **Supabase**: 数据库和存储（包含 RAG prompts）
- **Pydantic**: 数据验证和设置管理

## LLM 处理系统

系统支持使用 **Document AI + LLM** 进行高精度收据解析。详见 [LLM Processing 文档](docs/LLM_PROCESSING.md)。

### 快速开始

1. 配置 OpenAI API Key：
   ```env
   OPENAI_API_KEY=sk-your-key-here
   ```

2. 创建 merchant_prompts 表：
   ```sql
   -- 运行 database/002_merchant_prompts.sql
   ```

3. 使用新的 API 端点：
   ```bash
   curl -X POST "http://127.0.0.1:8000/api/receipt/llm-process" \
     -F "file=@/path/to/receipt.jpg"
   ```

## 开发

### 运行测试

```bash
# 待实现
pytest tests/
```

### 代码格式

```bash
# 建议使用 black 和 isort
black app/
isort app/
```

## 许可证

MIT
