# 文件清理报告 - 2026-02-12

## 📋 清理目标
审查项目中所有 .md 和调试文件，识别哪些有用、哪些可以删除，并提出归档建议。

---

## 🗂️ 根目录文件分析

### 1. Prompt_in_Queue.md ❌ **删除**
**内容**：待办清单（Trader Joe's 分类、会员卡处理、税费逻辑）
**状态**：已过时，大部分已完成
**建议**：删除

### 2. FRONTEND_IMPLEMENTATION_SUMMARY.md ⚠️ **归档**
**内容**：前端实现的完整总结（技术栈、功能、下一步计划）
**价值**：有用的历史记录
**建议**：移到 `docs/frontend/IMPLEMENTATION_SUMMARY.md`

### 3. CATEGORIZATION_ARCHITECTURE.md ⚠️ **归档**
**内容**：Categorization 系统架构设计（数据流、API 使用、设计决策）
**价值**：重要的架构文档
**建议**：移到 `docs/architecture/CATEGORIZATION.md`

---

## 🗂️ backend/ 文件分析

### backend/tests/ 文件夹

#### ✅ **保留** (有用的文档)
- `README.md` - 测试说明
- `PIPELINE_FLOW.md` - Pipeline 流程图
- `TWO_APPROACHES_SUMMARY.md` - 方案对比
- `tag_matching_rules_explanation.md` - Tag 匹配规则说明

#### ⚠️ **移到 agent-tbd** (调试文档)
- `DEBUG_121422_DIAGNOSIS.md` - 特定小票的调试报告
- `DEBUG_LOGIC_DIAGNOSIS.md` - 逻辑错误诊断

**理由**：这两个是针对具体问题的调试记录，不是长期文档，但可能在回顾时有用。

---

### backend/docs/ 文件夹

#### ✅ **保留** (核心文档)
- `ARCHITECTURE.md` (应该在 backend/app/ 里)
- `AUTH_IMPLEMENTATION.md` - 认证实现
- `DATABASE_DESIGN.md` - 数据库设计
- `LLM_PROCESSING.md` - LLM 处理逻辑
- `UNIFIED_OCR_PROCESSING.md` - OCR 处理统一方案
- `SUPABASE_AUTH_SETUP.md` - Supabase 设置

#### ❌ **删除** (过时/重复)
- `GET_JWT_SECRET_STEP_BY_STEP.md` - 临时指导文档
- `NAVIGATE_TO_JWT_SECRET.md` - 临时指导文档

**理由**：这两个是给用户的临时指导，已经在 SETUP_GUIDE.md 中有更完整的说明。

---

### backend/config/ 文件夹

#### ✅ **保留**
- `PIPELINE_OUTPUT_STANDARD.md` - Pipeline 输出标准
- `store_receipts/README.md` - 商店配置说明
- `store_receipts/AGGREGATED_OUTPUT_AND_CSV.md` - 输出格式说明

---

### backend/app/processors/validation/ 文件夹

#### ⚠️ **归档价值评估**
- `VALIDATION_MODULES.md` - 验证模块说明
- `PIPELINE_V2_README.md` - Pipeline V2 文档
- `FEEDBACK_ANALYSIS.md` - 反馈分析

**建议**：这些是 validation 子系统的文档，保留在原处。但如果 V2 已不再使用，可以移到 `backend/agent-tbd/archived/`

---

### backend/app/processors/stores/ 文件夹

#### ✅ **保留**
- `README.md` - 商店处理器说明

---

### backend/app/middleware/ 文件夹

#### ✅ **保留**
- `README.md` - 中间件说明

---

### backend/ 根目录文件

#### ✅ **保留**
- `README.md` - 后端主文档
- `RATE_LIMITER_SETUP.md` - Rate limiter 配置
- `STORE_SPECIFIC_RULES_README.md` - 商店特定规则

---

### backend/database/ 文件夹

#### ✅ **已整理** (上一轮清理)
- `MIGRATIONS_README.md` - Migration 指南（保留）
- `CHECK_TABLES.sql` - 诊断工具（保留）
- `documents/` - 所有文档已归档
- `deprecated/` - 已废弃的 migrations

---

## 📊 清理建议汇总

### 立即删除 (5 个文件)
```bash
# 根目录
rm Prompt_in_Queue.md

# backend/docs/
rm backend/docs/GET_JWT_SECRET_STEP_BY_STEP.md
rm backend/docs/NAVIGATE_TO_JWT_SECRET.md
```

### 移动到 docs/ (2 个文件)
```bash
mkdir -p docs/frontend docs/architecture

# 根目录 → docs/
mv FRONTEND_IMPLEMENTATION_SUMMARY.md docs/frontend/IMPLEMENTATION_SUMMARY.md
mv CATEGORIZATION_ARCHITECTURE.md docs/architecture/CATEGORIZATION.md
```

### 移动到 backend/agent-tbd/ (2 个调试文件)
```bash
mv backend/tests/DEBUG_121422_DIAGNOSIS.md backend/agent-tbd/
mv backend/tests/DEBUG_LOGIC_DIAGNOSIS.md backend/agent-tbd/
```

---

## 🎯 清理后的目录结构

```
LedgerLens/
├── temp/                                    # 临时调试文件
├── docs/                                     # 项目级文档
│   ├── frontend/
│   │   └── IMPLEMENTATION_SUMMARY.md
│   └── architecture/
│       └── CATEGORIZATION.md
│
├── backend/
│   ├── agent-tbd/                           # AI 生成的待审查内容
│   │   ├── FILE_CLEANUP_REPORT_20260212.md (本文件)
│   │   ├── DEBUG_121422_DIAGNOSIS.md
│   │   └── DEBUG_LOGIC_DIAGNOSIS.md
│   ├── docs/                                # 后端核心文档（保留）
│   ├── tests/                               # 测试文档（保留，移除 DEBUG）
│   ├── config/                              # 配置文档（保留）
│   ├── database/
│   │   ├── MIGRATIONS_README.md
│   │   ├── CHECK_TABLES.sql
│   │   └── documents/                       # 数据库文档
│   └── app/
│       ├── processors/validation/           # 验证模块文档（保留）
│       ├── processors/stores/               # 商店处理器文档（保留）
│       └── middleware/                      # 中间件文档（保留）
```

---

## ✅ 执行清单

- [ ] 删除 3 个临时/过时文件
- [ ] 创建 `docs/frontend/` 和 `docs/architecture/` 文件夹
- [ ] 移动 2 个根目录文档到 `docs/`
- [ ] 移动 2 个调试文件到 `backend/agent-tbd/`
- [ ] 更新 `.cursor/rules/file-management.mdc` 规则文件

---

## 📝 文件管理规范（未来）

### 放在 backend/agent-tbd/
- 调试诊断报告
- 临时分析文档
- 待确认的架构设计
- 实验性功能文档

### 放在 temp/
- 调试输出（JSON, logs）
- 测试结果
- 临时脚本
- "阅后即焚"文件

### 放在 docs/
- 架构设计（architecture/）
- 用户指南（guides/）
- 前端文档（frontend/）
- 决策记录（decisions/）

### 放在 backend/docs/
- 后端核心文档
- API 文档
- 数据库设计
- 认证/授权文档
