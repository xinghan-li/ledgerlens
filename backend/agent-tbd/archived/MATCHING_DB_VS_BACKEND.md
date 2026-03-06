> **结论（归档原因）**：部分过时。DB 的 find_categorization_rule RPC 已废弃，匹配逻辑已迁移到后端；以 docs/categorization-matching.md 为准。保留作历史参考。

# 分类规则匹配：DB vs 后端

## 当前分工

- **数据库（RPC）**：`find_categorization_rule(p_normalized_name, p_store_chain_id, p_threshold)`  
  顺序：store-specific exact → universal exact → store-specific fuzzy → universal fuzzy → store-specific contains → universal contains。  
  **没有** prefix 逻辑（由 migration 033 保证）。

- **后端**：在 `receipt_categorizer._enrich_items_category_from_rules` 里：
  1. 先调 RPC `find_categorization_rule`（exact / fuzzy / contains）；
  2. 若 RPC 无结果且 `len(normalized_name) >= 20`，再做 **prefix 匹配**：查 `product_categorization_rules` 中 `normalized_name ILIKE receipt_normalized_name + '%'`（即规则名以小票归一化名为前缀），用于小票名被截断、规则存完整名的情况（如小票 "soup dumplings pork and"，规则 "soup dumplings pork and ginger"）。

## 小结

- 主要匹配（exact / fuzzy / contains）在 **DB**。
- 只有「小票名为规则名前缀」的 **prefix 匹配** 在 **后端**，且仅当 RPC 未命中且名称长度 ≥ 20 时使用。
