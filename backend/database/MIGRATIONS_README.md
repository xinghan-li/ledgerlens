# Database Migrations Guide

## 📋 Overview

This directory contains SQL migration files for the LedgerLens database schema. Migrations are numbered sequentially and should be applied in order.

## 🚀 For Production (Fresh Database)

If you're setting up a **brand new production database**, run these migrations in order:

### Required Migrations (in order):

1. **001_schema_v2.sql** - Core database schema
   - Creates all base tables: users, receipts, receipt_processing_runs, store_chains, store_locations, etc.
   - ✅ Already uses correct `current_stage` values: `'ocr', 'llm_primary', 'llm_fallback', 'manual'`

2. **003_add_file_hash.sql** - Add file hash for duplicate detection
   - Adds `file_hash` column to receipts table
   - Creates indexes for duplicate detection

3. **004_update_user_class.sql** - Update user_class constraint
   - Ensures user_class supports: `'super_admin', 'admin', 'premium', 'free'`
   - ⚠️ NOTE: This is technically redundant (001 already has correct constraint), but safe to run

4. **006_add_validation_status.sql** - Add validation_status to receipt_processing_runs
   - Adds `validation_status` column for tracking validation results

5. **007_add_chain_name_to_store_locations.sql** - Add chain_name column
   - Adds `chain_name` to store_locations for human-readable reference
   - Creates trigger to auto-sync with store_chains.name

6. **010_update_costco_lynnwood_address.sql** - Data migration (optional)
   - Updates Costco Lynnwood store address to canonical format
   - ⚠️ Only needed if you have Costco Lynnwood data

7. **012_add_record_items_and_summaries.sql** - Receipt data denormalization
   - Creates `record_items` table for individual line items
   - Creates `record_summaries` table for receipt-level metadata
   - Enables efficient querying, aggregation, and API export

8. **013_auto_create_user_on_signup.sql** - Auto-create user on signup
   - Creates trigger to auto-create public.users when auth.users is created
   - Backfills existing auth users

9. **015_add_categories_tree.sql** - Categories tree structure
    - Creates hierarchical categories table
    - Seeds initial categories (Grocery, Household, etc.)
    - Independent table, can run anytime

10. **016_add_products_catalog.sql** - Products catalog
    - Creates unified product catalog for cross-receipt aggregation
    - **Depends on**: 015 (categories)

11. **017_link_record_items_to_products.sql** - Link receipt items to products
    - Adds `product_id` and `category_id` foreign keys to record_items
    - **Depends on**: 016 (products catalog)

12. **018_add_price_snapshots.sql** - Price snapshots for PricePeek
    - Creates price_snapshots table for price aggregation
    - Creates materialized views and aggregation functions
    - **Depends on**: 016 (products catalog)

14. **019_add_categorization_rules.sql** - Product categorization rules

15. **020_drop_brands_table.sql** - Drop brands table (MVP simplification)
    - Removes brands table and products.brand_id
    - **Depends on**: 014+016 (if brands existed) or 016 alone

15. **021_simplify_categories.sql** - Simplify categories table
    - Drops display_order, icon, color, product_count; renames normalized_name→name
    - **Depends on**: 015 (categories)

16. **022_simplify_products.sql** - Simplify products table
    - Drops brand_id, variant_type, is_organic, aliases, search_keywords, description, image_url, barcode
    - **Depends on**: 016 (products)

17. **023_prompt_library_and_binding.sql** - Prompt library system
    - Creates prompt_library (content) and prompt_binding (routing by scope)
    - Replaces legacy tag-based RAG (prompt_tags, prompt_snippets, tag_matching_rules)

18. **023_seed_prompt_library.sql** - Seed prompt data (run after 023)
    - Inserts receipt_parse_base, package_price_discount, deposit_and_fee, membership_card, user_template, schema
    - Binds all to prompt_key='receipt_parse', scope='default'

19. **024_simplify_record_items.sql** - Simplify record_items (MVP)
    - Drops brand, category_l1/2/3, ocr_coordinates, ocr_confidence
    - All quantities/prices as BIGINT (quantity x100, prices in cents)
    - Drops record_items_enriched view
    - Updates aggregate_prices_for_date for new schema

### ❌ Skip These (Deprecated Migrations):

- **~~014_add_brands_table.sql~~** - DEPRECATED 2026-02-12, moved to deprecated/
  - Brands table removed per MVP simplification (run 020 to drop from existing DBs)

- **~~008_update_current_stage.sql~~** - DO NOT RUN on fresh database
  - This was a development migration that expanded stage values
  - Creates complexity that was later reverted
  
- **~~011_simplify_receipts_stage_values.sql~~** - DO NOT RUN on fresh database
  - This reverts the changes from 008
  - Only needed for existing development databases

