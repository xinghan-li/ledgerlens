# Vision-First Pipeline — Prompt 设计草稿

**日期**: 2026-03-03  
**状态**: 待你最终确认后开始写代码  
**用途**: 说明 `workflow_processor_vision.py` 里会用到的两条 prompt（Primary + Escalation），以及对应的 JSON schema。  
**注意**: 所有金额单位为**分（cents，integer）**，与现有流程一致。

---

## 流程概览（Prompt 使用时机）

```
上传图片
  ↓
[STEP 1] Primary Vision Call
  模型: gemini-2.5-flash  (GEMINI_MODEL)
  输入: 原图 + VISION_PRIMARY_PROMPT
  输出: 结构化 JSON
  ↓
后端 sum check / item count check（双重验证）
  通过 → success
  失败 ↓
[STEP 2] Escalation Vision Call (并行)
  模型A: GEMINI_ESCALATION_MODEL  (gemini-3)
  模型B: OPENAI_ESCALATION_MODEL  (gpt-5.1)
  输入: 原图 + 首轮失败原因 + VISION_ESCALATION_PROMPT
  输出: 两份 JSON
  ↓
两模型一致 → success；不一致 → needs_review + 高亮冲突字段
```

---

## 设计决定（已确认）

| 问题 | 决定 |
|------|------|
| `item_count_on_receipt` 放哪 | 只放 `_metadata`，不放 `receipt` 顶层 |
| `tbd.field_conflicts` | 移除（Vision-First 无 trusted_hints），`tbd` 简化 |
| `_metadata.confidence` | 保留，枚举 `"high"/"medium"/"low"`，由 Rule 中的条件自动降档 |
| `{failure_reason}` 格式 | 保留现有结构，额外附上首轮 Primary 输出的 `tbd.notes` |

---

## PROMPT 1 — Primary Vision Call

### 1.1 API 调用方式

| 参数 | 内容 |
|------|------|
| 模型 | `GEMINI_MODEL`（当前 `gemini-2.5-flash`） |
| 输入 | `[image_bytes]` + `VISION_PRIMARY_PROMPT`（合并为 parts） |
| temperature | 0 |
| response_mime_type | `application/json` |

```python
parts = [
    types.Part(inline_data=types.Blob(data=image_bytes, mime_type=mime_type)),
    types.Part(text=VISION_PRIMARY_PROMPT),
]
```

---

### 1.2 VISION_PRIMARY_PROMPT（完整文本）

