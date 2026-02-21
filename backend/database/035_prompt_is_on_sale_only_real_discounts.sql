-- ============================================
-- Migration 035: Clarify is_on_sale = only real discounts
-- ============================================
-- Purpose: "N at $price" (e.g. 5 at 0.23) is normal quantity pricing, NOT a discount.
-- Set is_on_sale = true ONLY for explicit sale/discount (e.g. (SALE) label, was $X now $Y).
-- Run after: 023
-- ============================================

BEGIN;

UPDATE prompt_library
SET content = '## Package Price Discounts (CRITICAL)

When you see patterns like "2/$9.00", "3 for $10", "Buy 2 Get 1", or similar package deals:
1. Extract the ACTUAL line_total from the receipt, NOT calculated quantity × unit_price
2. Do NOT "correct" line_total for package discounts - use actual values from receipt
3. If "2/$9.00" and two items sum to $9.00, this is CORRECT
4. Mark is_on_sale = true ONLY for items that are explicitly on sale (e.g. (SALE) label, or "was $X now $Y"). Do NOT set is_on_sale = true for simple quantity pricing like "5 at $0.23" or "2 lb @ $1.99" — those are normal prices, not discounts.
5. Do NOT add items_with_inconsistent_price for package discounts - expected behavior

Validation: If package pattern exists, verify line_totals sum to stated package price (tolerance ±0.03). If sum matches, extraction is correct even when line_total ≠ quantity × unit_price.'
WHERE key = 'package_price_discount'
  AND category = 'receipt'
  AND content_role = 'system';

COMMIT;
