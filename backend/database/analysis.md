# Database Migrations 分析与合并计划

**目的**：为「拆除旧 production、新建 production」准备一套精简迁移方案，将约 50 个 SQL 压缩到约 20–30 个，便于一次性在新库上跑完。

**范围**：仅分析 `backend/database/` 下编号迁移 `001_*.sql` ~ `053_*.sql`（不含 `deprecated/`、`scripts/`、`CHECK_*.sql`）。

---

## 一、当前迁移清单与依赖关系

### 1.1 按执行顺序的迁移列表（约 53 个有效迁移）

| # | 文件名 | 类型 | 主要内容 |
|---|--------|------|----------|
| 001 | schema_v2 | **CREATE** | 核心表：store_chains, store_locations, users, receipt_status, receipt_processing_runs, api_calls, store_candidates + 触发器 |
| 003 | add_file_hash | ALTER | receipt_status + file_hash + 索引 |
| 004 | update_user_class | ALTER | users.user_class check 约束 |
| 006 | add_validation_status | ALTER | receipt_processing_runs + validation_status + 索引 |
| 007 | add_chain_name_to_store_locations | ALTER + 触发器 | store_locations.chain_name + 自动同步 trigger |
| 010 | update_costco_lynnwood_address | **DATA** | 单条 Costco Lynnwood 地址修正（可并入 seed 或省略） |
| 012 | add_receipt_items_and_summaries | **CREATE** | record_summaries, record_items + 索引 + pg_trgm |
| 013 | auto_create_user_on_signup | 触发器 + 数据 | handle_new_user(), auth.users 同步 + backfill |
| 015 | add_categories_tree | **CREATE** | categories + category_migration_mapping + seed 数据 |
| 016 | add_products_catalog | **CREATE** | products |
| 017 | link_receipt_items_to_products | ALTER + VIEW | record_items + product_id, category_id + record_items_enriched 视图 |
| 018 | add_price_snapshots | **CREATE** | price_snapshots + latest_prices MV + aggregate_prices_for_date |
| 019 | add_categorization_rules | **CREATE** | product_categorization_rules + find_categorization_rule() |
| 020 | drop_brands_table | DROP + ALTER | 删 brands、products.brand_id，改 products 唯一约束，重做视图/MV |
| 021 | simplify_categories | ALTER | categories 删 name/display_order/icon/color/product_count，normalized_name→name，重做视图 |
| 022 | simplify_products | ALTER | products 删多列，唯一约束 (normalized_name, size)，重做视图 |
| 023 | prompt_library_and_binding | **CREATE** | 删旧 prompt 表，建 prompt_library + prompt_binding |
| 023_seed | seed_prompt_library | **DATA** | prompt_library/prompt_binding 初始数据 |
| 024 | simplify_receipt_items | ALTER + 函数 | record_items 删列、数值改 x100，重写 aggregate_prices_for_date，**删** record_items_enriched |
| 025 | add_classification_review | **CREATE** | classification_review 表 |
| 026 | add_classification_prompt | **DATA** | prompt_library 插入 classification |
| 027 | size_quantity_unit_package | ALTER | products/classification_review: size→size_quantity+size_unit+package_type，**重建** record_items_enriched |
| 028 | categories_lowercase | **DATA** | categories name/path 小写 UPDATE |
| 029 | size_quantity_2dec_and_products_store_chain | ALTER | size_quantity NUMERIC(12,2)，products+store_chain_id，唯一索引含 store_chain_id，**再建** record_items_enriched |
| 030 | increment_product_usage_rpc | 函数 | increment_product_usage() |
| 031 | record_summaries_information_and_int_totals | ALTER | record_summaries + information JSONB，金额改分 (int)，删 uploaded_at |
| 032 | store_locations_and_candidates_phone | ALTER | store_locations.phone, store_candidates.phone |
| 033 | ensure_find_categorization_rule_no_prefix_match | 函数 | 重写 find_categorization_rule（仅 exact/fuzzy/contains） |
| 034 | fix_milk_and_soup_dumplings_rules | **DATA** | 规则数据 UPDATE/INSERT |
| 035 | prompt_is_on_sale_only_real_discounts | **DATA** | prompt_library 更新 package_price_discount 文案 |
| 037 | drop_find_categorization_rule_rpc | DROP | 删 find_categorization_rule() |
| 038 | backfill_record_items_batch_rpc | 函数 | backfill_record_items_batch() |
| 039 | sync_record_items_batch_update_rpc | 函数 | sync_record_items_batch_update() |
| 040 | receipt_processing_runs_stage_rule_based_cleaning | ALTER | receipt_processing_runs.stage 加 rule_based_cleaning |
| 041 | seed_prompt_library_debug_cascade | **DATA** | prompt 插入 debug_ocr / debug_vision |
| 042 | firebase_uid_and_drop_auth_fk | ALTER | users.firebase_uid，删 users→auth.users FK |
| 043 | non_receipt_rejects | **CREATE** | non_receipt_rejects 表 |
| 044 | rls_policies | **CREATE** | is_admin() + 各表 RLS 策略 |
| 045 | receipt_workflow_steps | ALTER + **CREATE** | receipt_status.current_stage 扩展，receipt_workflow_steps 表 |
| 046 | user_strikes_and_lock | **CREATE** | user_strikes, user_lock |
| 047 | users_registration_no_and_username | ALTER + 序列 | users.registration_no + user_name unique |
| 048 | receipt_status_pipeline_version | ALTER | receipt_status.pipeline_version |
| 049 | receipt_processing_runs_stage_vision | ALTER | receipt_processing_runs.stage 加 vision_* / shadow_legacy |
| 050 | receipt_status_stage_vision | ALTER | receipt_status.current_stage 加 vision_primary / vision_escalation |
| 051 | category_source_and_user_categories | ALTER + **CREATE** | record_items.category_source，user_categories，user_item_category_overrides |
| 052 | user_item_idk | ALTER | record_items.user_marked_idk |
| 053 | record_items_user_feedback | ALTER | record_items.user_feedback |