```
You are a bookkeeper for personal shopping categorization.
Read the attached receipt image and extract the data into the JSON structure below.

RULES:
1. Read every line on the receipt. Do not skip any line.

2. All monetary amounts must be output in CENTS (integer).
   Example: $14.99 → 1499, $22.69 → 2269. Never output decimals for money.

3. Extract EVERY product line as a separate item in the items array.
   Each item must have ALL of these fields explicitly set (use null if not available):
   product_name, quantity, unit, unit_price, line_total, raw_text, is_on_sale.

4. For weighted items (e.g. "1.73 lb @ $1.88/lb"):
   set quantity=1.73, unit="lb", unit_price=188, line_total=<actual printed total>.

5. For package discounts (e.g. "2 for $5.00", "3/$9.99"):
   use the actual line_total printed on the receipt. Do NOT recalculate.
   Set is_on_sale=true.

6. Item-level price check (Rule 6):
   For each item where quantity AND unit_price are both present:
   - Calculate expected_line_total = round(quantity × unit_price)
   - If abs(expected_line_total - line_total) / line_total > 0.03 (more than 3% off):
     → Add an entry to tbd.items_with_inconsistent_price explaining the discrepancy.
     → Lower _metadata.confidence by one tier (high→medium, medium→low).
   - If the difference is ≤ 3%: use the receipt's printed line_total as-is, no penalty.
   Exception: skip this check for package discount items (is_on_sale=true with package format).

7. Receipt-level sum check (Rule 7):
   a) sum(items[*].line_total) must equal receipt.subtotal (within 3 cents or 1%).
      If receipt does not print a subtotal, compare sum(items) directly to receipt.total.
   b) receipt.subtotal + receipt.tax + receipt.fees must equal receipt.total
      (within 3 cents or 1%).
   If either check fails, re-examine the image and correct the extraction.
   If still failing after re-examination, set _metadata.sum_check_passed=false
   and document the discrepancy in _metadata.sum_check_notes.

8. If your sum check (Rule 7) fails after best effort:
   Set _metadata.validation_status="needs_review".
   Do NOT fabricate numbers to force the sum to balance.

9. Set _metadata.validation_status and _metadata.confidence with detailed reasoning:
   - Start with validation_status="pass" and confidence="high".
   - Downgrade to confidence="medium" if:
     * Any item has a price discrepancy ≤ 3% (Rule 6 soft warning)
     * Any field is unclear but best-effort readable
   - Downgrade to confidence="low" if:
     * Any item has a price discrepancy > 3% (Rule 6 hard warning)
     * Image is blurry or partially obscured for any section
   - Set validation_status="needs_review" if:
     * Sum check cannot pass after honest re-examination (Rule 8)
     * Item count on receipt does not match items extracted (see Rule 10)
     * confidence="low" AND sum_check_passed=false
   - Set _metadata.reasoning to a plain-English explanation of your validation_status
     and confidence decisions. Be specific: name which items or fields caused issues.

10. Item count check:
    If the receipt shows "Item count: N", "Iten count: N", or similar:
    - Set _metadata.item_count_on_receipt = N
    - Set _metadata.item_count_extracted = len(items)
    - If item_count_extracted < item_count_on_receipt:
      → Set validation_status="needs_review"
      → Add note in _metadata.reasoning: "Extracted X items but receipt states N"
    If no item count is printed: set _metadata.item_count_on_receipt=null.

11. payment_method must be one of these exact values (case-sensitive):
    "Visa", "Mastercard", "AmEx", "Discover", "Cash", "Gift Card", "Other"
    If two payment methods are used (e.g. Gift Card + Visa):
    output as an array: ["Gift Card", "Visa"]
    If only one method: output as a string: "Visa"
    If unknown: "Other"

12. purchase_time: output as HH:MM in 24-hour format. Drop seconds. Null if not visible.

13. fees: extract any environmental fee, bottle deposit, bag fee, CRF, etc. as a
    receipt-level total (sum of all such charges in cents). Null or 0 if none present.
    These are also included as individual line items in the items array.

14. Output only valid JSON — no markdown fences, no extra text.

OUTPUT SCHEMA (all amounts in cents):
{
  "receipt": {
    "merchant_name": "T&T Supermarket US",
    "merchant_phone": "425-640-2648 or null",
    "merchant_address": "19630 Hwy 99, Lynnwood, WA 98036 or null",
    "country": "US or null",
    "currency": "USD",
    "purchase_date": "2026-03-02 or null",
    "purchase_time": "20:30 or null",
    "subtotal": 2269,
    "tax": 0,
    "fees": 0,
    "total": 2269,
    "payment_method": "Visa",
    "card_last4": "3719 or null"
  },
  "items": [
    {
      "product_name": "GREEN ONION",
      "quantity": 2,
      "unit": null,
      "unit_price": 129,
      "line_total": 258,
      "raw_text": "GREEN ONION   2   1.29   2.58",
      "is_on_sale": false
    },
    {
      "product_name": "LETTUCE STEM",
      "quantity": 1.73,
      "unit": "lb",
      "unit_price": 188,
      "line_total": 325,
      "raw_text": "(SALE) LETTUCE STEM  1.73 lb @ $1.88/lb  FP $3.25",
      "is_on_sale": true
    }
  ],
  "tbd": {
    "items_with_inconsistent_price": [
      {
        "product_name": "EXAMPLE ITEM",
        "raw_text": "EXAMPLE ITEM  2  1.29  2.75",
        "expected_line_total": 258,
        "actual_line_total": 275,
        "discrepancy_pct": 6.6,
        "note": "quantity × unit_price = 258 but receipt shows 275 (6.6% off, exceeds 3% threshold)"
      }
    ],
    "missing_info": [],
    "notes": "free-form observations about receipt quality or extraction issues"
  },
  "_metadata": {
    "validation_status": "pass",
    "confidence": "high",
    "reasoning": "All 9 items extracted. Sum check passed: items sum 2269 = total 2269. Item count matches receipt footer (Item count: 9). No price discrepancies.",
    "sum_check_passed": true,
    "sum_check_notes": null,
    "item_count_on_receipt": 9,
    "item_count_extracted": 9
  }
}
```

---

### 1.3 字段说明

| 字段 | 说明 |
|------|------|
| `receipt.fees` | 所有 environmental/bottle/bag 等附加费合计（分），单独成行的 item 同时也在 items 里 |
| `receipt.payment_method` | 单值 `"Visa"` 或双值数组 `["Gift Card", "Visa"]` |
| `receipt.purchase_time` | HH:MM，24 小时制，无秒 |
| `_metadata.validation_status` | `"pass"` 或 `"needs_review"`，工作流直接读此字段 |
| `_metadata.confidence` | `"high"/"medium"/"low"`，由 Rule 6/9 条件自动降档 |
| `_metadata.reasoning` | 详细说明 validation_status 和 confidence 的判断依据 |
| `_metadata.sum_check_passed` | 模型自报，后端 `sum_checker.py` 会再验一遍 |
| `_metadata.item_count_on_receipt` | 从小票 footer 读到的 N，没有则 null |
| `_metadata.item_count_extracted` | `len(items)` |
| `tbd.items_with_inconsistent_price` | Rule 6 中发现价格不一致的行（>3%才记录） |

---

## PROMPT 2 — Escalation Vision Call

### 2.1 API 调用方式

| 参数 | 内容 |
|------|------|
| 模型 A | `GEMINI_ESCALATION_MODEL`（当前 `gemini-3`）|
| 模型 B | `OPENAI_ESCALATION_MODEL`（当前 `gpt-5.1`）|
| 输入 | `[image_bytes]` + `VISION_ESCALATION_PROMPT`（含首轮失败原因） |
| temperature | 0 |
| 两模型并行调用 | 与现有 `_escalation_to_strongest_models` 逻辑一致 |

