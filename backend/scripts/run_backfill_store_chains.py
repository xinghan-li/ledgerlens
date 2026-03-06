#!/usr/bin/env python3
"""
One-off: backfill record_summaries.store_chain_id for all active store_chains.
Run from repo root: python -m backend.scripts.run_backfill_store_chains
Or from backend: python scripts/run_backfill_store_chains.py (with PYTHONPATH=.)
"""
import sys
from pathlib import Path

# Allow importing app when run as script
backend = Path(__file__).resolve().parent.parent
if str(backend) not in sys.path:
    sys.path.insert(0, str(backend))

from app.services.database.supabase_client import backfill_record_summaries_for_store_chain
from app.services.admin.store_review_service import list_store_chains


def main():
    chains = list_store_chains(active_only=True)
    print(f"Found {len(chains)} active store chain(s). Running backfill...")
    total = 0
    for c in chains:
        cid = c.get("id")
        name = c.get("name") or ""
        norm = (c.get("normalized_name") or "").strip() or None
        if not cid or not name.strip():
            continue
        n = backfill_record_summaries_for_store_chain(str(cid), name.strip(), normalized_name=norm)
        if n:
            print(f"  {name}: {n} record_summaries updated")
        total += n
    print(f"Backfill done. Total updated: {total}")


if __name__ == "__main__":
    main()
