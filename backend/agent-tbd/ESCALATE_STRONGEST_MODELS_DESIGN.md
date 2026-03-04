# 最强模型兜底设计：OCR/LLM 双 needs_review 时直接看图 + 双模型共识

**日期**: 2026-03-04  
**背景**: 传统 OCR + 常规 LLM 对部分小票（如 T&T 这张）识别差、行项错配（如葱 2.58 填成 2.89）。Gemini 3 等最强模型直接读图毫无压力。在「OCR 与 LLM 结构均为 needs_review」时，用原图直接交给最强模型，并用双模型共识做校验，一致部分采纳，不一致部分交给客户复核。

---

## 1. 触发条件

- **仅当** 以下同时成立时进入本兜底流程：
  - OCR 阶段结果为 **needs_review**（如 Document AI 的 `validation_status: needs_review` 或 OCR 失败/质量差）；
  - 且后续 LLM 结构化结果也为 **needs_review**（如 `_metadata.validation_status: needs_review` 或 sum check 失败后 cascade 仍不通过）。
- 即：**只有 OCR 和 LLM 结构都 needs_review 时才「直接扔图给最强模型」**，避免对正常单也走昂贵模型。

---

## 2. 流程概要

1. **输入**：小票原图 `image_bytes`（不再依赖既有 OCR 文本）。
2. **调用**：将同一张图、同一套「结构化 JSON」的 schema 与说明，分别发给：
   - **OpenAI 最强模型**（如 o1、GPT-5.1 等，见下 API 配置）；
   - **Gemini 最强模型**（如 Gemini 3）。
3. **Prompt 要点**：明确说明「传统 OCR 无法可靠识别这张小票，请直接阅读图片并输出结构化 JSON」，并列出字段：店名、地址、电话、商品行（items：名称、数量、单价、行小计）、subtotal、total、支付方式、Visa 尾号、日期、时间等（与现有 receipt schema 对齐）。
4. **输出**：两份结构化 JSON（与现有 `receipt` + `items` 结构兼容）。
5. **校验（共识）**：
   - **一致部分**：两模型在某一字段/某一行上的输出一致（或数值在容差内一致）→ 采纳为最终结果；
   - **不一致部分**：两模型在该字段或该行不一致 → 标记为 **escalate 给客户**（needs_review），前端可展示「模型 A / 模型 B 分别给出 X / Y，请确认」。
6. **落库与状态**：
   - 若整单共识度高（如关键字段 total、subtotal、items 合计均一致），可标为 success，仅对不一致的字段做 needs_review 或留 note；
   - 若关键字段不一致或差异大，整单标 needs_review，并把两份结果都存下来供前端对比/编辑。

---

## 3. 输出结构（与现有 schema 对齐）

沿用现有 receipt 结构化 schema，便于与当前 pipeline 复用 sum_check、categorize 等逻辑。例如：

- `receipt`: merchant_name, merchant_address, merchant_phone, subtotal, tax, total, currency, payment_method, card_last4, purchase_date, purchase_time, country 等；
- `items`: product_name, quantity, unit, unit_price, line_total, raw_text, is_on_sale 等。

这样「双模型共识」后的结果可以直接走现有 sum check（容差 3 分或 1%）和 categorization。

---

## 4. API 与配置建议

- **环境变量 / 配置项**（建议在 `config.py` 或 `.env` 中）：
  - **触发开关**（可选）：如 `ENABLE_ESCALATION_STRONGEST_MODELS=true`，仅在此为 true 且上述「OCR + LLM 双 needs_review」满足时才走兜底。
  - **OpenAI 兜底模型**：如 `OPENAI_ESCALATION_MODEL=o1` 或 `gpt-5.1`（具体型号以你当前 API 支持为准）。不设则可不走 OpenAI 兜底或沿用现有 `OPENAI_MODEL`。
  - **Gemini 兜底模型**：如 `GEMINI_ESCALATION_MODEL=gemini-2.5-pro` 或未来 `gemini-3`。不设则可不走 Gemini 兜底或沿用现有 `GEMINI_MODEL`。
- **API Key**：复用现有 `OPENAI_API_KEY`、`GEMINI_API_KEY` 即可；若希望兜底走不同账号，可再增加 `OPENAI_ESCALATION_API_KEY` 等（按需）。
- **调用方式**：与现有 Vision 调用一致，只传图片 + 上述「直接读图输出 JSON」的 system/user prompt，不传 OCR 文本。

---

## 5. 校验规则（双模型共识）

- **数值字段**（如 total, subtotal, line_total）：两模型结果在「3 分或 1%」容差内视为一致，否则标为不一致 → escalate。
- **文本字段**（如 merchant_name, product_name）：字符串一致或高相似度（如 trim、大小写归一后相等，或编辑距离小于阈值）视为一致，否则 escalate。
- **items 行**：可按「行顺序 + 行小计」或「product_name + line_total」做对齐后逐行比较，一致行采纳，不一致行标出并 escalate 给客户确认。

---

## 6. 与现有流程的衔接

- 本兜底在 **cascade 末端** 插入：当「OCR needs_review 且 LLM 结构也 needs_review」时，不直接标 needs_review 结束，而是先走「最强模型 + 共识」；若共识后仍有关键不一致，再标 needs_review 并保存两份结果供前端。
- 现有 **sum_check**、**categorize**、**receipt_status** 逻辑可继续复用：把共识后的 JSON 当作「首轮 LLM 结果」再跑一遍 sum check 和 categorize 即可。

---

## 7. 小结

| 项目       | 说明 |
|------------|------|
| 触发       | 仅当 OCR 与 LLM 结构 **都** needs_review |
| 输入       | 小票原图，不依赖 OCR 文本 |
| 模型       | OpenAI 最强（如 o1/5.1）+ Gemini 最强（如 Gemini 3），由配置指定 |
| 校验       | 两模型输出一致部分采纳，不一致部分 escalate 给客户 |
| API 配置   | `ENABLE_ESCALATION_STRONGEST_MODELS`、`OPENAI_ESCALATION_MODEL`、`GEMINI_ESCALATION_MODEL`（及可选 key） |

实现时可在 `workflow_processor` 中在「cascade 仍失败 / 仍 needs_review」的分支里增加本段逻辑，并增加对应 config 与调用最强模型的 client 封装。
