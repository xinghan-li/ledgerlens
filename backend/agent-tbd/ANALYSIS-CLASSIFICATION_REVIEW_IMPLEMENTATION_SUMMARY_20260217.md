# Classification Review 与 Admin Dashboard 实施总结

**日期**: 2026-02-17  
**依据**: Plan « Classification Review Table and Admin Dashboard »（待办 1–8）

---

## 1. 已完成项

### 1.1 Migration 025：classification_review 表

- **文件**: `backend/database/025_add_classification_review.sql`
- **内容**:
  - 新建表 `classification_review`，字段：id, raw_product_name, normalized_name（可空）, category_id（可空）, store_chain_id, size, unit_type, match_type（默认 exact）, source_record_item_id, status（pending/confirmed/unable_to_decide/deferred/cancelled）, created_at, updated_at, confirmed_at, confirmed_by
  - 索引：status, created_at；以及 (raw_product_name, store_chain_id) WHERE status = 'pending' 用于去重查询
  - 外键：categories, store_chains, record_items, users
- **说明**: normalized_name / category_id 允许为空，便于小票流程自动插入时只填 raw_product_name 等，由 Admin 在界面补全后再 Confirm。

### 1.2 后端：小票流程集成（未命中项入 CR + 去重）

- **文件**:
  - `backend/app/services/database/supabase_client.py`: 新增 `enqueue_unmatched_items_to_classification_review(receipt_id)`。
  - `backend/app/services/categorization/receipt_categorizer.py`: 在 `categorize_receipt` 中，在 `save_receipt_items` 成功后调用上述函数。
- **逻辑**:
  - 从 `record_summaries` 取该 receipt 的 `store_chain_id`。
  - 从 `record_items` 取该 receipt 下 `category_id IS NULL` 的行（id, product_name）。
  - 对每一行：若已存在同 (raw_product_name, store_chain_id) 且 status=pending 的 CR 行则跳过；否则 insert 一行（raw_product_name, source_record_item_id, store_chain_id, status=pending）。
- **结果**: 上传小票并成功 categorize 后，未命中分类的商品会自动进入 classification_review，且同品名同店链不重复插入。

### 1.3 后端：Classification Review CRUD + Confirm API

- **文件**:
  - `backend/app/services/admin/classification_review_service.py`: 列表、单条获取、PATCH、Confirm 逻辑。
  - `backend/app/main.py`: 注册 Admin 路由（均依赖 `require_admin`）。
- **接口**:
  - `GET /api/admin/classification-review`  
    查询参数：status, limit, offset。返回 data + total；每条带 category_name/category_path、store_chain_name。
  - `GET /api/admin/classification-review/suggest-normalized?q=...&limit=20`  
    从 products 与 product_categorization_rules 的 normalized_name 做 ilike 建议，供前端 autocomplete。
  - `PATCH /api/admin/classification-review/{cr_id}`  
    Body: normalized_name, category_id, store_chain_id, size, unit_type, match_type, status。对 normalized_name 做规范化（见下）。
  - `POST /api/admin/classification-review/{cr_id}/confirm`  
    Body 可选：`force_different_name: true` 跳过相似名检查。  
    逻辑：校验 normalized_name、category_id 已填；规范化 normalized_name；可选相似度检查（rapidfuzz），若存在高相似且未传 force_different_name 则返回 409 及 similar_to；写入 product_categorization_rules（upsert）与 products（select 后 update 或 insert）；将 CR 行设为 status=confirmed、confirmed_at、confirmed_by。
- **规范化**: 使用 `app.services.standardization.product_normalizer.normalize_name_for_storage`：全小写、trim、简单单数化（尾 -es/-s）。PATCH 与 Confirm 前对 normalized_name 应用。

### 1.4 后端：Categories 树接口 + Category 管理 API

- **文件**: `backend/app/services/admin/categories_admin_service.py`，以及 `main.py` 中 Admin Categories 路由。
- **接口**:
  - `GET /api/admin/categories?active_only=true`  
    返回扁平列表：id, parent_id, name, path, level, is_active, is_system。前端可据此建树或级联下拉。
  - `POST /api/admin/categories`  
    Body: parent_id（null 表示 L1）, name, level。同名同 parent 已存在则 409。
  - `PATCH /api/admin/categories/{cat_id}`  
    Body: name。更新 name（存为小写）。
  - `DELETE /api/admin/categories/{cat_id}`  
    软删：is_active = false。

### 1.5 后端：normalized_name 建议接口

- 已包含在 1.3：`GET /api/admin/classification-review/suggest-normalized?q=...`，从 products 与 product_categorization_rules 取 normalized_name 做 ilike 过滤并去重返回。

### 1.6 前端：Admin 权限与入口

- **文件**: `frontend/app/admin/layout.tsx`，以及 `frontend/app/dashboard/page.tsx` 中新增「Admin」链接。
- **逻辑**:
  - Admin 布局：取 session；无 session 则跳转登录。有 session 时请求 `GET /api/admin/classification-review?limit=1`；403 则视为非 Admin，展示「需要 Admin 或 Super Admin 权限」并链回 Dashboard；200 则渲染子页面及导航。
  - Dashboard 顶栏增加「Admin」链接指向 `/admin/classification-review`。非 Admin 用户点击后由 Admin 布局统一提示无权限。

