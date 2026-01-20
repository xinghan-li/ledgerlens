-- Example: Insert a prompt for T&T Supermarket
-- This is a template that you can customize for each merchant

-- First, ensure the merchant exists (or get its ID)
-- Assuming merchant_id = 1 for T&T Supermarket

INSERT INTO merchant_prompts (
  merchant_id,
  merchant_name,
  prompt_template,
  system_message,
  model_name,
  temperature,
  output_schema,
  is_active
) VALUES (
  1,  -- Replace with actual merchant_id
  'T&T Supermarket',
  'Parse the following receipt text and extract structured information.

## Raw Text:
{raw_text}

## Trusted Hints (high confidence fields from Document AI):
{trusted_hints}

## Output Schema:
{output_schema}

## Instructions:
1. Extract receipt-level fields (merchant, date, time, amounts, payment method)
2. Extract all line items from raw_text, ensuring each item has:
   - product_name (cleaned, no extra formatting)
   - quantity and unit (if available)
   - unit_price (if available)
   - line_total (must match quantity × unit_price if both are present)
3. Validate calculations:
   - For each item: if quantity and unit_price exist, verify: quantity × unit_price ≈ line_total (±0.01)
   - Sum all line_totals and verify: sum ≈ total (±0.01)
4. Document any issues in the "tbd" section:
   - Items with inconsistent price calculations
   - Field conflicts between raw_text and trusted_hints
   - Missing information

## T&T Supermarket Specific Notes:
- Items are often listed with "FP" (Final Price) prefix
- Weight-based items show format: "X.XX lb @ $X.XX/lb FP $X.XX"
- Sale items are marked with "(SALE)" prefix
- Categories: FOOD, PRODUCE, DELI, etc.

## Currency Logic:
- T&T stores are in USA/Canada, default to USD for USA, CAD for Canada
- If currency is explicitly mentioned in raw_text, use that

## Important:
- If raw_text conflicts with trusted_hints, prefer raw_text and document conflict in tbd
- Do not invent or guess values - use null if information is not available
- Output must be valid JSON matching the schema exactly

Output the JSON now:',
  'You are a receipt parsing expert specializing in T&T Supermarket receipts. Your task is to extract structured information from receipt text and trusted hints from Document AI.

Key requirements:
1. Output ONLY valid JSON, no additional text
2. Follow the exact schema provided
3. Perform validation: quantity × unit_price ≈ line_total (tolerance: ±0.01)
4. Sum of all line_totals must ≈ total (tolerance: ±0.01)
5. If information is missing or uncertain, set to null and document in tbd
6. Do not hallucinate or guess values
7. Pay special attention to T&T''s format with FP prices and weight-based items',
  NULL,  -- 使用环境变量 OPENAI_MODEL 的默认值
  0.0,
  '{
    "receipt": {
      "merchant_name": "string or null",
      "merchant_address": "string or null",
      "merchant_phone": "string or null",
      "country": "string or null",
      "currency": "string (USD, CAD, etc.)",
      "purchase_date": "string (YYYY-MM-DD) or null",
      "purchase_time": "string (HH:MM:SS) or null",
      "subtotal": "number or null",
      "tax": "number or null",
      "total": "number",
      "payment_method": "string or null",
      "card_last4": "string or null"
    },
    "items": [
      {
        "raw_text": "string",
        "product_name": "string or null",
        "quantity": "number or null",
        "unit": "string or null",
        "unit_price": "number or null",
        "line_total": "number or null",
        "is_on_sale": "boolean",
        "category": "string or null"
      }
    ],
    "tbd": {
      "items_with_inconsistent_price": [
        {
          "raw_text": "string",
          "product_name": "string or null",
          "reason": "string (e.g., 'quantity × unit_price (X.XX) does not equal line_total (Y.YY)' or 'Unable to match product name with correct price')"
        }
      ],
      "field_conflicts": {
        "field_name": {
          "from_raw_text": "value or null",
          "from_trusted_hints": "value or null",
          "reason": "string"
        }
      },
      "missing_info": [
        "string (description of missing information)"
      ],
      "total_mismatch": {
        "calculated_total": "number (sum of all line_totals)",
        "documented_total": "number (from receipt total)",
        "difference": "number",
        "reason": "string"
      }
    }
  }'::jsonb,
  true
)
ON CONFLICT (merchant_id) WHERE is_active = true
DO UPDATE SET
  prompt_template = EXCLUDED.prompt_template,
  system_message = EXCLUDED.system_message,
  model_name = EXCLUDED.model_name,
  temperature = EXCLUDED.temperature,
  output_schema = EXCLUDED.output_schema,
  updated_at = now();
