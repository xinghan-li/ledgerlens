# Backend Scripts

本目录包含所有后端辅助脚本，按功能分类存放。

---

## 📁 目录结构

```
scripts/
├── tools/          # 常用开发工具
├── diagnostic/     # 诊断调试工具
├── test/           # 测试脚本
└── maintenance/    # 维护/一次性任务脚本
```

---

## 🛠️ tools/ - 常用工具

### get_jwt_token.py ⭐⭐
获取 Supabase JWT token 用于 API 测试。

```bash
python backend/scripts/tools/get_jwt_token.py
```

### get_user_id.py
查询用户 ID。

```bash
python backend/scripts/tools/get_user_id.py
```

### import_category_rules.py ⭐⭐⭐
从 CSV 导入商品分类规则到数据库。

```bash
python backend/scripts/tools/import_category_rules.py --csv path/to/file.csv
```

**工作流程**：
1. 运行 `generate_standardization_preview.py` 生成 CSV
2. 人工修正 CSV 中的分类
3. 运行此脚本导入规则

### generate_standardization_preview.py ⭐⭐⭐
生成商品标准化预览 CSV 供人工审核。

```bash
python backend/scripts/tools/generate_standardization_preview.py
```

**输出位置**：`output/standardization_preview/standardization_summary_*.csv`

---

## 🔍 diagnostic/ - 诊断工具

### check_database_connection.py ⭐⭐
检查数据库连接和配置。

```bash
python backend/scripts/diagnostic/check_database_connection.py
```

**检查内容**：
- 环境变量配置
- 用户是否存在
- 能否创建 receipt

### check_db_constraint.py
检查和诊断数据库约束问题。

```bash
python backend/scripts/diagnostic/check_db_constraint.py
```

### check_duplicates_detail.py ⭐
检查重复小票数据。

```bash
python backend/scripts/diagnostic/check_duplicates_detail.py
```

### check_processing_runs.py
检查处理运行状态。

### check_receipt_summaries_structure.py
检查 receipt_summaries 表结构。

### check_tables.py
检查数据库表。

### view_processing_run_details.py ⭐
查看小票处理运行详情。

```bash
python backend/scripts/diagnostic/view_processing_run_details.py
```

---

## 🧪 test/ - 测试脚本

### test_aws_textract.py
测试 AWS Textract OCR（如果使用）。

### test_categorization_api.py
测试 Categorization API 功能。

### test_phase1_data.py
测试 Phase 1 数据功能。

### test_supabase_user.py
测试 Supabase 用户功能。

---

## 🔧 maintenance/ - 维护脚本

### backfill_phase1_data.py
为已有小票补充 Phase 1 数据（一次性任务）。

### clean_duplicate_receipts.py
清理重复小票数据。

### migrate_output_structure.py
迁移输出结构（历史任务）。

---

## 💡 使用建议

### 日常开发
- 需要测试 API？→ `tools/get_jwt_token.py`
- 管理分类规则？→ `tools/generate_standardization_preview.py` + `tools/import_category_rules.py`

### 遇到问题
- 数据库连不上？→ `diagnostic/check_database_connection.py`
- 有重复数据？→ `diagnostic/check_duplicates_detail.py`
- 处理失败了？→ `diagnostic/view_processing_run_details.py`

### 测试功能
- 所有测试脚本在 `test/` 目录

---

## 📝 注意事项

1. **环境变量**：大部分脚本需要 `.env` 文件配置
2. **工作目录**：脚本应从项目根目录运行（`F:/LedgerLens/`）
3. **权限**：诊断和维护脚本可能需要 `SUPABASE_SERVICE_ROLE_KEY`

---

## 🔗 相关文档

- 主项目文档：`README.md`
- 数据库 Migrations：`backend/database/MIGRATIONS_README.md`
- 分类规则说明：`backend/STORE_SPECIFIC_RULES_README.md`
