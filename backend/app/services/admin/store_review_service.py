"""
Admin Store Review service.

CRUD and approve for store_candidates; approve creates store_chains and/or store_locations.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services.database.supabase_client import (
    _get_client,
    backfill_record_summaries_for_store_chain,
    backfill_record_summaries_for_store_location,
)

logger = logging.getLogger(__name__)

STATUS_VALUES = frozenset({"pending", "approved", "rejected"})


def _normalize_chain_name(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "_") or ""


def list_store_candidates(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    List store_candidates with optional status filter.
    Returns (rows with suggested_chain_name, total count).
    """
    supabase = _get_client()
    q = supabase.table("store_candidates").select(
        "id, raw_name, normalized_name, source, receipt_id, suggested_chain_id, suggested_location_id, "
        "confidence_score, status, rejection_reason, metadata, created_at, reviewed_at, reviewed_by",
        count="exact",
    )
    if status and status in STATUS_VALUES:
        q = q.eq("status", status)
    q = q.order("created_at", desc=True).range(offset, offset + limit - 1)
    res = q.execute()
    rows = list(res.data or [])
    total = res.count if hasattr(res, "count") and res.count is not None else len(rows)

    # Enrich with suggested chain name
    chain_ids = {r["suggested_chain_id"] for r in rows if r.get("suggested_chain_id")}
    chains = {}
    if chain_ids:
        ch = supabase.table("store_chains").select("id, name").in_("id", list(chain_ids)).execute()
        for c in (ch.data or []):
            chains[c["id"]] = c.get("name")
    for r in rows:
        r["suggested_chain_name"] = chains.get(r["suggested_chain_id"]) if r.get("suggested_chain_id") else None
        # Flatten address from metadata for display
        meta = r.get("metadata") or {}
        addr = meta.get("address") or {}
        r["address_display"] = (
            addr.get("full_address")
            or ", ".join(filter(None, [addr.get("address1"), addr.get("city"), addr.get("state"), addr.get("zipcode"), addr.get("country")]))
            or None
        )

    return rows, total


def get_one(candidate_id: str) -> Optional[Dict[str, Any]]:
    """Get a single store_candidates row by id."""
    supabase = _get_client()
    res = supabase.table("store_candidates").select("*").eq("id", candidate_id).limit(1).execute()
    if not res.data:
        return None
    return res.data[0]


