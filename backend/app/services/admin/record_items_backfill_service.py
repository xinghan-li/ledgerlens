"""
Backfill record_items: product_name_clean, on_sale correction, product_id.

Used by:
- Admin API POST /api/admin/classification-review/backfill-record-items
- CLI script scripts/maintenance/backfill_product_name_clean.py
"""
from typing import Any, Dict, Optional

from ..database.supabase_client import (
    _get_client,
    _is_quantity_unit_pricing,
    _has_explicit_sale_indicator,
)
from ..standardization.product_normalizer import normalize_name_for_storage


def run_record_items_backfill(
    limit: int = 0,
    batch_size: int = 200,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Backfill record_items: product_name_clean (where NULL), on_sale→false (qty×unit), product_id (match products).
    Returns dict with total_processed, updated, need_clean, need_onsale, need_product_id, message.
    """
    supabase = _get_client()

    query = (
        supabase.table("record_items")
        .select(
            "id, receipt_id, product_name, product_name_clean, quantity, unit_price, line_total, on_sale, product_id"
        )
        .not_.is_("product_name", "null")
        .order("id")
    )
    if limit:
        query = query.limit(limit)
    res = query.execute()
    rows = res.data or []
    total = len(rows)
    if total == 0:
        return {
            "total_processed": 0,
            "updated": 0,
            "need_clean": 0,
            "need_onsale": 0,
            "need_product_id": 0,
            "message": "No record_items with product_name.",
        }

    receipt_ids = list({r["receipt_id"] for r in rows})
    store_chain_by_receipt = {}
    for i in range(0, len(receipt_ids), 100):
        chunk = receipt_ids[i : i + 100]
        rs = (
            supabase.table("record_summaries")
            .select("receipt_id, store_chain_id")
            .in_("receipt_id", chunk)
            .execute()
        )
        for r in (rs.data or []):
            store_chain_by_receipt[str(r["receipt_id"])] = r.get("store_chain_id")

    prod_res = supabase.table("products").select("id, normalized_name, store_chain_id, usage_count").execute()
    products_list = prod_res.data or []

    def _norm(s):
        return (s or "").strip().lower()

    def _sc_str(sc):
        return str(sc) if sc else "null"

    by_key = {}
    for p in products_list:
        k = (_norm(p.get("normalized_name")), _sc_str(p.get("store_chain_id")))
        if k not in by_key or (p.get("usage_count") or 0) > (by_key[k].get("usage_count") or 0):
            by_key[k] = p

    def _find_product_id(clean_lower: str, store_chain_id: Any) -> Optional[str]:
        if not clean_lower:
            return None
        sc = _sc_str(store_chain_id)
        p = by_key.get((clean_lower, sc)) or by_key.get((clean_lower, "null"))
        return str(p["id"]) if p and p.get("id") else None

    need_clean = sum(
        1
        for r in rows
        if r.get("product_name_clean") is None
        or (isinstance(r.get("product_name_clean"), str) and not (r.get("product_name_clean") or "").strip())
    )
    need_onsale = 0
    need_product_id = sum(1 for r in rows if not r.get("product_id"))
    for r in rows:
        pname = (r.get("product_name") or "").strip()
        item = {
            "quantity": r.get("quantity"),
            "unit_price": r.get("unit_price"),
            "line_total": r.get("line_total"),
        }
        if r.get("on_sale") and _is_quantity_unit_pricing(item) and not _has_explicit_sale_indicator(pname):
            need_onsale += 1

    if dry_run:
        return {
            "total_processed": total,
            "updated": 0,
            "need_clean": need_clean,
            "need_onsale": need_onsale,
            "need_product_id": need_product_id,
            "message": f"Dry run: {total} rows; would fix clean={need_clean}, on_sale={need_onsale}, product_id={need_product_id}.",
        }

    updated = 0
    for i in range(0, total, batch_size):
        chunk = rows[i : i + batch_size]
        for r in chunk:
            rid = r.get("id")
            pname = (r.get("product_name") or "").strip()
            if not pname:
                continue
            payload: Dict[str, Any] = {}

            if (
                r.get("product_name_clean") is None
                or (isinstance(r.get("product_name_clean"), str) and not (r.get("product_name_clean") or "").strip())
            ):
                payload["product_name_clean"] = normalize_name_for_storage(pname) or None

            item = {
                "quantity": r.get("quantity"),
                "unit_price": r.get("unit_price"),
                "line_total": r.get("line_total"),
            }
            if r.get("on_sale") and _is_quantity_unit_pricing(item) and not _has_explicit_sale_indicator(pname):
                payload["on_sale"] = False

            if not r.get("product_id"):
                clean = payload.get("product_name_clean") or normalize_name_for_storage(pname) or ""
                clean_lower = clean.lower() if isinstance(clean, str) else ""
                if clean_lower:
                    sc = store_chain_by_receipt.get(str(r.get("receipt_id")))
                    pid = _find_product_id(clean_lower, sc)
                    if pid:
                        payload["product_id"] = pid

            if not payload:
                continue
            try:
                supabase.table("record_items").update(payload).eq("id", rid).execute()
                updated += 1
            except Exception:
                pass

    return {
        "total_processed": total,
        "updated": updated,
        "need_clean": need_clean,
        "need_onsale": need_onsale,
        "need_product_id": need_product_id,
        "message": f"Updated {updated} row(s).",
    }
