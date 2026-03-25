"""Quick check of tax/fees data in record_summaries."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.database.supabase_client import _get_client

supabase = _get_client()
res = supabase.table("record_summaries").select("receipt_id, store_name, total, subtotal, tax, fees").execute()
rows = res.data or []

print(f"Total summaries: {len(rows)}")
print(f"{'Store':<30} {'Total':>10} {'Subtotal':>10} {'Tax':>10} {'Fees':>10}")
print("-" * 80)

total_tax = 0
total_fees = 0
for r in sorted(rows, key=lambda x: x.get("store_name") or ""):
    t = r.get("total") or 0
    st = r.get("subtotal") or 0
    tx = r.get("tax") or 0
    fe = r.get("fees") or 0
    total_tax += tx
    total_fees += fe
    name = (r.get("store_name") or "Unknown")[:29]
    print(f"{name:<30} {t:>10} {st:>10} {tx:>10} {fe:>10}")

print("-" * 80)
print(f"{'TOTALS':<30} {'':>10} {'':>10} {total_tax:>10} {total_fees:>10}")
print(f"\nTotal tax (dollars): ${total_tax/100:.2f}")
print(f"Total fees (dollars): ${total_fees/100:.2f}")
