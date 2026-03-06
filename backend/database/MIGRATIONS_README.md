# Database Migrations Guide

> **Last updated**: 2026-03-05  
> **Reflects**: analysis.md consolidation — 53 original migrations compressed to 19 active files.

---

## 🚀 Fresh Production Database — Run These 19 Files In Order

```
001_schema_v2.sql
010_update_costco_lynnwood_address.sql   ← optional (Costco Lynnwood address data)
012_add_receipt_items_and_summaries.sql
013_auto_create_user_on_signup.sql
015_add_categories_tree.sql
016_add_products_catalog.sql
017_link_receipt_items_to_products.sql
018_add_price_snapshots.sql
019_add_categorization_rules.sql
023_prompt_library_and_binding.sql
023_seed_prompt_library.sql
025_add_classification_review.sql
030_increment_product_usage_rpc.sql
034_fix_milk_and_soup_dumplings_rules.sql
043_non_receipt_rejects.sql
044_rls_policies.sql
045_receipt_workflow_steps.sql
046_user_strikes_and_lock.sql
051_category_source_and_user_categories.sql
```

That's it. Do **not** run anything in `deprecated/`.

---

## 📋 Migration Details

### 001 — Core schema (merged: 003, 006, 007, 032, 040, 048, 049, 050)

Creates all foundation tables with **final** column sets and constraints. No ALTER needed later.

| Table | Key points |
|-------|-----------|
| `store_chains` | normalized_name unique index, aliases GIN |
| `store_locations` | chain_name (auto-synced via trigger), phone |
| `users` | user_class check (super_admin/admin/premium/free), status check |
| `receipt_status` | file_hash + duplicate index; pipeline_version; **final** current_stage enum |
| `receipt_processing_runs` | validation_status; **final** stage enum |
| `api_calls` | OCR/LLM call tracking |
| `store_candidates` | phone column |

**Final `current_stage` values** (no ALTER ever needed):
```
ocr | llm_primary | llm_fallback | manual |
rejected_not_receipt | pending_receipt_confirm |
vision_primary | vision_escalation
```

**Final `stage` values for receipt_processing_runs**:
```
ocr | llm | manual | rule_based_cleaning |
vision_primary | vision_escalation | shadow_legacy
```

---

### 010 — Data: Costco Lynnwood address *(optional)*

One-time UPDATE to `store_locations`. Safe to skip on a fresh database with no seed data.

---

### 012 — record_summaries + record_items (merged: 024, 031, 051-col, 052, 053)

Creates both tables in **final form**. No ALTER needed later.

**record_summaries** (final):
- Totals as `INTEGER` (cents) — subtotal, tax, fees, total
- `information JSONB` for cashier/membership/phone/time extras
- No `uploaded_at` (redundant with receipt_status)

**record_items** (final):
- No brand, category_l1/2/3, ocr_coordinates, ocr_confidence columns
- `quantity BIGINT` (×100), `unit_price/line_total/original_price/discount_amount BIGINT` (cents)
- `category_source TEXT` (rule_exact | rule_fuzzy | llm | user_override | crowd_assigned)
- `user_marked_idk BOOLEAN` — user said "I don't know" on Unclassified page
- `user_feedback JSONB` — dismissal feedback `{dismissed, reason, comment, dismissed_at}`

> ⚠️ `product_id` and `category_id` FKs are added in **017** (after 015/016 exist).

---

### 013 — User auth + registration (merged: 042, 047)

- `handle_new_user()` trigger: auto-creates `users` row on `auth.users` INSERT
- `firebase_uid TEXT UNIQUE` — Firebase Auth support
- Drops `users_id_fkey` (users.id no longer FK to auth.users, enabling Firebase-only users)
- `registration_no` sequence (1, 2, 3 … 999999999), backfilled for existing users
- `user_name` unique index

---

### 015 — Categories tree (merged: 021, 028)

Final structure — no display_order, icon, color, product_count. Single `name` column (lowercase).

Seed includes L1 (grocery, household, personal care, pet supplies, health, other), L2, and L3 subcategories. All names and paths lowercase.

---

### 016 — Products catalog (merged: 020, 022, 027, 029)

Final structure — no brand_id, no variant_type/is_organic/aliases etc.