**说明**：014 (brands) 已废弃，新库不跑；008/011 针对旧表名 `receipts`，当前为 `receipt_status`，新库不涉及。

---

## 二、主要「先加后删/反复改」模式

### 2.1 record_items_enriched 视图

- **017** 创建。
- **020** 因删 brands 先 DROP 再 CREATE。
- **021** 因 categories 改列 DROP 再 CREATE。
- **022** 因 products 改列 DROP 再 CREATE。
- **024** 直接 **DROP**（MVP 不保留）。
- **027** 又 **CREATE**（products 改为 size_quantity/unit/package）。
- **029** 再 DROP + CREATE（products 加 store_chain_id 等）。

**合并建议**：新库里只在一个地方「按最终 schema」建一次 `record_items_enriched`，中间迁移里所有 DROP/CREATE 全部省略。

### 2.2 products 唯一约束与列

- **016**：唯一 (normalized_name, size)，无 brand_id（当前代码）。
- **020**：删 brand_id，唯一改为 (normalized_name, size, variant_type)——但 016 从未建 variant_type，020 在无 014 时会报错或需条件判断。
- **022**：删 variant_type 等，唯一再改为 (normalized_name, size)。
- **027**：删 size/unit_type，改为 (normalized_name, size_quantity, size_unit, package_type)。
- **029**：再改为含 store_chain_id 的唯一索引。

**合并建议**：新库中 products 直接建为「029 之后」的形态，唯一索引 = (normalized_name, size_quantity, size_unit, package_type, COALESCE(store_chain_id, sentinel))，不再经历 020/022 的约束来回改。

### 2.3 categories 列与命名

- **015**：建 categories（含 name, normalized_name, display_order, icon, color, product_count 等）。
- **021**：删 name/display_order/icon/color/product_count，normalized_name → name。
- **028**：name/path 小写 UPDATE。

**合并建议**：新库中 categories 直接建为「021+028 之后」的结构（单 name 小写、path 小写），seed 数据直接插小写，省掉 021 的改列和 028 的 UPDATE。

### 2.4 receipt_status / receipt_processing_runs 的 stage

- **001**：receipt_status.current_stage = ocr | llm_primary | llm_fallback | manual；receipt_processing_runs.stage = ocr | llm | manual。
- **040**：receipt_processing_runs 加 rule_based_cleaning。
- **045**：receipt_status 加 rejected_not_receipt, pending_receipt_confirm。
- **049**：receipt_processing_runs 加 vision_primary, vision_escalation, shadow_legacy。
- **050**：receipt_status 加 vision_primary, vision_escalation。