### 1.7 前端：Classification Review 页

- **文件**: `frontend/app/admin/classification-review/page.tsx`
- **功能**:
  - 按 status 筛选（pending / confirmed / unable_to_decide / deferred / cancelled）、分页（limit/offset）。
  - 表格列：raw_product_name；normalized_name（可编辑 input）；category（L3 下拉，数据来自 GET /api/admin/categories）；status（下拉可改）；操作：pending 时显示 Confirm，confirmed/cancelled/deferred 时显示「重开」。
  - Confirm：请求 POST confirm；若 409 且返回 similar_to，则展示「与 XXX 相似」并提供「坚持使用」（force_different_name=true）与「取消」。
  - 重开：PATCH 将 status 改回 pending。

### 1.8 前端：Category 管理页

- **文件**: `frontend/app/admin/categories/page.tsx`
- **功能**:
  - 拉取 GET /api/admin/categories（active_only=false）展示树状（根 + 按 parent_id 分组子节点）。
  - 「＋ 新增分类」：选择父节点（或 L1 根）、输入 name、显示 level，POST /api/admin/categories 创建。
  - 每行：编辑（PATCH name）、软删（DELETE）。编辑时行内 input + 保存/取消。

---

## 2. 未实现或可后续增强项（与 Plan 对照）

- **CR 下拉内「＋ 新增分类」2-in-1**  
  Plan 中在 Classification Review 的 category 下拉最下方增加「＋ 新增分类」并在弹窗内确认「当前列表中不存在该分类且新增必要」。当前前端 CR 页仅使用现有 categories 下拉，未做「下拉内新增分类」入口；可后续在 CR 页增加该入口并调用 POST /api/admin/categories，创建后刷新下拉并自动选中新节点。

- **normalized_name 的 Autocomplete 数据源**  
  Plan 建议 CR 页 normalized_name 使用 suggest API 做 autocomplete。当前 CR 页为普通 input，未接 GET /api/admin/classification-review/suggest-normalized；可后续在输入框上增加异步建议列表。

- **Admin 入口按 user_class 显示**  
  当前 Dashboard 对所有用户显示「Admin」链接，非 Admin 点击后由 Admin 布局返回 403 并提示。若后端提供「当前用户 user_class」接口（如 GET /api/auth/me），可仅在 user_class in (admin, super_admin) 时显示 Admin 链接。

- **产品表 upsert 与 NULL size**  
  products 表 unique(normalized_name, size)；当前 Confirm 逻辑为「按 normalized_name + size 查询，存在则 update，否则 insert」，以兼容 size 为 NULL 的情况。若未来约束或业务变化，可再统一为 DB 层 upsert。

---

## 3. 文件清单（本次新增/修改）

| 路径 | 操作 |
|------|------|
| `backend/database/025_add_classification_review.sql` | 新增 |
| `backend/app/services/database/supabase_client.py` | 修改（enqueue_unmatched_items_to_classification_review） |
| `backend/app/services/categorization/receipt_categorizer.py` | 修改（调用 enqueue） |
| `backend/app/services/standardization/product_normalizer.py` | 修改（normalize_name_for_storage） |
| `backend/app/services/admin/classification_review_service.py` | 新增 |
| `backend/app/services/admin/categories_admin_service.py` | 新增 |
| `backend/app/main.py` | 修改（Admin Classification Review + Admin Categories 路由，Body 依赖） |
| `frontend/app/admin/layout.tsx` | 新增 |
| `frontend/app/admin/classification-review/page.tsx` | 新增 |
| `frontend/app/admin/categories/page.tsx` | 新增 |
| `frontend/app/dashboard/page.tsx` | 修改（Admin 链接） |
| `backend/agent-tbd/CLASSIFICATION_REVIEW_IMPLEMENTATION_SUMMARY_20260217.md` | 本文件 |

---

## 4. 如何验证

1. **跑 Migration 025**  
   在目标库执行 `025_add_classification_review.sql`（需已执行 012, 015, 017, 019, 020, 021, 022, 024）。

2. **小票进 CR**  
   上传小票并走通 workflow → 调用 categorize（或包含 categorize 的流程）；检查 `classification_review` 表中是否出现该小票下未命中 category 的行，且同 (raw_product_name, store_chain_id) 仅一条 pending。

3. **Admin 接口**  
   使用 admin/super_admin 用户的 JWT：  
   - GET /api/admin/classification-review?status=pending  
   - PATCH /api/admin/classification-review/{id}  
   - POST /api/admin/classification-review/{id}/confirm  
   - GET/POST/PATCH/DELETE /api/admin/categories  

4. **前端**  
   以 Admin 用户登录 → Dashboard 点「Admin」→ 进入「分类审核」或「分类管理」；非 Admin 用户点「Admin」应看到无权限提示。

---

## 5. 备注

- **重开**：将 status 从 confirmed/cancelled/deferred 改回 pending 时，不删除已写入的 product_categorization_rules/products；再次 Confirm 时按现有逻辑 upsert/update。
- **相似名 409**：Confirm 时若检测到高相似 normalized_name 且未传 `force_different_name`，返回 409 与 similar_to，前端可提示并允许「坚持使用」或改用已有名称。
