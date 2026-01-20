-- Add extraction_rules field to merchant_prompts table
-- This allows merchant-specific price extraction rules to be stored in the database

alter table merchant_prompts
add column if not exists extraction_rules jsonb;

-- Add comment
comment on column merchant_prompts.extraction_rules is 
'Merchant-specific extraction rules for price parsing. JSON structure:
{
  "price_patterns": [
    {
      "pattern": "regex pattern",
      "priority": 1,
      "description": "description"
    }
  ],
  "skip_patterns": ["regex1", "regex2"],
  "special_rules": {
    "use_global_fp_match": true,
    "min_fp_count": 3,
    "category_identifiers": ["GROCERY", "PRODUCE", "DELI"]
  }
}';

-- Example: T&T Supermarket extraction rules
-- This can be inserted/updated via SQL or admin interface
/*
UPDATE merchant_prompts
SET extraction_rules = '{
  "price_patterns": [
    {
      "pattern": "FP\\s+\\$(\\d+\\.\\d{2})",
      "priority": 1,
      "description": "T&T specific FP price format",
      "flags": "IGNORECASE"
    },
    {
      "pattern": "\\$(\\d+\\.\\d{2})",
      "priority": 2,
      "description": "Generic dollar price format"
    }
  ],
  "skip_patterns": [
    "^TOTAL",
    "^Subtotal",
    "^Tax",
    "^Points",
    "^Reference",
    "^Trans:",
    "^Terminal:",
    "^CLERK",
    "^INVOICE:",
    "^REFERENCE:",
    "^AMOUNT",
    "^APPROVED",
    "^AUTH CODE",
    "^APPLICATION",
    "^Visa",
    "^VISA",
    "^Mastercard",
    "^Credit Card",
    "^CREDIT CARD",
    "^Customer Copy",
    "^STORE:",
    "^Ph:",
    "^www\\.",
    "^\\d{2}/\\d{2}/\\d{2}",
    "^\\*{3,}",
    "^Not A Member",
    "^立即下載",
    "^Get Exclusive",
    "^Enjoy Online",
    "^GROCERY$",
    "^PRODUCE$",
    "^DELI$",
    "^FOOD$"
  ],
  "special_rules": {
    "use_global_fp_match": true,
    "min_fp_count": 3,
    "category_identifiers": ["GROCERY", "PRODUCE", "DELI", "FOOD"]
  }
}'::jsonb
WHERE merchant_name ILIKE '%T&T%' AND is_active = true;
*/