**合并建议**：新库中两表的 check 约束直接写成「040+045+049+050」的最终枚举，一个 ALTER 都不用。

### 2.5 小 alter / 单列 / 单函数

适合与相邻迁移合并的「小步」：

- **003**：receipt_status + file_hash + 索引 → 可并入 001 或紧跟 001 的「001 扩展」。
- **004**：users.user_class check → 可并入 001（001 里已是 super_admin, admin, premium, free）。
- **006**：receipt_processing_runs.validation_status → 可并入 001 或「001 扩展」。
- **007**：store_locations.chain_name + trigger → 可并入 001 或「001 扩展」。
- **030**：increment_product_usage() → 与 029 或「products 相关」合并。
- **032**：store_locations.phone, store_candidates.phone → 可与 001 或 007 合并。
- **033**：find_categorization_rule 重写 → 与 019 合并为「建规则表 + 最终版函数」；若采用 037 删函数，则新库不建该函数，033 可忽略。
- **035**：prompt 文案 UPDATE → 与 023_seed 或「prompt 种子」合并为最终文案。
- **037**：删 find_categorization_rule → 新库本来就不建，可忽略。
- **038、039**：两个 RPC → 合并为一个「record_items RPC」迁移。
- **040、049**：receipt_processing_runs.stage 两次扩展 → 与 001 或「stage 统一」合并为一次。
- **045、050**：receipt_status.current_stage 两次扩展 → 同上，一次到位。
- **048**：receipt_status.pipeline_version → 可与 receipt_status 的建表或 stage 合并。
- **052、053**：record_items 两列 → 合并为一个 ALTER（user_marked_idk + user_feedback）。

### 2.6 数据类迁移（可合并或单独）

- **010**：Costco Lynnwood 地址 → 可并入 seed 或「一次性数据」脚本，不单独占一号。
- **023_seed**：prompt 种子 → 与 041（debug 种子）合并为一个「prompt 种子」文件。
- **026**：classification prompt → 同上。
- **028**：categories 小写 → 见 2.3，直接 seed 小写。
- **034**：规则数据 → 可与 019 的 seed 或单独「规则 seed」合并。
- **035**：package_price_discount 文案 → 见 2.5，并入 prompt 种子。

---

## 三、合并后的目标结构（约 20–30 个文件）

按「逻辑块」合并，不改变最终 schema，只减少文件数与重复的 DROP/ADD。

### 3.1 建议的新迁移编号与内容

