"""
Backfill record_items: product_name_clean, on_sale correction, product_id.

Delegates to record_items_backfill_service. Same logic is used by the admin API
POST /api/admin/classification-review/backfill-record-items (Classification Review page button).

Run from backend directory:
  python scripts/maintenance/backfill_product_name_clean.py --dry-run
  python scripts/maintenance/backfill_product_name_clean.py
  python scripts/maintenance/backfill_product_name_clean.py --limit 5000 --batch 200
"""
import sys
import io
import argparse
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.services.admin.record_items_backfill_service import run_record_items_backfill


def main():
    ap = argparse.ArgumentParser(
        description="Backfill record_items: product_name_clean, on_sale correction, product_id"
    )
    ap.add_argument("--dry-run", action="store_true", help="Only count, do not update")
    ap.add_argument("--limit", type=int, default=0, help="Max rows to process (0 = no limit)")
    ap.add_argument("--batch", type=int, default=200, help="Update batch size")
    args = ap.parse_args()

    result = run_record_items_backfill(
        limit=args.limit,
        batch_size=args.batch,
        dry_run=args.dry_run,
    )
    print(f"Total processed: {result['total_processed']}")
    print(f"  Need product_name_clean: {result['need_clean']}")
    print(f"  Need on_sale=false (qty×unit): {result['need_onsale']}")
    print(f"  Need product_id: {result['need_product_id']}")
    if not args.dry_run:
        print(f"Updated: {result['updated']}")
    print(result["message"])


if __name__ == "__main__":
    main()
