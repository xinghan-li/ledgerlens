# Database Migrations Order

## 📋 Migration Files (In Order)

### Core Schema (Already Run)
- ✅ `001_schema_v2.sql` - Base schema (users, receipts, store_chains, store_locations, etc.)
- ✅ `004_update_user_class.sql` - Update user_class values
- ✅ `006_add_validation_status.sql` - Add validation_status to receipt_processing_runs
- ✅ `007_add_chain_name_to_store_locations.sql` - Add chain_name column
- ✅ `009_tag_based_rag_system.sql` - Tag-based RAG system
- ✅ `010_update_costco_lynnwood_address.sql` - Update Costco address
- ✅ `011_simplify_receipts_stage_values.sql` - Simplify stage values (deprecated/008 related)
- ✅ `012_add_receipt_items_and_summaries.sql` - Add receipt_items and receipt_summaries

### New Migrations (Need to Run)

#### 🔴 Priority 1: User Management (Run First)
- ⏸️ `013_auto_create_user_on_signup.sql` - Auto-create user on signup

#### 🔴 Priority 2: Product Catalog System (Run in Order)

**Step 1: Foundation Tables (Independent)**
- ⏸️ `014_add_brands_table.sql` - Brands table (independent)
- ⏸️ `015_add_categories_tree.sql` - Categories tree structure (independent)

**Step 2: Products Catalog (Depends on 014 + 015)**
- ⏸️ `016_add_products_catalog.sql` - Products catalog (depends on 014, 015)

**Step 3: Link Receipt Items (Depends on 016)**
- ⏸️ `017_link_receipt_items_to_products.sql` - Add product_id to receipt_items (depends on 016)

**Step 4: Price Snapshots (Depends on 016)**
- ⏸️ `018_add_price_snapshots.sql` - Price snapshots for PricePeek (depends on 016)

---

## 🚀 Execution Order (Must Follow)

### Batch 1: User Auto-Creation
```bash
# In Supabase SQL Editor:
1. Run: 013_auto_create_user_on_signup.sql
```

### Batch 2: Product Catalog Foundation
```bash
# In Supabase SQL Editor (run in order):
2. Run: 014_add_brands_table.sql
3. Run: 015_add_categories_tree.sql
```

### Batch 3: Products and Links
```bash
# In Supabase SQL Editor (run in order):
4. Run: 016_add_products_catalog.sql
5. Run: 017_link_receipt_items_to_products.sql
```

### Batch 4: PricePeek Foundation
```bash
# In Supabase SQL Editor:
6. Run: 018_add_price_snapshots.sql
```

---

## 📊 Table Dependencies Diagram

```
auth.users (Supabase)
    ↓
users (013) ────────────────────┐
    ↓                           ↓
receipts                   receipt_summaries (012)
    ↓                           ↓
receipt_processing_runs    receipt_items (012)
                                ↓
brands (014) ──┐                │
               ↓                │
categories (015) ─→ products (016)
                        ↓        ↓
                        │   receipt_items.product_id (017)
                        ↓        ↓
                   price_snapshots (018)
```

---

## ⚠️ Important Notes

### Before Running Migrations

1. **Backup your database** (Supabase Dashboard → Database → Backups)
2. **Test in development first** (if you have a dev environment)
3. **Review each migration** to understand what it does

### After Running Migrations

1. **Verify tables were created:**
```sql
SELECT tablename 
FROM pg_tables 
WHERE schemaname = 'public' 
  AND tablename IN ('brands', 'categories', 'products', 'price_snapshots')
ORDER BY tablename;
```

2. **Check indexes:**
```sql
SELECT indexname, tablename 
FROM pg_indexes 
WHERE schemaname = 'public' 
  AND tablename IN ('brands', 'categories', 'products', 'receipt_items', 'price_snapshots')
ORDER BY tablename, indexname;
```

3. **Verify triggers:**
```sql
SELECT trigger_name, event_object_table 
FROM information_schema.triggers 
WHERE trigger_schema = 'public'
  AND trigger_name IN ('on_auth_user_created', 'brands_updated_at', 'categories_updated_at', 'products_updated_at')
ORDER BY event_object_table, trigger_name;
```

---

## 🔄 Post-Migration Tasks

### After Migration 017 (Link Products)

You'll need to implement backend logic to:

1. **Product Normalization Service**
   - Extract normalized_name from product_name
   - Match or create products
   - Link receipt_items to products

2. **Backfill Existing Data**
   ```python
   # Pseudo-code
   for item in receipt_items:
       product = normalize_and_find_product(
           product_name=item.product_name,
           brand=item.brand,
           category_l1=item.category_l1
       )
       if not product:
           product = create_product(...)
       
       item.product_id = product.id
       item.category_id = find_category(item.category_l1, l2, l3)
       item.save()
   ```

3. **Update Workflow Processor**
   - Modify `workflow_processor.py` to create/link products
   - Modify LLM prompts to extract normalized product info

### After Migration 018 (Price Snapshots)

1. **Initial Backfill**
   ```sql
   SELECT * FROM backfill_all_price_snapshots();
   ```

2. **Set up Daily Cron Job**
   ```sql
   -- Run daily at midnight
   SELECT aggregate_prices_for_date(CURRENT_DATE);
   ```

3. **Create PricePeek API Endpoints**
   - Get latest prices for a product
   - Compare prices across stores
   - Price trend charts

---

## 📚 Related Documentation

- **Schema Overview**: `001_schema_v2.sql`
- **Receipt Items**: `012_add_receipt_items_and_summaries.sql`
- **Refactoring Summary**: `REFACTORING_SUMMARY.md`
- **Migration Notes**: `2026-01-31_MIGRATION_NOTES.md`

---

## 🆘 Troubleshooting

### If Migration Fails

1. **Check error message** in SQL Editor output
2. **Common issues:**
   - Missing prerequisite migrations
   - Data constraint violations
   - Permissions issues

3. **Rollback:**
   ```sql
   -- Each migration is wrapped in BEGIN/COMMIT
   -- If it fails, changes are automatically rolled back
   ```

4. **Manual cleanup** (if needed):
   ```sql
   DROP TABLE IF EXISTS price_snapshots CASCADE;
   DROP TABLE IF EXISTS products CASCADE;
   DROP TABLE IF EXISTS categories CASCADE;
   DROP TABLE IF EXISTS brands CASCADE;
   DROP MATERIALIZED VIEW IF EXISTS latest_prices;
   ```

### Need Help?

Check the comments in each migration file for:
- Example queries
- Verification steps
- Common issues