| Column | Type | Notes |
|--------|------|-------|
| normalized_name | TEXT | lowercase, singular |
| size_quantity | NUMERIC(12,2) | e.g. 3.50 |
| size_unit | TEXT | oz, ml, lb, ct… |
| package_type | TEXT | bottle, box, bag… |
| store_chain_id | UUID FK | NULL = global |
| category_id | UUID FK | from categories |
| usage_count | INT | incremented via RPC |

Unique index: `(normalized_name, size_quantity, size_unit, package_type, COALESCE(store_chain_id, sentinel_uuid))`

---

### 017 — record_items FKs + enriched view

- ADD `product_id UUID FK` to record_items
- ADD `category_id UUID FK` to record_items
- CREATE `record_items_enriched` view (final form, built once — no DROP/CREATE cycle)

> This is the only file that creates the enriched view. All previous DROP+CREATE cycles (020/021/022/027/029) are deprecated.

---

### 018 — Price snapshots (PricePeek)

- `price_snapshots` table (product × store_location × date)
- `latest_prices` materialized view
- `aggregate_prices_for_date(DATE)` function — uses cents-based unit_price (final form from 024, already merged into 012)
- `backfill_all_price_snapshots()` helper

---

### 019 — Product categorization rules

- `product_categorization_rules` table
- `update_rule_match_stats()` RPC

> `find_categorization_rule()` is **not created** — matching logic is Python backend-only. (Old DB function was dropped in migration 037, which is now deprecated.)

---

### 023 — Prompt library + binding tables

Creates `prompt_library` and `prompt_binding` tables. Replaces old tag-based RAG system (prompt_tags, prompt_snippets, tag_matching_rules — all dropped).

---

### 023_seed — All prompt seed data (merged: 026, 035, 041)

Inserts the final versions of all prompts in one shot:

| Key | Purpose |
|-----|---------|
| receipt_parse_base | Main system prompt |
| package_price_discount | Package deal rules **(final text — is_on_sale only for explicit sale)** |
| deposit_and_fee | Bottle deposit / env fee handling |
| membership_card | Membership number extraction |
| receipt_parse_user_template | User message template |
| receipt_parse_schema | Output JSON schema |
| classification | LLM pre-fill for classification_review |
| receipt_parse_debug_ocr | Debug step 1: re-parse with OCR |
| receipt_parse_debug_vision | Debug step 2: re-parse with image |

---

### 025 — Classification review (merged: 027-col)

Admin review queue for unclassified items. Final column structure:
- `size_quantity NUMERIC(12,2)`, `size_unit TEXT`, `package_type TEXT` (no old `size`/`unit_type`)

---

### 030 — RPC functions (merged: 038, 039)

- `increment_product_usage(product_id, category_id, last_seen_date)` — atomic usage_count bump
- `backfill_record_items_batch(jsonb)` — batch update product_name_clean / on_sale / product_id
- `sync_record_items_batch_update(jsonb)` — batch update all editable fields (for user corrections)

---

### 034 — Data: categorization rule fixes

- milk rule: changed to `contains` match so long names like "milk lactose free hg lf" match
- soup dumplings pork and ginger: added exact rule for prefix-match support

---

### 043 — Non-receipt rejects

`non_receipt_rejects` table — stores uploads that failed receipt validation for debug/tuning.

---

### 044 — RLS policies

- `is_admin()` helper function
- Row-Level Security on all tables:
  - Users see only their own data
  - super_admin / admin can read all rows
  - Global tables (categories, products, store_chains, store_locations, prompt_*) readable by all authenticated users, writable by admin only

---

### 045 — Receipt workflow steps

`receipt_workflow_steps` table — ordered log of every flowchart step per receipt (for "View workflow" debug UI).

> current_stage constraint changes are already in **001**. This file only creates the table.

---

### 046 — User strikes and lock

