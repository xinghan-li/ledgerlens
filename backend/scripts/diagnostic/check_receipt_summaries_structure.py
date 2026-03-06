"""
检查 record_summaries 表的结构
"""
import os
import sys
import io
from dotenv import load_dotenv
from supabase import create_client

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment variables
load_dotenv(dotenv_path=".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

print("\n" + "="*80)
print("🔍 Check record_summaries table structure")
print("="*80)

# 1. Check table exists
print("\n1. Checking if table exists...")
try:
    result = supabase.table('record_summaries').select('id').limit(0).execute()
    print("✓ record_summaries table exists")
except Exception as e:
    print(f"❌ record_summaries table not found or not accessible: {e}")
    sys.exit(0)

# 2. Get table structure (columns)
print("\n2. Table structure (columns)...")
print("   (Run the following query in Supabase SQL Editor:)")
print("""
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'record_summaries'
ORDER BY ordinal_position;
""")

# 3. Get indexes
print("\n3. Indexes (run in Supabase SQL Editor)...")
print("""
SELECT 
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = 'record_summaries'
ORDER BY indexname;
""")

# 4. Get constraints
print("\n4. Constraints (run in Supabase SQL Editor)...")
print("""
SELECT 
    conname as constraint_name,
    contype as constraint_type,
    pg_get_constraintdef(oid) as definition
FROM pg_constraint
WHERE conrelid = 'record_summaries'::regclass
ORDER BY conname;
""")

# 5. Row count
print("\n5. Row count...")
result = supabase.table('record_summaries').select('id', count='exact').limit(0).execute()
print(f"   Total rows: {result.count}")

# 6. Sample rows
print("\n6. Sample data...")
result = supabase.table('record_summaries')\
    .select('id, receipt_id, store_name, store_chain_id, total')\
    .limit(3)\
    .execute()

if result.data:
    for i, row in enumerate(result.data, 1):
        print(f"\n   [{i}] ID: {row['id']}")
        print(f"       Receipt ID: {row['receipt_id']}")
        print(f"       Store Name: {row.get('store_name', 'NULL')}")
        print(f"       Store Chain ID: {row.get('store_chain_id', 'NULL')}")
        print(f"       Total: {row.get('total', 'NULL')}")
else:
    print("   (no data)")

print("\n" + "="*80)
print("✓ Done")
print("="*80)
