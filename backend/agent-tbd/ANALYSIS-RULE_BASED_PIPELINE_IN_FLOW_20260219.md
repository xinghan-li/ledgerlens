# Rule-Based 清洗在流程中的位置与 receipt_processing_runs 的差异

## 结论

**Rule-based 清洗（横行竖列、store-specific 规则）已经在流程里**，在 LLM 之前执行，且结果会作为 prompt 的一部分传给 LLM。但 **receipt_processing_runs 表里没有单独记录这一步**，LLM 的 `input_payload` 之前只存了 `ocr_result`，所以看起来像「LLM 的输入直接就是 OCR」。

---

## 实际流程（workflow_processor）

1. **Step 1: Google Document AI OCR**  
   - 产出：`google_ocr_result`（含 `coordinate_data` 等）  
   - 存库：`receipt_processing_runs` 一条 **ocr** 记录，`output_payload` = 原始 OCR。

2. **Step 1.5: Initial Parse（rule-based）**  
   - 从 OCR 取 `coordinate_data` → `extract_text_blocks_with_coordinates` → blocks  
   - `get_store_config_for_receipt(merchant_name, blocks)` → **store-specific** config（T&T / Trader Joe's / Costco 等）  
   - `process_receipt_pipeline(blocks, store_config, merchant_name)`：  
     - **wash**：store config 的 `wash_data.amount_exclude_patterns`（如 SC-1、Points 等不算金额）  
     - **skew**：store-specific 纠偏  
     - **rows** → **columns** → **regions**（header / items / totals / payment，store markers）  
     - **items** → **totals** → **tax/fees** → **validation**  
   - T&T 会走专用 `process_tnt_supermarket`，其他店走 generic 或 Trader Joe's / Costco 专用 processor。  
   - 产出：`initial_parse_result`（items、totals、validation、method、chain_id 等）。  
   - **此前没有**写入 `receipt_processing_runs`，也没有出现在 LLM 的 `input_payload` 里。

3. **Step 3: LLM**  
   - 调用 `process_receipt_with_llm_from_ocr(ocr_result=google_ocr_data, initial_parse_result=initial_parse_result)`  
   - Prompt 里会拼上 **Initial Parse Result (Rule-Based Extraction)** 的摘要（items、totals、validation 等），让 LLM 参考。  
   - 存库：`receipt_processing_runs` 一条 **llm** 记录；此前 **input_payload 只有 `ocr_result`**，没有体现 rule-based 结果。

4. **Step 4 / 4.5 / 4.6**  
   - `clean_llm_result`、`clean_tnt_receipt_items`、`correct_address` 等是对 **LLM 输出** 的后处理，不是对 OCR 的预清洗。

---

## 为何会以为「rule-based 没在流程里」

- 表里只能看到：**ocr** 的 output = 原始 OCR，**llm** 的 input = 原始 OCR。  
- 中间那步 initial_parse（rule-based 横行竖列 + store-specific 规则）没有单独一行 run，也没有写在 LLM 的 input 里，所以从表结构上看不到「清洗后的结果」作为 LLM 的输入。

---

## 已做/建议的改动

1. **在 LLM 的 input_payload 里带上 initial_parse 摘要**  
   - 例如增加 `initial_parse_summary`：`success`、`method`、`items_count`、`chain_id` 等（不塞整份 result 以免 payload 过大）。  
   - 这样在 `receipt_processing_runs` 里能直接看到「LLM 的输入包含 rule-based 结果」，便于排查和审计。

2. **（可选）为 initial_parse 单独写一条 run**  
   - 若希望「rule-based 清洗结果」有完整一条记录，可新增 stage 如 `initial_parse`，保存：  
     - input_payload = 原始 OCR 或其引用  
     - output_payload = `initial_parse_result`  
   - 需要确认 `receipt_processing_runs.stage` 是否允许新值（当前为 ocr / llm / manual），必要时做小迁移或约定扩展。

---

## 相关代码位置

| 环节           | 文件 / 位置 |
|----------------|--------------|
| Initial parse 入口 | `workflow_processor.py` Step 1.5，`initial_parse` + `process_receipt_pipeline` |
| Store config   | `store_config_loader.get_store_config_for_receipt` |
| Pipeline 实现  | `processors/validation/pipeline.py`（wash → skew → rows → columns → regions → items → totals → tax/fees） |
| T&T 专用       | `processors/stores/tnt_supermarket/processor.py` |
| LLM 使用 initial_parse | `prompt_manager.format_prompt(..., initial_parse_result=...)`，拼到 user message |
| 存 LLM run     | `workflow_processor.py` 中 `save_processing_run(..., input_payload={"ocr_result": ...})` |
