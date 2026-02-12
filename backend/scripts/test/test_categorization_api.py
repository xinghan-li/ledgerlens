"""
测试 Categorization API
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
print("🧪 测试 Categorization API")
print("="*60)

# 找一张 success 的小票
print("\n1. 查找可以 categorize 的小票...")
success_receipts = supabase.table("receipts")\
    .select("id, user_id, current_status, uploaded_at")\
    .eq("current_status", "success")\
    .order("uploaded_at", desc=True)\
    .limit(5)\
    .execute()

if not success_receipts.data:
    print("❌ 没有找到成功的小票")
    sys.exit(1)

print(f"找到 {len(success_receipts.data)} 张成功的小票:")
for idx, r in enumerate(success_receipts.data, 1):
    print(f"  {idx}. {r['id']} - {r['uploaded_at']}")

# 使用第一张小票测试
test_receipt = success_receipts.data[0]
receipt_id = test_receipt['id']
user_id = test_receipt['user_id']

print(f"\n2. 测试小票: {receipt_id}")

# 检查是否有 processing run
runs = supabase.table("receipt_processing_runs")\
    .select("id, stage, status")\
    .eq("receipt_id", receipt_id)\
    .eq("stage", "llm")\
    .eq("status", "pass")\
    .execute()

if runs.data:
    print(f"✅ 有 {len(runs.data)} 个成功的 LLM processing run")
else:
    print("❌ 没有成功的 LLM processing run")
    sys.exit(1)

# 检查 output_payload
run = runs.data[0]
run_detail = supabase.table("receipt_processing_runs")\
    .select("output_payload")\
    .eq("id", run['id'])\
    .single()\
    .execute()

output = run_detail.data.get("output_payload", {})
print(f"✅ output_payload 包含:")
print(f"   - receipt: {'✅' if 'receipt' in output else '❌'}")
print(f"   - items: {len(output.get('items', []))} 个")

# 测试 categorization
print("\n3. 开始 categorize...")
print("=" * 60)

# Import the function
sys.path.insert(0, os.path.dirname(__file__))
from app.services.categorization.receipt_categorizer import categorize_receipt

try:
    result = categorize_receipt(receipt_id, force=True)
    
    if result.get("success"):
        print("✅ Categorization 成功!")
        print(f"   - Summary ID: {result.get('summary_id')}")
        print(f"   - Items Count: {result.get('items_count')}")
        print(f"   - Message: {result.get('message')}")
    else:
        print("❌ Categorization 失败:")
        print(f"   - Message: {result.get('message')}")
except Exception as e:
    print(f"❌ 错误: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 验证数据
print("\n4. 验证保存的数据...")

summary = supabase.table("receipt_summaries")\
    .select("*")\
    .eq("receipt_id", receipt_id)\
    .execute()

if summary.data:
    print("✅ receipt_summary:")
    s = summary.data[0]
    print(f"   Store: {s.get('store_name')}")
    print(f"   Date: {s.get('receipt_date')}")
    print(f"   Total: ${s.get('total')}")
else:
    print("❌ 没有 receipt_summary")

items = supabase.table("receipt_items")\
    .select("id, product_name, line_total")\
    .eq("receipt_id", receipt_id)\
    .execute()

if items.data:
    print(f"✅ receipt_items: {len(items.data)} 个")
    for idx, item in enumerate(items.data[:3], 1):
        print(f"   {idx}. {item.get('product_name')} - ${item.get('line_total')}")
    if len(items.data) > 3:
        print(f"   ... 还有 {len(items.data) - 3} 个")
else:
    print("❌ 没有 receipt_items")

print("\n" + "="*60)
print("✅ 测试完成！")
print("="*60)
