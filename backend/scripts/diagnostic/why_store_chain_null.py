"""
Diagnose why some record_summaries have store_chain_id / store_location_id NULL.
Target: Walmart Supercentre (London ON) and T&T Supermarket (Surrey BC).
"""
import os
import sys
from dotenv import load_dotenv

# backend/scripts/diagnostic/ -> backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from app.services.database.supabase_client import _get_client

def main():
    supabase = _get_client()

    print("\n" + "=" * 70)
    print("1. store_chains: all active (name / normalized_name)")
    print("=" * 70)
    chains = supabase.table("store_chains").select("id, name, normalized_name").eq("is_active", True).execute()
    for c in (chains.data or []):
        print(f"  id={c['id'][:8]}...  name={c.get('name')!r}  normalized_name={c.get('normalized_name')!r}")

    print("\n" + "=" * 70)
    print("2. store_locations: all active (chain_id, name, address, city, state, zip, country)")
    print("=" * 70)
    locs = supabase.table("store_locations").select(
        "id, chain_id, name, address_line1, address_line2, city, state, zip_code, country_code"
    ).eq("is_active", True).execute()
    for loc in (locs.data or []):
        chain_id_short = (loc.get("chain_id") or "")[:8] if loc.get("chain_id") else "-"
        addr1 = (loc.get("address_line1") or "")[:50]
        city = loc.get("city") or ""
        state = loc.get("state") or ""
        zipcode = loc.get("zip_code") or ""
        country = loc.get("country_code") or ""
        print(f"  chain_id={chain_id_short}...  name={loc.get('name')!r}")
        print(f"    address: {addr1} | {city}, {state} {zipcode} {country}")

    print("\n" + "=" * 70)
    print("3. record_summaries with store_chain_id NULL (Walmart / T&T)")
    print("=" * 70)
    rs = supabase.table("record_summaries").select(
        "id, store_chain_id, store_location_id, store_name, store_address"
    ).is_("store_chain_id", "null").execute()
    for r in (rs.data or []):
        name = (r.get("store_name") or "").lower()
        if "walmart" in name or "t&t" in name or "t and t" in name:
            print(f"  id={r.get('id')[:8]}...  store_name={r.get('store_name')!r}")
            print(f"    store_address={r.get('store_address')!r}")
            print(f"    store_chain_id={r.get('store_chain_id')}  store_location_id={r.get('store_location_id')}")

    print("\n" + "=" * 70)
    print("4. record_summaries already matched (T&T / Walmart) for comparison")
    print("=" * 70)
    rs2 = supabase.table("record_summaries").select(
        "id, store_chain_id, store_location_id, store_name, store_address"
    ).not_.is_("store_chain_id", "null").execute()
    for r in (rs2.data or []):
        name = (r.get("store_name") or "").lower()
        if "walmart" in name or "t&t" in name:
            print(f"  store_name={r.get('store_name')!r}  store_chain_id={r.get('store_chain_id')[:8]}...  store_location_id={r.get('store_location_id')[:8] if r.get('store_location_id') else None}...")
            print(f"    store_address={(r.get('store_address') or '')[:80]}...")

    print("\n" + "=" * 70)
    print("5. Conclusion: why not matched")
    print("=" * 70)
    chain_names = [c.get("name", "").lower() for c in (chains.data or [])]
    has_walmart = any("walmart" in n for n in chain_names)
    has_tt = any("t&t" in n or "t and t" in n for n in chain_names)
    locations_by_chain = {}
    for loc in (locs.data or []):
        cid = loc.get("chain_id")
        if cid:
            locations_by_chain.setdefault(cid, []).append(loc)
    print(f"  - Has Walmart in store_chains: {has_walmart}")
    print(f"  - Has T&T in store_chains: {has_tt}")
    london_locs = [loc for loc in (locs.data or []) if (loc.get("city") or "").upper() == "LONDON" and (loc.get("state") or "").upper() == "ON"]
    surrey_locs = [loc for loc in (locs.data or []) if (loc.get("city") or "").upper() == "SURREY" and (loc.get("state") or "").upper() == "BC"]
    print(f"  - store_locations London, ON count: {len(london_locs)}")
    print(f"  - store_locations Surrey, BC count: {len(surrey_locs)}")
    if london_locs:
        for loc in london_locs:
            print(f"      London addr: {loc.get('address_line1')} | {loc.get('city')}, {loc.get('state')} {loc.get('zip_code')}")
    if surrey_locs:
        for loc in surrey_locs:
            print(f"      Surrey addr: {loc.get('address_line1')} | {loc.get('city')}, {loc.get('state')} {loc.get('zip_code')}")

    print("\n" + "=" * 70)
    print("6. store_candidates: T&T / Walmart / Surrey / King George (all statuses)")
    print("=" * 70)
    cand = supabase.table("store_candidates").select(
        "id, raw_name, normalized_name, status, receipt_id, suggested_chain_id, created_at, metadata"
    ).execute()
    for c in (cand.data or []):
        raw = (c.get("raw_name") or "").lower()
        meta = c.get("metadata") or {}
        addr = (meta.get("address") or {}).get("full_address") or ""
        addr_lower = addr.lower()
        if "t&t" in raw or "walmart" in raw or "surrey" in addr_lower or "king george" in addr_lower:
            print(f"  id={c.get('id')[:8]}...  raw_name={c.get('raw_name')!r}  status={c.get('status')}  receipt_id={c.get('receipt_id')}")
            if addr:
                print(f"    address: {addr[:70]}...")
            print(f"    suggested_chain_id={c.get('suggested_chain_id')}  created_at={c.get('created_at')}")

    print("\n" + "=" * 70)
    print("7. record_summaries T&T Surrey: get receipt_id to link to candidates")
    print("=" * 70)
    rs_surrey = supabase.table("record_summaries").select("id, receipt_id, store_name, store_address").execute()
    for r in (rs_surrey.data or []):
        if (r.get("store_address") or "").find("King George") >= 0 or (r.get("store_address") or "").find("Surrey") >= 0:
            print(f"  record_summary id={r.get('id')}  receipt_id={r.get('receipt_id')}  store_name={r.get('store_name')!r}")
    print()

if __name__ == "__main__":
    main()
