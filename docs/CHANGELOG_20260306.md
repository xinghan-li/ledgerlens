# Changelog — 2026-03-06

准备合并到 production 的改动摘要（基于 fix/frontend-features 与当前工作区 diff）。

---

## 前端（主要改动）

- **Dashboard**
  - `dashboard/layout.tsx`：布局与鉴权加载逻辑调整
  - `dashboard/page.tsx`：列表展示、操作流程与状态管理优化（约 500+ 行变动）
- **数据分析**
  - `DataAnalysisSection.tsx`：数据拉取与展示逻辑更新
- **相机**
  - `CameraCaptureButton.tsx`：拍照/上传交互与错误处理改进
- **开发者页**
  - `developer/page.tsx`：页面结构重构与功能整理（约 300 行变动）
- **管理端**
  - `admin/layout.tsx`：管理布局小调整
  - 新增 `admin/user-management/`：用户管理相关页面
- **样式与配置**
  - `globals.css`、`tailwind.config.js`：主题与样式微调

---

## 后端

### 多一轮 LLM + Prompt 调整

- **Vision 流程**（`workflow_processor_vision.py`）：在首轮识别后，对匹配到门店的小票增加**第二轮 LLM**，使用校正后的信息 + 门店定制 prompt 做精修（如 Costco 折扣行合并等）
- **Prompt**
  - `prompt_loader.py`：支持从 DB 加载 second-round / 门店定制 prompt（如 `receipt_parse_second_common`、Costco 第二轮）
  - `prompt_manager.py`：与 prompt_loader 的集成与 key 使用方式更新
- **数据库**
  - **052_costco_discount_line_prompt.sql**：Costco 第二轮 prompt（折扣行合并到上一行、original_price、is_on_sale、sum check）
  - **053_user_class_integer.sql**：`users.user_class` 由 TEXT 改为 SMALLINT（0=free, 2=premium, 7=admin, 9=super_admin）
  - 文档：`STORE_SPECIFIC_PROMPTS.md` 说明门店定制与第二轮 prompt 的用法

### 性能优化（后端即可生效）

- **鉴权**
  - `jwt_auth.py`：增加 **token → user_id 短 TTL 缓存**（5 分钟），同一 token 在 TTL 内不再重复走 Firebase 校验 + Supabase get_or_create，减轻刷新/列表/删除等接口延迟；并去掉每请求的 warning 级调试日志
- **列表**
  - `supabase_client.py`：`list_receipts_by_user` 中 **record_summaries 与 fallback LLM merchant name 查询改为并行**（ThreadPoolExecutor），减少一次 Supabase 往返
- **删除**
  - `failed_receipts_service.py`：删除小票时 **api_calls 与 store_candidates 的清理 update 改为并行**，再执行 receipt_status delete，少一次串行往返

### 其他后端

- `workflow_processor.py`：与 prompt/initial-parse 等的小幅调整
- `address_matcher.py`：地址匹配逻辑更新
- `rate_limiter.py`：与 user_class 整型化及 admin 豁免规则一致
- `main.py`：路由与依赖的小幅修改
- `firebase_auth.py`、`init_deposit_fee_rag.py`：小改动

---

## 未跟踪 / 可选

- `backend/agent-tbd/PRODUCTION_SLOW_LOADING_ANALYSIS_20260306.md`：生产环境 Loading/Deleting 慢的分析与建议（可归档或删除）
- `backend/database/scripts/VERIFY_*.sql`：Schema/系统数据校验脚本，按需运行

---

## 部署前提醒

1. 若上线 053，需先执行 **053_user_class_integer.sql**（或已纳入迁移流程）；052 若未跑过需执行 **052_costco_discount_line_prompt.sql**。
2. 生产环境建议在合并后做一次短回归：登录 → 列表加载 → 删除一条 → 上传/相机一条，确认无报错且体感延迟改善。
