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

6. **009_tag_based_rag_system.sql** - Tag-based RAG system
   - Creates tables for prompt_tags, prompt_snippets, tag_matching_rules
   - Enables dynamic RAG content management

7. **010_update_costco_lynnwood_address.sql** - Data migration (optional)
   - Updates Costco Lynnwood store address to canonical format
   - ⚠️ Only needed if you have Costco Lynnwood data

8. **012_add_receipt_items_and_summaries.sql** - Receipt data denormalization
   - Creates `receipt_items` table for individual line items
   - Creates `receipt_summaries` table for receipt-level metadata
   - Enables efficient querying, aggregation, and API export

### ❌ Skip These (Development-Only Migrations):

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
-- Run in Supabase SQL Editor:
001_schema_v2.sql
003_add_file_hash.sql
004_update_user_class.sql
006_add_validation_status.sql
007_add_chain_name_to_store_locations.sql
009_tag_based_rag_system.sql
010_update_costco_lynnwood_address.sql (optional)
012_add_receipt_items_and_summaries.sql
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
| 009 | Tag-based RAG | ✅ Production |
| 010 | Costco address | ✅ Production (optional) |
| 011 | Simplify stage values | 🔄 Dev-only fix for 008 |
| 012 | Receipt items & summaries | ✅ Production |

## 🎯 Current Stage Values (Final)

After running production migrations, `receipts.current_stage` supports:
- `'ocr'` - OCR processing stage
- `'llm_primary'` - Primary LLM processing (Gemini/OpenAI)
- `'llm_fallback'` - Fallback LLM processing
- `'manual'` - Manual review needed

## 📁 File Organization

```
backend/database/
├── MIGRATIONS_README.md (this file)
├── 001_schema_v2.sql (✅ production)
├── 003_add_file_hash.sql (✅ production)
├── 004_update_user_class.sql (✅ production)
├── 006_add_validation_status.sql (✅ production)
├── 007_add_chain_name_to_store_locations.sql (✅ production)
├── 009_tag_based_rag_system.sql (✅ production)
├── 010_update_costco_lynnwood_address.sql (✅ production)
├── 012_add_receipt_items_and_summaries.sql (✅ production)
├── deprecated/
│   ├── README.md
│   ├── 008_update_current_stage.sql (❌ dev only)
│   └── 011_simplify_receipts_stage_values.sql (🔄 dev only)
└── 2026-01-31_MIGRATION_NOTES.md (data backfill notes)
```

## 🚨 Important Notes

1. **Migration 008 + 011 = No-op**: Running both is equivalent to not running either. They cancel each other out.
2. **Fresh databases should skip both 008 and 011** to avoid unnecessary complexity.
3. **Existing dev databases with 008 applied must run 011** to fix constraints.
4. **Always backup your database** before running migrations in production.

## 📞 Questions?

If you're unsure which migrations to run, ask yourself:
- **Is this a brand new database?** → Run production list (skip 008, 011)
- **Did I already run 008?** → You must run 011 to fix it
- **Am I starting fresh in production?** → Run production list only

## 🔍 Verification

After running migrations, verify correct schema:

```sql
-- Check receipts constraint
SELECT 
    conname, 
    pg_get_constraintdef(oid) 
FROM pg_constraint 
WHERE conrelid = 'receipts'::regclass 
AND conname = 'receipts_current_stage_check';

-- Expected result:
-- CHECK (current_stage IN ('ocr', 'llm_primary', 'llm_fallback', 'manual'))
```
