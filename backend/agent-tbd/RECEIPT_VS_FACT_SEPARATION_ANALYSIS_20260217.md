# 小票层 vs Fact 层数据分离需求分析

**日期**: 2026-02-17  
**需求**: 抹掉小票数据重传时，products、stores、last price seen 等 fact 层数据不受影响，保持独立，避免污染。

---

## 1. 需求是否合理？

**合理。** 典型分层设计：
- **Receipt 层（小票层）**：每次上传的原始小票数据，可随时清空重来
- **Fact 层（事实/目录层）**：products、store_chains、store_locations、price_snapshots，长期积累，不随小票删除而删除

这样在 alpha 结束后清空小票重传时，产品目录、价格历史、门店信息都能保留。

---

## 2. 当前数据库做到了吗？

**部分做到，但有残留引用和副作用。**

### 2.1 删除小票时的级联行为

| 操作 | 级联效果 |
|------|----------|
| DELETE receipt_status | CASCADE → receipt_processing_runs, record_summaries, record_items |
| 删除 record_items | 不级联到 products（product_id 是 FK，ON DELETE SET NULL） |
| 删除 record_summaries | 不级联到 store_chains / store_locations |

**结论**：删除小票时，products、store_chains、store_locations 不会被级联删除，能保留。

---

## 3. 仍存在的链接与问题

### 3.1 小票层 → Fact 层的引用

| 表 | 列 | 引用 | 说明 |
|----|-----|------|------|
| record_items | product_id | → products(id) | 小票行关联产品 |
| record_items | category_id | → categories(id) | 小票行关联分类 |
| record_summaries | store_chain_id | → store_chains(id) | 小票摘要关联门店链 |
| record_summaries | store_location_id | → store_locations(id) | 小票摘要关联具体门店 |
| classification_review | source_record_item_id | → record_items(id) | 分类审核行关联小票行 |
| api_calls | receipt_id | → receipt_status(id) | API 调用关联小票 |

### 3.2 数据流与依赖关系

```
receipt_status ──CASCADE──> receipt_processing_runs
     │
     └──CASCADE──> record_summaries ──FK──> store_chains
     │                    │              └──> store_locations
     │                    │
     └──CASCADE──> record_items ──FK──> products
                          │          └──> categories
                          │
                          └──> classification_review (source_record_item_id)

price_snapshots ◄── aggregate_prices_for_date() ◄── record_items + record_summaries
     │
     └──FK──> products, store_locations
```

### 3.3 主要问题

1. **record_items / record_summaries 持有 Fact 层 FK**
   - 虽不会级联删除 Fact，但小票层仍显式引用 Fact
   - 小票删除后，products.usage_count、last_seen_date 不会回滚，会偏大/过期

2. **products.usage_count 与 last_seen_date**
   - 在 classification_review 确认时，由 record_items 写入并累加
   - 删除小票时不会自动减少，导致统计失真

3. **price_snapshots**
   - 由 aggregate_prices_for_date() 从 record_items 汇总
   - 小票删掉后，price_snapshots 不会被清空，但也不再更新
   - 逻辑上仍依赖小票数据，只是没有 FK

4. **classification_review**
   - source_record_item_id → record_items
   - 小票删除后，classification_review 中的引用会失效（若 record_items 被 CASCADE 删除）

---

## 4. 当前未做到的「提交后解耦」

目标：小票数据复制进 products/stores 后，两者之间不再保持引用关系。

当前：小票层仍然保存 product_id、store_chain_id、store_location_id 等 FK。

理想模型：
- record_items：只存 product_name、category 文本等，不存 product_id
- record_summaries：只存 store_name、store_address 等，不存 store_chain_id、store_location_id
- 提交时：从小票文本解析，UPSERT 到 products / store_chains / store_locations
- 提交后：小票表与小票行不再持有对 Fact 表的 FK

---

## 5. 改造建议（概要）

如需实现「提交后解耦」：

| 改造项 | 说明 |
|--------|------|
| record_items | 移除 product_id、category_id FK，保留 product_name、category 文本 |
| record_summaries | 移除 store_chain_id、store_location_id FK，保留 store_name、store_address |
| 提交逻辑 | 解析小票文本 → UPSERT products / store_chains / store_locations |
| products.usage_count | 改为由 job 按 record_items 实时聚合，或接受「只增不减」的语义 |
| price_snapshots | 仍从 record_items 汇总，但 record_items 不再通过 product_id 引用 products，需通过 product_name 匹配后再写入 |

注意：完全解耦需要较大改动，包括 schema、提交流程、分类审核、聚合 job 等。若仅需「删除小票不删 Fact」，当前设计已经满足；若要求「小票与 Fact 无 FK 引用」，则需要按上表做拆分与改造。
