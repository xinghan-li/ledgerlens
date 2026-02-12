# Database Migration Refactoring Summary
## 2026-02-11

## 🎯 目标

重构 database migrations，消除"弯路"，让 production 环境可以一次性构建到最终正确状态，而不需要经历开发过程中的实验性变更。

## 📝 问题背景

在开发过程中，我们的 migration 历史形成了一个"弯路"：

1. **001_schema_v2.sql** 创建了正确的 schema，使用简单的 stage 值
2. **008_update_current_stage.sql** 把 stage 值从简单改成复杂（实验性的"更好的调试"）
3. **011_simplify_receipts_stage_values.sql** 又把 stage 值从复杂改回简单（修正 008）

这导致：
- **新的 production 数据库**：不应该运行 008 和 011（它们互相抵消）
- **已有的 development 数据库**：必须运行 011 来修正 008 的影响
- **混乱**：不清楚哪些 migrations 应该在 production 运行

## ✅ 解决方案

### 1. 文件重组

**移动到 `deprecated/` 文件夹：**
- `008_update_current_stage.sql` - 错误的扩展
- `011_simplify_receipts_stage_values.sql` - 修正 008 的补丁

**保留在主目录（production 需要）：**
- `001_schema_v2.sql` - 核心 schema ✅
- `003_add_file_hash.sql` - 文件哈希 ✅
- `004_update_user_class.sql` - 用户类别 ✅
- `006_add_validation_status.sql` - 验证状态 ✅
- `007_add_chain_name_to_store_locations.sql` - 连锁店名称 ✅
- `009_tag_based_rag_system.sql` - Tag-based RAG ✅
- `010_update_costco_lynnwood_address.sql` - Costco 地址（可选）✅

### 2. 新增文档

**MIGRATIONS_README.md**
- 完整的 migration 执行指南
- 区分 production vs development 场景
- 清晰说明每个 migration 的用途和状态

**deprecated/README.md**
- 解释为什么这些 migrations 被废弃
- 什么情况下需要运行它们
- 数据迁移映射表

**PRODUCTION_SETUP.sql**
- 一键运行所有 production migrations
- 包含验证步骤
- 跳过 008 和 011

**REFACTORING_SUMMARY.md** (本文件)
- 重构的完整记录
- 问题背景和解决方案
- 未来参考指南

## 📊 最终文件结构

```
backend/database/
├── 📘 MIGRATIONS_README.md        (migration 执行指南)
├── 📘 REFACTORING_SUMMARY.md      (本文件 - 重构记录)
├── 📄 PRODUCTION_SETUP.sql        (一键 production setup)
├── ✅ 001_schema_v2.sql            (核心 schema)
├── ✅ 003_add_file_hash.sql        (文件哈希)
├── ✅ 004_update_user_class.sql    (用户类别)
├── ✅ 006_add_validation_status.sql (验证状态)
├── ✅ 007_add_chain_name_to_store_locations.sql (连锁店名称)
├── ✅ 009_tag_based_rag_system.sql (RAG 系统)
├── ✅ 010_update_costco_lynnwood_address.sql (Costco 地址)
├── 📘 2026-01-30 MIGRATION_NOTES.md
├── 📘 2026-01-31_MIGRATION_NOTES.md
└── deprecated/
    ├── 📘 README.md
    ├── ❌ 008_update_current_stage.sql
    └── 🔄 011_simplify_receipts_stage_values.sql
```

## 🚀 使用指南

### 场景 1：全新 Production 数据库

**方式 A：使用一键脚本**
```bash
# 在 Supabase SQL Editor 中运行
\i PRODUCTION_SETUP.sql
```

**方式 B：手动运行（推荐，更可控）**
```sql
-- 在 Supabase SQL Editor 依次运行：
001_schema_v2.sql
003_add_file_hash.sql
004_update_user_class.sql
006_add_validation_status.sql
007_add_chain_name_to_store_locations.sql
009_tag_based_rag_system.sql
010_update_costco_lynnwood_address.sql  -- 可选
```

