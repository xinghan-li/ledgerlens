# AI Agent 文件管理指南

> 📌 **给 AI Agent 的重要说明**：请在创建文件前仔细阅读本指南，确保文件放在正确的位置。

---

## 🎯 核心原则

**避免在 `backend/` 根目录创建临时文件和文档！**

`backend/` 是业务代码目录，应该只包含：
- `app/` - 应用代码
- `config/` - 配置文件
- `database/` - 数据库 migrations
- `scripts/` - 工具脚本
- `run_backend.py` - 启动脚本
- `.env` - 环境变量

---

## 📁 文件分类规则

### 1. 🤖 AI 生成的业务分析 → `backend/agent-tbd/`

**放置这里**：
- 调试诊断报告（如 `DEBUG_*_DIAGNOSIS.md`）
- 业务逻辑分析（如 `*_ANALYSIS.md`）
- 架构设计草稿
- 功能实现建议
- 待用户审查的文档

**特点**：
- 与业务逻辑相关
- 需要用户 review
- 不确定是否长期保留

**示例**：
```
backend/agent-tbd/
├── FILE_CLEANUP_REPORT_20260212.md
├── BACKEND_SCRIPTS_ANALYSIS_20260212.md
├── DEBUG_121422_DIAGNOSIS.md
└── ARCHITECTURE_DRAFT.md
```

---

### 2. 🗂️ 永久项目文档 → `docs/`

**放置这里**：
- 架构设计（`docs/architecture/`）
- 前端文档（`docs/frontend/`）
- 用户指南（`docs/guides/`）
- 决策记录（`docs/decisions/`）

**特点**：
- 长期保留
- 正式文档
- 面向团队或用户

**示例**：
```
docs/
├── architecture/
│   └── CATEGORIZATION.md
├── frontend/
│   └── IMPLEMENTATION_SUMMARY.md
└── guides/
    └── GETTING_STARTED.md
```

---

### 3. 🗄️ 数据库文档 → `backend/database/documents/`

**放置这里**：
- Migration 说明
- 数据库设计文档
- Schema 变更记录
- 重构总结

**特点**：
- 数据库相关
- 技术文档
- 供开发者参考

**示例**：
```
backend/database/documents/
├── PRODUCT_CATALOG_DESIGN.md
├── REFACTORING_SUMMARY.md
└── 2026-01-31_MIGRATION_NOTES.md
```

---

### 4. 🛠️ 工具脚本 → `backend/scripts/`

**按功能分类**：

#### `scripts/tools/` - 常用开发工具 ⭐⭐⭐
- JWT token 获取
- 分类规则导入
- 数据预览生成
- 其他日常工具

#### `scripts/diagnostic/` - 诊断工具 🔍
- 数据库连接检查
- 约束检查
- 重复数据检查
- 处理运行查看

#### `scripts/test/` - 测试脚本 🧪
- API 测试
- 功能测试
- 集成测试

#### `scripts/maintenance/` - 维护脚本 🔧
- 数据回填
- 清理任务
- 一次性迁移

**特点**：
- Python 脚本
- 可执行工具
- 辅助开发/运维

---

### 5. 🗑️ 临时调试文件 → `temp/`

**放置这里**：
- JSON 调试输出
- 日志文件
- 测试结果
- 临时脚本

**特点**：
- 非业务相关
- 阅后即焚
- 不需要 review

**示例**：
```
temp/
├── debug_output.json
├── test_results.txt
└── temp_script.py
```

---

### 6. ✅ 正常业务代码 → 对应功能文件夹

**按功能放置**：
- 服务代码 → `backend/app/services/`
- 处理器 → `backend/app/processors/`
- API 路由 → `backend/app/routers/`
- 工具函数 → `backend/app/utils/`
- 前端组件 → `frontend/app/components/`

**重要**：
- 不要因为是 AI 生成就放特殊位置
- 按正常项目结构组织
- 遵循代码规范

---

## 🚫 禁止的操作

### ❌ 永远不要在项目根目录创建 .md 文件

