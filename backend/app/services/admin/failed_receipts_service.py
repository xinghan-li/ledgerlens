"""
Admin Failed Receipts service.

List failed/needs_review receipts with failure reason; get one for manual correct; submit corrected data.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from app.services.database.supabase_client import (
    _get_client,
    get_store_chain,
    create_store_candidate,
    save_receipt_summary,
    save_receipt_items,
    update_receipt_summary,
    sync_receipt_items,
    update_receipt_status,
    enqueue_unmatched_items_to_classification_review,
)

logger = logging.getLogger(__name__)

FAILED_STATUSES = ("failed", "needs_review")


def delete_receipt_hard(receipt_id: str) -> None:
    """
    Hard-delete a receipt and all related records.
    Clears api_calls/store_candidates.receipt_id then deletes receipt_status;
    CASCADE removes receipt_processing_runs, record_summaries, record_items.
    classification_review.source_record_item_id is SET NULL when record_items are removed.
    Does not modify products, price_snapshots, or product_categorization_rules.
    """
    _clear_receipt_refs_and_delete(receipt_id)
    logger.info(f"Hard-deleted receipt {receipt_id}")


def _clear_receipt_refs_and_delete(receipt_id: str) -> None:
    """Clear api_calls/store_candidates.receipt_id in parallel, then delete receipt_status (CASCADE removes runs, summaries, items)."""
    supabase = _get_client()

    def _clear_api_calls():
        try:
            supabase.table("api_calls").update({"receipt_id": None}).eq("receipt_id", receipt_id).execute()
        except Exception as e:
            logger.warning(f"Clear api_calls.receipt_id: {e}")

    def _clear_store_candidates():
        try:
            supabase.table("store_candidates").update({"receipt_id": None}).eq("receipt_id", receipt_id).execute()
        except Exception as e:
            logger.warning(f"Clear store_candidates.receipt_id: {e}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_clear_api_calls)
        f2 = pool.submit(_clear_store_candidates)
        f1.result()
        f2.result()

    supabase.table("receipt_status").delete().eq("id", receipt_id).execute()


def delete_receipt_for_user(receipt_id: str, user_id: str) -> bool:
    """
    Permanently delete a receipt for the current user (ownership check).
    Same effect as delete_receipt_hard: removes receipt_status and CASCADE removes
    record_summaries, record_items, receipt_processing_runs. Does not touch
    products, price_snapshots, or product_categorization_rules.
    Returns True if deleted, False if receipt not found or not owned by user.
    """
    supabase = _get_client()
    res = supabase.table("receipt_status").select("id").eq("id", receipt_id).eq("user_id", user_id).limit(1).execute()
    if not res.data or len(res.data) == 0:
        return False
    _clear_receipt_refs_and_delete(receipt_id)
    logger.info(f"User {user_id} deleted receipt {receipt_id}")
    return True


def list_failed_receipts(
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    List receipt_status rows where current_status in ('failed', 'needs_review').
    Returns (rows with failure_reason from latest receipt_processing_runs, total count).
    """
    supabase = _get_client()
    q = (
        supabase.table("receipt_status")
        .select("id, user_id, uploaded_at, current_status, current_stage, raw_file_url", count="exact")
        .in_("current_status", list(FAILED_STATUSES))
        .order("uploaded_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    res = q.execute()
    rows = list(res.data or [])
    total = res.count if hasattr(res, "count") and res.count is not None else len(rows)

    if not rows:
        return rows, total

    receipt_ids = [r["id"] for r in rows]
    # Get latest run per receipt (any status) for failure reason
    runs_by_receipt: Dict[str, Dict] = {}
    for rid in receipt_ids:
        run = (
            supabase.table("receipt_processing_runs")
            .select("status, error_message, stage, model_provider, created_at")
            .eq("receipt_id", rid)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if run.data:
            r = run.data[0]
            runs_by_receipt[rid] = {
                "failure_reason": r.get("error_message") if r.get("status") == "fail" else None,
                "stage": r.get("stage"),
                "provider": r.get("model_provider"),
                "run_created_at": r.get("created_at"),
            }
        else:
            runs_by_receipt[rid] = {"failure_reason": "No processing run", "stage": None, "provider": None, "run_created_at": None}

    for r in rows:
        info = runs_by_receipt.get(r["id"]) or {}
        r["failure_reason"] = info.get("failure_reason") or f"Status: {r.get('current_status')}, Stage: {r.get('current_stage') or 'unknown'}"
        r["run_stage"] = info.get("stage")
        r["run_provider"] = info.get("provider")

    return rows, total


def get_failed_receipt_for_edit(receipt_id: str) -> Optional[Dict[str, Any]]:
    """
    Get one receipt for manual correct: receipt_status + prefill from record_summaries/record_items
    or from latest receipt_processing_runs.output_payload (even if status=fail).
    """
    supabase = _get_client()
    receipt = (
        supabase.table("receipt_status")
        .select("id, user_id, uploaded_at, current_status, current_stage, raw_file_url")
        .eq("id", receipt_id)
        .limit(1)
        .execute()
    )
    if not receipt.data:
        return None
    out = receipt.data[0]

    # Failure reason from latest run
    run = (
        supabase.table("receipt_processing_runs")
        .select("status, error_message, stage, output_payload")
        .eq("receipt_id", receipt_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if run.data:
        r = run.data[0]
        out["failure_reason"] = r.get("error_message") if r.get("status") == "fail" else None
        out["run_stage"] = r.get("stage")
        payload = r.get("output_payload") or {}
        out["_output_payload"] = payload
    else:
        out["failure_reason"] = "No processing run"
        out["_output_payload"] = {}

    # Prefill: prefer record_summaries + record_items; else from output_payload
    summary = (
        supabase.table("record_summaries")
        .select("*")
        .eq("receipt_id", receipt_id)
        .limit(1)
        .execute()
    )
    items = (
        supabase.table("record_items")
        .select("id, product_name, quantity, unit, unit_price, line_total, on_sale, original_price, discount_amount, category_id, item_index")
        .eq("receipt_id", receipt_id)
        .order("item_index")
        .execute()
    )

    if summary.data and items.data:
        s = summary.data[0]
        # record_summaries columns subtotal/tax/total store integer cents (migration 031)
        out["prefill"] = {
            "store_name": s.get("store_name"),
            "store_address": s.get("store_address"),
            "receipt_date": s.get("receipt_date"),
            "subtotal": _cents_to_dollars(s.get("subtotal")) or 0.0,
            "tax": _cents_to_dollars(s.get("tax")) or 0.0,
            "total": _cents_to_dollars(s.get("total")) or 0.0,
            "currency": s.get("currency") or "USD",
            "payment_method": s.get("payment_method"),
            "payment_last4": s.get("payment_last4"),
            "cashier": None,
        }
        out["prefill_items"] = []
        for it in items.data:
            out["prefill_items"].append({
                "product_name": it.get("product_name") or "",
                "quantity": _quantity_to_display(it.get("quantity")),
                "unit": it.get("unit"),
                "unit_price": _cents_to_dollars(it.get("unit_price")),
                "line_total": _cents_to_dollars(it.get("line_total")),
                "on_sale": it.get("on_sale") or False,
                "original_price": _cents_to_dollars(it.get("original_price")),
                "discount_amount": _cents_to_dollars(it.get("discount_amount")),
            })
    else:
        # From output_payload
        payload = out.get("_output_payload") or {}
        receipt_data = payload.get("receipt") or {}
        items_data = payload.get("items") or []
        out["prefill"] = {
            "store_name": receipt_data.get("merchant_name"),
            "store_address": receipt_data.get("merchant_address"),
            "receipt_date": receipt_data.get("purchase_date"),
            "subtotal": _safe_float(receipt_data.get("subtotal")),
            "tax": _safe_float(receipt_data.get("tax")),
            "total": _safe_float(receipt_data.get("total")),
            "currency": receipt_data.get("currency") or "USD",
            "payment_method": receipt_data.get("payment_method"),
            "payment_last4": receipt_data.get("card_last4"),
            "cashier": receipt_data.get("cashier"),
        }
        out["prefill_items"] = []
        for it in items_data:
            out["prefill_items"].append({
                "product_name": it.get("product_name") or "",
                "quantity": _safe_float(it.get("quantity")),
                "unit": it.get("unit"),
                "unit_price": _safe_float(it.get("unit_price")),
                "line_total": _safe_float(it.get("line_total")),
                "on_sale": it.get("on_sale") or False,
                "original_price": _safe_float(it.get("original_price")),
                "discount_amount": _safe_float(it.get("discount_amount")),
            })
    out.pop("_output_payload", None)
    return out


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _cents_to_dollars(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return int(val) / 100.0
    except (TypeError, ValueError):
        return None


def _quantity_to_display(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return int(val) / 100.0
    except (TypeError, ValueError):
        return None


def submit_manual_correction(
    receipt_id: str,
    summary: Dict[str, Any],
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Apply manual correction: update only changed summary fields; sync items (update/insert/delete by id).
    Does not delete-and-recreate: record_summaries is updated in place; record_items are updated/inserted/deleted.
    summary: store_name, store_address, receipt_date, subtotal, tax, total, currency, payment_method, payment_last4, purchase_time
    items: list of { id?, product_name, quantity, unit, unit_price, line_total, ... }. id = existing record_items.id for update.
    """
    supabase = _get_client()
    receipt = (
        supabase.table("receipt_status")
        .select("id, user_id, current_status")
        .eq("id", receipt_id)
        .limit(1)
        .execute()
    )
    if not receipt.data:
        raise ValueError("Receipt not found")
    row = receipt.data[0]
    user_id = row["user_id"]
    current_status = (row.get("current_status") or "").strip()

    total = summary.get("total")
    if total is None:
        raise ValueError("summary.total is required")
    try:
        total_float = float(total)
    except (TypeError, ValueError):
        raise ValueError("summary.total must be a number")

    # Normalize card_last4 to digits only; time to HH:mm
    raw_last4 = summary.get("payment_last4")
    card_last4 = None
    if raw_last4 is not None and str(raw_last4).strip():
        digits = "".join(c for c in str(raw_last4).strip() if c.isdigit())
        card_last4 = digits[-4:] if len(digits) >= 4 else (digits or None)
    raw_time = summary.get("purchase_time")
    purchase_time = None
    if raw_time is not None and str(raw_time).strip():
        s = str(raw_time).strip()
        if ":" in s:
            parts = s.split(":")
            purchase_time = f"{parts[0].zfill(2)}:{parts[1]}" if len(parts) >= 2 else s[:5]
        else:
            purchase_time = s[:5]

    receipt_data = {
        "merchant_name": summary.get("store_name"),
        "merchant_address": summary.get("store_address"),
        "purchase_date": summary.get("receipt_date"),
        "subtotal": summary.get("subtotal"),
        "tax": summary.get("tax"),
        "total": total_float,
        "currency": summary.get("currency") or "USD",
        "payment_method": summary.get("payment_method"),
        "card_last4": card_last4,
        "country": summary.get("country"),
        "cashier": summary.get("cashier"),
        "merchant_phone": summary.get("merchant_phone"),
        "purchase_time": purchase_time,
    }

    # Resolve store_chain_id / store_location_id when we have store name (for insert or update)
    chain_id = None
    location_id = None
    match_result: Dict[str, Any] = {}
    store_name = (receipt_data.get("merchant_name") or "").strip()
    store_address = receipt_data.get("merchant_address")
    if store_name:
        try:
            match_result = get_store_chain(store_name, store_address)
            if match_result.get("matched"):
                chain_id = match_result.get("chain_id")
                location_id = match_result.get("location_id")
                logger.info(f"Manual correction store match: {store_name} -> chain_id={chain_id}, location_id={location_id}")
        except Exception as e:
            logger.warning(f"get_store_chain during manual submit: {e}")

    # Build items_data for sync (include id when present so we update instead of insert)
    items_data = []
    for it in items:
        product_name = (it.get("product_name") or "").strip()
        if not product_name:
            logger.info("[MANUAL_CORRECT_DEBUG] skip item: no product_name, raw=%s", it)
            continue
        if it.get("line_total") is None:
            logger.info("[MANUAL_CORRECT_DEBUG] skip item: no line_total, product_name=%s", product_name[:50])
            continue
        items_data.append({
            "id": it.get("id"),
            "product_name": product_name,
            "quantity": it.get("quantity"),
            "unit": it.get("unit"),
            "unit_price": it.get("unit_price"),
            "line_total": it.get("line_total"),
            "on_sale": it.get("on_sale"),
            "is_on_sale": it.get("on_sale"),
            "original_price": it.get("original_price"),
            "discount_amount": it.get("discount_amount"),
            "category": it.get("category"),
            "category_id": it.get("category_id"),
        })

    logger.info(
        "[MANUAL_CORRECT_DEBUG] receipt_id=%s raw_items=%d items_data=%d sample=%s",
        receipt_id,
        len(items),
        len(items_data),
        [
            {"id": it.get("id"), "product_name": (it.get("product_name") or "")[:40], "line_total": it.get("line_total")}
            for it in items_data[:3]
        ],
    )

    summary_id = None
    # Update existing summary or insert if none (e.g. first correct after failure)
    updated = update_receipt_summary(
        receipt_id=receipt_id,
        user_id=user_id,
        receipt_data=receipt_data,
        chain_id=chain_id,
        location_id=location_id,
        items_data=items_data if items_data else None,
    )
    if updated is not None:
        summary_id = updated
        logger.info("[MANUAL_CORRECT_DEBUG] path=UPDATE summary_id=%s calling sync_receipt_items", summary_id)
        sync_receipt_items(receipt_id=receipt_id, user_id=user_id, items_data=items_data)
    else:
        logger.info("[MANUAL_CORRECT_DEBUG] path=INSERT (no existing record_summaries) calling save_receipt_summary + save_receipt_items")
        summary_id = save_receipt_summary(
            receipt_id=receipt_id,
            user_id=user_id,
            receipt_data=receipt_data,
            chain_id=chain_id,
            location_id=location_id,
            items_data=items_data,
        )
        if items_data:
            save_receipt_items(receipt_id=receipt_id, user_id=user_id, items_data=items_data)
        else:
            logger.warning("[MANUAL_CORRECT_DEBUG] items_data empty, save_receipt_items NOT called")

    # Only set status to success when receipt was not needs_review. needs_review stays until user explicitly clicks "Review complete".
    if current_status != "needs_review":
        update_receipt_status(receipt_id, current_status="success", current_stage="manual")
    # When corrected store name/address did not match a location, create store_candidate so admin can review (e.g. LLM was wrong, user fixed address)
    if store_name and (not chain_id or not location_id):
        try:
            existing = supabase.table("store_candidates").select("id").eq("receipt_id", receipt_id).limit(1).execute()
            if not (existing.data and len(existing.data) > 0):
                candidate_id = create_store_candidate(
                    chain_name=store_name,
                    receipt_id=receipt_id,
                    source="llm",
                    llm_result={"receipt": receipt_data},
                    suggested_chain_id=match_result.get("suggested_chain_id") or chain_id,
                    suggested_location_id=match_result.get("suggested_location_id") or location_id,
                    confidence_score=match_result.get("confidence_score"),
                )
                if candidate_id:
                    logger.info(
                        f"Manual correction: created store_candidate {candidate_id} for {store_name!r} (no match or new location) so admin can review"
                    )
        except Exception as e:
            logger.warning(f"Failed to create store_candidate after manual correction: {e}")

    # Enqueue items without category (or universal-only) to classification_review so they get reviewed
    try:
        enqueued = enqueue_unmatched_items_to_classification_review(receipt_id)
        if enqueued:
            logger.info(f"Manual correction: enqueued {enqueued} item(s) to classification_review for receipt {receipt_id}")
    except Exception as e:
        logger.warning(f"Failed to enqueue items to classification_review after manual correction: {e}")
    logger.info(f"Manual correction submitted for receipt {receipt_id}, summary_id={summary_id}")
    return {"success": True, "receipt_id": receipt_id, "summary_id": summary_id, "items_count": len(items_data)}