### 场景 2：已有 Development 数据库（已运行 008）

```sql
-- 必须运行 011 来修正：
deprecated/011_simplify_receipts_stage_values.sql
```

### 场景 3：已有 Development 数据库（未运行 008）

**不需要任何操作！** 你的数据库已经是正确状态。

## 🔍 验证

运行后验证 schema 正确性：

```sql
-- 检查 receipts 约束
SELECT 
    conname, 
    pg_get_constraintdef(oid) 
FROM pg_constraint 
WHERE conrelid = 'receipts'::regclass 
AND conname = 'receipts_current_stage_check';

-- 预期结果：
-- CHECK (current_stage IN ('ocr', 'llm_primary', 'llm_fallback', 'manual'))
```

## 📈 受益

### ✅ 清晰度
- 明确区分 production migrations 和 development-only migrations
- 文档完整，任何人都能理解 migration 历史

### ✅ 可靠性
- Production 部署不会经历开发过程中的实验性变更
- 减少了出错的可能性

### ✅ 可维护性
- 未来添加新 migrations 时有清晰的模式可循
- deprecated 文件夹保留了历史记录，便于追溯

### ✅ 性能
- Production 数据库只运行必要的 migrations
- 不需要运行互相抵消的 migrations

## 🎓 经验教训

### 1. Schema Changes 应该与代码同步
- 问题：008 扩展了 stage 值，但代码仍使用简单值
- 教训：在修改数据库约束前，先确认代码实际使用的值

### 2. 实验性变更应该标记
- 问题：008 看起来像正式的 migration，实际是实验
- 教训：实验性变更应该明确标记或在单独分支进行

### 3. Migration 应该是单向的
- 问题：008 → 011 形成了往返循环
- 教训：避免创建需要被其他 migration 回滚的 migrations

### 4. 文档至关重要
- 问题：没有清晰的文档说明哪些 migrations 是必需的
- 教训：每个 migration 都应该有清晰的文档和使用场景说明

## 🔮 未来建议

### 1. Migration 命名规范
建议格式：`NNN_action_subject.sql`
- `NNN`: 3位数字序号（保持现有）
- `action`: add, update, remove, fix 等动词
- `subject`: 操作的对象

例如：
- ✅ `003_add_file_hash.sql`
- ✅ `007_add_chain_name_to_store_locations.sql`
- ❌ `008_update_current_stage.sql` (太宽泛)

### 2. Migration 分类标记
在文件头部添加标记：
```sql
-- CATEGORY: [SCHEMA|DATA|INDEX|CONSTRAINT|DEPRECATED]
-- REQUIRED_FOR: [PRODUCTION|DEVELOPMENT|BOTH]
-- DEPENDS_ON: [001, 003]
```

### 3. 自动化验证
创建脚本验证：
- Schema 约束是否与代码一致
- Migration 顺序是否正确
- Production 和 development 数据库状态一致性

### 4. Migration 测试
在 CI/CD 中添加：
- 在空数据库上运行所有 production migrations
- 验证最终 schema 符合预期
- 运行集成测试确保业务逻辑正常

## 📞 联系

如有问题或需要澄清，请参考：
- `MIGRATIONS_README.md` - 执行指南
- `deprecated/README.md` - 废弃 migrations 说明
- `2026-01-31_MIGRATION_NOTES.md` - 详细的数据迁移说明

## 🎉 总结

通过这次重构，我们：
1. ✅ 清理了 migration 历史中的"弯路"
2. ✅ 创建了清晰的 production deployment 路径
3. ✅ 完善了文档，让任何人都能理解 migration 策略
4. ✅ 为未来的 migration 管理建立了最佳实践

现在，你可以自信地部署到 production，知道数据库会一次性构建到正确的最终状态！🚀
