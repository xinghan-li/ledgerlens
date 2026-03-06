# T&T Store Chain 合并后的后端逻辑与数据扫描说明

**背景**：在 DB 中将 T&T Supermarket US 与 T&T Supermarket Canada 合并为一条 store_chain，今后用商店地址区分美国/加拿大。

---

## 一、后端逻辑检查结论

### 1. 门店匹配：`get_store_chain` → `address_matcher.match_store`

- **数据来源**：完全依赖 DB 的 `store_chains` + `store_locations`（启动/首次调用时加载到内存缓存）。
- **合并后**：只存在一条 T&T 的 chain，匹配时返回同一个 `chain_id`（UUID）；地址用 `store_locations` 区分具体门店（美国/加拿大店）。
- **注意**：若合并时是「删除」了其中一条 chain：
  - `store_locations.chain_id` 为 `ON DELETE CASCADE`，**被删 chain 下的所有 store_locations 会一起被删**，加拿大 T&T 地址会从 DB 消失，`match_store` 无法再按地址匹配加拿大店。
  - 正确做法：先把要保留的那条 chain 的 id 记下，然后  
    `UPDATE store_locations SET chain_id = <保留的 chain_id> WHERE chain_id = <要删的 chain_id>`，  
    再 `DELETE FROM store_chains WHERE id = <要删的 chain_id>`。

### 2. Backfill：`backfill_record_summaries_for_store_chain`

- **逻辑**：`_store_name_matches_chain_for_backfill(store_name_lower, norm, name_lower)` 用「标准化名/名称前缀」判断是否属于该 chain。
- **合并后**：若保留的 chain 的 `normalized_name` 为 `t&t supermarket`（或等价），则：
  - `"t&t supermarket us"`、`"t&t supermarket canada"` 都会满足 `store_name_lower.startswith("t&t supermarket ")`，会被正确归到合并后的 T&T chain。
- **结论**：backfill 逻辑无需改，合并后对未关联的 T&T 小票仍会挂到唯一 T&T chain。

### 3. 流水线 / Store Config（`tnt_supermarket_us` / `tnt_supermarket_ca`）

- **来源**：来自**本地配置文件** `config/store_receipts/tnt_supermarket_us.json`、`tnt_supermarket_ca.json`，**不是** DB 的 store_chain id。
- **用途**：决定用哪套解析/清洗规则（同一套 `process_tnt_supermarket` + `clean_tnt_receipt_items`）。
- **合并后**：DB 只有一条 T&T chain，但小票上店名仍可能是 "T&T Supermarket US" 或 "T&T Supermarket Canada"，`find_chain_id_by_merchant_name` 仍会返回 `tnt_supermarket_us` 或 `tnt_supermarket_ca`，流水线照常走 T&T 专用 processor，**无需改代码**。
- **结论**：保留两个 config 键（us/ca）仅用于解析规则，与 DB「一条 chain」不冲突。

### 4. 可能出问题的地方

| 点 | 说明 |
|----|------|
| **孤儿 store_chain_id** | 若合并时只删了一条 chain、但没把其他表里的 `store_chain_id` 先改成保留的 chain id，则会出现「引用已删除 chain」的孤儿。`record_summaries` 的 FK 是默认 NO ACTION，删 chain 会报错；若先改了一部分表再删，可能留下部分表仍指向旧 id。 |
| **store_locations 被 CASCADE 删掉** | 若直接删了其中一条 chain，该 chain 下所有 `store_locations` 会被 CASCADE 删除，加拿大（或美国）的 T&T 地址全丢，后续无法按地址匹配。 |
| **product_categorization_rules 被 CASCADE 删掉** | 规则表对 `store_chain_id` 是 `ON DELETE CASCADE`，删 chain 会删掉该 chain 下所有规则，若之前有 T&T Canada 专用规则会丢失。 |
| **products** | `store_chain_id` 为 `ON DELETE SET NULL`，删 chain 后这些 product 的 `store_chain_id` 会变 NULL，逻辑上仍存在，但「按 chain 维度的商品」会变少。 |

---

## 二、数据扫描 SQL

已添加脚本：`backend/database/scripts/scan_after_store_chain_merge.sql`。

建议在 Supabase SQL Editor 或本机 psql 中执行，重点看：

1. **孤儿检查**（第 1、6 节）：各表中 `store_chain_id`/`suggested_chain_id` 指向不存在的 `store_chains.id` 的行数应为 0；若有，需要把这些引用改为合并后的 T&T chain id。
2. **T&T 当前状态**（第 2 节）：应只有一条 T&T 的 chain。
3. **未关联的 T&T 小票**（第 3b 节）：`store_chain_id IS NULL` 且 `store_name` 像 T&T 的，可跑一次 backfill 把它们挂到合并后的 chain。
4. **store_locations**（第 4 节）：合并后的 T&T chain 下应同时有美国、加拿大门店地址；若只有一国，说明合并时可能 CASCADE 删掉了另一国的 locations，需要从备份或重新录入补回。
5. **规则与商品数量**（第 5 节）：确认 T&T 下规则/商品数量是否符合预期（若曾 CASCADE 删过规则，这里会少）。

---

## 三、修复建议（若扫描发现问题）

1. **若有孤儿 store_chain_id**  
   确定「保留的 T&T chain_id」后，对每张表执行一次更新，例如：
   - `record_summaries`: `UPDATE record_summaries SET store_chain_id = <保留的 id> WHERE store_chain_id = <旧 id>;`
   - 同理处理 `products`、`classification_review`、`store_candidates`（若有）。  
   `product_categorization_rules` 若已被 CASCADE 删掉，只能重新加规则或从备份恢复。

2. **若 store_locations 缺加拿大（或美国）**  
   需要重新录入或从备份恢复被 CASCADE 删掉的 `store_locations`，并让它们的 `chain_id` 指向合并后的 T&T chain。

3. **Backfill 未关联的 T&T 小票**  
   合并后跑一次 backfill，把 `store_name` 像 T&T 但 `store_chain_id` 为空的 `record_summaries` 挂到合并后的 chain：
   - 使用现有脚本：`python -m backend.scripts.run_backfill_store_chains`（会对所有 active chain 做 backfill，包含 T&T）。

4. **以后合并 Costco / Walmart 等**  
   建议顺序：  
   (1) 选定保留的 chain_id；  
   (2) `UPDATE store_locations SET chain_id = <保留> WHERE chain_id = <要删的>`;  
   (3) `UPDATE record_summaries SET store_chain_id = <保留> WHERE store_chain_id = <要删的>`，并对 `products`、`classification_review`、`store_candidates` 做同样更新；  
   (4) 若需要保留被删 chain 的规则，先把 `product_categorization_rules` 的 `store_chain_id` 改为保留的 id，再删 chain；  
   (5) 最后 `DELETE FROM store_chains WHERE id = <要删的>`。

---

## 四、相关代码位置（便于后续改逻辑）

- 门店匹配：`backend/app/processors/enrichment/address_matcher.py`（`match_store`、`_populate_store_cache`）
- 汇总与 backfill：`backend/app/services/database/supabase_client.py`（`get_store_chain`、`backfill_record_summaries_for_store_chain`、`_store_name_matches_chain_for_backfill`）
- T&T 流水线分支：`backend/app/processors/validation/pipeline.py`（`chain_id in ("tnt_supermarket_us", "tnt_supermarket_ca")`）
- Store config 解析：`backend/app/processors/validation/store_config_loader.py`（`find_chain_id_by_merchant_name`、`get_store_config_for_receipt`）
