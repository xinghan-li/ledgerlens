"""
Admin Classification Review service.

CRUD and confirm for classification_review table; confirm writes to
product_categorization_rules and products.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.services.database.supabase_client import _get_client
from app.services.standardization.product_normalizer import normalize_name_for_storage

logger = logging.getLogger(__name__)

STATUS_VALUES = frozenset({"pending", "confirmed", "unable_to_decide", "deferred", "cancelled"})


def list_classification_review(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    List classification_review rows with optional status filter.
    Returns (rows with category name/path and store_chain name, total count).
    """
    supabase = _get_client()
    q = supabase.table("classification_review").select(
        "id, raw_product_name, normalized_name, category_id, store_chain_id, size_quantity, size_unit, package_type, "
        "match_type, source_record_item_id, status, created_at, updated_at, confirmed_at, confirmed_by",
        count="exact",
    )
    if status and status in STATUS_VALUES:
        q = q.eq("status", status)
    q = q.order("created_at", desc=True).range(offset, offset + limit - 1)
    res = q.execute()
    rows = list(res.data or [])
    total = res.count if hasattr(res, "count") and res.count is not None else len(rows)

    # Enrich with category name/path and store_chain name
    category_ids = {r["category_id"] for r in rows if r.get("category_id")}
    store_chain_ids = {r["store_chain_id"] for r in rows if r.get("store_chain_id")}
    categories = {}
    if category_ids:
        cats = supabase.table("categories").select("id, name, path").in_("id", list(category_ids)).execute()
        for c in (cats.data or []):
            categories[c["id"]] = {"name": c.get("name"), "path": c.get("path")}
    chains = {}
    if store_chain_ids:
        ch = supabase.table("store_chains").select("id, name").in_("id", list(store_chain_ids)).execute()
        for c in (ch.data or []):
            chains[c["id"]] = c.get("name")

    for r in rows:
        r["category_name"] = None
        r["category_path"] = None
        if r.get("category_id") and r["category_id"] in categories:
            r["category_name"] = categories[r["category_id"]].get("name")
            r["category_path"] = categories[r["category_id"]].get("path")
        r["store_chain_name"] = chains.get(r["store_chain_id"]) if r.get("store_chain_id") else None

    return rows, total


def get_one(cr_id: str) -> Optional[Dict[str, Any]]:
    """Get a single classification_review row by id."""
    supabase = _get_client()
    res = supabase.table("classification_review").select("*").eq("id", cr_id).limit(1).execute()
    if not res.data:
        return None
    return res.data[0]


def delete_classification_review(cr_id: str) -> None:
    """Hard-delete a classification_review row by id. No cascade (table has no child FKs)."""
    if get_one(cr_id) is None:
        raise ValueError("classification_review row not found")
    supabase = _get_client()
    supabase.table("classification_review").delete().eq("id", cr_id).execute()
    logger.info(f"Hard-deleted classification_review row {cr_id}")