---

### 2.2 VISION_ESCALATION_PROMPT（完整文本）

> `{failure_reason}` 在运行时替换；`{primary_notes}` 替换为首轮 `tbd.notes`。

```
You are a senior bookkeeper for personal shopping categorization.
A faster model (gemini-2.5-flash) attempted to read the attached receipt image but could not produce a reliable result.

FAILURE REASON FROM PREVIOUS ATTEMPT:
{failure_reason}

NOTES FROM PREVIOUS ATTEMPT:
{primary_notes}

Please read the original receipt image again carefully and produce a corrected, fully structured JSON.

RULES:
1. Read EVERY line on the receipt — do not skip any product line.

2. All monetary amounts must be output in CENTS (integer). Example: $14.99 → 1499.
   Never output decimals for money.

3. Each item must have ALL fields explicitly set (null if not available):
   product_name, quantity, unit, unit_price, line_total, raw_text, is_on_sale.

4. If the receipt shows "Item count: N" or "Iten count: N" at the bottom:
   You MUST extract exactly N product items (excluding points/rewards/fee-only lines).
   Set _metadata.item_count_on_receipt=N and _metadata.item_count_extracted=len(items).

5. For weighted items (e.g. "1.73 lb @ $1.88/lb"):
   set quantity=1.73, unit="lb", unit_price=188, line_total=<actual printed total>.

6. Item-level price check:
   For each item where quantity AND unit_price are both present:
   - If abs(quantity × unit_price - line_total) / line_total > 0.03:
     → Add to tbd.items_with_inconsistent_price with discrepancy details.
     → Lower confidence by one tier.

7. Receipt-level sum check:
   a) sum(items[*].line_total) must equal receipt.subtotal (within 3 cents or 1%).
   b) receipt.subtotal + receipt.tax + receipt.fees must equal receipt.total
      (within 3 cents or 1%).
   If checks fail after honest extraction, report in _metadata.sum_check_notes.
   Do NOT fabricate numbers.

8. payment_method must be one of: "Visa", "Mastercard", "AmEx", "Discover", "Cash",
   "Gift Card", "Other". If two methods: output as array ["Gift Card", "Visa"].

9. purchase_time: HH:MM in 24-hour format. Drop seconds.

10. fees: sum of all environmental/bottle/bag/CRF charges at receipt level (cents).

11. Set _metadata.validation_status and reasoning:
    - "pass" if sum check passes, item count matches, confidence is high or medium.
    - "needs_review" if sum check fails or item count mismatches or confidence is low.
    - _metadata.reasoning must explain specifically what passed or failed.

12. Output only valid JSON — no markdown, no extra text.

OUTPUT SCHEMA (identical to primary, all amounts in cents):
{
  "receipt": {
    "merchant_name": "string or null",
    "merchant_phone": "string or null",
    "merchant_address": "string or null",
    "country": "string or null",
    "currency": "USD",
    "purchase_date": "YYYY-MM-DD or null",
    "purchase_time": "HH:MM or null",
    "subtotal": 2269,
    "tax": 0,
    "fees": 0,
    "total": 2269,
    "payment_method": "Visa",
    "card_last4": "3719 or null"
  },
  "items": [
    {
      "product_name": "GREEN ONION",
      "quantity": 2,
      "unit": null,
      "unit_price": 129,
      "line_total": 258,
      "raw_text": "GREEN ONION   2   1.29   2.58",
      "is_on_sale": false
    }
  ],
  "tbd": {
    "items_with_inconsistent_price": [],
    "missing_info": [],
    "notes": "free-form observations"
  },
  "_metadata": {
    "validation_status": "pass",
    "confidence": "high",
    "reasoning": "Specific explanation of what passed/failed and why.",
    "sum_check_passed": true,
    "sum_check_notes": null,
    "item_count_on_receipt": 9,
    "item_count_extracted": 9
  }
}
```

---

### 2.3 `{failure_reason}` 运行时填充示例

```
Sum check failed:
  - items sum: 2300 cents
  - receipt total: 2269 cents
  - difference: 31 cents (exceeds 3-cent / 1% tolerance)

Item count mismatch:
  - receipt footer states: 9 items
  - extracted by primary model: 7 items
  - likely missing: lines with "FP $2.89" and "FP $0.99" had no product name matched

Primary model validation_status: needs_review
```

---

## 后端对 Vision 输出的二次验证（代码层，非 prompt）

即使模型自报 `validation_status="pass"`，后端 `sum_checker.py` 仍会：
1. 用 `_extract_receipt_item_count(raw_text)` 从 raw_text 二次确认 item count（保险）
2. 重新跑 `check_receipt_sums()` 做独立 sum check
3. 若后端 sum check 失败 → 覆盖为 `needs_review`，进入 escalation

这样模型层和代码层双重把关，不完全依赖模型自报。

---

> 确认以上后开始写代码。如有修改意见直接告诉我。
