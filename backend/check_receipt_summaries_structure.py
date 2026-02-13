"""
检查 receipt_summaries 表的结构
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
print("🔍 检查 receipt_summaries 表结构")
print("="*80)

# 1. 检查表是否存在
print("\n1. 检查表是否存在...")
try:
    result = supabase.table('receipt_summaries').select('id').limit(0).execute()
    print("✓ receipt_summaries 表存在")
except Exception as e:
    print(f"❌ receipt_summaries 表不存在或无法访问: {e}")
    sys.exit(0)

# 2. 获取表结构（列信息）
print("\n2. 获取表结构（列）...")
print("   (需要在 Supabase SQL Editor 中运行以下查询：)")
print("""
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'receipt_summaries'
ORDER BY ordinal_position;
""")

# 3. 获取索引信息
print("\n3. 获取索引（在 Supabase SQL Editor 中运行）...")
print("""
SELECT 
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = 'receipt_summaries'
ORDER BY indexname;
""")

# 4. 获取约束信息
print("\n4. 获取约束（在 Supabase SQL Editor 中运行）...")
print("""
SELECT 
    conname as constraint_name,
    contype as constraint_type,
    pg_get_constraintdef(oid) as definition
FROM pg_constraint
WHERE conrelid = 'receipt_summaries'::regclass
ORDER BY conname;
""")

# 5. 检查数据量
print("\n5. 检查数据量...")
result = supabase.table('receipt_summaries').select('id', count='exact').limit(0).execute()
print(f"   总记录数: {result.count}")

# 6. 查看几条数据示例
print("\n6. 数据示例...")
result = supabase.table('receipt_summaries')\
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
    print("   (无数据)")

print("\n" + "="*80)
print("✓ 检查完成")
print("="*80)
