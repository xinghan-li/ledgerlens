SCHEMA_DEFINITION

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
It is intended to store aggregated price data derived from receipt_items, enabling cross-user price tracking, trend analysis, and crowd-sourced price comparison.

At the current LedgerLens MVP stage:

This table is not actively populated.

No background jobs aggregate data into this table.

No application features depend on it.

It does not affect receipt parsing, categorization, or dashboard analytics.

This table represents a planned expansion module and is intentionally separated from core LedgerLens functionality.

中文说明

模块分类：未来模块（PricePeek）

price_snapshots 表用于未来的价格聚合系统（PricePeek）。
它的设计目标是从 receipt_items 中提取数据进行跨用户价格统计、趋势分析以及价格对比。

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
| price_change_cents   | Absolute change in price compared to                          |                |      |


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

No rule engine actively reads from this table.

No automated categorization logic depends on these rules.

All classification is handled directly by the LLM or manual correction.

This table does not affect receipt parsing or dashboard analytics.

This module represents a future performance and cost optimization layer.

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
| id                   | Unique identifier for each categorization rule.                    | 每条分类规则的唯一标识。           | 尚未开发 |
| normalized_name      | Normalized product name used for matching rules.                   | 用于规则匹配的标准化商品名称。        | 尚未开发 |
| original_examples    | Example raw product names that triggered this rule.                | 触发该规则的原始商品名称示例。        | 尚未开发 |
| store_chain_id       | Optional reference to restrict the rule to a specific store chain. | 可选的门店连锁 ID，用于限定规则适用范围。 | 尚未开发 |
| category_id          | Target category to assign when rule matches.                       | 规则匹配成功时分配的分类 ID。       | 尚未开发 |
| match_type           | Matching strategy (exact, fuzzy, contains).                        | 匹配方式（精确、模糊、包含）。        | 尚未开发 |
| similarity_threshold | Similarity score threshold for fuzzy matching.                     | 模糊匹配所需的相似度阈值。          | 尚未开发 |
| source               | Indicates how the rule was created (manual/system).                | 标记规则来源（人工或系统生成）。       | 尚未开发 |
| priority             | Determines rule execution order when multiple rules match.         | 当多个规则匹配时的优先级。          | 尚未开发 |
| times_matched        | Counter tracking how often this rule was triggered.                | 该规则被触发的次数统计。           | 尚未开发 |
| last_matched_at      | Timestamp of the most recent match.                                | 最近一次匹配时间。              | 尚未开发 |
| created_by           | Reference to the user who created the rule.                        | 创建该规则的用户 ID。           | 尚未开发 |
| created_at           | Timestamp when the rule was created.                               | 规则创建时间。                | 尚未开发 |
| updated_at           | Timestamp when the rule was last updated.                          | 规则更新时间。                | 尚未开发 |


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

| Field           | English Definition                                        | 中文定义                | 当前状态 |
| --------------- | --------------------------------------------------------- | ------------------- | ---- |
| id              | Unique identifier for each product entity.                | 每个商品实体的唯一标识。        | 已实现  |
| normalized_name | Canonical normalized product name used for deduplication. | 用于去重的标准化商品名称。       | 已实现  |
| size            | Product size or quantity descriptor if available.         | 商品规格或容量描述（如有）。      | 已实现  |
| unit_type       | Unit of measurement (e.g., oz, lb, pack).                 | 计量单位（如 oz、lb、pack）。 | 已实现  |
| category_id     | Associated category ID for aggregation.                   | 关联分类 ID，用于统计聚合。     | 已实现  |
| usage_count     | Number of times this product has appeared in receipts.    | 商品在小票中出现次数统计。       | 已实现  |
| last_seen_date  | Most recent date this product was observed.               | 最近一次出现日期。           | 已实现  |
| created_at      | Timestamp when product was created.                       | 商品创建时间。             | 已实现  |
| updated_at      | Timestamp when product was last updated.                  | 商品更新时间。             | 已实现  |









Table: prompt_library
Primary Key: id (uuid)
Purpose: Prompt content library (receipt_parse_base, user_template, schema, etc.)
Fields: id, key, category, content_role (system|user_template|schema), content, version, is_active

Table: prompt_binding
Primary Key: id (uuid)
Purpose: Routing which library prompts to use per prompt_key and scope (default|chain|location)
Fields: id, prompt_key, library_id (FK → prompt_library), scope, chain_id, location_id, priority, is_active

Table: receipt_items
Primary Key:
- id (uuid)

Fields:
- id (uuid)
- receipt_id (uuid, FK → receipts.id)
- user_id (uuid, FK → users.id)
- product_name (text)
- product_name_clean (text)
- brand (text)
- quantity (numeric)
- unit (text)
- unit_price (numeric)
- line_total (numeric)
- on_sale (boolean)
- original_price (numeric)
- discount_amount (numeric)
- category_l1 (text)
- category_l2 (text)
- category_l3 (text)
- ocr_coordinates (jsonb)
- ocr_confidence (numeric)
- item_index (integer)
- product_id (uuid, FK → products.id)
- category_id (uuid, FK → categories.id)
- created_at (timestamptz)

Table: receipt_processing_runs
Primary Key:
- id (uuid)

Fields:
- id (uuid)
- receipt_id (uuid, FK → receipts.id)
- stage (enum: ocr, llm, manual)
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

Table: receipt_summaries
Primary Key:
- id (uuid)

Fields:
- id (uuid)
- receipt_id (uuid, unique)
- user_id (uuid, FK → users.id)
- store_chain_id (uuid, FK → store_chains.id)
- store_location_id (uuid, FK → store_locations.id)
- store_name (text)
- store_address (text)
- subtotal (numeric)
- tax (numeric)
- fees (numeric)
- total (numeric)
- currency (text)
- payment_method (text)
- payment_last4 (text)
- user_note (text)
- user_tags (text[])
- receipt_date (date)
- uploaded_at (timestamptz)
- created_at (timestamptz)
- updated_at (timestamptz)

Table: receipts
Primary Key:
- id (uuid)

Fields:
- id (uuid)
- user_id (uuid, FK → users.id)
- uploaded_at (timestamptz)
- current_status (enum: success, failed, needs_review)
- current_stage (enum: ocr, llm_primary, llm_fallback, manual)
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
Primary Key:
- id (uuid)

Fields:
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
- chain_name (text)
- created_at (timestamptz)
- updated_at (timestamptz)

Table: store_candidates
Primary Key:
- id (uuid)

Fields:
- id (uuid)
- raw_name (text)
- normalized_name (text)
- source (enum: ocr, llm, user)
- receipt_id (uuid, FK → receipts.id)
- suggested_chain_id (uuid, FK → store_chains.id)
- suggested_location_id (uuid, FK → store_locations.id)
- confidence_score (numeric)
- status (enum: pending, approved, rejected)
- rejection_reason (text)
- metadata (jsonb)
- created_at (timestamptz)
- reviewed_at (timestamptz)
- reviewed_by (uuid, FK → users.id)

Table: users
Primary Key:
- id (uuid)

Fields:
- id (uuid, FK → auth.users.id)
- user_name (text)
- email (text, unique)
- user_class (enum: super_admin, admin, premium, free)
- status (enum: active, suspended, deleted)
- stripe_customer_id (text)
- subscription_status (text)
- subscription_tier (text)
- created_at (timestamptz)
- updated_at (timestamptz)