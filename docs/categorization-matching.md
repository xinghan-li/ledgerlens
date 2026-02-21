# 分类匹配逻辑（Categorization Matching）

## 概述

Smart categorization（以及全量小票分类）的匹配**全部在后端 Python 完成**：先查表做 exact，未命中再用后端维护的 universal 规则做 fuzzy，仍未命中可走 LLM（若有）。

## 匹配流程

1. **Exact（数据库表）**  
   用归一化商品名查 `product_categorization_rules`：
   - `normalized_name` 精确等于当前名（支持空格/下划线两种形式）
   - 先 store-specific（`store_chain_id` 匹配），再 universal（`store_chain_id IS NULL`）
   - 命中则得到 `category_id`，分类结束

2. **Universal fuzzy（后端维护）**  
   未命中时，用后端维护的「与 CSV 同源」的 universal 规则做模糊匹配：
   - 数据来源：`backend/data/initial_categorization_rules.csv` 中 `store_chain_name = NULL` 的行
   - 匹配方式：先 **contains**（规则名 in 商品名，最长优先），再 **fuzzy**（rapidfuzz ratio ≥ 90）
   - 解析 `category_path` 到 `categories.id`，写入 `category_id`

3. **仍未命中**  
   交给后续步骤（例如 LLM 建议），或留空由用户校对。

## 数据与代码位置

- **Exact 查表**：`receipt_categorizer._match_exact_from_db()`，只做精确匹配
- **Universal fuzzy**：`receipt_categorizer._load_universal_rules_for_fuzzy()` + `_match_universal_fuzzy()`
- **统一入口**：`receipt_categorizer.get_category_id_for_product(normalized_name, store_chain_id)`，供 categorizer 与 product_normalizer 共用

## 数据库侧

- `product_categorization_rules` 表仍用于 exact 查询（以及 store-specific 规则）
- **已废弃**：DB 内的 `find_categorization_rule` RPC（exact/fuzzy/contains 逻辑已迁移到后端，见 migration 037）
- `update_rule_match_stats` 仍保留，供 Classification Review 等场景更新规则统计

---

## TODO（未来实现）

- **Confidence score**：为每个匹配结果输出置信度分数，用户只需重点核对低分项，无需逐条全看。  
  - 实现前可在此补充设计（分数来源：exact=1.0，fuzzy=score/100，LLM=待定等）。
