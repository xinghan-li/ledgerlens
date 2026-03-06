> **结论（归档原因）**：已实现。脚本已重组至 scripts/tools、diagnostic、test、maintenance 并配有 README。保留作历史参考。

# Backend 根目录脚本分析报告
## 2026-02-12

## 📊 当前状态

backend 根目录有 **19 个 Python 脚本**，需要整理分类。

---

## 📁 建议的文件夹结构

```
backend/
├── run_backend.py                    # ✅ 保留在根目录（主启动脚本）
│
└── scripts/                          # 新建：所有工具脚本
    ├── tools/                        # 常用工具
    │   ├── get_jwt_token.py
    │   ├── get_user_id.py
    │   ├── import_category_rules.py
    │   └── generate_standardization_preview.py
    │
    ├── diagnostic/                   # 诊断工具
    │   ├── check_database_connection.py
    │   ├── check_db_constraint.py
    │   ├── check_duplicates_detail.py
    │   ├── check_processing_runs.py
    │   ├── check_receipt_summaries_structure.py
    │   ├── check_tables.py
    │   └── view_processing_run_details.py
    │
    ├── test/                         # 测试脚本
    │   ├── test_aws_textract.py
    │   ├── test_categorization_api.py
    │   ├── test_phase1_data.py
    │   └── test_supabase_user.py
    │
    └── maintenance/                  # 维护/一次性脚本
        ├── backfill_phase1_data.py
        ├── clean_duplicate_receipts.py
        └── migrate_output_structure.py
```

---

## 📋 文件分类详情

### ✅ 保留在根目录（1个）

#### `run_backend.py`
- **用途**：启动 FastAPI 后端的主脚本
- **功能**：自动端口选择（8000-8084）、写入端口信息
- **理由**：这是启动入口，应该在根目录方便调用

---

### 🛠️ 工具脚本 - `scripts/tools/`（4个）

#### 1. `get_jwt_token.py` ⭐
- **用途**：从 Supabase Auth 获取 JWT token
- **使用频率**：高（开发测试时经常用）
- **价值**：帮助测试 API 认证

#### 2. `get_user_id.py` ⭐
- **用途**：获取用户 ID
- **使用频率**：中
- **价值**：测试时查找用户信息

#### 3. `import_category_rules.py` ⭐⭐⭐
- **用途**：从 CSV 导入分类规则到数据库
- **使用频率**：高（核心业务工具）
- **价值**：**关键工具**，用于分类规则管理
- **依赖**：需要配合 `generate_standardization_preview.py` 使用

#### 4. `generate_standardization_preview.py` ⭐⭐⭐
- **用途**：生成商品标准化预览 CSV
- **使用频率**：高（核心业务工具）
- **价值**：**关键工具**，用于人工审核标准化规则
- **输出**：`output/standardization_preview/standardization_summary_*.csv`

---

### 🔍 诊断脚本 - `scripts/diagnostic/`（7个）

#### 1. `check_database_connection.py` ⭐⭐
- **用途**：诊断数据库连接问题
- **功能**：检查环境变量、用户存在、能否创建 receipt
- **使用频率**：中（出现问题时使用）
- **价值**：非常有用的调试工具

#### 2. `check_db_constraint.py` ⭐
- **用途**：检查和修复 receipts 表约束
- **使用频率**：低（已解决的历史问题）
- **价值**：可能在未来遇到类似问题时有用

#### 3. `check_duplicates_detail.py` ⭐⭐
- **用途**：详细检查重复小票数据
- **使用频率**：中（数据清理时使用）
- **价值**：帮助识别和清理重复数据

#### 4. `check_processing_runs.py`
- **用途**：检查处理运行状态
- **使用频率**：待确认（需要读取文件）

#### 5. `check_receipt_summaries_structure.py`
- **用途**：检查 receipt_summaries 表结构
- **使用频率**：低（调试用）

#### 6. `check_tables.py`
- **用途**：检查数据库表
- **使用频率**：中

#### 7. `view_processing_run_details.py` ⭐
- **用途**：查看处理运行详情
- **使用频率**：中（调试时查看具体处理过程）
- **价值**：帮助理解小票处理流程

---

### 🧪 测试脚本 - `scripts/test/`（4个）

#### 1. `test_aws_textract.py`
- **用途**：测试 AWS Textract OCR
- **使用频率**：低（可能已不使用 AWS）
- **建议**：确认是否还在使用，如果不用可以删除

#### 2. `test_categorization_api.py`
- **用途**：测试 Categorization API
- **使用频率**：中（功能测试）
- **价值**：验证 categorization 功能

#### 3. `test_phase1_data.py`
- **用途**：测试 Phase 1 数据
- **使用频率**：低
- **建议**：确认 Phase 1 是否还在使用

