"""
Migration: normalize store_address in record_summaries from old multi-line format to new single-line format.

Old format (written by legacy workflow):
    "19630 Hwy 99\nLynnwood, WA 98036\nUS"

New format (written by _assemble_address_parts):
    "19630 Hwy 99, Lynnwood, WA 98036"

This script finds all record_summaries rows where store_address contains newlines and
rewrites them to comma-separated single-line format. Run once after deploying the new
address-formatting code.

Usage:
    cd backend
    python scripts/maintenance/migrate_store_addresses.py [--dry-run]
"""
import os
import sys
import io
import re
import argparse
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

from app.services.database.supabase_client import _get_client  # noqa: E402


def normalize_address(addr: str) -> str:
    """Convert a newline-separated address to a comma-separated single-line address.

    Examples:
        "19630 Hwy 99\\nLynnwood, WA 98036\\nUS"  -> "19630 Hwy 99, Lynnwood, WA 98036, US"
        "19630 Hwy 99\\nLynnwood, WA 98036"        -> "19630 Hwy 99, Lynnwood, WA 98036"
        "19630 Hwy 99, Lynnwood, WA 98036"         -> unchanged (already single-line)
    """
    parts = [p.strip() for p in addr.split("\n") if p.strip()]
    return ", ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize store_address newlines in record_summaries")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing to DB")
    args = parser.parse_args()

    supabase = _get_client()

    print("Fetching record_summaries rows with multi-line store_address…")

    # Supabase PostgREST: filter rows where store_address contains a newline.
    # We use ilike with %\n% — but PostgREST doesn't support literal \n in ilike.
    # Instead, fetch all non-null store_address rows and filter in Python.
    # Page through in batches to avoid memory issues on large tables.
    PAGE = 500
    offset = 0
    to_update: list[tuple[str, str]] = []  # (id, new_address)

    while True:
        res = (
            supabase.table("record_summaries")
            .select("id, store_address")
            .not_.is_("store_address", "null")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            break

        for row in rows:
            addr = row.get("store_address") or ""
            if "\n" in addr:
                new_addr = normalize_address(addr)
                to_update.append((row["id"], new_addr))

        if len(rows) < PAGE:
            break
        offset += PAGE

    print(f"Found {len(to_update)} rows to update.")

    if not to_update:
        print("Nothing to do.")
        return

    for summary_id, new_addr in to_update:
        if args.dry_run:
            print(f"  [DRY RUN] {summary_id}: -> {new_addr!r}")
        else:
            supabase.table("record_summaries").update({"store_address": new_addr}).eq("id", summary_id).execute()
            print(f"  Updated {summary_id}: {new_addr!r}")

    if args.dry_run:
        print("\nDry run complete — no changes written.")
    else:
        print(f"\nDone. Updated {len(to_update)} rows.")


if __name__ == "__main__":
    main()
