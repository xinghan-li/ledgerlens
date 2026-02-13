"""
详细检查重复数据
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

print("\n" + "="*60)
print("🔍 详细检查重复数据")
print("="*60)

# 查询所有 receipts，按 file_hash 分组
print("\n1. 按 file_hash 分组查询...")
all_receipts = supabase.table("receipt_status")\
    .select("id, user_id, file_hash, uploaded_at, current_status")\
    .order("uploaded_at")\
    .execute()

print(f"总共 {len(all_receipts.data)} 张小票")

# Group by file_hash
hash_groups = {}
no_hash_count = 0

for receipt in all_receipts.data:
    file_hash = receipt.get('file_hash')
    if file_hash:
        if file_hash not in hash_groups:
            hash_groups[file_hash] = []
        hash_groups[file_hash].append(receipt)
    else:
        no_hash_count += 1

print(f"有 {no_hash_count} 张小票没有 file_hash（跳过）")
print(f"有 {len(hash_groups)} 个唯一的 file_hash")

# 找出重复的
duplicates = []
for file_hash, receipts in hash_groups.items():
    if len(receipts) > 1:
        duplicates.append({
            'file_hash': file_hash,
            'count': len(receipts),
            'receipts': receipts
        })

duplicates.sort(key=lambda x: x['count'], reverse=True)

if not duplicates:
    print("\n✅ 没有发现重复的小票！")
else:
    print(f"\n⚠️  发现 {len(duplicates)} 组重复小票：")
    for idx, dup in enumerate(duplicates, 1):
        print(f"\n组 {idx}: {dup['count']} 张重复")
        print(f"  file_hash: {dup['file_hash'][:30]}...")
        for r in dup['receipts']:
            print(f"    - ID: {r['id']}")
            print(f"      时间: {r['uploaded_at']}")
            print(f"      状态: {r['current_status']}")

print("\n" + "="*60)
