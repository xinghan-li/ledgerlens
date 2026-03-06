SCHEMA_DEFINITION

This document is kept in sync with migrations. As of the last update it reflects schema through migration 053. Full audit (2025-03): products (027/029), record_summaries (031), users (042/047), store_locations/store_candidates (032 phone), classification_review (025/027), receipt_workflow_steps (045), non_receipt_rejects (043), user_strikes/user_lock (046), record_items (051), receipt_status (048/050), receipt_processing_runs (049). See backend/database/*.sql for migration order.

Table: api_calls
表用途说明 | Table Purpose

English

The api_calls table records every external OCR or LLM API call triggered during receipt processing.
Its primary purpose is to provide basic operational visibility, debugging support, and failure tracking.

It is not intended to function as a full observability or analytics system at the MVP stage.

中文

api_calls 表用于记录小票处理过程中触发的每一次 OCR 或 LLM 外部接口调用。
它的主要作用是提供基础运行监控、调试支持以及失败追踪能力。

在 MVP 阶段，该表并非用于构建完整的可观测性或分析系统。

字段定义 | Field Definitions
Primary Key:
- id (uuid)

| 字段                | English Definition                                                       | 中文定义                | 当前状态 |
| ----------------- | ------------------------------------------------------------------------ | ------------------- | ---- |
| id                | Unique identifier for each API call record.                              | 每一次 API 调用记录的唯一标识。  | 已实现✅  |
| call_type         | Indicates whether the call was made to an OCR service or an LLM service. | 表示本次调用是 OCR 还是 LLM。 | 已实现✅  |
| provider          | Name of the external service provider used for this call.                | 本次调用所使用的外部服务提供方名称。  | 已实现✅  |
| receipt_id        | Reference to the receipt that triggered this API call.                   | 关联触发本次调用的小票记录。      | 已实现✅  |
| duration_ms       | Execution time of the API call in milliseconds.                          | API 调用耗时（毫秒）。       | 暂未实现❌ |
| status            | Indicates whether the API call succeeded or failed.                      | 表示本次调用成功或失败。        | 已实现✅  |
| error_code        | Machine-readable error classification for failed calls.                  | 失败时的机器可识别错误类型。      | 暂未实现❌ |
| error_message     | Human-readable error description.                                        | 失败时的可读错误信息。         | 已实现✅  |
| request_metadata  | Structured JSON containing additional request details.                   | 记录请求侧的附加结构化信息。      | 暂未实现❌ |
| response_metadata | Structured JSON containing additional response details.                  | 记录响应侧的附加结构化信息。      | 暂未实现❌ |
| created_at        | Timestamp indicating when the API call occurred.                         | 本次调用发生时间。           | 已实现✅  |


Table Purpose | 表用途说明
English

The categories table defines the hierarchical classification system used to group receipt items for spending analysis.

It enables:

Aggregation of expenses by category

Multi-level grouping (parent-child structure)

Consistent classification across receipts

Future extensibility for user-defined categories

This table is foundational to dashboard reporting and financial summaries.

中文

categories 表用于定义小票条目的分类体系，是支出分析的核心结构。

它支持：

按分类聚合支出

多层级分类结构（父子关系）

小票之间的统一分类标准

未来支持用户自定义分类

该表是 Dashboard 和财务统计的基础数据结构。


| Field       | English Definition                                                          | 中文定义                        | 当前状态 |
| ----------- | --------------------------------------------------------------------------- | --------------------------- | ---- |
| id          | Unique identifier for a category node.                                      | 分类节点的唯一标识。                  | 已实现  |
| parent_id   | Reference to the parent category node, used to build the hierarchy.         | 父级分类节点 ID，用于构建层级关系。         | 已实现  |
| level       | Depth level of the category node in the hierarchy.                          | 分类所在层级深度。                   | 已实现  |
| name        | Display name of the category.                                               | 分类展示名称。                     | 已实现  |
| path        | Optional full path string representing the category’s position in the tree. | 可选的完整路径字符串，用于表示分类在树中的位置。    | 已实现 |
| description | Optional description to clarify category meaning or usage.                  | 可选的分类说明，用于解释含义或使用场景。        | 已实现  |
| is_system   | Indicates whether the category is system-defined rather than user-defined.  | 标记该分类是否为系统内置分类（区别于未来用户自定义）。 | 已实现  |
| is_active   | Indicates whether the category is active and selectable.                    | 标记该分类是否启用，可用于软删除或禁用。        | 已实现  |
| created_at  | Timestamp when the category record was created.                             | 分类记录创建时间。                   | 已实现  |
| updated_at  | Timestamp when the category record was last updated.                        | 分类记录最后更新时间。                 | 已实现  |



⚠️ Module Status Note – price_snapshots
English

Module Classification: Future Module (PricePeek)

The price_snapshots table is reserved for a future price aggregation system (PricePeek).
It is intended to store aggregated price data derived from record_items, enabling cross-user price tracking, trend analysis, and crowd-sourced price comparison.

At the current LedgerLens MVP stage:

This table is not actively populated.

No background jobs aggregate data into this table.

No application features depend on it.

It does not affect receipt parsing, categorization, or dashboard analytics.

This table represents a planned expansion module and is intentionally separated from core LedgerLens functionality.

中文说明

模块分类：未来模块（PricePeek）

price_snapshots 表用于未来的价格聚合系统（PricePeek）。
它的设计目标是从 record_items 中提取数据进行跨用户价格统计、趋势分析以及价格对比。

在当前 LedgerLens MVP 阶段：

该表未被实际写入数据。

没有定时任务或聚合逻辑依赖该表。

前端或 API 未使用该表。

不影响小票解析或分类统计功能。

该表属于未来扩展模块，已与当前核心记账功能逻辑分离。

| Field                | English Definition                                            | 中文定义           | 当前状态 |
| -------------------- | ------------------------------------------------------------- | -------------- | ---- |
| id                   | Unique identifier for each price snapshot record.             | 每条价格快照记录的唯一标识。 | 尚未开发 |
| product_id           | Reference to the product being priced.                        | 关联的产品 ID。      | 尚未开发 |
| store_location_id    | Reference to the store location where the price was observed. | 记录价格的门店位置 ID。  | 尚未开发 |
| latest_price_cents   | Most recent recorded price in cents.                          | 最近记录的价格（单位：分）。 | 尚未开发 |
| currency             | Currency code of the price.                                   | 价格对应的货币代码。     | 尚未开发 |
| snapshot_date        | Date the snapshot represents.                                 | 该价格快照对应的日期。    | 尚未开发 |
| last_seen_date       | Most recent date this exact price was observed.               | 最近一次观察到该价格的日期。 | 尚未开发 |
| sample_count         | Number of price samples aggregated into this record.          | 聚合到该记录中的样本数量。  | 尚未开发 |
| avg_price_cents      | Average price calculated from samples.                        | 样本计算得到的平均价格。   | 尚未开发 |
| min_price_cents      | Minimum observed price in the sample set.                     | 样本中的最低价格。      | 尚未开发 |
| max_price_cents      | Maximum observed price in the sample set.                     | 样本中的最高价格。      | 尚未开发 |
| previous_price_cents | Previous recorded price before the latest change.             | 最新变价前的价格。      | 尚未开发 |
| price_change_cents   | Absolute change in price compared to previous snapshot.         | 与前一快照的价差。      | 尚未开发 |


很好 👍
我们保持和 price_snapshots 一致的风格，把它明确标注为 Future Module，避免和 MVP 混淆。

下面是可以直接放进 .md 的正式 Notes。

⚠️ Module Status Note – product_categorization_rules
English

Module Classification: Future Optimization Module

The product_categorization_rules table is designed as a rule-based categorization layer intended to reduce reliance on LLM classification and improve consistency over time.

It is meant to:

Automatically assign categories based on product name patterns

Reduce repeated LLM calls for high-frequency items

Improve classification stability

Support cost optimization at scale

At the current LedgerLens MVP stage:

The receipt_categorizer (rule exact → rule fuzzy → LLM fallback) reads from this table. Manual and seed rules are used; crowd-sourced promotion from user overrides is not yet implemented.

This table does not affect receipt parsing or dashboard analytics beyond categorization.

中文说明

模块分类：未来优化模块

product_categorization_rules 表用于未来构建基于规则的商品分类系统，目的是减少对 LLM 分类的依赖并提高分类一致性。

其设计目标包括：

根据商品名称模式自动分配分类

减少高频商品重复调用 LLM

提高分类稳定性

在规模增长后优化成本

在当前 LedgerLens MVP 阶段：

系统未启用规则引擎读取该表。

商品分类完全依赖 LLM 或人工修正。

该表不影响小票解析或统计展示功能。

该表属于未来的性能与成本优化层。

| Field                | English Definition                                                 | 中文定义                   | 当前状态 |
| -------------------- | ------------------------------------------------------------------ | ---------------------- | ---- |
| id                   | Unique identifier for each categorization rule.                    | 每条分类规则的唯一标识。           | 已实现  |
| normalized_name      | Normalized product name used for matching rules.                   | 用于规则匹配的标准化商品名称。        | 已实现  |
| original_examples    | Example raw product names that triggered this rule.                | 触发该规则的原始商品名称示例。        | 已实现  |
| store_chain_id       | Optional reference to restrict the rule to a specific store chain. | 可选的门店连锁 ID，用于限定规则适用范围。 | 已实现  |
| category_id          | Target category to assign when rule matches.                       | 规则匹配成功时分配的分类 ID。       | 已实现  |
| match_type           | Matching strategy (exact, fuzzy, contains).                        | 匹配方式（精确、模糊、包含）。        | 已实现  |
| similarity_threshold | Similarity score threshold for fuzzy matching.                     | 模糊匹配所需的相似度阈值。          | 已实现  |
| source               | manual / auto / seed.                                               | 规则来源。                         | 已实现  |
| priority             | Determines rule execution order when multiple rules match.         | 当多个规则匹配时的优先级。          | 已实现  |
| times_matched        | Counter tracking how often this rule was triggered.                | 该规则被触发的次数统计。           | 已实现  |
| last_matched_at      | Timestamp of the most recent match.                                | 最近一次匹配时间。              | 已实现  |
| created_by           | Reference to the user who created the rule.                        | 创建该规则的用户 ID。           | 已实现  |
| created_at           | Timestamp when the rule was created.                               | 规则创建时间。                | 已实现  |
| updated_at           | Timestamp when the rule was last updated.                          | 规则更新时间。                | 已实现  |


Table: user_categories
Primary Key: id (uuid)
Purpose: Per-user custom category tree (e.g. "Weekend Treats", "Kids"). Users can create their own L1/L2/L3. Overrides (user_item_category_overrides) may point to categories (system) or user_categories (user-defined).

Fields:
- id (uuid)
- user_id (uuid, FK → users.id)
- parent_id (uuid, FK → user_categories.id, nullable for L1)
- level (int, 1–10)
- name (text)
- path (text, optional)
- system_category_id (uuid, FK → categories.id, optional) — Map to system category for analytics
- created_at, updated_at (timestamptz)

Unique: (user_id, COALESCE(parent_id, sentinel), name).


Table: user_item_category_overrides
Primary Key: id (uuid)
Purpose: Per-user category override per receipt line item. Display logic: for a given user, use override if exists, else record_items.category_id. Also the data source for future crowd tally (count overrides by normalized_name + store_chain to promote to product_categorization_rules). No separate votes table; tally by querying this table + record_items.

Fields:
- id (uuid)
- user_id (uuid, FK → users.id)
- record_item_id (uuid, FK → record_items.id)
- category_id (uuid, FK → categories.id, nullable) — System category when user chose system
- user_category_id (uuid, FK → user_categories.id, nullable) — User category when user chose own
- created_at, updated_at (timestamptz)

Constraint: exactly one of category_id or user_category_id must be set.
Unique: (user_id, record_item_id).


Table: classification_review
Primary Key: id (uuid)
Purpose: Admin review queue for receipt items that did not match any category. Rows inserted when items have no category; admin fills normalized_name/category_id and confirms to write to product_categorization_rules and products.

Fields (post-027):
- id (uuid)
- raw_product_name (text, NOT NULL)
- source_record_item_id (uuid, FK → record_items.id, ON DELETE SET NULL)
- store_chain_id (uuid, FK → store_chains.id)
- normalized_name (text) — Admin-filled before confirm
- category_id (uuid, FK → categories.id)
- size_quantity (numeric 12,2), size_unit (text), package_type (text) — Replaced size/unit_type in 027
- match_type (text: exact, fuzzy, contains)
- status (text: pending, confirmed, unable_to_decide, deferred, cancelled)
- created_at, updated_at, confirmed_at (timestamptz)
- confirmed_by (uuid, FK → users.id)


Table: receipt_workflow_steps
Primary Key: id (uuid)
Purpose: Ordered log of workflow steps/decisions per receipt for “View workflow” debug UI (045).

Fields:
- id (uuid)
- receipt_id (uuid, FK → receipt_status.id)
- sequence (int, UNIQUE with receipt_id)
- step_name (text)
- result (text)
- run_id (uuid, FK → receipt_processing_runs.id)
- details (jsonb)
- created_at (timestamptz)


Table: non_receipt_rejects
Primary Key: id (uuid)
Purpose: Store uploads that failed receipt-like validation (e.g. no total or no store/address in top 1/3) for debugging and filter tuning (043).

Fields:
- id (uuid)
- user_id (uuid, FK → users.id)
- file_hash (text), image_path (text), reason (text), ocr_text_snippet (text)
- created_at (timestamptz)


Table: user_strikes
Primary Key: id (uuid)
Purpose: Strikes when user confirmed receipt but result was not a receipt; 3 in 1h → 12h lock (046).

Fields:
- id (uuid)
- user_id (uuid, FK → users.id)
- receipt_id (uuid, FK → receipt_status.id, nullable)
- created_at (timestamptz)


Table: user_lock
Primary Key: id (uuid)
Purpose: User upload lock until locked_until (12h from 3 strikes in 1h) (046).

Fields:
- id (uuid)
- user_id (uuid, FK → users.id, UNIQUE)
- locked_until (timestamptz, NOT NULL)
- created_at (timestamptz)


Table: products
Module Classification

Core Module (Lightweight Normalization Layer)

表用途说明 | Table Purpose

English
The products table stores lightweight normalized product entities derived from receipt items.
Its purpose is to reduce duplication and enable consistent aggregation across receipts without attempting to maintain a full product master database.

中文
products 表用于存储从小票条目中提取的轻量级标准化商品实体。
其目标是减少重复商品记录，并支持跨小票的一致聚合，而不是构建完整的商品主数据系统。

| Field            | English Definition                                                                 | 中文定义                           | 当前状态 |
| ---------------- | ---------------------------------------------------------------------------------- | -------------------------------- | ---- |
| id               | Unique identifier for each product entity.                                          | 每个商品实体的唯一标识。                   | 已实现  |
| normalized_name  | Canonical normalized product name used for deduplication.                           | 用于去重的标准化商品名称。                  | 已实现  |
| size_quantity    | Numeric quantity (e.g. 3.5); 2 decimals (027, 029).                                | 规格数量（如 3.5）。                    | 已实现  |
| size_unit        | Unit of measure (oz, ml, lb, ct).                                                   | 计量单位（oz、ml、lb、ct 等）。           | 已实现  |
| package_type     | Package type (bottle, box, bag, jar, can).                                         | 包装类型。                            | 已实现  |
| store_chain_id   | Store chain for this product; NULL = legacy/global (029).                          | 门店连锁 ID；NULL 表示通用。               | 已实现  |
| category_id      | Associated category ID for aggregation.                                             | 关联分类 ID，用于统计聚合。                | 已实现  |
| usage_count      | Number of times this product has appeared in receipts.                              | 商品在小票中出现次数统计。                  | 已实现  |
| last_seen_date   | Most recent date this product was observed.                                          | 最近一次出现日期。                      | 已实现  |
| created_at       | Timestamp when product was created.                                                  | 商品创建时间。                        | 已实现  |
| updated_at       | Timestamp when product was last updated.                                             | 商品更新时间。                        | 已实现  |

Unique (029): (normalized_name, size_quantity, size_unit, package_type, COALESCE(store_chain_id, sentinel)). Removed: size, unit_type (027).









Table: prompt_library
Primary Key: id (uuid)
Purpose: Prompt content library (receipt_parse_base, user_template, schema, etc.)
Fields: id, key, category, content_role (system|user_template|schema), content, version, is_active

Table: prompt_binding
Primary Key: id (uuid)
Purpose: Routing which library prompts to use per prompt_key and scope (default|chain|location)
Fields: id, prompt_key, library_id (FK → prompt_library), scope, chain_id, location_id, priority, is_active

Table: record_items
Primary Key: id (uuid)
Purpose: Individual line items from receipts (all users, high-volume table). category_id = server-assigned category; user’s effective category = user_item_category_overrides for that user+item if present, else record_items.category_id.

Fields (post-053):
- id (uuid)
- receipt_id (uuid, FK → receipt_status.id)
- user_id (uuid, FK → users.id)
- product_name (text)
- product_name_clean (text, optional)
- quantity (bigint, x100 e.g. 1.5→150, 2→200)
- unit (text)
- unit_price (bigint, cents)
- line_total (bigint, cents)
- on_sale (boolean)
- original_price (bigint, cents, nullable)
- discount_amount (bigint, cents, nullable)
- category_id (uuid, FK → categories, level-3/leaf; L1/L2 via JOIN)
- category_source (text, optional) — How category_id was set: rule_exact (chain+normalized name exact), rule_fuzzy (similarity), llm (Gemini), user_override (user changed), crowd_assigned (promoted from votes). No rule_contains.
- item_index (integer)
- product_id (uuid, FK → products.id)
- user_feedback (jsonb, optional) — User dismissal on unclassified page. Shape: {dismissed: bool, reason: "incorrect_item"|"other", comment: string, dismissed_at: timestamptz}. Dismissed items are hidden from unclassified list. reason=other also escalates to classification_review. (053)
- created_at (timestamptz)

Removed (024): brand, category_l1/l2/l3, ocr_coordinates, ocr_confidence
Removed (MVP): record_items_enriched view

Table: receipt_processing_runs
Primary Key: id (uuid)

Fields (post-049):
- id (uuid)
- receipt_id (uuid, FK → receipt_status.id)
- stage (text, check: ocr, llm, manual, rule_based_cleaning, vision_primary, vision_escalation, shadow_legacy)
- model_provider (text)
- model_name (text)
- model_version (text)
- input_payload (jsonb)
- output_payload (jsonb)
- output_schema_version (text)
- status (enum: pass, fail)
- error_message (text)
- validation_status (enum: pass, needs_review, unknown)
- created_at (timestamptz)

Table: record_summaries
Primary Key: id (uuid)

Fields (post-031):
- id (uuid)
- receipt_id (uuid, unique)
- user_id (uuid, FK → users.id)
- store_chain_id (uuid, FK → store_chains.id)
- store_location_id (uuid, FK → store_locations.id)
- store_name (text)
- store_address (text)
- information (jsonb, optional) — Standardized payload: other_info + items (031)
- subtotal (integer, cents)
- tax (integer, cents)
- fees (integer, cents)
- total (integer, cents, NOT NULL)
- currency (text)
- payment_method (text)
- payment_last4 (text)
- user_note (text)
- user_tags (text[])
- receipt_date (date)
- created_at (timestamptz)
- updated_at (timestamptz)

Removed (031): uploaded_at (redundant with receipt_status.uploaded_at). Totals migrated from numeric to integer cents.

Table: receipt_status
Primary Key: id (uuid)

Fields (post-050):
- id (uuid)
- user_id (uuid, FK → users.id)
- uploaded_at (timestamptz)
- current_status (enum: success, failed, needs_review)
- current_stage (text, check: ocr, llm_primary, llm_fallback, manual, rejected_not_receipt, pending_receipt_confirm, vision_primary, vision_escalation)
- pipeline_version (text, default legacy_a) — legacy_a | vision_b (048)
- raw_file_url (text)
- file_hash (text)
- created_at (timestamptz)
- updated_at (timestamptz)

Table: store_chains
Primary Key:
- id (uuid)

Fields:
- id (uuid)
- name (text)
- normalized_name (text)
- aliases (text[])
- is_active (boolean)
- created_at (timestamptz)
- updated_at (timestamptz)

Table: store_locations
Primary Key: id (uuid)

Fields (post-032):
- id (uuid)
- chain_id (uuid, FK → store_chains.id)
- name (text)
- address_line1 (text)
- address_line2 (text)
- city (text)
- state (text)
- zip_code (text)
- country_code (text)
- latitude (numeric)
- longitude (numeric)
- is_active (boolean)
- chain_name (text) — From 007; kept in sync with store_chains.name via trigger
- phone (text, optional) — Canonical format xxx-xxx-xxxx (032)
- created_at (timestamptz)
- updated_at (timestamptz)

Table: store_candidates
Primary Key: id (uuid)

Populated by: **Text pipeline** (`receipt_llm_processor` when no store match or new location) and **Vision pipeline** (`receipt_categorizer` step 5b when `categorize_receipt` runs with no store_chain_id). Both use `create_store_candidate()` with suggested_chain_id / suggested_location_id / confidence_score. See docs/architecture/RECEIPT_WORKFLOW_CASCADE.md §4.1.

Fields (post-032):
- id (uuid)
- raw_name (text)
- normalized_name (text)
- source (text: ocr, llm, user)
- receipt_id (uuid, FK → receipt_status.id)
- suggested_chain_id (uuid, FK → store_chains.id)
- suggested_location_id (uuid, FK → store_locations.id)
- confidence_score (numeric)
- status (text: pending, approved, rejected)
- rejection_reason (text)
- phone (text, optional) — Proposed store phone; canonical format (032)
- metadata (jsonb)
- created_at (timestamptz)
- reviewed_at (timestamptz)
- reviewed_by (uuid, FK → users.id)

Table: users
Primary Key: id (uuid)

Fields (post-047):
- id (uuid) — No longer FK to auth.users (042); may be gen_random_uuid() for Firebase-only users
- firebase_uid (text, unique, nullable) — Firebase Auth UID; set when user signs in with Firebase (042)
- user_name (text, unique when not empty) — Display name for greeting; set from frontend (047)
- registration_no (integer, NOT NULL, unique) — 9-digit registration order (1=first user); display as 000000001 (047)
- email (text, unique)
- user_class (text: super_admin, admin, premium, free)
- status (text: active, suspended, deleted)
- stripe_customer_id (text)
- subscription_status (text)
- subscription_tier (text)
- created_at (timestamptz)
- updated_at (timestamptz)