**错误**：
```
LedgerLens/
├── ANALYSIS.md              # ❌ 不要这样
├── DEBUG_REPORT.md          # ❌ 不要这样
└── SUMMARY.md               # ❌ 不要这样
```

**正确**：
```
LedgerLens/
├── backend/agent-tbd/
│   ├── ANALYSIS_20260212.md           # ✅ 这样
│   └── DEBUG_REPORT_20260212.md       # ✅ 这样
└── docs/
    └── architecture/
        └── SUMMARY.md                 # ✅ 这样（如果是永久文档）
```

### ❌ 不要在 backend/ 根目录堆积文件

**错误**：
```
backend/
├── check_something.py       # ❌ 应该在 scripts/diagnostic/
├── test_feature.py          # ❌ 应该在 scripts/test/
├── my_tool.py               # ❌ 应该在 scripts/tools/
└── NOTES.md                 # ❌ 应该在 agent-tbd/
```

---

## 🎯 工作流程

### 创建分析/调试文档

1. **确定类型**：
   - 业务相关分析？→ `backend/agent-tbd/`
   - 永久架构文档？→ `docs/architecture/`
   - 数据库相关？→ `backend/database/documents/`

2. **命名规范**：
   - 加上日期：`FILENAME_YYYYMMDD.md`
   - 描述性名称：`DEBUG_RECEIPT_PARSING_20260212.md`

3. **任务完成后询问用户**：
   ```
   我在 backend/agent-tbd/ 创建了以下文件：
   - FILE_ANALYSIS_20260212.md
   
   这些文件：
   □ 要归档到 docs/？
   □ 要删除？
   □ 暂时保留？
   ```

### 创建工具脚本

1. **确定分类**：
   - 日常使用？→ `scripts/tools/`
   - 诊断问题？→ `scripts/diagnostic/`
   - 测试功能？→ `scripts/test/`
   - 一次性任务？→ `scripts/maintenance/`

2. **不要放在 backend/ 根目录**

3. **在 `backend/scripts/README.md` 中添加说明**

### 清理临时文件

定期询问用户：
```
以下位置有临时文件：
- temp/ (3 个文件)
- backend/agent-tbd/ (5 个文件)

要我清理吗？
```

---

## 📊 决策树

```
创建文件？
├─ 是调试输出/日志？
│  └─ → temp/
│
├─ 是业务逻辑分析？
│  └─ → backend/agent-tbd/
│
├─ 是永久项目文档？
│  ├─ 架构设计？→ docs/architecture/
│  ├─ 前端文档？→ docs/frontend/
│  └─ 数据库文档？→ backend/database/documents/
│
├─ 是 Python 脚本工具？
│  ├─ 日常工具？→ backend/scripts/tools/
│  ├─ 诊断工具？→ backend/scripts/diagnostic/
│  ├─ 测试脚本？→ backend/scripts/test/
│  └─ 维护任务？→ backend/scripts/maintenance/
│
└─ 是业务代码？
   └─ → backend/app/* 或 frontend/app/*
```

---

## ✅ 检查清单

创建文件前，问自己：

- [ ] 这个文件放的位置符合分类规则吗？
- [ ] 文件名包含日期了吗（如果是临时/分析文件）？
- [ ] 我没有在项目根目录或 backend/ 根目录创建文件吗？
- [ ] 如果是脚本，我放在 `backend/scripts/` 的正确子文件夹了吗？
- [ ] 如果是文档，我选择了正确的 docs/ 子文件夹吗？

---

## 📚 相关规则

- Cursor 规则：`.cursor/rules/file-management.mdc`
- Backend 脚本说明：`backend/scripts/README.md`
- 数据库 Migration 指南：`backend/database/MIGRATIONS_README.md`

---

## 🎉 总结

**核心思想**：

1. **backend/ 只放业务代码和脚本，不放文档**
2. **临时分析 → agent-tbd/**
3. **永久文档 → docs/**
4. **工具脚本 → scripts/**
5. **调试输出 → temp/**

遵循这些规则，项目结构会一直保持清晰整洁！🚀