- `user_strikes` — one row per strike (user confirmed receipt but it wasn't one)
- `user_lock` — 12h upload lock after 3 strikes in 1h

---

### 051 — User categories + overrides

- `user_categories` — per-user custom category tree (e.g. "Weekend Treats", "Kids")
- `user_item_category_overrides` — per-user override per record_item

> `record_items.category_source` is already in **012**. This file only creates the two new tables.

---

## 📁 File Structure

```
backend/database/
├── MIGRATIONS_README.md          ← this file
├── DB_DEFINITIONS.md             ← full schema reference
│
├── Active Migrations (run these in order):
│   ├── 001_schema_v2.sql
│   ├── 010_update_costco_lynnwood_address.sql
│   ├── 012_add_receipt_items_and_summaries.sql
│   ├── 013_auto_create_user_on_signup.sql
│   ├── 015_add_categories_tree.sql
│   ├── 016_add_products_catalog.sql
│   ├── 017_link_receipt_items_to_products.sql
│   ├── 018_add_price_snapshots.sql
│   ├── 019_add_categorization_rules.sql
│   ├── 023_prompt_library_and_binding.sql
│   ├── 023_seed_prompt_library.sql
│   ├── 025_add_classification_review.sql
│   ├── 030_increment_product_usage_rpc.sql
│   ├── 034_fix_milk_and_soup_dumplings_rules.sql
│   ├── 043_non_receipt_rejects.sql
│   ├── 044_rls_policies.sql
│   ├── 045_receipt_workflow_steps.sql
│   ├── 046_user_strikes_and_lock.sql
│   └── 051_category_source_and_user_categories.sql
│
├── scripts/                      ← one-time scripts and diagnostic queries
│   ├── CHECK_TABLES.sql
│   ├── CHECK_RECEIPT_SUMMARIES.sql
│   ├── wipe_receipts_by_filter.sql
│   ├── wipe_all_receipt_records.sql
│   ├── query_receipts_by_date.sql
│   ├── one_time_link_firebase_to_existing_user.sql
│   ├── scan_after_store_chain_merge.sql
│   └── backfill_classification_review_store_chain_trader_joes.sql
│
├── deprecated/                   ← DO NOT RUN on fresh databases
│   ├── 003  → merged into 001
│   ├── 004  → merged into 001 (was already a no-op)
│   ├── 006  → merged into 001
│   ├── 007  → merged into 001
│   ├── 008  → dev-only (stage values experiment, reverted by 011)
│   ├── 011  → dev-only (reverts 008)
│   ├── 014  → brands table, never needed
│   ├── 020  → brands drop; products in 016
│   ├── 021  → categories simplify; in 015
│   ├── 022  → products simplify; in 016
│   ├── 024  → record_items simplify; in 012
│   ├── 026  → classification prompt; in 023_seed
│   ├── 027  → size columns; in 016 + 025
│   ├── 028  → categories lowercase; in 015
│   ├── 029  → products store_chain_id; in 016
│   ├── 031  → record_summaries int totals; in 012
│   ├── 032  → phone columns; in 001
│   ├── 033  → find_categorization_rule rewrite; function not created on fresh db
│   ├── 035  → prompt text update; in 023_seed (final text)
│   ├── 037  → drop find_categorization_rule; function not created on fresh db
│   ├── 038  → backfill RPC; in 030
│   ├── 039  → sync RPC; in 030
│   ├── 040  → stage check; in 001
│   ├── 041  → debug prompts; in 023_seed
│   ├── 042  → firebase_uid; in 013
│   ├── 047  → registration_no; in 013
│   ├── 048  → pipeline_version; in 001
│   ├── 049  → stage check (vision); in 001
│   ├── 050  → current_stage check (vision); in 001
│   ├── 052  → user_marked_idk; in 012
│   └── 053  → user_feedback; in 012
│
└── documents/                    ← permanent design docs and historical notes
    └── ...
```

---

## 📊 Migration Status Table

| # | File | Merged From | Status |
|---|------|-------------|--------|
| 001 | schema_v2 | +003,006,007,032,040,048,049,050 | ✅ Active |
| 010 | costco address | — | ✅ Active (optional data) |
| 012 | record_summaries + items | +024,031,051-col,052,053 | ✅ Active |
| 013 | user auth | +042,047 | ✅ Active |
| 015 | categories | +021,028 | ✅ Active |
| 016 | products | +020,022,027,029 | ✅ Active |
| 017 | record_items FKs + view | — (final view, once) | ✅ Active |
| 018 | price snapshots | — (function updated) | ✅ Active |
| 019 | categorization rules | — (no find_cat_rule) | ✅ Active |
| 023 | prompt tables | — | ✅ Active |
| 023_seed | prompt seed | +026,035,041 | ✅ Active |
| 025 | classification_review | +027-col | ✅ Active |
| 030 | RPCs | +038,039 | ✅ Active |
| 034 | rule data fixes | — | ✅ Active |
| 043 | non_receipt_rejects | — | ✅ Active |
| 044 | RLS policies | — | ✅ Active |
| 045 | workflow steps | — (stage already in 001) | ✅ Active |
| 046 | user strikes/lock | — | ✅ Active |
| 051 | user categories | — (category_source in 012) | ✅ Active |
| 003–007, 020–029, 031–033, 035, 037–042, 047–050, 052–053 | — | merged → see above | ❌ Deprecated |
| 008, 011 | — | dev-only stage experiment | ❌ Deprecated |
| 014 | brands table | never needed | ❌ Deprecated |

---

## 🔍 Verification Queries

After running all 19 migrations, verify:

```sql
-- 1. All expected tables exist
SELECT tablename
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
-- Expected: api_calls, categories, classification_review, non_receipt_rejects,
--           price_snapshots, product_categorization_rules, products,
--           prompt_binding, prompt_library, receipt_processing_runs,
--           receipt_status, receipt_workflow_steps, record_items,
--           record_summaries, store_candidates, store_chains, store_locations,
--           user_categories, user_item_category_overrides, user_lock, user_strikes, users

-- 2. receipt_status current_stage constraint (final values)
SELECT pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'receipt_status'::regclass
  AND conname LIKE '%current_stage%';
-- Expected: CHECK (current_stage IN ('ocr','llm_primary','llm_fallback','manual',
--           'rejected_not_receipt','pending_receipt_confirm','vision_primary','vision_escalation'))

-- 3. receipt_processing_runs stage constraint (final values)
SELECT pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'receipt_processing_runs'::regclass
  AND conname LIKE '%stage%';
-- Expected: CHECK (stage IN ('ocr','llm','manual','rule_based_cleaning',
--           'vision_primary','vision_escalation','shadow_legacy'))

-- 4. record_items has BIGINT prices (cents)
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'record_items'
  AND column_name IN ('quantity','unit_price','line_total');
-- Expected: all bigint

-- 5. record_summaries has INTEGER totals (cents)
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'record_summaries'
  AND column_name IN ('subtotal','tax','fees','total');
-- Expected: all integer

-- 6. Prompt seed loaded
SELECT key, content_role FROM prompt_library ORDER BY key;
-- Expected 9 rows: classification, deposit_and_fee, membership_card,
--   package_price_discount, receipt_parse_base, receipt_parse_debug_ocr,
--   receipt_parse_debug_vision, receipt_parse_schema, receipt_parse_user_template

-- 7. RLS enabled on user tables
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
-- rowsecurity = true for: users, receipt_status, record_summaries, record_items, etc.
```

---

## 🚨 Important Notes

1. **All columns, constraints, and stage values are at their final form in the earliest possible migration** — no ALTER TABLE steps needed after a fresh install.
2. **Never run files in `deprecated/`** on a fresh database.
3. **`010` is optional** — only needed if you want the Costco Lynnwood address pre-populated.
4. **`034` is data-only** — safe to skip if you have no receipt data yet and will seed rules manually later.
5. Always run in Supabase SQL Editor or `psql` **one file at a time** — each file is wrapped in `BEGIN/COMMIT`.

---

## 🆘 Troubleshooting

### Migration fails mid-way
Each file uses `BEGIN/COMMIT`, so a failure rolls back automatically. Fix the issue and re-run the same file.

### "relation does not exist"
Check that prerequisite files have been run. Dependency order:
- 015 before 016 before 017
- 012 before 017, 025, 030, 051
- 001 before everything

### Manual cleanup (start over)
```sql
DROP TABLE IF EXISTS
  user_item_category_overrides, user_categories, user_strikes, user_lock,
  receipt_workflow_steps, non_receipt_rejects,
  classification_review, product_categorization_rules,
  record_items, record_summaries,
  price_snapshots, products, categories,
  prompt_binding, prompt_library,
  store_candidates, api_calls,
  receipt_processing_runs, receipt_status,
  users, store_locations, store_chains
CASCADE;

DROP MATERIALIZED VIEW IF EXISTS latest_prices;
DROP VIEW IF EXISTS record_items_enriched;
DROP FUNCTION IF EXISTS update_updated_at, handle_new_user, update_store_location_chain_name,
  increment_product_usage, backfill_record_items_batch, sync_record_items_batch_update,
  aggregate_prices_for_date, backfill_all_price_snapshots, is_admin, update_rule_match_stats;
DROP SEQUENCE IF EXISTS users_registration_no_seq;
```
