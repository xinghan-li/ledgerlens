"""
Backfill record_summaries.tax and record_summaries.fees from receipt_processing_runs.output_payload.

For each record_summary where tax IS NULL, reads the original LLM/vision output_payload,
extracts the tax and fees values, and updates the record_summary.

Usage:
    cd backend
    python -m scripts.backfill_tax_fees [--dry-run]
"""
import sys
import logging
from pathlib import Path

# Add backend to path so we can import app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.database.supabase_client import _get_client
from app.services.categorization.receipt_categorizer import _normalize_output_payload_to_dollars

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _to_cents(val) -> int | None:
    if val is None:
        return None
    try:
        return int(round(float(val) * 100))
    except (TypeError, ValueError):
        return None


def backfill(dry_run: bool = False):
    supabase = _get_client()

    # Find all record_summaries where tax is NULL
    res = (
        supabase.table("record_summaries")
        .select("id, receipt_id, tax, fees, total, subtotal")
        .is_("tax", "null")
        .execute()
    )
    summaries = res.data or []
    logger.info(f"Found {len(summaries)} record_summaries with tax=NULL")

    updated = 0
    skipped = 0
    errors = 0

    for s in summaries:
        receipt_id = s["receipt_id"]
        summary_id = s["id"]

        # Try to get the processing run output_payload
        run = (
            supabase.table("receipt_processing_runs")
            .select("output_payload")
            .eq("receipt_id", receipt_id)
            .in_("stage", ["vision_primary", "vision_store_specific", "vision_escalation", "llm"])
            .eq("status", "pass")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if not run.data:
            logger.warning(f"  [{receipt_id}] No processing run found, skipping")
            skipped += 1
            continue

        output_payload = run.data[0].get("output_payload")
        if not output_payload or not isinstance(output_payload, dict):
            logger.warning(f"  [{receipt_id}] No output_payload, skipping")
            skipped += 1
            continue

        # Normalize to dollars (same as categorize_receipt does)
        try:
            receipt_data, _ = _normalize_output_payload_to_dollars(
                output_payload.get("receipt", {}),
                output_payload.get("items", []),
            )
        except Exception as e:
            logger.error(f"  [{receipt_id}] Error normalizing: {e}")
            errors += 1
            continue

        tax_dollars = receipt_data.get("tax")
        fees_raw = receipt_data.get("fees")

        # fees can be a list (sum them) or a scalar
        if isinstance(fees_raw, list):
            fees_dollars = sum(f for f in fees_raw if f is not None)
        else:
            fees_dollars = fees_raw

        tax_cents = _to_cents(tax_dollars)
        fees_cents = _to_cents(fees_dollars)

        if tax_cents is None and fees_cents is None:
            logger.info(f"  [{receipt_id}] tax=None, fees=None in output_payload, skipping")
            skipped += 1
            continue

        update = {}
        if tax_cents is not None:
            update["tax"] = tax_cents
        if fees_cents is not None and s.get("fees") is None:
            update["fees"] = fees_cents

        if not update:
            skipped += 1
            continue

        logger.info(f"  [{receipt_id}] Updating: {update}")
        if not dry_run:
            try:
                supabase.table("record_summaries").update(update).eq("id", summary_id).execute()
                updated += 1
            except Exception as e:
                logger.error(f"  [{receipt_id}] Update failed: {e}")
                errors += 1
        else:
            updated += 1

    logger.info(f"\nDone. Updated: {updated}, Skipped: {skipped}, Errors: {errors}")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if dry:
        logger.info("=== DRY RUN MODE ===")
    backfill(dry_run=dry)