## 🔧 For Existing Development Database

If you already have a database with data and ran 008:

1. Run all migrations 001-010 in order
2. **Must run 011** to fix the stage values from 008

## 📝 Migration Execution Order Summary

### ✅ Production (Fresh Database):
```sql
-- Run in Supabase SQL Editor (in order):
001_schema_v2.sql
003_add_file_hash.sql
004_update_user_class.sql
006_add_validation_status.sql
007_add_chain_name_to_store_locations.sql
010_update_costco_lynnwood_address.sql (optional)
012_add_record_items_and_summaries.sql
013_auto_create_user_on_signup.sql
015_add_categories_tree.sql
016_add_products_catalog.sql
017_link_record_items_to_products.sql
018_add_price_snapshots.sql
019_add_categorization_rules.sql
020_drop_brands_table.sql
021_simplify_categories.sql
022_simplify_products.sql
023_prompt_library_and_binding.sql
023_seed_prompt_library.sql
024_simplify_record_items.sql
```

### 📊 Execution Order (with Dependencies):

**Batch 1 - Foundation (Independent):**
```
001 → 003 → 004 → 006 → 007 → 010 → 012 → 013
```

**Batch 2 - Product System (Has Dependencies):**
```
015 (categories) → 016 (products) → 017 (link items)
                                   → 018 (price snapshots)
                                   → 019 (categorization rules)
                                   → 020 (drop brands)
                                   → 021 (simplify categories)
                                   → 022 (simplify products)
                                   → 023 (prompt library/binding)
```

### 🔄 Development (Existing Database):
```sql
-- If you already ran 008, you must run:
011_simplify_receipts_stage_values.sql
```

## 📊 Schema Version Tracking

| Migration | Description | Status |
|-----------|-------------|--------|
| 001 | Core schema v2 | ✅ Production |
| 003 | File hash | ✅ Production |
| 004 | User class | ✅ Production (redundant but safe) |
| 006 | Validation status | ✅ Production |
| 007 | Chain name | ✅ Production |
| 008 | Expand stage values | ❌ Deprecated (dev only) |
| 009 | Tag-based RAG | ❌ Removed (replaced by 023) |
| 010 | Costco address | ✅ Production (optional) |
| 011 | Simplify stage values | 🔄 Dev-only fix for 008 |
| 012 | Receipt items & summaries | ✅ Production |
| 013 | Auto-create user on signup | ✅ Production |
| 014 | Brands table | ❌ Deprecated (run 020 to drop) |
| 015 | Categories tree | ✅ Production |
| 016 | Products catalog | ✅ Production |
| 017 | Link receipt items to products | ✅ Production |
| 018 | Price snapshots | ✅ Production |
| 019 | Categorization rules | ✅ Production |
| 020 | Drop brands table | ✅ Production |
| 021 | Simplify categories | ✅ Production |
| 022 | Simplify products | ✅ Production |
| 023 | Prompt library + binding | ✅ Production |
| 024 | Simplify record_items | ✅ Production |

## 🎯 Current Stage Values (Final)

After running production migrations, `receipt_status.current_stage` supports:
- `'ocr'` - OCR processing stage
- `'llm_primary'` - Primary LLM processing (Gemini/OpenAI)
- `'llm_fallback'` - Fallback LLM processing
- `'manual'` - Manual review needed

## 📁 File Organization

```
backend/database/
├── MIGRATIONS_README.md (this file - migration guide)
├── CHECK_TABLES.sql (diagnostic tool)
│
├── 📁 Migration Files (001-023)
│   ├── 001_schema_v2.sql → 023_prompt_library_and_binding.sql
│
├── 📁 deprecated/
│   ├── README.md
│   ├── 008_update_current_stage.sql
│   ├── 011_simplify_receipts_stage_values.sql
│   └── 014_add_brands_table.sql
│
└── 📁 documents/ (all documentation files)
    ├── REFACTORING_SUMMARY.md (重构记录)
    ├── CHECK_USER_CREATION.md (013 说明)
    ├── PRODUCT_CATALOG_DESIGN.md (014-018 设计)
    ├── FILE_CLEANUP_ANALYSIS.md (文件清理分析)
    ├── 2026-01-30 MIGRATION_NOTES.md (历史记录)
    └── 2026-01-31_MIGRATION_NOTES.md (详细笔记)
```

### 📝 Documentation Guidelines

**All future documentation files should be placed in `documents/` folder:**
- Design documents
- Migration notes
- Troubleshooting guides
- Historical records
- Analysis reports

**Only keep in root database/ folder:**
- `MIGRATIONS_README.md` (this file)
- Migration SQL files (001-023)
- Diagnostic SQL tools (CHECK_*.sql)