def update_store_candidate(
    candidate_id: str,
    raw_name: Optional[str] = None,
    normalized_name: Optional[str] = None,
    status: Optional[str] = None,
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """PATCH a store_candidates row."""
    supabase = _get_client()
    payload: Dict[str, Any] = {}
    if raw_name is not None:
        payload["raw_name"] = (raw_name or "").strip() or None
    if normalized_name is not None:
        payload["normalized_name"] = _normalize_chain_name(normalized_name) or None
    if status is not None and status in STATUS_VALUES:
        payload["status"] = status
    if rejection_reason is not None:
        payload["rejection_reason"] = (rejection_reason or "").strip() or None

    if not payload:
        row = get_one(candidate_id)
        if not row:
            raise ValueError("store_candidates row not found")
        return row

    res = supabase.table("store_candidates").update(payload).eq("id", candidate_id).execute()
    if not res.data:
        raise ValueError("store_candidates row not found")
    return res.data[0]


def _normalize_country_code(code: Optional[str]) -> Optional[str]:
    """Use US/CA only; never USA or CANADA for store_location.country_code."""
    if not code or not isinstance(code, str):
        return (code or "").strip() or None
    s = code.strip().upper()
    if s in ("USA", "UNITED STATES", "US"):
        return "US"
    if s in ("CANADA", "CA"):
        return "CA"
    return code.strip() or None


def approve_store_candidate(
    candidate_id: str,
    approved_by: str,
    *,
    chain_name: Optional[str] = None,
    add_as_location_of_chain_id: Optional[str] = None,
    location_name: Optional[str] = None,
    address_line1: Optional[str] = None,
    address_line2: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
    country_code: Optional[str] = None,
    phone: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Approve a store_candidates row:
    - If add_as_location_of_chain_id: create only store_location under that chain.
    - Else: create new store_chain, then create store_location under it.
    Then set candidate status=approved, reviewed_at, reviewed_by.
    """
    supabase = _get_client()
    row = get_one(candidate_id)
    if not row:
        raise ValueError("store_candidates row not found")
    if row.get("status") == "approved":
        return {"message": "already approved", "row": row}

    now_utc = datetime.now(timezone.utc)
    meta = row.get("metadata") or {}
    addr = meta.get("address") or {}

    # Resolve chain: either use existing or create new
    if add_as_location_of_chain_id:
        chain_id = add_as_location_of_chain_id
        chain = supabase.table("store_chains").select("id, name").eq("id", chain_id).limit(1).execute()
        if not chain.data:
            raise ValueError("store_chain not found")
    else:
        # Create new store_chain
        name = (chain_name or row.get("raw_name") or "").strip()
        if not name:
            raise ValueError("chain_name is required when creating new chain")
        normalized = _normalize_chain_name(name)
        if not normalized:
            raise ValueError("chain_name is required")
        # Avoid duplicate normalized_name
        existing = supabase.table("store_chains").select("id").eq("normalized_name", normalized).limit(1).execute()
        if existing.data:
            chain_id = existing.data[0]["id"]
            logger.info(f"Store candidate approved as existing chain: {normalized} -> {chain_id}")
        else:
            ins = supabase.table("store_chains").insert({
                "name": name,
                "normalized_name": normalized,
                "is_active": True,
            }).execute()
            if not ins.data:
                raise ValueError("Failed to create store_chain")
            chain_id = ins.data[0]["id"]
            logger.info(f"Created store_chain: {chain_id} ({name})")

    # Create store_location
    loc_name = (location_name or row.get("raw_name") or "").strip() or "Store"
    loc_payload: Dict[str, Any] = {
        "chain_id": chain_id,
        "name": loc_name,
        "is_active": True,
    }
    if address_line1 is not None:
        loc_payload["address_line1"] = (address_line1 or "").strip() or None
    if address_line2 is not None:
        loc_payload["address_line2"] = (address_line2 or "").strip() or None
    if city is not None:
        loc_payload["city"] = (city or "").strip() or None
    if state is not None:
        loc_payload["state"] = (state or "").strip() or None
    if zip_code is not None:
        loc_payload["zip_code"] = (zip_code or "").strip() or None
    if country_code is not None:
        loc_payload["country_code"] = _normalize_country_code(country_code)
    if phone is not None:
        loc_payload["phone"] = (phone or "").strip() or None
    # Fallback to metadata address if not provided
    if loc_payload.get("address_line1") is None and addr.get("address1"):
        loc_payload["address_line1"] = addr.get("address1")
    if loc_payload.get("city") is None and addr.get("city"):
        loc_payload["city"] = addr.get("city")
    if loc_payload.get("state") is None and addr.get("state"):
        loc_payload["state"] = addr.get("state")
    if loc_payload.get("zip_code") is None and addr.get("zipcode"):
        loc_payload["zip_code"] = addr.get("zipcode")
    if loc_payload.get("country_code") is None and addr.get("country"):
        loc_payload["country_code"] = _normalize_country_code(addr.get("country"))

    loc_res = supabase.table("store_locations").insert(loc_payload).execute()
    new_location_row = loc_res.data[0] if loc_res.data else None
    new_location_id = new_location_row.get("id") if new_location_row else None
    logger.info(f"Created store_location for chain {chain_id}: {loc_name} (id={new_location_id})")

    # Mark candidate as approved
    update_payload: Dict[str, Any] = {
        "status": "approved",
        "reviewed_at": now_utc.isoformat(),
        "reviewed_by": approved_by,
        "rejection_reason": None,
    }
    if not approved_by:
        update_payload.pop("reviewed_by", None)
    supabase.table("store_candidates").update(update_payload).eq("id", candidate_id).execute()

    # Backfill record_summaries: (1) set store_chain_id where store_name matches and chain_id was null
    try:
        chain_row = supabase.table("store_chains").select("name").eq("id", chain_id).limit(1).execute()
        if chain_row.data and chain_row.data[0].get("name"):
            n = backfill_record_summaries_for_store_chain(chain_id, chain_row.data[0]["name"])
            if n:
                logger.info(f"Backfilled {n} record_summaries with new store_chain_id after approval")
    except Exception as e:
        logger.warning(f"Backfill record_summaries after store approval: {e}")

    # (2) 门店确认后：激活并更新所有与该地址关联的小票（store_location_id + 规范地址/店名）
    if new_location_id and new_location_row:
        try:
            chain_name_for_loc = chain_row.data[0].get("name") if chain_row.data else None
            n_loc = backfill_record_summaries_for_store_location(chain_id, new_location_id, new_location_row, chain_name=chain_name_for_loc)
            if n_loc:
                logger.info(f"Backfilled {n_loc} record_summaries with new store_location_id (address match) after approval")
        except Exception as e:
            logger.warning(f"Backfill record_summaries for store_location after approval: {e}")

    updated = get_one(candidate_id)
    return {"message": "approved", "row": updated, "chain_id": chain_id}


def reject_store_candidate(
    candidate_id: str,
    reviewed_by: str,
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Set store_candidates row to status=rejected."""
    supabase = _get_client()
    row = get_one(candidate_id)
    if not row:
        raise ValueError("store_candidates row not found")
    now_utc = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "status": "rejected",
        "reviewed_at": now_utc.isoformat(),
        "reviewed_by": reviewed_by,
        "rejection_reason": (rejection_reason or "").strip() or None,
    }
    if not reviewed_by:
        payload.pop("reviewed_by", None)
    supabase.table("store_candidates").update(payload).eq("id", candidate_id).execute()
    return {"message": "rejected", "row": get_one(candidate_id)}


def list_store_chains(active_only: bool = True) -> List[Dict[str, Any]]:
    """List store_chains for dropdown (e.g. 'add as location of')."""
    supabase = _get_client()
    q = supabase.table("store_chains").select("id, name, normalized_name").order("name")
    if active_only:
        q = q.eq("is_active", True)
    res = q.execute()
    return list(res.data or [])
