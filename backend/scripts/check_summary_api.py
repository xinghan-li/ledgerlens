"""Check what the analytics summary API returns for tax."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.database.supabase_client import _get_client, get_user_analytics_summary

supabase = _get_client()

# Get user_id from receipt_status
users = supabase.table("receipt_status").select("user_id").execute()
user_ids = list({r["user_id"] for r in (users.data or [])})
print(f"Found user_ids: {user_ids}")

for uid in user_ids:
    print(f"\n--- User: {uid} ---")
    result = get_user_analytics_summary(uid, None, None)
    print(f"  total_amount_cents: {result.get('total_amount_cents')}")
    print(f"  total_tax_cents: {result.get('total_tax_cents')}")
    print(f"  total_fees_cents: {result.get('total_fees_cents')}")
    print(f"  total_receipts: {result.get('total_receipts')}")
    print(f"  unclassified_count: {result.get('unclassified_count')}")
    print(f"  unclassified_amount_cents: {result.get('unclassified_amount_cents')}")