def _dedupe_key(row: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """(store_chain_id, normalized_name) for grouping. Later submission overrides earlier."""
    store_chain_id = row.get("store_chain_id")
    raw = (row.get("raw_product_name") or "").strip()
    norm = (row.get("normalized_name") or "").strip()
    name_for_key = normalize_name_for_storage(norm or raw) if (norm or raw) else ""
    return (str(store_chain_id) if store_chain_id else None, name_for_key or "")


def dedupe_classification_review() -> Dict[str, Any]:
    """
    Remove duplicate classification_review rows: same store_chain_id + same normalized product.
    Keeps the latest row (by created_at) per (store_chain_id, normalized_name); deletes the rest.
    So "later submission overrides earlier" and we never keep duplicate items under the same store.
    Returns {"deleted": N, "message": "..."}.
    """
    supabase = _get_client()
    res = (
        supabase.table("classification_review")
        .select("id, store_chain_id, normalized_name, raw_product_name, created_at")
        .execute()
    )
    rows = list(res.data or [])
    groups: Dict[Tuple[Optional[str], str], List[Dict[str, Any]]] = {}
    for r in rows:
        key = _dedupe_key(r)
        if key not in groups:
            groups[key] = []
        groups[key].append(r)

    to_delete: List[str] = []
    for key, group in groups.items():
        if len(group) <= 1:
            continue
        # Keep latest (max created_at), delete the rest
        group_sorted = sorted(group, key=lambda x: (x.get("created_at") or ""), reverse=True)
        for r in group_sorted[1:]:
            to_delete.append(r["id"])

    for cr_id in to_delete:
        supabase.table("classification_review").delete().eq("id", cr_id).execute()
        logger.info(f"Dedupe: deleted classification_review row {cr_id}")

    if to_delete:
        logger.info(f"Dedupe: removed {len(to_delete)} duplicate classification_review row(s)")
    return {
        "deleted": len(to_delete),
        "message": f"Removed {len(to_delete)} duplicate row(s). Kept latest per (store, product).",
    }


def update_classification_review(
    cr_id: str,
    normalized_name: Optional[str] = None,
    category_id: Optional[str] = None,
    store_chain_id: Optional[str] = None,
    size_quantity: Optional[float] = None,
    size_unit: Optional[str] = None,
    package_type: Optional[str] = None,
    match_type: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    PATCH a classification_review row. Normalizes normalized_name (lowercase, trim, singularize).
    """
    supabase = _get_client()
    payload: Dict[str, Any] = {}
    if normalized_name is not None:
        payload["normalized_name"] = normalize_name_for_storage(normalized_name) or None
    if category_id is not None:
        payload["category_id"] = category_id
    if store_chain_id is not None:
        payload["store_chain_id"] = store_chain_id
    if size_quantity is not None:
        try:
            payload["size_quantity"] = float(size_quantity) if str(size_quantity).strip() else None
        except (TypeError, ValueError):
            payload["size_quantity"] = None
    if size_unit is not None:
        payload["size_unit"] = (size_unit or "").strip() or None
    if package_type is not None:
        payload["package_type"] = (package_type or "").strip() or None
    if match_type is not None and match_type in ("exact", "fuzzy", "contains"):
        payload["match_type"] = match_type
    if status is not None and status in STATUS_VALUES:
        payload["status"] = status

    if not payload:
        row = get_one(cr_id)
        if not row:
            raise ValueError("classification_review row not found")
        return row

    res = supabase.table("classification_review").update(payload).eq("id", cr_id).execute()
    if not res.data:
        raise ValueError("classification_review row not found")
    return res.data[0]


def _find_similar_normalized_name(supabase, normalized_name: str, threshold: float = 0.9) -> Optional[str]:
    """If a very similar normalized_name exists in products or rules, return it (for 409 suggestion)."""
    try:
        # Simple substring / prefix check; full pg_trgm would need RPC
        from rapidfuzz import fuzz
        candidates = []
        p = supabase.table("products").select("normalized_name").limit(500).execute()
        for r in (p.data or []):
            n = (r.get("normalized_name") or "").strip()
            if n:
                candidates.append(n)
        r = supabase.table("product_categorization_rules").select("normalized_name").limit(500).execute()
        for row in (r.data or []):
            n = (row.get("normalized_name") or "").strip()
            if n and n not in candidates:
                candidates.append(n)
        best_ratio = 0.0
        best_name = None
        for c in candidates:
            ratio = fuzz.ratio(normalized_name.lower(), c.lower()) / 100.0
            if ratio >= threshold and ratio > best_ratio:
                best_ratio = ratio
                best_name = c
        return best_name
    except Exception as e:
        logger.debug(f"Similarity check failed: {e}")
        return None


def confirm_classification_review(cr_id: str, confirmed_by: str, force_different_name: bool = False) -> Dict[str, Any]:
    """
    Confirm a classification_review row: set status=confirmed, then write to
    product_categorization_rules and products; backfill the source record_item and cascade
    to all other unclassified record_items that match (same normalized_name + store_chain_id).
    So when admin sets a default classification for a product, every "— — —" item that
    matches gets updated to that default. User overrides (already classified) are unchanged.
    If a very similar normalized_name exists and force_different_name is False, returns
    {"similar_to": "..."} and does not write (caller may retry with force_different_name=True).
    """
    supabase = _get_client()
    row = get_one(cr_id)
    if not row:
        raise ValueError("classification_review row not found")
    if row.get("status") == "confirmed":
        return {"message": "already confirmed", "row": row}

    normalized = (row.get("normalized_name") or "").strip()
    category_id = row.get("category_id")
    if not normalized or not category_id:
        raise ValueError("normalized_name and category_id are required before confirm")

    normalized = normalize_name_for_storage(normalized)
    if not normalized:
        raise ValueError("normalized_name is required")

    if not force_different_name:
        similar = _find_similar_normalized_name(supabase, normalized)
        if similar and similar != normalized:
            return {"similar_to": similar, "message": "Similar name exists; use it or confirm with force_different_name"}

    store_chain_id = row.get("store_chain_id")
    # Fallback: get store_chain_id from record_summaries via source record_item
    if not store_chain_id and row.get("source_record_item_id"):
        try:
            ri = supabase.table("record_items").select("receipt_id").eq("id", row["source_record_item_id"]).limit(1).execute()
            if ri.data and ri.data[0].get("receipt_id"):
                rs = supabase.table("record_summaries").select("store_chain_id").eq("receipt_id", ri.data[0]["receipt_id"]).limit(1).execute()
                if rs.data and rs.data[0].get("store_chain_id"):
                    store_chain_id = rs.data[0]["store_chain_id"]
        except Exception:
            pass
    size_qty = row.get("size_quantity")
    if size_qty is not None and str(size_qty).strip():
        try:
            size_qty = round(float(size_qty), 2)
        except (TypeError, ValueError):
            size_qty = None
    else:
        size_qty = None
    size_unit = (row.get("size_unit") or "").strip() or None
    package_type = (row.get("package_type") or "").strip() or None
    match_type = row.get("match_type") or "exact"

    # Receipt date for products.last_seen_date and price_snapshots (from source record_item)
    source_ri_id = row.get("source_record_item_id")
    receipt_date_value = None
    if source_ri_id:
        try:
            ri = supabase.table("record_items").select("receipt_id").eq("id", source_ri_id).limit(1).execute()
            if ri.data and ri.data[0].get("receipt_id"):
                rs = supabase.table("record_summaries").select("receipt_date").eq("receipt_id", ri.data[0]["receipt_id"]).limit(1).execute()
                if rs.data and rs.data[0].get("receipt_date"):
                    rd = rs.data[0]["receipt_date"]
                    receipt_date_value = rd.strftime("%Y-%m-%d") if hasattr(rd, "strftime") else str(rd)[:10]
        except Exception:
            pass

    # Insert or update product_categorization_rules
    # - New: times_matched=1, last_matched_at=now, created_by=confirmed_by
    # - Existing: call update_rule_match_stats to increment times_matched and last_matched_at
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    rule_payload = {
        "normalized_name": normalized,
        "store_chain_id": store_chain_id,
        "category_id": category_id,
        "match_type": match_type,
        "source": "manual",
        "priority": 100,
        "times_matched": 1,
        "last_matched_at": now_utc.isoformat(),
        "created_by": confirmed_by if confirmed_by else None,
    }
    # Check if rule exists (unique on normalized_name, store_chain_id, category_id)
    q = (
        supabase.table("product_categorization_rules")
        .select("id")
        .eq("normalized_name", normalized)
        .eq("category_id", category_id)
    )
    if store_chain_id:
        q = q.eq("store_chain_id", store_chain_id)
    else:
        q = q.is_("store_chain_id", "null")
    existing_rule = q.limit(1).execute()
    if existing_rule.data:
        rule_id = existing_rule.data[0]["id"]
        supabase.rpc("update_rule_match_stats", {"p_rule_id": rule_id}).execute()
    else:
        supabase.table("product_categorization_rules").insert(rule_payload).execute()

    # Insert or update products (unique on normalized_name, size_quantity, size_unit, package_type, store_chain_id)
    product_payload: Dict[str, Any] = {
        "normalized_name": normalized,
        "size_quantity": size_qty,
        "size_unit": size_unit,
        "package_type": package_type,
        "store_chain_id": store_chain_id,
        "category_id": category_id,
        "usage_count": 1,
        "last_seen_date": receipt_date_value,
    }
    q = supabase.table("products").select("id").eq("normalized_name", normalized)
    if size_qty is None:
        q = q.is_("size_quantity", "null")
    else:
        q = q.eq("size_quantity", size_qty)
    if size_unit is None:
        q = q.is_("size_unit", "null")
    else:
        q = q.eq("size_unit", size_unit)
    if package_type is None:
        q = q.is_("package_type", "null")
    else:
        q = q.eq("package_type", package_type)
    if store_chain_id is None:
        q = q.is_("store_chain_id", "null")
    else:
        q = q.eq("store_chain_id", store_chain_id)
    existing = q.limit(1).execute()
    product_id = None
    if existing.data:
        product_id = existing.data[0]["id"]
        # Atomic increment to avoid race when multiple confirms hit the same product
        supabase.rpc(
            "increment_product_usage",
            {
                "p_product_id": product_id,
                "p_category_id": category_id,
                "p_last_seen_date": receipt_date_value,
            },
        ).execute()
    else:
        ins = supabase.table("products").insert(product_payload).execute()
        product_id = ins.data[0]["id"] if ins.data else None

    # Backfill payload for record_items: product_id, product_name_clean, category_id, unit (package_type)
    backfill_ri: Dict[str, Any] = {
        "product_name_clean": normalized,
        "category_id": category_id,
        "unit": package_type or None,
    }
    if product_id:
        backfill_ri["product_id"] = product_id

    # 1) Backfill the source record_item (the one that was in classification_review)
    if source_ri_id:
        supabase.table("record_items").update(backfill_ri).eq("id", source_ri_id).execute()

    # 2) Cascade: update all other unclassified record_items that match (same normalized_name + store_chain)
    #    so that "— — —" items get the new default classification when admin confirms a rule
    try:
        if store_chain_id:
            rs = supabase.table("record_summaries").select("receipt_id").eq("store_chain_id", store_chain_id).execute()
        else:
            rs = supabase.table("record_summaries").select("receipt_id").is_("store_chain_id", "null").execute()
        receipt_ids = [r["receipt_id"] for r in (rs.data or []) if r.get("receipt_id")]
        if not receipt_ids:
            pass
        else:
            # Fetch unclassified record_items for these receipts (batch to avoid too many IDs)
            ids_to_cascade: List[str] = []
            chunk = 200
            for i in range(0, len(receipt_ids), chunk):
                sub = receipt_ids[i : i + chunk]
                items = (
                    supabase.table("record_items")
                    .select("id, product_name")
                    .in_("receipt_id", sub)
                    .is_("category_id", "null")
                    .execute()
                )
                for row in (items.data or []):
                    raw = (row.get("product_name") or "").strip()
                    if not raw:
                        continue
                    if normalize_name_for_storage(raw) == normalized:
                        ids_to_cascade.append(row["id"])
            if ids_to_cascade:
                # Exclude source so we don't double-update (already done above)
                if source_ri_id:
                    ids_to_cascade = [x for x in ids_to_cascade if x != source_ri_id]
                if ids_to_cascade:
                    for uid in ids_to_cascade:
                        supabase.table("record_items").update(backfill_ri).eq("id", uid).execute()
                    logger.info(
                        f"Cascade: updated {len(ids_to_cascade)} unclassified record_items to category_id={category_id} (normalized_name={normalized!r}, store_chain_id={store_chain_id!r})"
                    )
    except Exception as e:
        logger.warning(f"Cascade unclassified record_items after confirm failed: {e}")

    # Refresh price_snapshots for the receipt's date so new product_id gets aggregated
    if source_ri_id and product_id and receipt_date_value:
        try:
            supabase.rpc("aggregate_prices_for_date", {"target_date": receipt_date_value}).execute()
            logger.debug(f"Refreshed price_snapshots for date {receipt_date_value}")
        except Exception as e:
            logger.warning(f"Failed to refresh price_snapshots after confirm: {e}")

    # Mark CR row as confirmed
    update_payload: Dict[str, Any] = {
        "status": "confirmed",
        "confirmed_at": now_utc.isoformat(),
        "confirmed_by": confirmed_by,
    }
    if not confirmed_by:
        update_payload.pop("confirmed_by", None)  # FK requires valid user id or NULL
    supabase.table("classification_review").update(update_payload).eq("id", cr_id).execute()

    updated = get_one(cr_id)
    return {"message": "confirmed", "row": updated}