#### 4. `test_supabase_user.py`
- **用途**：测试 Supabase 用户功能
- **使用频率**：低

---

### 🔧 维护脚本 - `scripts/maintenance/`（3个）

#### 1. `backfill_phase1_data.py`
- **用途**：为已有小票补充 Phase 1 数据
- **使用频率**：低（一次性任务）
- **价值**：数据迁移工具，执行后可能不再需要

#### 2. `clean_duplicate_receipts.py`
- **用途**：清理重复小票
- **使用频率**：低（一次性清理）
- **价值**：数据清理工具

#### 3. `migrate_output_structure.py`
- **用途**：迁移输出结构
- **使用频率**：低（一次性迁移）
- **价值**：历史迁移工具

---

## 🎯 清理建议

### 立即执行的操作

1. **创建文件夹结构**：
   ```bash
   mkdir -p backend/scripts/tools
   mkdir -p backend/scripts/diagnostic
   mkdir -p backend/scripts/test
   mkdir -p backend/scripts/maintenance
   ```

2. **移动常用工具**（移到 `scripts/tools/`）：
   - `get_jwt_token.py` ⭐
   - `get_user_id.py` ⭐
   - `import_category_rules.py` ⭐⭐⭐
   - `generate_standardization_preview.py` ⭐⭐⭐

3. **移动诊断工具**（移到 `scripts/diagnostic/`）：
   - `check_database_connection.py` ⭐⭐
   - `check_db_constraint.py`
   - `check_duplicates_detail.py` ⭐
   - `check_processing_runs.py`
   - `check_receipt_summaries_structure.py`
   - `check_tables.py`
   - `view_processing_run_details.py` ⭐

4. **移动测试脚本**（移到 `scripts/test/`）：
   - `test_aws_textract.py`
   - `test_categorization_api.py`
   - `test_phase1_data.py`
   - `test_supabase_user.py`

5. **移动维护脚本**（移到 `scripts/maintenance/`）：
   - `backfill_phase1_data.py`
   - `clean_duplicate_receipts.py`
   - `migrate_output_structure.py`

### 可选：需要确认的清理

1. **测试脚本审查**：
   - `test_aws_textract.py` - 确认是否还在使用 AWS Textract？
   - `test_phase1_data.py` - Phase 1 是否已完成？

2. **一次性脚本审查**：
   - `backfill_phase1_data.py` - 数据已回填？可以归档到 `agent-tbd/archived/`？
   - `migrate_output_structure.py` - 迁移已完成？可以删除？

---

## 📝 创建 README

在 `backend/scripts/` 下创建 `README.md`：

```markdown
# Backend Scripts

## 📁 文件夹说明

### tools/ - 常用工具
经常使用的工具脚本，支持日常开发和运维。

### diagnostic/ - 诊断工具
用于调试和诊断问题的脚本。

### test/ - 测试脚本
功能测试和集成测试脚本。

### maintenance/ - 维护脚本
数据迁移、清理等一次性维护任务。

## 🔧 常用命令

### 获取 JWT Token
```bash
python scripts/tools/get_jwt_token.py
```

### 导入分类规则
```bash
python scripts/tools/import_category_rules.py --csv path/to/file.csv
```

### 生成标准化预览
```bash
python scripts/tools/generate_standardization_preview.py
```

### 检查数据库连接
```bash
python scripts/diagnostic/check_database_connection.py
```
```

---

## ✅ 执行清单

- [ ] 创建 `backend/scripts/` 及子文件夹
- [ ] 移动 18 个脚本到对应文件夹
- [ ] 创建 `backend/scripts/README.md`
- [ ] 更新文档中引用这些脚本的路径
- [ ] 测试关键脚本是否仍能正常运行
- [ ] 删除或归档已完成的一次性脚本

---

## 💡 未来建议

1. **添加 `scripts/tools/` 到 PATH**：
   - 创建快捷命令别名
   - 例如：`ljwt` = `python scripts/tools/get_jwt_token.py`

2. **统一脚本入口**：
   - 考虑创建 `scripts/cli.py` 作为统一入口
   - 使用 Click 或 Typer 框架
   - 例如：`python scripts/cli.py jwt` 代替单独脚本

3. **脚本文档化**：
   - 每个脚本添加 `--help` 支持
   - 在 README 中添加使用示例

---

## 📊 优先级总结

### ⭐⭐⭐ 核心工具（必须保留）
- `import_category_rules.py`
- `generate_standardization_preview.py`

### ⭐⭐ 常用工具（建议保留）
- `get_jwt_token.py`
- `check_database_connection.py`
- `check_duplicates_detail.py`

### ⭐ 有用但不常用（可保留）
- 其他 check_* 和 test_* 脚本

### ❓ 需要确认（可能删除/归档）
- `test_aws_textract.py`
- `backfill_phase1_data.py`
- `migrate_output_structure.py`
