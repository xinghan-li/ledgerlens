# Deprecated Migrations

## ⚠️ Warning

The migrations in this folder are **deprecated** and should **NOT** be run on fresh production databases.

## 📁 Files in This Folder

### 008_update_current_stage.sql ❌
- **Purpose**: Expanded `receipts.current_stage` from 4 simple values to 8 granular values
- **Why Deprecated**: This added unnecessary complexity that was later reverted
- **Status**: DO NOT RUN on new databases

**What it did:**
- Changed from: `'ocr', 'llm_primary', 'llm_fallback', 'manual'`
- Changed to: `'ocr_google', 'ocr_aws', 'llm_primary', 'llm_fallback', 'sum_check_failed', 'manual_review', 'success', 'failed'`

### 011_simplify_receipts_stage_values.sql 🔄
- **Purpose**: Reverted the changes from 008 back to simple values
- **Why Exists**: Needed to fix databases that already ran 008
- **Status**: Only run if you previously ran 008

**What it does:**
- Migrates existing data from granular values back to simple values
- Changes from: `'ocr_google', 'ocr_aws', ... 'success', 'failed'`
- Changes to: `'ocr', 'llm_primary', 'llm_fallback', 'manual'`

## 🎯 When to Use These

### ✅ Run 011 ONLY IF:
- You have an existing development database
- You previously ran migration 008
- Your database has receipts with values like `'ocr_google'`, `'manual_review'`, `'success'`, etc.
- You need to align with the current codebase

### ❌ DO NOT Run Either If:
- You're setting up a fresh database
- You're deploying to production for the first time
- You never ran 008

## 📝 Technical Details

### Data Migration Map (from 011):

```
Old Value (008)      →  New Value (Current)
─────────────────────────────────────────────
'ocr_google'         →  'ocr'
'ocr_aws'            →  'ocr'
'sum_check_failed'   →  'manual'
'manual_review'      →  'manual'
'failed'             →  'ocr'
'success'            →  'llm_primary'
'llm_primary'        →  'llm_primary' (no change)
'llm_fallback'       →  'llm_fallback' (no change)
'manual'             →  'manual' (no change)
```

## 🔍 How to Check If You Need 011

Run this query in Supabase SQL Editor:

```sql
SELECT 
    current_stage, 
    COUNT(*) as count
FROM receipts
GROUP BY current_stage
ORDER BY count DESC;
```

**If you see:**
- `'ocr_google'`, `'ocr_aws'`, `'sum_check_failed'`, `'manual_review'`, `'success'`, or `'failed'`
- **Then you need to run 011**

**If you only see:**
- `'ocr'`, `'llm_primary'`, `'llm_fallback'`, `'manual'`
- **Then your database is already correct, no action needed**

## 🚀 Migration Path

### Scenario 1: Fresh Database (Recommended)
```
Run: 001 → 003 → 004 → 006 → 007 → 009 → 010
Skip: 008, 011
```

### Scenario 2: Existing Dev Database That Ran 008
```
Previous: 001 → 003 → 004 → 006 → 007 → 008 → 009 → 010
Now Run: 011 (to fix 008)
```

## 📚 History

- **2026-01-31**: Migration 008 created to add granular debugging stages
- **2026-02-09**: Discovered backend code uses simple values, not granular ones
- **2026-02-11**: Created migration 011 to revert to simple values
- **2026-02-11**: Moved 008 and 011 to deprecated/ folder for clarity

## 💡 Lesson Learned

**Always align database constraints with actual code usage before deploying.**

In this case:
1. Migration 008 expanded stage values for "better debugging"
2. Backend code continued using simple values
3. This created a mismatch causing constraint violations
4. Migration 011 fixed the mismatch by reverting to simple values

For future production deployments, we skip both 008 and 011 to avoid this entire detour.
