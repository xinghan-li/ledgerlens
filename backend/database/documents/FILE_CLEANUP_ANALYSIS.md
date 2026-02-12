# Database 文件夹清理分析

## 📁 当前非标准命名的文件（11个）

### 🗑️ 可以删除的文件（临时/调试用）

#### 1. **check_constraint.sql** ❌ 删除
- **用途**：检查 receipts 表的约束定义
- **原因**：临时调试用，现在约束已修复（Migration 011）
- **替代**：可以用 `CHECK_TABLES.sql` 或直接查询

#### 2. **fix_constraint.sql** ❌ 删除  
- **用途**：修复 receipts_current_stage_check 约束
- **原因**：已被 Migration 011 正式化（deprecated/011_simplify_receipts_stage_values.sql）
- **替代**：如果需要修复，运行 Migration 011

#### 3. **CHECK_RECEIPT_SUMMARIES.sql** ❌ 删除
- **用途**：检查 receipt_summaries 表结构
- **原因**：今天早上刚创建的临时检查脚本
- **替代**：可以用 `CHECK_TABLES.sql`

---

### 📋 保留的文档文件

#### 4. **MIGRATIONS_README.md** ✅ 保留
- **用途**：Migration 执行指南
- **原因**：重要！解释哪些 migrations 是 production 需要的，哪些是 deprecated
- **重要性**：★★★★★

#### 5. **REFACTORING_SUMMARY.md** ✅ 保留
- **用途**：数据库 migration 重构记录（2026-02-11）
- **原因**：重要！记录了为什么 008/011 被移到 deprecated
- **重要性**：★★★★☆

#### 6. **MIGRATIONS_ORDER.md** ⚠️ 可以合并
- **用途**：说明 migration 执行顺序
- **原因**：与 `MIGRATIONS_README.md` 内容重复
- **建议**：合并到 `MIGRATIONS_README.md` 中

#### 7. **CHECK_USER_CREATION.md** ✅ 保留
- **用途**：解释 Migration 013（自动创建用户机制）
- **原因**：有用的文档，解释了 auth.users → public.users 的触发器
- **重要性**：★★★☆☆

#### 8. **PRODUCT_CATALOG_DESIGN.md** ✅ 保留
- **用途**：产品目录系统的完整设计文档
- **原因**：详细解释了 014-018 migrations 的设计思路
- **重要性**：★★★★☆

#### 9. **2026-01-30 MIGRATION_NOTES.md** ✅ 保留
- **用途**：2026-01-30 的 migration 历史记录
- **原因**：历史文档，记录了早期的数据库设计决策
- **重要性**：★★★☆☆

#### 10. **2026-01-31_MIGRATION_NOTES.md** ✅ 保留
- **用途**：2026-01-31 的详细 migration 笔记
- **原因**：包含数据回填说明、设计决策等重要信息
- **重要性**：★★★★☆

---

### 🧪 保留的工具文件

#### 11. **CHECK_TABLES.sql** ✅ 保留
- **用途**：快速检查数据库中存在哪些表
- **原因**：有用的诊断工具
- **重要性**：★★☆☆☆

---

## 📊 清理建议总结

### 🗑️ 立即删除（3个）：
```bash
backend/database/check_constraint.sql
backend/database/fix_constraint.sql  
backend/database/CHECK_RECEIPT_SUMMARIES.sql
```

### 📝 合并建议（1个）：
```
MIGRATIONS_ORDER.md → 合并到 MIGRATIONS_README.md
```

### ✅ 保留（7个）：
```
MIGRATIONS_README.md          ★★★★★ (关键文档)
REFACTORING_SUMMARY.md        ★★★★☆ (重构记录)
CHECK_USER_CREATION.md        ★★★☆☆ (013 说明)
PRODUCT_CATALOG_DESIGN.md     ★★★★☆ (014-018 设计)
2026-01-30 MIGRATION_NOTES.md ★★★☆☆ (历史记录)
2026-01-31_MIGRATION_NOTES.md ★★★★☆ (详细笔记)
CHECK_TABLES.sql              ★★☆☆☆ (诊断工具)
```

---

## 🎯 清理后的目录结构

```
backend/database/
├── 📘 文档（必需）
│   ├── MIGRATIONS_README.md (总指南)
│   ├── REFACTORING_SUMMARY.md (重构记录)
│   ├── CHECK_USER_CREATION.md (013 说明)
│   ├── PRODUCT_CATALOG_DESIGN.md (014-018 设计)
│   ├── 2026-01-30 MIGRATION_NOTES.md (历史)
│   └── 2026-01-31_MIGRATION_NOTES.md (详细笔记)
│
├── 🛠️ 工具（可选保留）
│   └── CHECK_TABLES.sql
│
├── ✅ Migrations (Production)
│   ├── 001_schema_v2.sql
│   ├── 003_add_file_hash.sql
│   ├── 004_update_user_class.sql
│   ├── 006_add_validation_status.sql
│   ├── 007_add_chain_name_to_store_locations.sql
│   ├── 009_tag_based_rag_system.sql
│   ├── 010_update_costco_lynnwood_address.sql
│   ├── 012_add_receipt_items_and_summaries.sql
│   ├── 013_auto_create_user_on_signup.sql
│   ├── 014_add_brands_table.sql
│   ├── 015_add_categories_tree.sql
│   ├── 016_add_products_catalog.sql
│   ├── 017_link_receipt_items_to_products.sql
│   ├── 018_add_price_snapshots.sql
│   └── 019_add_categorization_rules.sql
│
└── 📁 deprecated/
    ├── README.md
    ├── 008_update_current_stage.sql
    └── 011_simplify_receipts_stage_values.sql
```

---

## 💡 建议操作

### 立即执行：
```bash
cd backend/database
rm check_constraint.sql
rm fix_constraint.sql
rm CHECK_RECEIPT_SUMMARIES.sql
```

### 可选优化：
将 `MIGRATIONS_ORDER.md` 的内容合并到 `MIGRATIONS_README.md` 中，然后删除 `MIGRATIONS_ORDER.md`

---

## 🔍 各文件详细说明

### check_constraint.sql (❌ 删除)
```sql
-- 只是检查约束，没有实际操作
SELECT conname, pg_get_constraintdef(oid) 
FROM pg_constraint 
WHERE conrelid = 'receipts'::regclass;
```
**用途**：调试 Migration 011 时的临时文件

### fix_constraint.sql (❌ 删除)
```sql
-- 修复约束，但已被 Migration 011 正式化
ALTER TABLE receipts DROP CONSTRAINT ...
ALTER TABLE receipts ADD CONSTRAINT ...
```
**用途**：临时修复脚本，现在有正式的 Migration 011 了

### CHECK_RECEIPT_SUMMARIES.sql (❌ 删除)
```sql
-- 检查 receipt_summaries 表，今天早上创建的
SELECT * FROM information_schema.columns ...
```
**用途**：今天早上的临时检查脚本，可以用 CHECK_TABLES.sql 替代