| 新编号 | 内容概要 | 合并掉的原编号 |
|--------|----------|----------------|
| **01_schema_core** | store_chains, store_locations, users, receipt_status, receipt_processing_runs, api_calls, store_candidates；含 file_hash(003)、user_class check(004)、validation_status(006)、chain_name+trigger(007)、phone(032)；receipt_status/processing_runs 的 stage 直接为最终枚举(040/045/049/050)、pipeline_version(048) | 001, 003, 004, 006, 007, 032, 040, 045, 048, 049, 050（部分） |
| **02_receipt_status_stages** | 若 01 未含 receipt_status/processing_runs 的完整 stage，则本文件只做两表 stage 的最终 check | 040, 045, 049, 050 |
| **03_record_summaries_and_items** | record_summaries、record_items 建表（012 的最终结构）+ 024 的整型/分存储 + 051 的 category_source + 052/053 的 user_marked_idk、user_feedback | 012, 024, 051, 052, 053 |
| **04_categories** | categories 建表（021+028 后的结构）+ seed（小写 name/path）+ category_migration_mapping | 015, 021, 028 |
| **05_products** | products 建表（029 后：size_quantity/size_unit/package_type, store_chain_id, 唯一索引） | 016, 020, 022, 027, 029 |
| **06_record_items_fks_and_view** | record_items 的 product_id/category_id(017)、record_items_enriched 视图（最终版，只建一次） | 017, 024(不删视图), 027, 029 |
| **07_categorization_rules** | product_categorization_rules 表 + update_rule_match_stats；不建 find_categorization_rule(037 已删) | 019, 033(逻辑并入), 037(不建函数) |
| **08_price_snapshots** | price_snapshots + latest_prices MV + aggregate_prices_for_date（018 的、且兼容 024 的整型） | 018, 024(函数部分) |
| **09_prompt_system** | 删旧 prompt 表(023)、prompt_library + prompt_binding 建表 | 023 |
| **10_prompt_seed** | prompt_library/binding 种子：023_seed + 026 + 035 + 041 | 023_seed, 026, 035, 041 |
| **11_rules_seed** | 分类规则 seed（可选：034 的 milk/soup dumplings 等） | 034 |
| **12_classification_review** | classification_review 表（025 结构，含 size_quantity/size_unit/package_type） | 025, 027(该表部分) |
| **13_user_sync_and_auth** | handle_new_user(013)、users backfill、firebase_uid(042)、registration_no+user_name(047) | 013, 042, 047 |
| **14_rpcs** | increment_product_usage(030)、backfill_record_items_batch(038)、sync_record_items_batch_update(039) | 030, 038, 039 |
| **15_record_summaries_int_totals** | record_summaries 的 information、金额改分、删 uploaded_at(031) | 031 |
| **16_user_categories_and_overrides** | user_categories、user_item_category_overrides（051 的建表部分） | 051(建表) |
| **17_non_receipt_rejects** | non_receipt_rejects 表 | 043 |
| **18_rls** | is_admin() + 各表 RLS | 044 |
| **19_receipt_workflow_steps** | receipt_workflow_steps 表（045 已含 receipt_status stage 则可只建表） | 045 |
| **20_user_strikes_and_lock** | user_strikes、user_lock | 046 |
| **21_data_seed** | 可选：010 Costco 地址、034 规则等一次性数据 | 010, 034(若未并入 11) |

以上约 **21 个** 迁移文件，若把 02 并入 01、11 并入 10、15 并入 03 等，可再压到 **18–20 个**。

### 3.2 合并时注意事项

1. **020 的 variant_type**：新库从未建 brands/variant_type，020 的「删 brand_id、改唯一约束」在新合并脚本里体现为：products 从一开始就没有 brand_id，唯一约束直接是 029 的 (normalized_name, size_quantity, size_unit, package_type, store_chain_id)。
2. **record_items_enriched**：必须在 products、categories、record_items、record_summaries 都就绪后建一次即可，列名与 029 一致（size_quantity, size_unit, package_type 等）。
3. **aggregate_prices_for_date**：018 写的是「金额 * 100」；024 改为 record_items 已是分，直接用。合并后的 08 里只保留 024 版本的函数即可。
4. **RLS（044）**：依赖所有被保护的表已存在，顺序放最后或倒数第二（仅在有 RLS 的表上启用）。
5. **auth.users**：013 的 trigger 依赖 Supabase auth；042 删 users→auth.users FK，新库若只用 Firebase 可在一开始就不建该 FK，与 01/13 合并时写清楚。

---

## 四、执行顺序建议（合并后）

1. 01_schema_core（含 stage 最终值、048 pipeline_version）
2. 13_user_sync_and_auth（若 01 里 users 已含 firebase_uid/registration_no 等则部分可并入 01）
3. 03_record_summaries_and_items
4. 04_categories
5. 05_products
6. 06_record_items_fks_and_view
7. 07_categorization_rules
8. 08_price_snapshots
9. 09_prompt_system
10. 10_prompt_seed
11. 12_classification_review
12. 14_rpcs
13. 15_record_summaries_int_totals（若未并入 03）
14. 16_user_categories_and_overrides
15. 17_non_receipt_rejects
16. 19_receipt_workflow_steps
17. 20_user_strikes_and_lock
18. 18_rls
19. 11_rules_seed、21_data_seed（按需）

---

## 五、下一步

1. 按上表在 `backend/database/` 下新建目录如 `migrations_consolidated/`，按 01–21 写出合并后的 SQL。
2. 用空库跑一遍，对照当前 001–053 跑完后的 schema（含 DB_DEFINITIONS.md）做一次 diff（表、列、索引、约束、函数、RLS）。
3. 确认无遗漏后，将「新 production 的官方迁移」定为这 20 个左右文件，旧 001–053 仅作历史参考。

如需，我可以按上述编号直接写出合并后的 SQL 草稿（从 01_schema_core 开始）。
