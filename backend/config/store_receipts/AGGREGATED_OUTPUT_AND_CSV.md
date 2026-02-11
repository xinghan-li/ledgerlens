# Aggregated receipt output and CSV mapping

## Target JSON shape (for storage / API)

Pipeline output should conform to `aggregated_receipt_schema.json`:

- **chain_id**: From store config (e.g. `island_gourmet_markets`).
- **header**: Store name, location, address, phones, website, transaction date/time, operator, Inv#, Trs#.
- **items**: Array of `{ quantity, unit_price, product_name, line_total, code, promo, is_on_sale }`.
- **discounts_and_fees_in_body**: Optional lines like Package price discount, Markdown, Deposit, Environment fee (when present in body).
- **totals**: `subtotal`, `tax`, `bottle_deposit`, `environment_fee`, `total_sales`.
- **payment**: Payment method, amount, card last four, item count, discount recaps, saving grand total, network/mode/type/tender, amount USD, result, date/time, sequence, author, label, AID.

## CSV export (one row per item)

Existing CSV uses one row per **item** plus receipt-level columns. Mapping from aggregated JSON:

| CSV column   | Source |
|-------------|--------|
| UserID      | (from auth) |
| Date        | `header.transaction_date` |
| Time        | `header.transaction_time` |
| Class1/2/3  | (future: category from item) |
| ItemName    | `items[].product_name` |
| Amount      | `items[].line_total` |
| Currency    | (e.g. USD) |
| OnSale      | `items[].is_on_sale` |
| Payment Type| `payment.payment_method` (normalized) |
| Vendor      | `header.store_name` |
| Address1/2  | From `header.address` |
| City        | From `header.address` |
| State       | From `header.address` |
| Country     | From `header.address` |
| ZipCode     | From `header.address` |

Receipt-level totals and payment details live in the JSON; CSV can add optional columns (e.g. Subtotal, Tax, Total, Invoice#) if needed.
