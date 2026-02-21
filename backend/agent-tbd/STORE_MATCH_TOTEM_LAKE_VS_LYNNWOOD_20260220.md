# 商店识别逻辑：无匹配不落店，进 store_candidates

## 正确逻辑（与实现一致）

1. **store_locations 没有该门店（如 Totem Lake）时，不判定到任何已有门店（如 Lynnwood）**  
   有小票地址时**只做地址匹配**：小票地址与 DB 中某条 `store_locations` 地址 fuzzy 相似度 ≥ 90% 且店名一致 ⇒ 判定为该门店。  
   **若没有任何一条 location 的地址匹配 ⇒ 视为无匹配，不分配 chain_id/location_id，不落回同 chain 的其他店。**

2. **无匹配时**  
   - **输出 JSON**：使用**清理后的原地址**（LLM 提取的 `receipt.merchant_name` / `receipt.merchant_address`），不强制写入任何 canonical 地址。  
   - **人工审核**：为该小票创建 **store_candidates**（含 receipt_id、店名、地址等），进入人工地址审核；审核通过后再把正确地址加到 `store_locations`。

3. **无小票地址时**  
   才退回到「按名称」匹配：仅当能唯一定位到一家店（例如按门店名，或该 chain 只有一家店）时才返回 matched。

## 代码要点

- **address_matcher.match_store**  
  - 若有 `store_address`：只做地址匹配；若没有任一条 DB 地址达到阈值 ⇒ **直接返回 no match**，不做按店名/chain 名的 fallback。  
  - 若无 `store_address`：才做按门店名或单店 chain 的名称匹配。

- **correct_address**  
  - 仅当 `match_store` 返回 matched 时才用 canonical 覆盖 receipt；未匹配时保持原 `merchant_name` / `merchant_address`。

- **receipt_llm_processor**  
  - `get_store_chain` 未匹配时 `final_chain_id` / `final_location_id` 为 None，输出 `_metadata` 不写 chain_id/location_id；并调用 `create_store_candidate` 进入人工审核。