## 🔄 Post-Migration Tasks

### After Migration 017 (Link Products)

实现产品标准化服务：

1. **Product Normalization Service**
   - Extract normalized_name from product_name
   - Match or create products
   - Link record_items to products

2. **Backfill Existing Data**
   ```python
   # Update workflow_processor.py to:
   for item in record_items:
       product = normalize_and_find_product(
           product_name=item.product_name,
           brand=item.brand,
           category_l1=item.category_l1
       )
       if not product:
           product = create_product(...)
       
       item.product_id = product.id
       item.category_id = find_category(...)
       item.save()
   ```

### After Migration 018 (Price Snapshots)

1. **Initial Backfill**
   ```sql
   SELECT * FROM backfill_all_price_snapshots();
   ```

2. **Set up Daily Cron Job**
   ```sql
   SELECT aggregate_prices_for_date(CURRENT_DATE);
   ```

### After Migration 019 (Categorization Rules)

1. **Import Initial Rules**
   ```bash
   cd backend
   python import_category_rules.py
   ```

2. **Review & Correct Rules**
   - System generates `output/standardization_preview/standardization_summary_*.csv`
   - Manually correct categories
   - Re-import corrected CSV

## 🚨 Important Notes

1. **Migration 008 + 011 = No-op**: Running both is equivalent to not running either. They cancel each other out.
2. **Fresh databases should skip both 008 and 011** to avoid unnecessary complexity.
3. **Existing dev databases with 008 applied must run 011** to fix constraints.
4. **Always backup your database** before running migrations in production.

## 📞 Questions?

If you're unsure which migrations to run, ask yourself:
- **Is this a brand new database?** → Run production list (001-019, skip 008/011)
- **Did I already run 008?** → You must run 011 to fix it
- **Am I starting fresh in production?** → Run production list only

## 🔍 Verification

After running migrations, verify correct schema:

```sql
-- Check receipt_status constraint
SELECT 
    conname, 
    pg_get_constraintdef(oid) 
FROM pg_constraint 
WHERE conrelid = 'receipt_status'::regclass 
AND conname LIKE '%current_stage%';

-- Expected result:
-- CHECK (current_stage IN ('ocr', 'llm_primary', 'llm_fallback', 'manual'))

-- Verify all tables were created
SELECT tablename 
FROM pg_tables 
WHERE schemaname = 'public' 
  AND tablename IN (
    'users', 'receipt_status', 'receipt_processing_runs', 
    'record_items', 'record_summaries',
    'brands', 'categories', 'products', 
    'product_categorization_rules', 'price_snapshots'
  )
ORDER BY tablename;

-- Check indexes
SELECT indexname, tablename 
FROM pg_indexes 
WHERE schemaname = 'public' 
ORDER BY tablename, indexname;

-- Verify triggers
SELECT trigger_name, event_object_table 
FROM information_schema.triggers 
WHERE trigger_schema = 'public'
ORDER BY event_object_table, trigger_name;
```

## 🆘 Troubleshooting

### If Migration Fails

1. **Check error message** in SQL Editor output
2. **Common issues:**
   - Missing prerequisite migrations (check dependencies)
   - Data constraint violations
   - Permissions issues

3. **Rollback:**
   - Each migration is wrapped in `BEGIN/COMMIT`
   - If it fails, changes are automatically rolled back

4. **Manual cleanup** (if needed):
   ```sql
   DROP TABLE IF EXISTS price_snapshots CASCADE;
   DROP TABLE IF EXISTS product_categorization_rules CASCADE;
   DROP TABLE IF EXISTS products CASCADE;
   DROP TABLE IF EXISTS categories CASCADE;
   DROP TABLE IF EXISTS brands CASCADE;
   DROP MATERIALIZED VIEW IF EXISTS latest_prices;
   ```

## 📚 Related Documentation

All documentation files are stored in the `documents/` folder:

- **REFACTORING_SUMMARY.md** - Migration refactoring history (2026-02-11)
- **PRODUCT_CATALOG_DESIGN.md** - Product system design (migrations 014-018)
- **CHECK_USER_CREATION.md** - Migration 013 details (auto-create users)
- **2026-01-31_MIGRATION_NOTES.md** - Detailed data backfill procedures
- **2026-01-30 MIGRATION_NOTES.md** - Historical migration notes
- **FILE_CLEANUP_ANALYSIS.md** - File management decisions

### 📝 Documentation Policy

**All future documentation files must be placed in `documents/` folder:**
- Migration design documents
- Historical notes and records
- Analysis and decision-making documentation
- Troubleshooting guides
- Developer references

**Do NOT create new documentation files in the root `database/` folder.**
