# Categorization API 实际行为 vs 设想（Gap 说明）

## 文档目的

说明当前 **Categorization API**（`/api/receipt/categorize/{receipt_id}` 及 batch）**实际在做什么**，以及和“标准化 + 分类”设想的差异，便于对齐预期和后续改代码。

---

## 1. 当前 Categorization API 实际在做什么

流程概览：

1. **校验**：receipt 存在、`current_status = success`、存在一条 `stage=llm` 且 `status=pass` 的 processing run，且 `output_payload` 里有 `receipt` 和 `items`。
2. **若不 force**：若该 receipt 在 `receipt_summaries` 里已有记录，直接返回 “Already categorized”。
3. **读数据**：从 `receipt_processing_runs` 取最新一次 LLM 通过的 `output_payload`，得到：
   - `receipt_data = output_payload["receipt"]`（LLM 原始 receipt 节点）
   - `items_data = output_payload["items"]`（LLM 原始 items 数组）
4. **写 receipt_summaries**：调用 `save_receipt_summary(receipt_id, user_id, receipt_data)`。  
   - 这里 **只用了 `receipt_data`**（即 LLM 的 receipt），**没有用 `output_payload["_metadata"]`**。  
   - `save_receipt_summary` 内部用 `receipt_data.get("merchant_name")` 再去查 `store_chains` 做匹配，得到 `store_chain_id` / `store_location_id`；若 LLM 没填或匹配不到，这两项就是 NULL。
5. **写 receipt_items**：调用 `save_receipt_items(receipt_id, user_id, items_data)`。  
   - 这里用的是 **LLM 原始 items**，**没有**经过 `product_normalizer.standardize_product()`。  
   - 即：**没有**用你们现有的“商品名标准化、规则表 + 关键词分类”逻辑，只是把 LLM 返回的 `product_name`、`quantity`、`unit_price`、`line_total` 以及 **LLM 自己出的 category 字符串**（如 `"Grocery > Produce > Fruit"`）拆成 `category_l1/l2/l3` 存进 `receipt_items`。

所以，**当前 API 的实质是**：

- 把“**已跑完 LLM、且 sum check 通过**”的那份 `output_payload` 里的 **receipt + items 原样落库**到 `receipt_summaries` 和 `receipt_items`；
- 门店匹配只依赖 **LLM 的 receipt.merchant_name** 再查一次 store，**没有用** workflow 里已经算好的 `_metadata.chain_id` / `_metadata.location_id`；
- **没有**调用标准化/规则/关键词分类，所以**没有**“用 product_normalizer + 规则表做分类”这一步。

---

## 2. 和“你设想”的典型 gap

可能存在的设想 vs 实际对比如下（方便你勾选哪些符合你的预期）：

| 设想 | 实际 |
|------|------|
| 调用 Categorization API 时，会用 **标准化 + 规则/关键词** 给商品做分类 | 不会。只存 LLM 原始 items，category 完全来自 LLM 返回的字符串 |
| 小票已经通过 workflow 匹配到 store（有 chain_id/location_id），落 summary 时应用这份结果 | 不会。summary 的 store_chain_id/store_location_id 只用 `receipt.merchant_name` 再查一次，没用 `_metadata.chain_id` / `_metadata.location_id` |
| Categorization = “标准化商品名 + 品牌 + 分类再落库” | 当前 = “LLM 原始结果落库”，没有标准化步骤 |

因此，若你希望“**按 store_location_id 链接、且用规则/标准化做分类**”，需要：

- 要么在 Categorization API 里**先**对每条 item 调 `standardize_product()`（并传入 `store_chain_id`/location 等），再用标准化后的结果写 `receipt_items`；
- 要么在写 `receipt_summaries` 时，优先使用 `output_payload["_metadata"]` 里的 `chain_id` / `location_id`，仅在没有时才用 merchant_name 再匹配。

---

## 3. 小结

- **Categorization API 现在做的**：把 LLM 的 receipt + items **原样**写入 `receipt_summaries` 和 `receipt_items`，门店只靠 merchant_name 再匹配，**没有**标准化、也没有用规则表/关键词分类。
- **和设想的 gap**：没有用 workflow 的 store 匹配结果（_metadata），也没有用 product_normalizer + 规则表做分类；若要和你设想一致，需要在 API 内接入标准化逻辑并优先使用 _metadata 的 location_id/chain_id。

如需，我可以按你现有代码结构给一版“在 Categorization API 里接入 standardize_product + _metadata”的具体改法（函数调用顺序与字段传递）。
