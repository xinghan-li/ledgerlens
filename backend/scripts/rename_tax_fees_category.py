"""Rename user category 'tax & fees' to 'fees & misc'."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.database.supabase_client import _get_client

supabase = _get_client()

res = supabase.table("user_categories").select("id, name, user_id").ilike("name", "%tax%fee%").execute()
rows = res.data or []
print(f"Found {len(rows)} matching categories:")
for r in rows:
    print(f"  id={r['id']} user={r['user_id']} name={r['name']!r}")

if rows:
    for r in rows:
        print(f"  Renaming {r['name']!r} -> 'fees & misc'")
        supabase.table("user_categories").update({"name": "fees & misc"}).eq("id", r["id"]).execute()
    print("Done.")
else:
    print("No categories to rename.")
