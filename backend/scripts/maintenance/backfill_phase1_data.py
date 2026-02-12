"""
Backfill Phase 1 data for existing successful receipts
为已有的成功小票补充 Phase 1 数据
"""
import os
import sys
import io
import json
from pathlib import Path
from dotenv import load_dotenv

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment variables
load_dotenv(dotenv_path=".env")

# Import after path is set
from app.services.database.supabase_client import (
    save_receipt_summary,
    save_receipt_items,
    _get_client
)

print("\n" + "="*60)
print("🔄 Backfill Phase 1 Data")
print("="*60)

# Test with the most recent receipt
test_receipt_id = "e349f9b8-c37c-4840-b616-e9c1fa490388"
test_user_id = "7981c0a1-6017-4a8c-b551-3fb4118cd798"

# Load the output JSON
json_path = Path("F:/LedgerLens/output/20260212/00452946_021226_0045_WeChat_Image_2026020_output.json")

if not json_path.exists():
    print(f"❌ JSON file not found: {json_path}")
    sys.exit(1)

with open(json_path, 'r', encoding='utf-8') as f:
    output_data = json.load(f)

llm_result = output_data.get("data", {})
receipt_data = llm_result.get("receipt", {})
items_data = llm_result.get("items", [])

print(f"\n📄 Receipt ID: {test_receipt_id}")
print(f"👤 User ID: {test_user_id}")
print(f"🏪 Store: {receipt_data.get('merchant_name')}")
print(f"💰 Total: ${receipt_data.get('total')}")
print(f"📦 Items: {len(items_data)}")

# Save receipt_summary
print("\n1️⃣ Saving receipt_summary...")
try:
    summary_id = save_receipt_summary(
        receipt_id=test_receipt_id,
        user_id=test_user_id,
        receipt_data=receipt_data
    )
    print(f"✅ Saved receipt_summary: {summary_id}")
except Exception as e:
    print(f"❌ Failed to save receipt_summary: {e}")
    import traceback
    traceback.print_exc()

# Save receipt_items
print("\n2️⃣ Saving receipt_items...")
try:
    item_ids = save_receipt_items(
        receipt_id=test_receipt_id,
        user_id=test_user_id,
        items_data=items_data
    )
    print(f"✅ Saved {len(item_ids)} receipt_items")
except Exception as e:
    print(f"❌ Failed to save receipt_items: {e}")
    import traceback
    traceback.print_exc()

# Verify
print("\n3️⃣ Verifying data...")
supabase = _get_client()

summary = supabase.table("receipt_summaries").select("*").eq("receipt_id", test_receipt_id).execute()
if summary.data:
    print("✅ receipt_summary verified")
    s = summary.data[0]
    print(f"   Store: {s.get('store_name')}")
    print(f"   Date: {s.get('receipt_date')}")
    print(f"   Total: ${s.get('total')}")
else:
    print("❌ receipt_summary not found")

items = supabase.table("receipt_items").select("id, product_name, line_total").eq("receipt_id", test_receipt_id).execute()
if items.data:
    print(f"✅ {len(items.data)} receipt_items verified")
    for idx, item in enumerate(items.data[:3], 1):
        print(f"   {idx}. {item.get('product_name')} - ${item.get('line_total')}")
    if len(items.data) > 3:
        print(f"   ... and {len(items.data) - 3} more")
else:
    print("❌ receipt_items not found")

print("\n" + "="*60)
print("✅ Backfill completed successfully!")
print("="*60)
