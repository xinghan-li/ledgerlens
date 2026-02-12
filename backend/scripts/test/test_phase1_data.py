"""
测试 Phase 1 数据是否保存成功
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

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env")
    sys.exit(1)

# Create Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

print("\n" + "="*60)
print("🔍 检查 Phase 1 数据保存情况")
print("="*60)

# 查找最近处理的小票
print("\n1. 查找最近的成功小票...")
try:
    recent_receipts = supabase.table("receipts")\
        .select("id, user_id, current_status, current_stage, uploaded_at")\
        .eq("current_status", "success")\
        .order("uploaded_at", desc=True)\
        .limit(5)\
        .execute()
    
    if not recent_receipts.data:
        print("❌ 没有找到成功的小票")
        sys.exit(1)
    
    print(f"\n找到 {len(recent_receipts.data)} 张最近的成功小票:\n")
    
    for idx, receipt in enumerate(recent_receipts.data, 1):
        print(f"{idx}. Receipt ID: {receipt['id']}")
        print(f"   上传时间: {receipt['uploaded_at']}")
        print(f"   状态: {receipt['current_status']} / {receipt['current_stage']}")
        print()
    
    # 检查第一张小票的详细数据
    test_receipt_id = recent_receipts.data[0]['id']
    test_user_id = recent_receipts.data[0]['user_id']
    
    print("="*60)
    print(f"📊 检查第一张小票的详细数据")
    print(f"Receipt ID: {test_receipt_id}")
    print("="*60)
    
    # 检查 receipt_summaries
    print("\n2. 检查 receipt_summaries...")
    summary = supabase.table("receipt_summaries")\
        .select("*")\
        .eq("receipt_id", test_receipt_id)\
        .execute()
    
    if summary.data:
        print("✅ 找到 receipt_summary:")
        s = summary.data[0]
        print(f"   Store: {s.get('store_name')}")
        print(f"   Date: {s.get('receipt_date')}")
        print(f"   Total: ${s.get('total')}")
        print(f"   Tax: ${s.get('tax')}")
        print(f"   Payment: {s.get('payment_method')}")
    else:
        print("❌ 没有找到 receipt_summary")
    
    # 检查 receipt_items
    print("\n3. 检查 receipt_items...")
    items = supabase.table("receipt_items")\
        .select("*")\
        .eq("receipt_id", test_receipt_id)\
        .order("item_index")\
        .execute()
    
    if items.data:
        print(f"✅ 找到 {len(items.data)} 个 receipt_items:")
        for idx, item in enumerate(items.data[:5], 1):
            print(f"   {idx}. {item.get('product_name')}")
            print(f"      Brand: {item.get('brand')}")
            print(f"      Quantity: {item.get('quantity')} {item.get('unit')}")
            print(f"      Price: ${item.get('unit_price')} → ${item.get('line_total')}")
            print(f"      Category: {item.get('category_l1')} > {item.get('category_l2')} > {item.get('category_l3')}")
        if len(items.data) > 5:
            print(f"   ... 还有 {len(items.data) - 5} 个商品")
    else:
        print("❌ 没有找到 receipt_items")
    
    # 统计 Phase 1 数据覆盖率
    print("\n" + "="*60)
    print("📊 Phase 1 数据覆盖率统计")
    print("="*60)
    
    total_receipts = supabase.table("receipts")\
        .select("id", count="exact")\
        .eq("current_status", "success")\
        .execute()
    
    total_summaries = supabase.table("receipt_summaries")\
        .select("id", count="exact")\
        .execute()
    
    total_items = supabase.table("receipt_items")\
        .select("id", count="exact")\
        .execute()
    
    success_count = total_receipts.count if total_receipts.count else 0
    summary_count = total_summaries.count if total_summaries.count else 0
    item_count = total_items.count if total_items.count else 0
    
    print(f"\n成功的小票: {success_count}")
    print(f"receipt_summaries: {summary_count}")
    print(f"receipt_items: {item_count}")
    
    if success_count > 0:
        coverage = (summary_count / success_count) * 100
        print(f"\n覆盖率: {coverage:.1f}% ({summary_count}/{success_count})")
        
        if coverage < 100:
            print(f"\n⚠️  有 {success_count - summary_count} 张成功的小票没有 summary 数据")
            print("这可能是因为这些小票是在 Phase 1 实施之前处理的")
    
    print("\n" + "="*60)
    
except Exception as e:
    print(f"❌ 错误: {e}")
    import traceback
    traceback.print_exc()
