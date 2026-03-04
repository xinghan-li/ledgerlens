# T&T 小票 (最新上传) OCR 与 success/needs_review 诊断

**日期**: 2026-03-04  
**小票 receipt_id**: `70a22790-f5af-44aa-a818-b57d4195994e`  
**当前状态**: success（应为 needs_review）

## 1. 数据库查询结果摘要

- **最新小票**: 按 `uploaded_at` 取最新一条
- **Processing runs**: 4 条（OCR → rule_based_cleaning → llm 首轮 → llm debug_ocr）

## 2. OCR 与行项金额问题

### 2.1 葱 (GREEN ONION) 行金额错填：2.58 vs 2.89

- 小票上：**GREEN ONION - 2 @ $1.29ea → 应为 $2.58**
- 解析结果里该行被填成 **$2.89**（$2.89 实际是 KO-LE CABBAGE 的 line total：2.92 lb × $0.99/lb ≈ $2.89）
- 即 **line_total 串行/错配**：葱的金额错用成高丽菜那行的金额，导致 items 合计偏大（多出约 0.31），进而和真实 total $22.69 对不上；若再误把 subtotal 填成 23，就会出现「合计 23、total 22.69 却仍被判通过」的荒谬情况。根因是 OCR/LLM 把不同行的金额对错了，而不是「允许 3 分或 1%」的问题。

### 2.2 Document AI OCR (Run 1)

- **line_items**: 只有 **1 条** —— `"Points 20 0.00"`（唯一被识别为 line_item 的实体）
- **merchant_name**: `"Balance 180 Gymnastics & Sports Academy"`（错误，应为 T&T Supermarket）
- **raw_text**: 完整文本里有 T&T、商品行等，但 **结构化 line_items 里没有 KO-LE CABBAGE、Cilantro**
- **validation_status**: OCR 层已标 `needs_review`（共 6 条 needs_review 项）

结论：**OCR 的结构化抽取严重错误**——门店错、商品只识别到 1 行，KO-LE CABBAGE 和 Cilantro 未出现在 `line_items` 中。raw_text 中有 “FP $2.89”“FP $0.99” 等行，对应这两项金额，但未与商品名正确配对。

### 2.3 Rule-based cleaning (Run 2)

- **success**: False（initial_parse failed or no coordinate data）
- 使用 OCR 的 raw_text 做了分段，得到 6 个 item，但多个为 N/A

### 2.4 LLM 首轮 (Run 3) 与 Debug OCR (Run 4)

- 首轮 LLM 输出 8 个 item，**仍缺 KO-LE CABBAGE、Cilantro**；有一项为 “FP $0.99” 无商品名（对应 Cilantro 金额）
- **field_conflicts**: 明确提到 "Item count: 9" 但只识别到 8 个 item、"Several 'FP $X.XX' lines appeared without clear product context"
- **_metadata.validation_status**: **needs_review**（两轮 LLM 均为 needs_review）

## 3. 为何最终是 success 而不是 needs_review

### 3.1 当前逻辑

- `receipt_status.current_status` 的 **唯一驱动** 是 **Sum Check 是否通过**：
  - `sum_check_passed` → `success`
  - 否则进入 cascade（debug OCR → debug vision → AWS），仍失败则 `needs_review`
- **LLM 的 `_metadata.validation_status: "needs_review"` 目前未参与** 是否标为 success 的决策。

### 3.2 为何 Sum Check 会通过（误判）

- **Run 4 (debug_ocr)** 的 LLM 输出中：
  - **receipt.total**: `22.69`（美元）
  - **receipt.subtotal**: `23.0`（美元）或 **未填**
  - **items 的 line_total 之和**: `23.0`（美元），与真实 total 22.69 差 0.31（见上文葱 2.58 被错填成 2.89 等行项错配）
- 容差被错误实现为 **裸数字 3**，而不是「3 分或 1%」：
  - 比较时用 `差额 <= 3`，在金额为美元时相当于把 3 当成 3 美元容差；
  - `subtotal - total = 23.0 - 22.69 = 0.31` → `0.31 <= 3` 被误判为通过。
- **Subtotal 未填时**：逻辑会走「用 line_total 之和与 total 比较」。若 total 为 22.69、line_total 之和为 23.0，差额 0.31；同样因容差是数字 3，0.31 <= 3 再次误判通过。所以 **即使用户在前端看到 items 加起来和 22.69 差很多，只要当时容差是“数字 3”，就会错误通过**。

因此：**容差必须是「3 分或 1%」、且单位与金额一致**；不能使用裸数字 3。已改为 `max(3 分, 1% 参考金额)`。

## 4. 修复建议（已做 / 待做）

1. **Sum Check 容差：3 分或 1%**（已实现）
   - 容差 = `max(3 分, 1% × 参考金额)`，单位与金额一致；禁止裸数字 3。

2. **LLM validation_status 纳入决策**（已实现）
   - 若 LLM 返回 `_metadata.validation_status == "needs_review"`，即使 Sum Check 通过也标 **needs_review**。

3. **行项金额错配（如葱 2.58 vs 2.89）**
   - 属 OCR/LLM 行与行对应错误，需在 prompt 或后处理中强调「每行 line_total 必须与该行商品一致」；或通过最强模型兜底（见下）减少此类错误。

4. **最强模型兜底（needs_review 时直接看图 + 双模型共识）**
   - 当 **OCR 与 LLM 结构均为 needs_review** 时，将 **原图** 直接交给最强模型（如 OpenAI o1/5.1、Gemini 3），提示「传统 OCR 无法可靠识别，请直接读图并输出结构化 JSON」；用 **双模型输出一致的部分** 作为通过，**不一致的部分** 标给客户复核。详见 `ESCALATE_STRONGEST_MODELS_DESIGN.md`。

5. **小票件数校验（Item count check）**（已实现）
   - 若小票底部有 **"Item count: N"**（或 "Iten count: N" 等），且解析出的商品行数 **少于 N**，则 Sum Check **不通过**，进入 cascade/needs_review，避免漏掉 KO-LE CABBAGE、Chinese White Radish 等行仍被判 success。
   - 流程在调用 `check_receipt_sums` 前会注入 OCR 的完整 `raw_text`，以便从 raw_text 中解析出 "Item count: 9"。
