"""
Supabase client for storing receipt OCR data and parsed receipts.

Note: The database schema is defined in database/001_schema_v2.sql
"""
from supabase import create_client, Client
from ...config import settings
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from datetime import datetime
import logging
import json
import re

from rapidfuzz import fuzz

from ..standardization.product_normalizer import normalize_name_for_storage
from ...processors.enrichment.payment_types import normalize_payment_type

logger = logging.getLogger(__name__)


def _store_name_to_title_case(name: Optional[str]) -> Optional[str]:
    """
    Normalize store name: Title Case but preserve T&T (second T) and US/UK etc.
    E.g. "T&T Supermarket US" stays as-is; "t&t supermarket us" -> "T&T Supermarket US".
    """
    if not name or not isinstance(name, str):
        return name
    s = name.strip()
    if not s:
        return name

    def title_word(w: str) -> str:
        if not w:
            return w
        # 2-letter (US, UK) -> all caps
        if len(w) == 2 and w.isalpha():
            return w.upper()
        # 3-letter (USA, UAE) -> all caps
        if len(w) == 3 and w.isalpha():
            return w.upper()
        # Contains & (e.g. T&T): capitalize first letter of each part
        if "&" in w:
            parts = w.split("&")
            return "&".join(
                (p[0].upper() + p[1:].lower()) if len(p) > 0 else p for p in parts
            )
        return w[0].upper() + w[1:].lower() if len(w) > 0 else w

    return " ".join(title_word(w) for w in s.split())


def _purchase_time_to_24h(value: Optional[str]) -> Optional[str]:
    """Normalize purchase_time to 24-hour HH:MM (e.g. '03:34 PM' -> '15:34', '15:34:00' -> '15:34')."""
    if not value or not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    # Already HH:MM or HH:MM:SS (24h)
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?\s*$", s)
    if m:
        h, min_ = int(m.group(1)), m.group(2)
        if 0 <= h <= 23 and len(min_) == 2:
            return f"{h:02d}:{min_}"
    # 12h with AM/PM
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)\s*$", s, re.I)
    if m:
        h, min_, ampm = int(m.group(1)), m.group(2), m.group(3).upper()
        if ampm == "PM" and h != 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
        return f"{h:02d}:{min_}"
    return value


def _normalize_card_last4(raw: Optional[str]) -> Optional[str]:
    """Extract up to 4 digits from card_last4 (e.g. '****9463' or '9463' -> '9463'). Returns None if < 4 digits."""
    if not raw:
        return None
    digits = "".join(c for c in str(raw).strip() if c.isdigit())
    return digits[-4:] if len(digits) >= 4 else None


def _normalize_address_for_backfill(s: Optional[str]) -> str:
    """
    Normalize address for fuzzy comparison: strip Suite/Unit/Ste, trailing country,
    then expand abbreviations (PK->park, RD->road, HWY->highway, etc.) so "FANSHAWE PK RD" matches "Fanshawe Park Rd".
    """
    if not s or not isinstance(s, str):
        return ""
    raw = s.replace("\n", " ").replace("\r", " ").strip()
    if not raw:
        return ""
    one = " ".join(raw.lower().split())
    # Remove unit/suite/ste/apt/# number
    one = re.sub(
        r"[,]?\s*(?:suite|unit|ste|apt|#)\s*-?\s*[\d\w-]+",
        " ",
        one,
        flags=re.IGNORECASE,
    )
    # Strip trailing country tokens
    one = re.sub(r"\b(?:us|usa|ca|canada)\s*$", "", one, flags=re.IGNORECASE)
    one = " ".join(one.split())
    # Expand abbreviations (PK->park, RD->road, HWY->highway, etc.) so receipt and DB match
    from ...processors.enrichment.address_abbreviations import expand_address_abbreviations
    return expand_address_abbreviations(one)

# Singleton Supabase client
_supabase: Optional[Client] = None


def _get_client() -> Client:
    """Get or create the Supabase client."""
    global _supabase
    if _supabase is None:
        if not settings.supabase_url or not settings.supabase_anon_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment"
            )
        
        # Use service role key if available, otherwise use anon key
        key = settings.supabase_service_role_key or settings.supabase_anon_key
        _supabase = create_client(settings.supabase_url, key)
        logger.info("Supabase client initialized")
    
    return _supabase


def get_store_chains_with_receipt_counts(active_only: bool = True) -> List[Dict[str, Any]]:
    """
    Return active store chains with receipt count for each.
    Used by public homepage to show "samples we have" and tally per store.
    Count = receipts already linked (store_chain_id = chain) + receipts not yet linked
    but with store_name matching this chain (so the number reflects "receipts we have from this store").
    """
    supabase = _get_client()
    q = supabase.table("store_chains").select("id, name, normalized_name").order("name")
    if active_only:
        q = q.eq("is_active", True)
    res = q.execute()
    chains = list(res.data or [])
    # Count unlinked receipts by store_name (store_chain_id IS NULL); then assign to chain by prefix match
    unlinked_by_name: Dict[str, int] = {}
    try:
        unlinked = (
            supabase.table("record_summaries")
            .select("store_name")
            .is_("store_chain_id", "null")
            .execute()
        )
        for row in unlinked.data or []:
            name = (row.get("store_name") or "").strip().lower()
            if name:
                unlinked_by_name[name] = unlinked_by_name.get(name, 0) + 1
    except Exception as e:
        logger.warning(f"Failed to count unlinked receipts by store_name: {e}")

    def _store_name_matches_chain(store_name_lower: str, norm: str, name_lower: str) -> bool:
        if not store_name_lower:
            return False
        for key in (norm, name_lower):
            if not key:
                continue
            if store_name_lower == key:
                return True
            if store_name_lower.startswith(key + " ") or store_name_lower.startswith(key + "#") or store_name_lower.startswith(key + "'"):
                return True
        return False

    # Assign each unlinked (store_name, count) to the longest matching chain to avoid double-count
    chain_unlinked: Dict[str, int] = {str(c.get("id")): 0 for c in chains if c.get("id")}
    chains_by_norm_len = sorted(
        [c for c in chains if c.get("id") and (c.get("normalized_name") or c.get("name"))],
        key=lambda c: len((c.get("normalized_name") or c.get("name") or "").strip()),
        reverse=True,
    )
    for store_name_lower, cnt in unlinked_by_name.items():
        for c in chains_by_norm_len:
            norm = (c.get("normalized_name") or "").strip().lower()
            name_lower = (c.get("name") or "").strip().lower()
            if _store_name_matches_chain(store_name_lower, norm, name_lower):
                cid = str(c.get("id"))
                chain_unlinked[cid] = chain_unlinked.get(cid, 0) + cnt
                break

    out: List[Dict[str, Any]] = []
    for c in chains:
        cid = c.get("id")
        if not cid:
            continue
        try:
            count_res = (
                supabase.table("record_summaries")
                .select("id", count="exact")
                .eq("store_chain_id", cid)
                .limit(1)
                .execute()
            )
            linked = getattr(count_res, "count", None)
            if linked is None:
                linked = len(count_res.data) if count_res.data else 0
            else:
                linked = int(linked) if linked is not None else 0
        except Exception as e:
            logger.warning(f"Failed to count receipts for store_chain {cid}: {e}")
            linked = 0
        unlinked = chain_unlinked.get(str(cid), 0)
        total = linked + unlinked
        out.append({
            "id": str(cid),
            "name": c.get("name") or "",
            "normalized_name": c.get("normalized_name") or "",
            "receipt_count": total,
        })
    return out


# US state full name -> 2-letter code (for normalizing store_locations.state)
_US_STATE_TO_CODE: Dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
# Canadian province/territory full name -> 2-letter code
_CA_PROVINCE_TO_CODE: Dict[str, str] = {
    "alberta": "AB", "british columbia": "BC", "manitoba": "MB", "new brunswick": "NB",
    "newfoundland and labrador": "NL", "nl": "NL", "nova scotia": "NS", "nunavut": "NU",
    "ontario": "ON", "prince edward island": "PE", "quebec": "QC", "saskatchewan": "SK",
    "northwest territories": "NT", "yukon": "YT", "yukon territory": "YT",
}

# 2-letter code -> full name (single source of truth for location display names)
US_CODE_TO_NAME: Dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
CA_CODE_TO_NAME: Dict[str, str] = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}


def _parse_state_country_from_address(store_address: Optional[str]) -> Optional[Tuple[str, str]]:
    """
    Try to extract (country_code, state_code) from raw store_address for receipts without store_location_id.
    Returns ("US", "WA") or ("CA", "BC") etc., or None if not detected.
    """
    if not store_address or not isinstance(store_address, str):
        return None
    s = store_address.replace("\n", " ").strip()
    if not s:
        return None
    s_lower = s.lower()
    # Full names (longer first to avoid "New" matching before "New Jersey")
    full_names_ca = [
        ("british columbia", "BC"), ("new brunswick", "NB"), ("newfoundland and labrador", "NL"),
        ("nova scotia", "NS"), ("prince edward island", "PE"), ("northwest territories", "NT"),
        ("yukon territory", "YT"), ("alberta", "AB"), ("manitoba", "MB"), ("ontario", "ON"),
        ("quebec", "QC"), ("saskatchewan", "SK"), ("nunavut", "NU"), ("yukon", "YT"),
    ]
    for name, code in full_names_ca:
        if name in s_lower:
            return ("CA", code)
    full_names_us = [
        ("district of columbia", "DC"), ("new hampshire", "NH"), ("new jersey", "NJ"),
        ("new mexico", "NM"), ("new york", "NY"), ("north carolina", "NC"), ("north dakota", "ND"),
        ("rhode island", "RI"), ("south carolina", "SC"), ("south dakota", "SD"),
        ("west virginia", "WV"), ("washington", "WA"), ("california", "CA"), ("texas", "TX"),
    ]
    for name, code in full_names_us:
        if name in s_lower:
            return ("US", code)
    # Single-word state names (avoid "in" in "indiana")
    for name, code in _US_STATE_TO_CODE.items():
        if name in ("new", "north", "south", "west", "district", "rhode"):
            continue
        if len(name) <= 3:
            continue
        if name in s_lower:
            return ("US", code)
    # 2-letter codes with word boundary (e.g. ", WA 98101" or " Vancouver, BC")
    for code in list(US_CODE_TO_NAME.keys()) + list(CA_CODE_TO_NAME.keys()):
        if re.search(r"\b" + re.escape(code) + r"\b", s, re.I):
            if code in US_CODE_TO_NAME:
                return ("US", code)
            if code in CA_CODE_TO_NAME:
                return ("CA", code)
    return None


def _normalize_state_code(country_code: str, state_raw: Optional[str]) -> Optional[str]:
    """Return 2-letter state/province code for US/CA, or None."""
    if not state_raw or not isinstance(state_raw, str):
        return None
    s = state_raw.strip()
    if not s:
        return None
    s_lower = s.lower()
    if country_code == "US":
        if len(s) == 2:
            return s.upper()
        return _US_STATE_TO_CODE.get(s_lower) or (s.upper() if len(s) == 2 else None)
    if country_code == "CA":
        if len(s) == 2:
            return s.upper()
        return _CA_PROVINCE_TO_CODE.get(s_lower) or (s.upper() if len(s) == 2 else None)
    return s.upper() if len(s) == 2 else None


def get_location_stats() -> List[Dict[str, Any]]:
    """
    Return receipt counts and distinct store counts per US state and Canadian province.
    Same source as store stats: (1) receipts with store_location_id use store_locations state/country;
    (2) receipts without store_location_id but with store_address get state/country parsed from address
    so the map total matches the store section.
    Returns: list of { country_code, state_code, state_display_name, receipt_count, store_count }.
    """
    supabase = _get_client()
    receipt_agg: Dict[Tuple[str, str], int] = {}
    store_agg: Dict[Tuple[str, str], set] = {}

    # (1) Receipts with store_location_id — use store_locations state/country
    try:
        res = (
            supabase.table("record_summaries")
            .select("store_location_id, store_locations(state, country_code)")
            .not_.is_("store_location_id", "null")
            .execute()
        )
        for row in res.data or []:
            loc = row.get("store_locations") or row.get("store_location")
            if not isinstance(loc, dict):
                continue
            country = (loc.get("country_code") or "US").strip().upper()
            if country not in ("US", "CA"):
                continue
            state_raw = loc.get("state")
            code = _normalize_state_code(country, state_raw)
            if not code:
                continue
            key = (country, code)
            receipt_agg[key] = receipt_agg.get(key, 0) + 1
            loc_id = row.get("store_location_id")
            if loc_id:
                if key not in store_agg:
                    store_agg[key] = set()
                store_agg[key].add(str(loc_id))
    except Exception as e:
        logger.warning(f"Failed to get location stats (linked): {e}")

    # (2) Receipts without store_location_id but with store_address — parse address for state/country
    try:
        unlinked = (
            supabase.table("record_summaries")
            .select("id, store_address")
            .is_("store_location_id", "null")
            .execute()
        )
        for row in unlinked.data or []:
            addr = row.get("store_address")
            parsed = _parse_state_country_from_address(addr)
            if not parsed:
                continue
            country, code = parsed
            key = (country, code)
            receipt_agg[key] = receipt_agg.get(key, 0) + 1
    except Exception as e:
        logger.warning(f"Failed to get location stats (unlinked by address): {e}")

    out = []
    for (c, s) in sorted(set(receipt_agg.keys()) | set(store_agg.keys())):
        display_name = (US_CODE_TO_NAME.get(s) if c == "US" else CA_CODE_TO_NAME.get(s)) or s
        out.append({
            "country_code": c,
            "state_code": s,
            "state_display_name": display_name,
            "receipt_count": receipt_agg.get((c, s), 0),
            "store_count": len(store_agg.get((c, s), set())),
        })
    return out


def _parse_rpc_count(res: Any, rpc_name: str, default: int = 0) -> int:
    """Parse integer return value from a Supabase RPC response (e.g. sync_record_items_batch_update)."""
    if res.data is None:
        return default
    if isinstance(res.data, int):
        return res.data
    if isinstance(res.data, list) and len(res.data) > 0:
        first = res.data[0]
        if isinstance(first, dict):
            return int(first.get(rpc_name, default) or default)
        return int(first) if first is not None else default
    return default


# User tier constants (integer in DB: higher = more privilege)
USER_CLASS_FREE = 0
USER_CLASS_PREMIUM = 2
USER_CLASS_ADMIN = 7
USER_CLASS_SUPER_ADMIN = 9


def get_user_class(user_id: str) -> int:
    """
    Get user_class for a user (integer tier: 0=free, 2=premium, 7=admin, 9=super_admin).
    Used for rate limit bypass and duplicate-upload allowance.
    """
    if not user_id:
        return USER_CLASS_FREE
    supabase = _get_client()
    try:
        res = supabase.table("users").select("user_class").eq("id", user_id).limit(1).execute()
        if res.data and len(res.data) > 0:
            val = res.data[0].get("user_class")
            if val is not None:
                result = int(val)
                logger.debug("get_user_class(%s) = %s (raw=%r)", user_id, result, val)
                return result
            logger.warning("get_user_class(%s): user_class is None in DB row", user_id)
        else:
            logger.warning("get_user_class(%s): no rows returned from users table", user_id)
    except Exception as e:
        logger.warning("get_user_class(%s) failed: %s", user_id, e, exc_info=True)
    return USER_CLASS_FREE


def check_duplicate_by_hash(
    file_hash: str,
    user_id: str
) -> Optional[str]:
    """
    Check if a receipt with the same file hash already exists for this user.
    
    Args:
        file_hash: SHA256 hash of the file
        user_id: User ID (UUID string)
        
    Returns:
        Existing receipt_id if duplicate found, None otherwise
    """
    if not file_hash or not user_id:
        return None
    
    supabase = _get_client()
    
    try:
        res = supabase.table("receipt_status").select("id, uploaded_at, current_status").eq(
            "user_id", user_id
        ).eq("file_hash", file_hash).limit(1).execute()
        
        if res.data and len(res.data) > 0:
            existing_receipt = res.data[0]
            logger.info(
                f"Duplicate receipt found: file_hash={file_hash[:16]}..., "
                f"existing_receipt_id={existing_receipt['id']}, "
                f"uploaded_at={existing_receipt.get('uploaded_at')}, "
                f"status={existing_receipt.get('current_status')}"
            )
            return existing_receipt["id"]
        
        return None
    except Exception as e:
        logger.warning(f"Failed to check duplicate by hash: {e}")
        # Don't raise - allow processing to continue if check fails
        return None


def create_receipt(
    user_id: str,
    raw_file_url: Optional[str] = None,
    file_hash: Optional[str] = None,
    pipeline_version: str = "legacy_a",
) -> str:
    """
    Create a new receipt record in receipt_status table.
    
    Args:
        user_id: User identifier (UUID string)
        raw_file_url: Optional URL to the uploaded file
        file_hash: Optional SHA256 hash of the file for duplicate detection
        pipeline_version: Pipeline used ('legacy_a' or 'vision_b')
        
    Returns:
        receipt_id (UUID string)
    """
    if not user_id:
        raise ValueError("user_id is required")
    
    supabase = _get_client()
    
    payload = {
        "user_id": user_id,
        "current_status": "failed",  # Start with "failed", will be updated to "success" when processing completes
        "current_stage": "ocr",  # Start with ocr, will be updated during processing
        "raw_file_url": raw_file_url,
        "file_hash": file_hash,
        "pipeline_version": pipeline_version,
    }
    
    logger.info(f"[DEBUG] Attempting to insert receipt with payload: {payload}")
    
    try:
        res = supabase.table("receipt_status").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to create receipt, no data returned")
        receipt_id = res.data[0]["id"]
        logger.info(f"Created receipt record: {receipt_id}")
        return receipt_id
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[DEBUG] Insert failed with error: {type(e).__name__}")
        logger.error(f"[DEBUG] Error message: {error_msg}")
        logger.error(f"[DEBUG] Payload was: {payload}")
        # Check if it's a unique constraint violation (duplicate file_hash)
        if "unique" in error_msg.lower() or "duplicate" in error_msg.lower():
            logger.warning(
                f"Duplicate receipt detected (unique constraint): file_hash={file_hash[:16] if file_hash else 'None'}..., "
                f"user_id={user_id}. This receipt has already been uploaded."
            )
            # Try to find the existing receipt
            if file_hash:
                existing_id = check_duplicate_by_hash(file_hash, user_id)
                if existing_id:
                    raise ValueError(f"Duplicate receipt: This file has already been uploaded (receipt_id={existing_id})")
        
        logger.error(
            f"Failed to create receipt: {type(e).__name__}: {error_msg}. "
            f"user_id={user_id}. "
            "Common causes: "
            "1. user_id does not exist in users table (foreign key constraint violation), "
            "2. user_id is not a valid UUID format, "
            "3. Duplicate file_hash (same file uploaded twice), "
            "4. Database connection or permission issue."
        )
        raise


def save_processing_run(
    receipt_id: str,
    stage: str,
    model_provider: Optional[str],
    model_name: Optional[str],
    model_version: Optional[str],
    input_payload: Dict[str, Any],
    output_payload: Dict[str, Any],
    output_schema_version: Optional[str],
    status: str,
    error_message: Optional[str] = None
) -> str:
    """
    Save a processing run to receipt_processing_runs table.
    
    Args:
        receipt_id: Receipt ID (UUID string)
        stage: Processing stage ('ocr', 'llm', 'manual')
        model_provider: Model provider (e.g., 'google_documentai', 'gemini', 'openai')
        model_name: Model name (e.g., 'gpt-4o-mini', 'gemini-1.5-flash')
        model_version: Model version (e.g., '2024-01-01')
        input_payload: Input data (JSONB)
        output_payload: Output data (JSONB)
        output_schema_version: Output schema version
        status: Processing status ('pass' or 'fail')
        error_message: Optional error message if status is 'fail'
        
    Returns:
        run_id (UUID string)
    """
    if stage not in (
        'ocr', 'llm', 'manual', 'rule_based_cleaning',
        'vision_primary', 'vision_store_specific', 'vision_escalation', 'shadow_legacy',
    ):
        raise ValueError(f"Invalid stage: {stage}")
    if status not in ('pass', 'fail'):
        raise ValueError(f"Invalid status: {status}")
    
    supabase = _get_client()
    
    # Extract validation_status from output_payload for LLM stage records
    validation_status = None
    if stage == "llm" and output_payload:
        metadata = output_payload.get("_metadata", {})
        validation_status = metadata.get("validation_status")
        # Ensure validation_status is one of the valid values
        if validation_status and validation_status not in ("pass", "needs_review", "unknown"):
            logger.warning(f"Invalid validation_status '{validation_status}', setting to 'unknown'")
            validation_status = "unknown"
    
    payload = {
        "receipt_id": receipt_id,
        "stage": stage,
        "model_provider": model_provider,
        "model_name": model_name,
        "model_version": model_version,
        "input_payload": input_payload,
        "output_payload": output_payload,
        "output_schema_version": output_schema_version,
        "status": status,
        "error_message": error_message,
        "validation_status": validation_status,  # Add validation_status field
    }
    
    try:
        res = supabase.table("receipt_processing_runs").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to save processing run, no data returned")
        run_id = res.data[0]["id"]
        logger.info(f"Saved processing run: {run_id} (stage={stage}, status={status})")
        return run_id
    except Exception as e:
        logger.error(f"Failed to save processing run: {e}")
        raise


def update_receipt_status(
    receipt_id: str,
    current_status: str,
    current_stage: str
) -> None:
    """
    Update receipt current_status and current_stage.
    
    Args:
        receipt_id: Receipt ID (UUID string)
        current_status: New status ('success', 'failed', 'needs_review')
        current_stage: New stage ('ocr', 'llm_primary', 'llm_fallback', 'manual')
    """
    if current_status not in ('success', 'failed', 'needs_review'):
        raise ValueError(f"Invalid status: {current_status}")
    if current_stage not in (
        'ocr', 'llm_primary', 'llm_fallback', 'manual',
        'rejected_not_receipt', 'pending_receipt_confirm',
        'vision_primary', 'vision_store_specific', 'vision_escalation',
    ):
        raise ValueError(f"Invalid stage: {current_stage}")
    
    supabase = _get_client()
    
    try:
        supabase.table("receipt_status").update({
            "current_status": current_status,
            "current_stage": current_stage,
        }).eq("id", receipt_id).execute()
        logger.info(f"Updated receipt {receipt_id}: status={current_status}, stage={current_stage}")
    except Exception as e:
        logger.error(f"Failed to update receipt status: {e}")
        raise


def update_receipt_file_url(
    receipt_id: str,
    raw_file_url: str
) -> None:
    """
    Update receipt raw_file_url.
    
    Args:
        receipt_id: Receipt ID (UUID string)
        raw_file_url: File URL or path
    """
    supabase = _get_client()
    
    try:
        supabase.table("receipt_status").update({
            "raw_file_url": raw_file_url,
        }).eq("id", receipt_id).execute()
        logger.info(f"Updated receipt {receipt_id}: raw_file_url={raw_file_url}")
    except Exception as e:
        logger.error(f"Failed to update receipt file URL: {e}")
        raise


def save_non_receipt_reject(
    user_id: Optional[str],
    file_hash: Optional[str],
    image_path: Optional[str],
    reason: str,
    ocr_text_snippet: Optional[str] = None,
) -> None:
    """
    Save a rejected upload (failed receipt-like validation) for debug and filter tuning.
    Table: non_receipt_rejects (see 043_non_receipt_rejects.sql).
    """
    supabase = _get_client()
    try:
        supabase.table("non_receipt_rejects").insert({
            "user_id": user_id,
            "file_hash": file_hash,
            "image_path": image_path,
            "reason": reason,
            "ocr_text_snippet": (ocr_text_snippet[:5000] if ocr_text_snippet else None),
        }).execute()
        logger.info(f"Saved non_receipt_reject: user_id={user_id}, reason={reason[:80]}...")
    except Exception as e:
        logger.warning(f"Failed to save non_receipt_reject: {e}")


def append_workflow_step(
    receipt_id: str,
    step_name: str,
    result: str,
    run_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append one workflow step for a receipt (for View workflow debug). Uses next sequence.
    Table: receipt_workflow_steps (see 045_receipt_workflow_steps.sql).
    """
    supabase = _get_client()
    try:
        r = supabase.table("receipt_workflow_steps").select("sequence").eq("receipt_id", receipt_id).order("sequence", desc=True).limit(1).execute()
        next_seq = (r.data[0]["sequence"] + 1) if r.data else 0
        supabase.table("receipt_workflow_steps").insert({
            "receipt_id": receipt_id,
            "sequence": next_seq,
            "step_name": step_name,
            "result": result,
            "run_id": run_id,
            "details": details,
        }).execute()
    except Exception as e:
        logger.warning(f"Failed to append workflow step: {e}")


def get_receipt_workflow_steps(receipt_id: str) -> List[Dict[str, Any]]:
    """Get ordered workflow steps for a receipt (for View workflow API)."""
    supabase = _get_client()
    try:
        r = supabase.table("receipt_workflow_steps").select("*").eq("receipt_id", receipt_id).order("sequence", desc=False).execute()
        return list(r.data or [])
    except Exception as e:
        logger.warning(f"Failed to get workflow steps: {e}")
        return []


def check_user_locked(user_id: str) -> tuple:
    """
    Check if user is locked (3 strikes in 1h -> 12h lock).
    Returns (is_locked: bool, locked_until: Optional[datetime]).
    """
    supabase = _get_client()
    try:
        r = supabase.table("user_lock").select("locked_until").eq("user_id", user_id).limit(1).execute()
        if not r.data:
            return False, None
        locked_until = r.data[0].get("locked_until")
        if locked_until:
            from datetime import datetime, timezone
            until = locked_until if hasattr(locked_until, "replace") else datetime.fromisoformat(str(locked_until).replace("Z", "+00:00"))
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < until:
                return True, until
        return False, None
    except Exception as e:
        logger.warning(f"Failed to check user lock: {e}")
        return False, None


def record_strike(user_id: str, receipt_id: Optional[str] = None) -> None:
    """Record one strike for user (e.g. user confirmed receipt but Vision+TxtOpenAI said not receipt)."""
    supabase = _get_client()
    try:
        supabase.table("user_strikes").insert({
            "user_id": user_id,
            "receipt_id": receipt_id,
        }).execute()
    except Exception as e:
        logger.warning(f"Failed to record strike: {e}")


def count_strikes_in_last_hour(user_id: str) -> int:
    """Count strikes in the last 60 minutes for user."""
    supabase = _get_client()
    try:
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        r = supabase.table("user_strikes").select("id").eq("user_id", user_id).gte("created_at", since).execute()
        return len(r.data or [])
    except Exception as e:
        logger.warning(f"Failed to count strikes: {e}")
        return 0


def apply_user_lock(user_id: str, hours: float = 12.0) -> None:
    """Set user locked until now + hours (upsert by user_id)."""
    supabase = _get_client()
    try:
        from datetime import datetime, timedelta, timezone
        locked_until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
        existing = supabase.table("user_lock").select("id").eq("user_id", user_id).execute()
        if existing.data:
            supabase.table("user_lock").update({"locked_until": locked_until}).eq("user_id", user_id).execute()
        else:
            supabase.table("user_lock").insert({"user_id": user_id, "locked_until": locked_until}).execute()
    except Exception as e:
        logger.warning(f"Failed to apply user lock: {e}")


# DEPRECATED: save_parsed_receipt is no longer used
# Receipts are now saved via create_receipt + save_processing_run


def get_test_user_id() -> Optional[str]:
    """
    Get test user ID (if configured).
    In production environment, should get real user_id from authentication.
    
    Returns:
        User ID string or None
    """
    # First, try to get from environment variable
    if settings.test_user_id:
        logger.info(f"Using TEST_USER_ID from environment: {settings.test_user_id}")
        return settings.test_user_id
    
    logger.info("TEST_USER_ID not set in environment, attempting to get first user from database...")
    # If not set, try to get the first user from database
    try:
        supabase = _get_client()
        res = supabase.table("users").select("id, user_name, email").limit(1).execute()
        if res.data and len(res.data) > 0:
            user_id = res.data[0]["id"]
            user_name = res.data[0].get("user_name", "N/A")
            logger.info(f"✓ Auto-detected user_id from database: {user_id} (name: {user_name})")
            return user_id
        else:
            logger.warning("No users found in users table")
    except Exception as e:
        logger.error(f"✗ Failed to get user from database: {type(e).__name__}: {e}")
    
    # Return None if nothing found
    logger.warning("get_test_user_id() returning None - no user_id available")
    return None


def verify_user_exists(user_id: str) -> bool:
    """
    Verify if user exists in auth.users table.
    
    Args:
        user_id: User ID (UUID string)
        
    Returns:
        True if user exists, False otherwise
    """
    supabase = _get_client()
    try:
        # Note: Need service role key to query auth.users
        # If using anon key, may need to verify via Supabase Auth API or other methods
        # Here try to indirectly verify via receipt_status table query (if user has receipt records)
        res = supabase.table("receipt_status").select("user_id").eq("user_id", user_id).limit(1).execute()
        # If can query (or query doesn't error), user might exist
        return True
    except Exception as e:
        logger.warning(f"Could not verify user existence: {e}")
        # For development environment, assume user exists (let database throw specific error)
        return False


def _receipt_address_disagrees_with_canonical(merchant_address: Optional[str], location_row: Dict[str, Any]) -> bool:
    """True if receipt address clearly refers to a different place than the canonical location (e.g. Totem Lake vs Lynnwood)."""
    if not (merchant_address or "").strip():
        return False
    canonical_city = (location_row.get("city") or "").strip().lower()
    canonical_line1 = (location_row.get("address_line1") or "").strip().lower()
    if not canonical_city and not canonical_line1:
        return False
    receipt_lower = merchant_address.lower()
    # If receipt contains canonical city or main street, consider it same location
    if canonical_city and canonical_city in receipt_lower:
        return False
    if canonical_line1 and len(canonical_line1) > 5 and canonical_line1 in receipt_lower:
        return False
    # Receipt has substantial address but doesn't mention canonical place -> likely different (e.g. Totem Lake vs Lynnwood)
    return len(receipt_lower) > 15


def _assemble_address_parts(first_line: str, city: str, state: str, zip_code: str, country: str) -> str:
    """Join resolved address components into a newline-separated string."""
    parts = [first_line] if first_line else []
    if city or state or zip_code:
        parts.append(f"{city}, {state} {zip_code}".strip(", "))
    if country:
        parts.append(country)
    return "\n".join(p for p in parts if p)


def _store_address_from_location_row(row: Dict[str, Any]) -> str:
    """Build store_address from store_locations row. First line: address2-address1 (unit-street) when both present for readability."""
    line1 = (row.get("address_line1") or "").strip()
    line2 = (row.get("address_line2") or "").strip()
    if line2 and re.match(r"^\d+[\w-]*$", line2):
        line2_display = line2  # number-only, use as-is for "101-19715 Highway 99"
    elif line2:
        m = re.search(r"(?:Suite|Ste|Unit|Apt|#)\s*(\d+[\w-]*)", line2, re.I)
        line2_display = m.group(1).strip() if m else line2
    else:
        line2_display = ""
    if line1 and line2_display:
        first_line = f"{line2_display}-{line1}"
    elif line1:
        first_line = line1
    elif line2_display:
        first_line = f"Unit {line2_display}"
    else:
        first_line = ""
    return _assemble_address_parts(
        first_line,
        row.get("city") or "",
        row.get("state") or "",
        row.get("zip_code") or "",
        row.get("country_code") or "",
    )


def build_merchant_address_from_structured(receipt: Dict[str, Any]) -> Optional[str]:
    """
    Build a single merchant_address string from structured receipt fields.
    First line uses address2-address1 (unit-street) when both present for readability.
    """
    line1 = (receipt.get("address_line1") or receipt.get("address1") or "").strip()
    line2 = (receipt.get("address_line2") or receipt.get("address2") or "").strip()
    if line1 and line2:
        first_line = f"{line2}-{line1}"
    elif line1:
        first_line = line1
    elif line2:
        # Numeric-only unit → add "Unit" label; labelled string (e.g. "Suite 101") → keep as-is
        first_line = f"Unit {line2}" if re.match(r"^\d+[\w-]*$", line2) else line2
    else:
        first_line = ""
    result = _assemble_address_parts(
        first_line,
        (receipt.get("city") or "").strip(),
        (receipt.get("state") or "").strip(),
        (receipt.get("zip_code") or receipt.get("zipcode") or "").strip(),
        (receipt.get("country") or "").strip(),
    )
    return result or None


def _to_cents(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(round(float(val) * 100))
    except (TypeError, ValueError):
        return None


def _to_quantity_x100(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(round(float(val) * 100))
    except (TypeError, ValueError):
        return None


def _title_case(s: Optional[str]) -> str:
    """Title-case a string (e.g. 'chicken fried rice' -> 'Chicken Fried Rice')."""
    if not s or not s.strip():
        return s or ""
    return " ".join(w.capitalize() for w in (s or "").strip().split())


def _lookup_product_display_and_unit(
    supabase: Client,
    chain_id: Optional[str],
    raw_product_name: str,
) -> tuple:
    """
    Look up product by raw name and store_chain_id. Returns (display_name, unit).
    display_name = products.normalized_name in title case; unit = package_type or size_unit.
    """
    if not (raw_product_name or (raw_product_name or "").strip()):
        return None, None
    raw_lower = (raw_product_name or "").strip().lower()
    try:
        # Prefer chain-specific product, then fallback to store_chain_id null
        for sid in ([chain_id] if chain_id else []) + [None]:
            q = (
                supabase.table("products")
                .select("normalized_name, package_type, size_unit")
                .eq("normalized_name", raw_lower)
                .limit(1)
            )
            if sid is not None:
                q = q.eq("store_chain_id", sid)
            else:
                q = q.is_("store_chain_id", "null")
            res = q.execute()
            if res.data and len(res.data) > 0:
                row = res.data[0]
                display = _title_case(row.get("normalized_name"))
                unit = row.get("package_type") or row.get("size_unit")
                return display, unit
    except Exception as e:
        logger.debug(f"Product lookup for '{raw_product_name[:40]}': {e}")
    return None, None


def _build_information_json(
    receipt_data: Dict[str, Any],
    items_data: List[Dict[str, Any]],
    supabase: Optional[Client] = None,
    chain_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build record_summaries.information: other_info + items (section 2). Amounts in cents.
    Items: original_product_name = receipt raw name; product_name = from products.normalized (title case) or raw.
    unit = item.unit or from products (package_type/size_unit). other_info = cashier, membership_card, merchant_phone, purchase_time."""
    other_info = {
        "cashier": receipt_data.get("cashier"),
        "membership_card": receipt_data.get("membership_card"),
        "merchant_phone": receipt_data.get("merchant_phone"),
        "purchase_time": receipt_data.get("purchase_time"),
    }
    items = []
    for it in items_data or []:
        name = it.get("product_name")
        if not name:
            continue
        original_product_name = (name or "").strip()
        display_name, unit_from_product = None, None
        if supabase:
            display_name, unit_from_product = _lookup_product_display_and_unit(supabase, chain_id, original_product_name)
        product_name = display_name if display_name else _title_case(original_product_name)
        unit = it.get("unit") or unit_from_product
        items.append({
            "original_product_name": original_product_name,
            "product_name": product_name,
            "quantity": _to_quantity_x100(it.get("quantity")),
            "unit": unit,
            "unit_price": _to_cents(it.get("unit_price")),
            "line_total": _to_cents(it.get("line_total")),
            "on_sale": bool(it.get("on_sale") or it.get("is_on_sale")),
            "original_price": _to_cents(it.get("original_price")),
            "discount_amount": _to_cents(it.get("discount_amount")),
        })
    return {"other_info": other_info, "items": items}


def save_receipt_summary(
    receipt_id: str,
    user_id: str,
    receipt_data: Dict[str, Any],
    *,
    chain_id: Optional[str] = None,
    location_id: Optional[str] = None,
    items_data: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Save receipt summary data to record_summaries table.
    store_address: from store_locations when location_id set (address_line1, Unit address_line2, city, state zip, country).
    subtotal/tax/fees/total: stored as integer cents.
    information: JSON with other_info + items (see record_summaries_information_json_proposal.md).
    """
    if not receipt_id or not user_id:
        raise ValueError("receipt_id and user_id are required")
    
    supabase = _get_client()
    
    # Extract receipt-level fields
    merchant_name = receipt_data.get("merchant_name")
    merchant_address = receipt_data.get("merchant_address")
    purchase_date = receipt_data.get("purchase_date")
    subtotal = receipt_data.get("subtotal")
    tax = receipt_data.get("tax")
    total = receipt_data.get("total")
    fees = receipt_data.get("fees")
    currency = receipt_data.get("currency", "USD")
    # Standardize payment for consistent "By payment card" aggregation (Visa/MasterCard/AmEx/Discover/Gift Card/Cash/Other)
    payment_method = normalize_payment_type(receipt_data.get("payment_method") or "")
    card_last4 = _normalize_card_last4(receipt_data.get("card_last4"))
    
    if not total:
        raise ValueError("total is required in receipt_data")
    
    store_chain_id = chain_id
    store_location_id = location_id
    _addr_preview = (merchant_address[:100] + "...") if merchant_address and len(merchant_address) > 100 else merchant_address
    logger.info(
        "[STORE_DEBUG] save_receipt_summary IN: chain_id=%s, location_id=%s, receipt_data.merchant_address=%r",
        chain_id,
        location_id,
        _addr_preview,
    )

    # Trust chain_id/location_id from payload (set by workflow after address-aware match). Do NOT re-call
    # get_store_chain here: that would match by name only when address is missing and assign wrong store
    # (e.g. Totem Lake receipt -> Lynnwood). No match => store_chain_id/store_location_id stay None,
    # store_address = merchant_address; store_candidate is created in workflow.
    # store_address and location phone: from store_locations when store_location_id set
    store_address: Optional[str] = None
    location_phone: Optional[str] = None
    if store_location_id:
        try:
            loc = supabase.table("store_locations").select("address_line1, address_line2, city, state, zip_code, country_code, phone").eq("id", store_location_id).limit(1).execute()
            if loc.data and len(loc.data) > 0:
                loc_row = loc.data[0]
                canonical_addr = _store_address_from_location_row(loc_row)
                # If receipt address clearly describes a different place (e.g. Totem Lake), don't overwrite with canonical (e.g. Lynnwood)
                if _receipt_address_disagrees_with_canonical(merchant_address, loc_row):
                    store_address = merchant_address
                    logger.info(
                        "[STORE_DEBUG] save_receipt_summary: receipt address disagrees with location_id=%s (e.g. different city), using receipt store_address",
                        store_location_id,
                    )
                else:
                    store_address = canonical_addr
                location_phone = (loc_row.get("phone") or "").strip() or None
        except Exception as e:
            logger.warning(f"Failed to get store_location for address: {e}")
    if store_address is None:
        store_address = merchant_address
    _store_addr_preview = (store_address[:100] + "...") if store_address and len(store_address) > 100 else store_address
    logger.info(
        "[STORE_DEBUG] save_receipt_summary OUT: store_chain_id=%s, store_location_id=%s, store_address=%r",
        store_chain_id,
        store_location_id,
        _store_addr_preview,
    )

    # When we have a matched chain, use chain canonical name; otherwise normalize raw merchant name to title case (e.g. GOLD VALLEY -> Gold Valley)
    store_name_for_summary: Optional[str] = _store_name_to_title_case(merchant_name)
    if store_chain_id:
        try:
            sc = supabase.table("store_chains").select("name").eq("id", store_chain_id).limit(1).execute()
            if sc.data and sc.data[0].get("name"):
                # 链名称可能存成全大写，持久化时统一为首字母大写
                store_name_for_summary = _store_name_to_title_case(sc.data[0]["name"]) or sc.data[0]["name"]
        except Exception as e:
            logger.warning(f"Failed to get store_chain name for store_name: {e}")
    
    # Prefer store_locations.phone for other_info.merchant_phone when set (reduces OCR error)
    receipt_for_info = dict(receipt_data)
    receipt_for_info["merchant_name"] = store_name_for_summary  # 用已规范的首字母大写店名写回，保证 information 一致
    if location_phone and not receipt_for_info.get("merchant_phone"):
        receipt_for_info["merchant_phone"] = location_phone
    information = _build_information_json(receipt_for_info, items_data or [], supabase, store_chain_id)
    
    payload = {
        "receipt_id": receipt_id,
        "user_id": user_id,
        "store_chain_id": store_chain_id,
        "store_location_id": store_location_id,
        "store_name": store_name_for_summary,
        "store_address": store_address,
        "subtotal": _to_cents(subtotal),
        "tax": _to_cents(tax),
        "fees": _to_cents(fees) if fees is not None else 0,
        "total": _to_cents(total),
        "currency": currency,
        "payment_method": payment_method,
        "payment_last4": card_last4,
        "receipt_date": purchase_date,
        "information": information,
    }
    
    try:
        res = supabase.table("record_summaries").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to create receipt summary, no data returned")
        summary_id = res.data[0]["id"]
        logger.info(f"Created receipt_summary: {summary_id} for receipt {receipt_id}")
        return summary_id
    except Exception as e:
        logger.error(f"Failed to create receipt summary: {e}")
        raise


def update_receipt_summary(
    receipt_id: str,
    user_id: str,
    receipt_data: Dict[str, Any],
    *,
    chain_id: Optional[str] = None,
    location_id: Optional[str] = None,
    items_data: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """
    Update existing record_summaries row by receipt_id. Only updates fields present in receipt_data.
    If items_data is provided, rebuilds information JSON from it; otherwise updates only other_info from receipt_data.
    Returns summary id if found and updated, None if no row exists (caller may then insert).
    """
    supabase = _get_client()
    existing = (
        supabase.table("record_summaries")
        .select("id, information")
        .eq("receipt_id", receipt_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        logger.info("[UPDATE_SUMMARY_DEBUG] receipt_id=%s no existing record_summaries -> return None (caller will insert)", receipt_id)
        return None

    summary_id = existing.data[0]["id"]
    logger.info("[UPDATE_SUMMARY_DEBUG] receipt_id=%s found summary_id=%s -> will update", receipt_id, summary_id)
    store_chain_id = chain_id
    store_location_id = location_id
    merchant_name = receipt_data.get("merchant_name")
    merchant_address = receipt_data.get("merchant_address")
    # Trust chain_id/location_id from payload; do not re-call get_store_chain (would match by name only).

    store_address: Optional[str] = None
    location_phone: Optional[str] = None
    if store_location_id:
        try:
            loc = supabase.table("store_locations").select("address_line1, address_line2, city, state, zip_code, country_code, phone").eq("id", store_location_id).limit(1).execute()
            if loc.data:
                store_address = _store_address_from_location_row(loc.data[0])
                location_phone = (loc.data[0].get("phone") or "").strip() or None
        except Exception as e:
            logger.warning(f"Failed to get store_location: {e}")
    if store_address is None:
        store_address = merchant_address

    receipt_for_info = dict(receipt_data)
    if location_phone and not receipt_for_info.get("merchant_phone"):
        receipt_for_info["merchant_phone"] = location_phone

    if items_data is not None:
        information = _build_information_json(receipt_for_info, items_data, supabase, store_chain_id)
    else:
        info = (existing.data[0].get("information") or {}).copy()
        other = dict(info.get("other_info") or {})
        if receipt_data.get("purchase_time") is not None:
            other["purchase_time"] = receipt_data.get("purchase_time")
        if receipt_data.get("merchant_phone") is not None:
            other["merchant_phone"] = receipt_data.get("merchant_phone")
        if receipt_data.get("cashier") is not None:
            other["cashier"] = receipt_data.get("cashier")
        info["other_info"] = other
        information = info

    subtotal = receipt_data.get("subtotal")
    tax = receipt_data.get("tax")
    total = receipt_data.get("total")
    update_payload: Dict[str, Any] = {
        "information": information,
    }
    if merchant_name is not None and not store_chain_id:
        update_payload["store_name"] = _store_name_to_title_case(merchant_name)
    if store_address is not None:
        update_payload["store_address"] = store_address
    if receipt_data.get("purchase_date") is not None:
        update_payload["receipt_date"] = receipt_data.get("purchase_date")
    if subtotal is not None:
        update_payload["subtotal"] = _to_cents(subtotal)
    if tax is not None:
        update_payload["tax"] = _to_cents(tax)
    if total is not None:
        update_payload["total"] = _to_cents(total)
    if receipt_data.get("currency") is not None:
        update_payload["currency"] = receipt_data.get("currency")
    if receipt_data.get("payment_method") is not None:
        update_payload["payment_method"] = normalize_payment_type(receipt_data.get("payment_method") or "")
    if receipt_data.get("card_last4") is not None:
        update_payload["payment_last4"] = _normalize_card_last4(receipt_data.get("card_last4"))
    if store_chain_id is not None:
        update_payload["store_chain_id"] = store_chain_id
    if store_location_id is not None:
        update_payload["store_location_id"] = store_location_id

    # When we have store_chain_id, use chain canonical name in title case for store_name
    if store_chain_id:
        try:
            sc = supabase.table("store_chains").select("name").eq("id", store_chain_id).limit(1).execute()
            if sc.data and sc.data[0].get("name"):
                update_payload["store_name"] = _store_name_to_title_case(sc.data[0]["name"]) or sc.data[0]["name"]
        except Exception as e:
            logger.warning(f"Failed to get store_chain name for store_name: {e}")

    supabase.table("record_summaries").update(update_payload).eq("receipt_id", receipt_id).execute()
    logger.info(f"Updated record_summary for receipt {receipt_id}")
    return summary_id


def _resolve_category_id(supabase: Client, category_str: Optional[str]) -> Optional[str]:
    """
    Resolve category string (e.g. "Grocery > Produce > Fruit") to category_id (level-3).
    Uses category_migration_mapping or categories.path.
    """
    if not category_str or not category_str.strip():
        return None
    parts = [p.strip() for p in category_str.split(">")]
    if len(parts) < 3:
        return None
    l1, l2, l3 = parts[0], parts[1], parts[2]
    try:
        # Try category_migration_mapping first
        res = (
            supabase.table("category_migration_mapping")
            .select("new_category_id")
            .eq("old_l1", l1)
            .eq("old_l2", l2)
            .eq("old_l3", l3)
            .limit(1)
            .execute()
        )
        if res.data and res.data[0].get("new_category_id"):
            return str(res.data[0]["new_category_id"])
        # Fallback: match categories by path (Grocery/Produce/Fruit)
        path = f"{l1}/{l2}/{l3}"
        cat = supabase.table("categories").select("id").eq("path", path).limit(1).execute()
        if cat.data and cat.data[0].get("id"):
            return str(cat.data[0]["id"])
    except Exception as e:
        logger.debug(f"Category resolution failed for '{category_str}': {e}")
    return None


def _has_explicit_sale_indicator(product_name: str) -> bool:
    """True if product name contains explicit sale/discount label (e.g. (SALE), was $X now $Y)."""
    if not product_name or not isinstance(product_name, str):
        return False
    name_upper = product_name.strip().upper()
    if "(SALE)" in name_upper or name_upper.startswith("SALE "):
        return True
    if " WAS " in name_upper and " NOW " in name_upper:
        return True
    return False


def _is_quantity_unit_pricing(item: Dict[str, Any]) -> bool:
    """True if item looks like normal quantity × unit_price (e.g. 5 at $0.23), not a real discount."""
    qty = item.get("quantity")
    up = item.get("unit_price")
    total = item.get("line_total")
    if qty is None or up is None or total is None:
        return False
    try:
        q = float(qty)
        u = float(up)
        t = float(total)
        if q <= 0 or u <= 0 or t <= 0:
            return False
        # Dollars path: quantity=5, unit_price=0.23, line_total=1.15
        if t < 1000 and abs(q * u - t) <= 0.03:
            return True
        # Cents path: quantity x100 (500=5.0), unit_price cents (23), line_total cents (115)
        if t >= 10 and q >= 10 and abs((q / 100.0) * u - t) <= 3:
            return True
    except (TypeError, ValueError):
        pass
    return False


def save_receipt_items(
    receipt_id: str,
    user_id: str,
    items_data: List[Dict[str, Any]]
) -> List[str]:
    """
    Save receipt items to record_items table.
    
    All quantities and prices stored as integers (x100):
    - quantity: 1.5 -> 150, 2 -> 200
    - unit_price, line_total, etc.: dollars -> cents
    
    Args:
        receipt_id: Receipt ID (UUID string)
        user_id: User ID (UUID string)
        items_data: List of item dictionaries from LLM output
        
    Returns:
        List of item_ids (UUID strings)
    """
    if not receipt_id or not user_id:
        raise ValueError("receipt_id and user_id are required")
    
    if not items_data:
        logger.warning("[SAVE_ITEMS_DEBUG] No items_data, receipt_id=%s", receipt_id)
        return []

    logger.info(
        "[SAVE_ITEMS_DEBUG] receipt_id=%s items_data=%d sample=%s",
        receipt_id,
        len(items_data),
        [{"product_name": (it.get("product_name") or "")[:40], "line_total": it.get("line_total")} for it in items_data[:2]],
    )
    supabase = _get_client()

    def _to_cents(val) -> Optional[int]:
        if val is None:
            return None
        try:
            return int(round(float(val) * 100))
        except (TypeError, ValueError):
            return None

    def _to_quantity(val) -> Optional[int]:
        if val is None:
            return None
        try:
            return int(round(float(val) * 100))
        except (TypeError, ValueError):
            return None

    # Prepare batch insert
    items_payload = []
    for idx, item in enumerate(items_data):
        product_name = item.get("product_name")
        if not product_name:
            logger.warning(f"Skipping item without product_name at index {idx}")
            continue
        
        quantity = item.get("quantity")
        unit = item.get("unit")
        unit_price = item.get("unit_price")
        line_total = item.get("line_total")
        
        if line_total is None:
            logger.warning(f"Skipping item '{product_name}' without line_total")
            continue
        
        line_total_cents = _to_cents(line_total)
        if line_total_cents is None or line_total_cents < 0:
            logger.warning(f"Skipping item '{product_name}' with invalid line_total")
            continue

        # Prefer explicit category_id (e.g. from product_categorization_rules); else resolve category string from payload
        category_id = None
        if item.get("category_id"):
            try:
                category_id = str(item["category_id"]).strip() or None
            except (TypeError, ValueError):
                pass
        if not category_id:
            category_id = _resolve_category_id(supabase, item.get("category"))
        
        is_on_sale = item.get("is_on_sale", False)
        original_price = _to_cents(item.get("original_price"))
        discount_amount = _to_cents(item.get("discount_amount"))
        # Only true discounts: not "N at $price" quantity pricing (see prompt + safeguard below)
        if _is_quantity_unit_pricing(item) and not _has_explicit_sale_indicator(product_name):
            is_on_sale = False
        product_name_clean_val = normalize_name_for_storage(product_name) or None
        item_payload = {
            "receipt_id": receipt_id,
            "user_id": user_id,
            "product_name": product_name,
            "product_name_clean": product_name_clean_val,
            "quantity": _to_quantity(quantity),
            "unit": unit,
            "unit_price": _to_cents(unit_price),
            "line_total": line_total_cents,
            "on_sale": is_on_sale,
            "original_price": original_price,
            "discount_amount": discount_amount,
            "category_id": category_id,
            "item_index": idx,
        }
        
        items_payload.append(item_payload)
    
    if not items_payload:
        logger.warning(f"No valid items to insert for receipt {receipt_id}")
        return []
    
    try:
        logger.info("[SAVE_ITEMS_DEBUG] inserting payload count=%s receipt_id=%s", len(items_payload), receipt_id)
        res = supabase.table("record_items").insert(items_payload).execute()
        if not res.data:
            raise ValueError("Failed to create receipt items, no data returned")
        item_ids = [item["id"] for item in res.data]
        logger.info("[SAVE_ITEMS_DEBUG] receipt_id=%s inserted=%s", receipt_id, len(item_ids))
        return item_ids
    except Exception as e:
        logger.error("[SAVE_ITEMS_DEBUG] receipt_id=%s insert failed: %s", receipt_id, e)
        raise


def sync_receipt_items(
    receipt_id: str,
    user_id: str,
    items_data: List[Dict[str, Any]],
) -> tuple:
    """
    Update/insert/delete record_items to match payload. Preserves category_id on existing rows unless payload sends one.
    items_data: list of { id?: uuid, product_name, quantity, unit, unit_price, line_total, ... }. id = existing record_items.id.
    Returns (n_updated, n_inserted, n_deleted).
    """
    if not receipt_id or not user_id:
        raise ValueError("receipt_id and user_id are required")

    supabase = _get_client()

    def _to_cents(val) -> Optional[int]:
        if val is None:
            return None
        try:
            return int(round(float(val) * 100))
        except (TypeError, ValueError):
            return None

    def _to_qty(val) -> Optional[int]:
        if val is None:
            return None
        try:
            return int(round(float(val) * 100))
        except (TypeError, ValueError):
            return None

    current = (
        supabase.table("record_items")
        .select("id, category_id")
        .eq("receipt_id", receipt_id)
        .execute()
    )
    existing_by_id = {(str(row["id"])): row for row in (current.data or [])}
    existing_ids = set(existing_by_id.keys())

    logger.info(
        "[SYNC_ITEMS_DEBUG] receipt_id=%s items_data_in=%d existing_record_items=%s existing_ids=%s",
        receipt_id,
        len(items_data),
        len(existing_ids),
        list(existing_ids)[:5] if existing_ids else [],
    )

    n_updated = 0
    n_inserted = 0
    valid_items: List[Dict[str, Any]] = []
    for idx, item in enumerate(items_data):
        product_name = (item.get("product_name") or "").strip()
        if not product_name:
            logger.info("[SYNC_ITEMS_DEBUG] skip: no product_name idx=%s", idx)
            continue
        if item.get("line_total") is None:
            logger.info("[SYNC_ITEMS_DEBUG] skip: no line_total idx=%s product_name=%s", idx, product_name[:40])
            continue
        line_total_cents = _to_cents(item.get("line_total"))
        if line_total_cents is None or line_total_cents < 0:
            logger.info("[SYNC_ITEMS_DEBUG] skip: invalid line_total idx=%s line_total=%s", idx, item.get("line_total"))
            continue
        valid_items.append({**item, "_idx": idx})

    ids_in_payload = {str(it.get("id")) for it in valid_items if it.get("id")}
    to_delete_ids = existing_ids - ids_in_payload

    logger.info(
        "[SYNC_ITEMS_DEBUG] valid_items=%d ids_in_payload=%s to_delete=%s",
        len(valid_items),
        list(ids_in_payload)[:5] if ids_in_payload else [],
        list(to_delete_ids)[:5] if to_delete_ids else [],
    )

    update_payloads: List[Dict[str, Any]] = []
    updated_ids_with_name: List[tuple] = []  # (item_id, product_name) for classification_review sync
    insert_rows: List[Dict[str, Any]] = []

    for it in valid_items:
        idx = it.pop("_idx")
        item_id = it.get("id") and str(it.get("id")).strip()
        category_id = None
        if it.get("category_id"):
            try:
                category_id = str(it["category_id"]).strip() or None
            except (TypeError, ValueError):
                pass
        if not category_id:
            category_id = _resolve_category_id(supabase, it.get("category"))

        product_name_str = (it.get("product_name") or "").strip()
        on_sale_val = bool(it.get("on_sale") or it.get("is_on_sale"))
        if _is_quantity_unit_pricing(it) and not _has_explicit_sale_indicator(product_name_str):
            on_sale_val = False
        payload = {
            "product_name": product_name_str,
            "product_name_clean": normalize_name_for_storage(product_name_str) or None,
            "quantity": _to_qty(it.get("quantity")),
            "unit": it.get("unit"),
            "unit_price": _to_cents(it.get("unit_price")),
            "line_total": _to_cents(it.get("line_total")),
            "on_sale": on_sale_val,
            "original_price": _to_cents(it.get("original_price")),
            "discount_amount": _to_cents(it.get("discount_amount")),
            "item_index": idx,
        }
        if item_id and item_id in existing_by_id:
            if category_id is not None:
                payload["category_id"] = category_id
            else:
                existing_cat = existing_by_id.get(item_id, {}).get("category_id")
                if existing_cat is not None:
                    payload["category_id"] = existing_cat
            payload["id"] = item_id
            update_payloads.append(payload)
            updated_ids_with_name.append((item_id, product_name_str))
        else:
            insert_rows.append({
                "receipt_id": receipt_id,
                "user_id": user_id,
                "category_id": category_id,
                **payload,
            })

    # Batch delete
    if to_delete_ids:
        for rid in to_delete_ids:
            logger.info("[SYNC_ITEMS_DEBUG] DELETE id=%s", rid)
        supabase.table("record_items").delete().in_("id", list(to_delete_ids)).eq("receipt_id", receipt_id).execute()

    # Batch update via RPC
    if update_payloads:
        try:
            res = supabase.rpc("sync_record_items_batch_update", {"updates": update_payloads}).execute()
            n_updated = _parse_rpc_count(res, "sync_record_items_batch_update", len(update_payloads))
            for item_id, pname in updated_ids_with_name:
                sync_classification_review_raw_product_name(item_id, pname)
        except Exception as e:
            logger.warning("[SYNC_ITEMS_DEBUG] batch update RPC failed, falling back to per-row update: %s", e)
            n_updated = 0
            for it in update_payloads:
                item_id = it.pop("id", None)
                if not item_id:
                    continue
                try:
                    supabase.table("record_items").update(it).eq("id", item_id).eq("receipt_id", receipt_id).execute()
                    n_updated += 1
                    sync_classification_review_raw_product_name(item_id, it.get("product_name") or "")
                except Exception:
                    pass

    # Batch insert
    if insert_rows:
        for row in insert_rows:
            logger.info(
                "[SYNC_ITEMS_DEBUG] INSERT product_name=%s line_total_cents=%s",
                (row.get("product_name") or "")[:40],
                row.get("line_total"),
            )
        supabase.table("record_items").insert(insert_rows).execute()
        n_inserted = len(insert_rows)

    n_deleted = len(to_delete_ids)
    logger.info(
        "[SYNC_ITEMS_DEBUG] receipt=%s DONE updated=%s inserted=%s deleted=%s",
        receipt_id,
        n_updated,
        n_inserted,
        n_deleted,
    )
    return (n_updated, n_inserted, n_deleted)


def sync_classification_review_raw_product_name(record_item_id: str, raw_product_name: str) -> int:
    """
    When a user corrects product name on a receipt (record_items), propagate that
    to classification_review so raw_product_name stays in sync. Updates all rows
    where source_record_item_id = record_item_id.
    Returns number of classification_review rows updated.
    """
    if not record_item_id or not isinstance(raw_product_name, str):
        return 0
    name = raw_product_name.strip()
    supabase = _get_client()
    try:
        res = (
            supabase.table("classification_review")
            .update({"raw_product_name": name})
            .eq("source_record_item_id", record_item_id)
            .execute()
        )
        count = len(res.data) if res.data else 0
        if count:
            logger.debug(f"Synced raw_product_name to classification_review for record_item {record_item_id}: {count} row(s)")
        return count
    except Exception as e:
        logger.warning(f"Failed to sync classification_review raw_product_name for record_item {record_item_id}: {e}")
        return 0


def enqueue_unmatched_items_to_classification_review(
    receipt_id: str,
    universal_only_record_item_ids: Optional[List[str]] = None,
) -> int:
    """
    After saving record_items, enqueue rows that have no category_id into
    classification_review for admin review. Also enqueues items that got their
    category from universal (general) rules only, so admin can confirm or add chain-specific rules.
    Dedupe: do not insert if there is already a pending row with the same (raw_product_name, store_chain_id).

    Calls LLM (Gemini) to pre-fill category_id, size, unit_type as unconfirmed.

    Args:
        receipt_id: Receipt ID (UUID string)
        universal_only_record_item_ids: Optional list of record_item ids that were matched by universal rules only.

    Returns:
        Number of new rows inserted into classification_review.
    """
    import asyncio

    supabase = _get_client()
    inserted = 0

    try:
        # Get store_chain_id and chain name for this receipt
        summary = (
            supabase.table("record_summaries")
            .select("store_chain_id")
            .eq("receipt_id", receipt_id)
            .limit(1)
            .execute()
        )
        store_chain_id = summary.data[0]["store_chain_id"] if summary.data else None
        store_chain_name = None
        if store_chain_id:
            sc = supabase.table("store_chains").select("name").eq("id", store_chain_id).limit(1).execute()
            if sc.data:
                store_chain_name = sc.data[0].get("name")

        # Existing pending rows for this store: (normalized_key -> id). Later submission overrides; do not create duplicate.
        q = supabase.table("classification_review").select("id, raw_product_name, normalized_name, created_at").eq("status", "pending")
        if store_chain_id is None:
            q = q.is_("store_chain_id", "null")
        else:
            q = q.eq("store_chain_id", store_chain_id)
        existing_rows = (q.execute()).data or []
        existing_by_norm: Dict[str, str] = {}
        for row in sorted(existing_rows, key=lambda x: (x.get("created_at") or ""), reverse=True):
            raw = (row.get("raw_product_name") or "").strip()
            norm = (row.get("normalized_name") or "").strip()
            key = normalize_name_for_storage(norm or raw) if (norm or raw) else ""
            if not key:
                continue
            if key not in existing_by_norm:
                existing_by_norm[key] = row["id"]

        def _should_skip(raw_name: str) -> bool:
            if not (raw_name or "").strip():
                return True
            key = normalize_name_for_storage(raw_name.strip())
            return key in existing_by_norm

        # 1) Items with no category_id
        items = (
            supabase.table("record_items")
            .select("id, product_name")
            .eq("receipt_id", receipt_id)
            .is_("category_id", "null")
            .execute()
        )
        to_enqueue: List[Dict[str, Any]] = []
        for row in (items.data or []):
            raw_name = (row.get("product_name") or "").strip()
            if not raw_name or _should_skip(raw_name):
                continue
            to_enqueue.append({"source_record_item_id": row["id"], "raw_product_name": raw_name})

        # 2) Items matched by universal rules only (have category_id but should still be reviewed)
        if universal_only_record_item_ids:
            uni = (
                supabase.table("record_items")
                .select("id, product_name")
                .in_("id", universal_only_record_item_ids)
                .execute()
            )
            for row in (uni.data or []):
                raw_name = (row.get("product_name") or "").strip()
                if not raw_name or _should_skip(raw_name):
                    continue
                to_enqueue.append({"source_record_item_id": row["id"], "raw_product_name": raw_name})

        if not to_enqueue:
            return 0

        # LLM pre-fill: suggest category, size, unit_type (avoid asyncio.run on main thread)
        raw_names = [r["raw_product_name"] for r in to_enqueue]
        suggestions: List[Dict[str, Any]] = []
        try:
            from app.services.admin.classification_llm import suggest_classifications
            try:
                _loop = asyncio.get_running_loop()
            except RuntimeError:
                _loop = None
            if _loop is None:
                suggestions = asyncio.run(suggest_classifications(raw_names, store_chain_name))
            else:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=1) as _pool:
                    _f = _pool.submit(
                        lambda: asyncio.run(suggest_classifications(raw_names, store_chain_name))
                    )
                    suggestions = _f.result()
        except Exception as e:
            logger.warning(f"Classification LLM pre-fill failed: {e}")

        suggestion_map = {s["raw_product_name"]: s for s in suggestions}

        for r in to_enqueue:
            raw_name = r["raw_product_name"]
            norm_key = normalize_name_for_storage(raw_name)
            sugg = suggestion_map.get(raw_name, {})
            payload = {
                "raw_product_name": raw_name,
                "source_record_item_id": r["source_record_item_id"],
                "store_chain_id": store_chain_id,
                "status": "pending",
            }
            if sugg.get("category_id"):
                payload["category_id"] = sugg["category_id"]
            if sugg.get("size_quantity") is not None:
                payload["size_quantity"] = sugg["size_quantity"]
            if sugg.get("size_unit"):
                payload["size_unit"] = sugg["size_unit"]
            if sugg.get("package_type"):
                payload["package_type"] = sugg["package_type"]
            if norm_key and norm_key in existing_by_norm:
                # Same store + same normalized product: override existing row (later submission wins)
                cr_id = existing_by_norm[norm_key]
                supabase.table("classification_review").update(payload).eq("id", cr_id).execute()
                logger.debug("Enqueue: updated existing classification_review row %s (same store+product)", cr_id)
            else:
                supabase.table("classification_review").insert(payload).execute()
                inserted += 1
                if norm_key:
                    # Fetch the new row id so we can override if same product appears again in this batch
                    latest = (
                        supabase.table("classification_review")
                        .select("id, created_at")
                        .eq("source_record_item_id", r["source_record_item_id"])
                        .order("created_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    if latest.data:
                        existing_by_norm[norm_key] = latest.data[0]["id"]

        if inserted:
            logger.info(
                f"Enqueued {inserted} unmatched items to classification_review for receipt {receipt_id}"
            )
    except Exception as e:
        logger.warning(f"Failed to enqueue unmatched items to classification_review: {e}")

    return inserted


def get_store_chain(
    chain_name: str,
    store_address: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get store chain by name using fuzzy matching.
    Does NOT create candidate here - candidate should be created after LLM processing
    with complete information.
    
    Args:
        chain_name: Store chain name (e.g., "Costco", "T&T Supermarket")
        store_address: Optional store address for better matching
        
    Returns:
        Dict with:
        - 'matched': bool - Whether a high confidence match was found
        - 'chain_id': Optional[str] - Matched chain_id (if high confidence)
        - 'location_id': Optional[str] - Matched location_id (if high confidence)
        - 'suggested_chain_id': Optional[str] - Suggested chain_id (if low confidence)
        - 'suggested_location_id': Optional[str] - Suggested location_id (if low confidence)
        - 'confidence_score': Optional[float] - Confidence score (0.0-1.0)
    """
    if not chain_name:
        return {
            "matched": False,
            "chain_id": None,
            "location_id": None,
            "suggested_chain_id": None,
            "suggested_location_id": None,
            "confidence_score": None
        }
    _addr_preview = (store_address[:100] + "...") if store_address and len(store_address) > 100 else store_address
    logger.info("[STORE_DEBUG] get_store_chain IN: chain_name=%r, store_address=%r", chain_name, _addr_preview)
    
    # Import here to avoid circular dependency
    from ...processors.enrichment.address_matcher import match_store
    
    # Try to match using address_matcher
    match_result = match_store(chain_name, store_address)
    logger.info(
        "[STORE_DEBUG] get_store_chain OUT: matched=%s, chain_id=%s, location_id=%s",
        match_result.get("matched"),
        match_result.get("chain_id"),
        match_result.get("location_id"),
    )
    
    if match_result.get("matched"):
        # High confidence match - return directly
        result = {
            "matched": True,
            "chain_id": match_result.get("chain_id"),
            "location_id": match_result.get("location_id"),
            "suggested_chain_id": None,
            "suggested_location_id": None,
            "confidence_score": match_result.get("confidence_score")
        }
        logger.info(f"Matched store chain: {chain_name} -> chain_id={result['chain_id']}, location_id={result.get('location_id')}")
        return result
    
    # Not matched - return suggestion info if available
    result = {
        "matched": False,
        "chain_id": None,
        "location_id": None,
        "suggested_chain_id": match_result.get("suggested_chain_id"),
        "suggested_location_id": match_result.get("suggested_location_id"),
        "confidence_score": match_result.get("confidence_score")
    }
    
    if result.get("suggested_chain_id"):
        logger.info(f"Low confidence match for store chain: {chain_name} -> suggested_chain_id={result['suggested_chain_id']}, confidence={result.get('confidence_score', 0):.2f}")
    else:
        logger.info(f"Store chain not found: {chain_name}, will create candidate after LLM processing")
    
    return result


def _store_name_matches_chain_for_backfill(store_name_lower: str, norm: str, name_lower: str) -> bool:
    """True if unlinked store_name should be assigned to this chain (exact or prefix match)."""
    if not store_name_lower:
        return False
    # Normalize spelling variants so "walmart supercentre" matches "walmart supercenter"
    store_name_norm = store_name_lower.replace("supercentre", "supercenter")
    for key in (norm, name_lower):
        if not key:
            continue
        key_norm = key.replace("supercentre", "supercenter")
        if store_name_norm == key_norm:
            return True
        if store_name_norm.startswith(key_norm + " ") or store_name_norm.startswith(key_norm + "#") or store_name_norm.startswith(key_norm + "'"):
            return True
    return False


def backfill_record_summaries_for_store_chain(chain_id: str, chain_name: str, normalized_name: Optional[str] = None) -> int:
    """
    Set store_chain_id and store_name (canonical) on record_summaries that have store_chain_id null
    and store_name matching this chain (exact or prefix: "Costco Wholesale" -> Costco).
    Uses normalized_name if provided, else derives from chain_name.
    """
    if not chain_id or not (chain_name or "").strip():
        return 0
    supabase = _get_client()
    name_lower = (chain_name or "").strip().lower()
    norm = (normalized_name or name_lower).strip().lower()
    try:
        res = (
            supabase.table("record_summaries")
            .select("id, store_name")
            .is_("store_chain_id", "null")
            .execute()
        )
        ids_to_update = [
            r["id"] for r in (res.data or [])
            if _store_name_matches_chain_for_backfill((r.get("store_name") or "").strip().lower(), norm, name_lower)
        ]
        if not ids_to_update:
            return 0
        supabase.table("record_summaries").update({
            "store_chain_id": chain_id,
            "store_name": chain_name.strip(),
        }).in_("id", ids_to_update).execute()
        logger.info(f"Backfilled store_chain_id={chain_id} and store_name={chain_name!r} for {len(ids_to_update)} record_summaries")
        return len(ids_to_update)
    except Exception as e:
        logger.warning(f"backfill_record_summaries_for_store_chain failed: {e}")
        return 0


def backfill_record_summaries_for_store_location(
    chain_id: str,
    location_id: str,
    location_row: Dict[str, Any],
    address_match_threshold: float = 0.85,
    chain_name: Optional[str] = None,
) -> int:
    """
    When a store location is confirmed (e.g. Everett): activate and update all receipts
    associated with that address. Finds record_summaries that have this chain_id but no
    store_location_id, and whose store_address fuzzy-matches the new location; then sets
    store_location_id, store_address (canonical multi-line), and store_name (canonical)
    so those receipts display the correct multi-line layout and chain name.
    """
    if not chain_id or not location_id or not location_row:
        return 0
    supabase = _get_client()
    canonical_address = _store_address_from_location_row(location_row)
    if not (canonical_address or "").strip():
        return 0
    canonical_norm = _normalize_address_for_backfill(canonical_address)
    try:
        res = (
            supabase.table("record_summaries")
            .select("id, store_address")
            .eq("store_chain_id", chain_id)
            .is_("store_location_id", "null")
            .execute()
        )
        ids_to_update: List[str] = []
        for r in (res.data or []):
            rec_addr = (r.get("store_address") or "").strip()
            if not rec_addr:
                continue
            rec_norm = _normalize_address_for_backfill(rec_addr)
            if not rec_norm:
                continue
            score = fuzz.ratio(rec_norm, canonical_norm) / 100.0
            if score >= address_match_threshold:
                ids_to_update.append(r["id"])
        if not ids_to_update:
            return 0
        update_payload: Dict[str, Any] = {
            "store_location_id": location_id,
            "store_address": canonical_address,
        }
        if chain_name and (chain_name or "").strip():
            update_payload["store_name"] = chain_name.strip()
        supabase.table("record_summaries").update(update_payload).in_("id", ids_to_update).execute()
        logger.info(
            f"Backfilled store_location_id={location_id} for {len(ids_to_update)} record_summaries (address match to new location)"
        )
        return len(ids_to_update)
    except Exception as e:
        logger.warning(f"backfill_record_summaries_for_store_location failed: {e}")
        return 0


def _backfill_unlinked_record_summaries_for_location(
    chain_id: str,
    location_id: str,
    location_row: Dict[str, Any],
    chain_name: str,
    normalized_name: Optional[str],
    address_match_threshold: float = 0.85,
) -> int:
    """
    Find record_summaries with store_chain_id NULL but store_address matching this location
    and store_name matching this chain; set store_chain_id, store_location_id, store_address, store_name.
    Used so that receipts that never got chain_id at processing time (e.g. address abbrev mismatch)
    still get linked after we add abbreviation normalization.
    """
    if not chain_id or not location_id or not location_row or not (chain_name or "").strip():
        return 0
    supabase = _get_client()
    canonical_address = _store_address_from_location_row(location_row)
    if not (canonical_address or "").strip():
        return 0
    canonical_norm = _normalize_address_for_backfill(canonical_address)
    name_lower = (chain_name or "").strip().lower()
    norm = (normalized_name or name_lower).replace(" ", "_").strip().lower()
    try:
        res = (
            supabase.table("record_summaries")
            .select("id, store_address, store_name")
            .is_("store_chain_id", "null")
            .execute()
        )
        ids_to_update = []
        for r in (res.data or []):
            rec_addr = (r.get("store_address") or "").strip()
            if not rec_addr:
                continue
            rec_norm = _normalize_address_for_backfill(rec_addr)
            if not rec_norm:
                continue
            if fuzz.ratio(rec_norm, canonical_norm) / 100.0 < address_match_threshold:
                continue
            store_name_lower = (r.get("store_name") or "").strip().lower()
            if not _store_name_matches_chain_for_backfill(store_name_lower, norm, name_lower):
                continue
            ids_to_update.append(r["id"])
        if not ids_to_update:
            return 0
        update_payload: Dict[str, Any] = {
            "store_chain_id": chain_id,
            "store_location_id": location_id,
            "store_address": canonical_address,
            "store_name": chain_name.strip(),
        }
        supabase.table("record_summaries").update(update_payload).in_("id", ids_to_update).execute()
        logger.info(
            f"Backfilled unlinked record_summaries: set chain_id={chain_id[:8]}..., location_id={location_id[:8]}... for {len(ids_to_update)} rows"
        )
        return len(ids_to_update)
    except Exception as e:
        logger.warning(f"_backfill_unlinked_record_summaries_for_location failed: {e}")
        return 0


def run_backfill_store_locations(location_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Backfill record_summaries.store_location_id (and store_address/store_name) for all
    active store_locations, or for a single location if location_id is given.
    Uses normalized address matching (Suite/Unit/Ste stripped) so receipts with
    "Suite 101" vs "Unit 101" still match the same store_location.
    Returns: { "total_updated": int, "per_location": [ { "location_id", "chain_id", "updated": int } ] }
    """
    supabase = _get_client()
    # Fetch locations: all active or the one specified
    loc_q = supabase.table("store_locations").select("*").eq("is_active", True)
    if location_id:
        loc_q = loc_q.eq("id", location_id)
    loc_res = loc_q.execute()
    locations = list(loc_res.data or [])
    if not locations:
        return {"total_updated": 0, "per_location": []}
    chain_ids = {loc["chain_id"] for loc in locations if loc.get("chain_id")}
    chains = {}
    if chain_ids:
        ch_res = supabase.table("store_chains").select("id, name").in_("id", list(chain_ids)).execute()
        for c in ch_res.data or []:
            chains[c["id"]] = (c.get("name") or "").strip()
    total_updated = 0
    per_location: List[Dict[str, Any]] = []
    for loc in locations:
        cid = loc.get("chain_id")
        lid = loc.get("id")
        if not cid or not lid:
            continue
        chain_name = chains.get(cid) or ""
        n = backfill_record_summaries_for_store_location(
            chain_id=cid,
            location_id=lid,
            location_row=loc,
            address_match_threshold=0.85,
            chain_name=chain_name or None,
        )
        # Also link record_summaries that have store_chain_id NULL but address+name match (e.g. Walmart Supercentre)
        norm_name = None
        if chain_name:
            ch_res = supabase.table("store_chains").select("normalized_name").eq("id", cid).limit(1).execute()
            if ch_res.data:
                norm_name = (ch_res.data[0].get("normalized_name") or "").strip()
        n2 = _backfill_unlinked_record_summaries_for_location(
            chain_id=cid,
            location_id=lid,
            location_row=loc,
            chain_name=chain_name,
            normalized_name=norm_name,
            address_match_threshold=0.85,
        )
        total_updated += n + n2
        per_location.append({"location_id": lid, "chain_id": cid, "updated": n + n2})
    return {"total_updated": total_updated, "per_location": per_location}


def create_store_candidate(
    chain_name: str,
    receipt_id: Optional[str] = None,
    source: str = "llm",
    llm_result: Optional[Dict[str, Any]] = None,
    suggested_chain_id: Optional[str] = None,
    suggested_location_id: Optional[str] = None,
    confidence_score: Optional[float] = None
) -> Optional[str]:
    """
    Create a store candidate in store_candidates table with complete information.
    
    Args:
        chain_name: Store chain name
        receipt_id: Receipt ID that triggered this candidate
        source: Source of the candidate ('ocr', 'llm', 'user')
        llm_result: Optional LLM result to extract structured data (address, phone, currency, etc.)
        suggested_chain_id: Optional suggested chain_id from fuzzy matching
        suggested_location_id: Optional suggested location_id from fuzzy matching
        confidence_score: Optional confidence score (0.00 - 1.00)
        
    Returns:
        candidate_id (UUID string) or None
    """
    if not chain_name:
        return None
    
    if source not in ('ocr', 'llm', 'user'):
        raise ValueError(f"Invalid source: {source}")
    
    supabase = _get_client()
    
    normalized_name = chain_name.lower().strip()
    
    # Extract structured data from LLM result
    metadata = {}
    if llm_result:
        receipt = llm_result.get("receipt", {})
        
        # Extract address information (structured)
        address_info = {}
        if receipt.get("merchant_address"):
            address_info["full_address"] = receipt.get("merchant_address")
        
        # Prefer address_line1/address_line2 (prompt output) so DB gets correct split; fallback to address1/address2
        addr1 = receipt.get("address_line1") or receipt.get("address1")
        addr2 = receipt.get("address_line2") or receipt.get("address2")
        if addr1:
            address_info["address_line1"] = addr1
            address_info["address1"] = addr1
        if addr2:
            address_info["address_line2"] = addr2
            address_info["address2"] = addr2
        if receipt.get("city"):
            address_info["city"] = receipt.get("city")
        if receipt.get("state"):
            address_info["state"] = receipt.get("state")
        if receipt.get("country"):
            address_info["country"] = receipt.get("country")
        if receipt.get("zip_code") or receipt.get("zipcode"):
            address_info["zip_code"] = receipt.get("zip_code") or receipt.get("zipcode")
            address_info["zipcode"] = address_info["zip_code"]

        # If structured fields are missing but we have merchant_address, try to parse it
        if not address_info.get("address_line1") and not address_info.get("address1") and receipt.get("merchant_address"):
            try:
                from ...processors.enrichment.address_matcher import extract_address_components_from_string
                parsed_components = extract_address_components_from_string(receipt.get("merchant_address"))
                if parsed_components:
                    if parsed_components.get("address1"):
                        address_info["address1"] = parsed_components["address1"]
                        address_info.setdefault("address_line1", parsed_components["address1"])
                    if parsed_components.get("address2"):
                        address_info["address2"] = parsed_components["address2"]
                        address_info.setdefault("address_line2", parsed_components["address2"])
                    if parsed_components.get("city"):
                        address_info["city"] = parsed_components["city"]
                    if parsed_components.get("state"):
                        address_info["state"] = parsed_components["state"]
                    if parsed_components.get("country"):
                        address_info["country"] = parsed_components["country"]
                    if parsed_components.get("zipcode"):
                        address_info["zipcode"] = parsed_components["zipcode"]
                        address_info["zip_code"] = parsed_components["zipcode"]
            except Exception as e:
                logger.warning(f"Failed to parse address from merchant_address: {e}")
        
        if address_info:
            metadata["address"] = address_info
        
        # Extract contact information
        if receipt.get("merchant_phone"):
            metadata["phone"] = receipt.get("merchant_phone")
        
        # Extract currency
        if receipt.get("currency"):
            metadata["currency"] = receipt.get("currency")
        
        # Extract purchase date/time (for reference)
        if receipt.get("purchase_date"):
            metadata["purchase_date"] = receipt.get("purchase_date")
        if receipt.get("purchase_time"):
            metadata["purchase_time"] = receipt.get("purchase_time")
    
    payload = {
        "raw_name": chain_name,
        "normalized_name": normalized_name,
        "source": source,
        "receipt_id": receipt_id,
        "suggested_chain_id": suggested_chain_id,
        "suggested_location_id": suggested_location_id,
        "confidence_score": confidence_score,
        "status": "pending",
        "metadata": metadata if metadata else None,
    }
    
    try:
        res = supabase.table("store_candidates").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to create store candidate, no data returned")
        candidate_id = res.data[0]["id"]
        logger.info(f"Created store candidate: {candidate_id} for '{chain_name}' (receipt_id={receipt_id})")
        return candidate_id
    except Exception as e:
        logger.error(f"Failed to create store candidate: {e}")
        return None


def list_receipts_by_user(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    List receipt_status rows for a user, most recent first.
    Attaches store_name from record_summaries for card display.
    record_summaries and fallback LLM-run queries are issued in parallel.
    """
    supabase = _get_client()
    res = (
        supabase.table("receipt_status")
        .select("id, uploaded_at, current_status, current_stage")
        .eq("user_id", user_id)
        .order("uploaded_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return []

    receipt_ids = [r["id"] for r in rows]

    def _fetch_summaries():
        return (
            supabase.table("record_summaries")
            .select("receipt_id, store_name, store_chain_id, receipt_date")
            .in_("receipt_id", receipt_ids)
            .execute()
        )

    def _fetch_fallback_names():
        return _merchant_name_from_latest_llm_run(supabase, receipt_ids)

    # Parallel: record_summaries + fallback LLM merchant names
    sum_res = None
    fallback_names: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_summaries = pool.submit(_fetch_summaries)
        f_fallback = pool.submit(_fetch_fallback_names)
        sum_res = f_summaries.result()
        fallback_names = f_fallback.result()

    summary_by_id = {s["receipt_id"]: s for s in (sum_res.data or [])}
    chain_ids = {s.get("store_chain_id") for s in (sum_res.data or []) if s.get("store_chain_id")}
    chain_name_by_id: Dict[str, str] = {}
    if chain_ids:
        ch = supabase.table("store_chains").select("id, name").in_("id", list(chain_ids)).execute()
        if ch.data:
            # 统一用 str(id) 做 key，避免 UUID 与字符串比较取不到
            chain_name_by_id = {str(c["id"]): c.get("name", "") for c in ch.data}

    for r in rows:
        s = summary_by_id.get(r["id"]) or {}
        r["store_chain_id"] = s.get("store_chain_id")
        sid = s.get("store_chain_id")
        raw_chain = chain_name_by_id.get(str(sid)) if sid else None
        r["chain_name"] = _store_name_to_title_case(raw_chain) if raw_chain else None
        r["store_name"] = r["chain_name"] if r["chain_name"] else (_store_name_to_title_case(s.get("store_name")) or s.get("store_name"))
        r["receipt_date"] = s.get("receipt_date")
        # Apply pre-fetched fallback merchant name for receipts still without a store_name
        if not (r.get("store_name") or "").strip():
            name = fallback_names.get(str(r["id"]))
            if name:
                r["store_name"] = _store_name_to_title_case(name) or name

    return rows


def _merchant_name_from_latest_llm_run(supabase: Client, receipt_ids: List[str]) -> Dict[str, str]:
    """For each receipt_id, get merchant_name from the latest LLM run's output_payload (receipt.merchant_name or _metadata.merchant_name)."""
    if not receipt_ids:
        return {}
    try:
        runs = (
            supabase.table("receipt_processing_runs")
            .select("receipt_id, output_payload, created_at")
            .in_("receipt_id", receipt_ids)
            .eq("stage", "llm")
            .eq("status", "pass")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        logger.debug("Fallback merchant_name from runs failed: %s", e)
        return {}
    out: Dict[str, str] = {}
    for row in (runs.data or []):
        rid = row.get("receipt_id")
        if rid is not None:
            rid = str(rid)
        if not rid or rid in out:
            continue
        payload = row.get("output_payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        name = (payload.get("receipt") or {}).get("merchant_name") or (payload.get("_metadata") or {}).get("merchant_name")
        if name and isinstance(name, str) and name.strip():
            out[rid] = name.strip()
    return out


def get_receipt_detail_for_user(receipt_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """
    Build workflow-style JSON for one receipt (same shape as POST /api/receipt/workflow response).
    Verifies receipt belongs to user. Returns None if not found or not owner.
    Uses parallel DB queries where possible to reduce latency (summary+items, then chains+locations+categories+runs).
    """
    supabase = _get_client()
    rec = (
        supabase.table("receipt_status")
        .select("id, user_id, uploaded_at, current_status")
        .eq("id", receipt_id)
        .limit(1)
        .execute()
    )
    if not rec.data or rec.data[0]["user_id"] != user_id:
        return None
    status_row = rec.data[0]

    def _fetch_summary() -> Any:
        return (
            supabase.table("record_summaries")
            .select("*")
            .eq("receipt_id", receipt_id)
            .limit(1)
            .execute()
        )

    def _fetch_items() -> Any:
        return (
            supabase.table("record_items")
            .select("id, product_name, quantity, unit, unit_price, line_total, on_sale, original_price, discount_amount, item_index, category_id, category_source")
            .eq("receipt_id", receipt_id)
            .order("item_index")
            .execute()
        )

    with ThreadPoolExecutor(max_workers=4) as ex:
        summary_future = ex.submit(_fetch_summary)
        items_future = ex.submit(_fetch_items)
        summary = summary_future.result()
        items = items_future.result()

    receipt_data: Dict[str, Any] = {}
    items_data: List[Dict[str, Any]] = []
    s = summary.data[0] if summary.data else None

    def _norm_cat_key(val: Any) -> str:
        if val is None:
            return ""
        s_val = str(val).strip().lower()
        return s_val if s_val else ""

    cat_ids: List[str] = []
    if items.data:
        cat_ids = list({_norm_cat_key(it.get("category_id")) for it in items.data if it.get("category_id")})
        cat_ids = [x for x in cat_ids if x]

    needs_review = status_row.get("current_status") == "needs_review"
    # store_name and store_address are already denormalized at write time (save/update_receipt_summary);
    # no need to read store_chains or store_locations here.
    cats_result: Any = None
    runs_result: Any = None

    def _fetch_categories() -> Any:
        if not cat_ids:
            return None
        return supabase.table("categories").select("id, path").in_("id", cat_ids).execute()

    def _fetch_runs() -> Any:
        if not needs_review:
            return None
        return (
            supabase.table("receipt_processing_runs")
            .select("output_payload")
            .eq("receipt_id", receipt_id)
            .in_("stage", ["vision_primary", "vision_escalation"])
            .eq("status", "pass")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

    with ThreadPoolExecutor(max_workers=2) as ex2:
        futures = []
        if cat_ids:
            futures.append(("cats", ex2.submit(_fetch_categories)))
        if needs_review:
            futures.append(("runs", ex2.submit(_fetch_runs)))
        for key, fut in futures:
            res = fut.result()
            if key == "cats":
                cats_result = res
            elif key == "runs":
                runs_result = res

    category_path_by_id: Dict[str, str] = {}
    if cats_result and cats_result.data:
        for c in cats_result.data:
            if c.get("id") is not None and c.get("path") is not None:
                category_path_by_id[_norm_cat_key(c["id"])] = c["path"]

    if s:
        raw_from_db = s.get("store_name")
        display_store_name = _store_name_to_title_case(raw_from_db) if raw_from_db else raw_from_db
        display_address = s.get("store_address")
        logger.info(
            "[STORE_NAME_DEBUG] get_receipt_detail receipt_id=%s display_store_name=%r",
            receipt_id, display_store_name,
        )
        receipt_data = {
            "merchant_name": display_store_name,
            "merchant_address": display_address,
            "merchant_phone": None,
            "country": None,
            "currency": s.get("currency") or "USD",
            "purchase_date": s.get("receipt_date"),
            "purchase_time": None,
            "subtotal": _cents_to_dollars(s.get("subtotal")) if s.get("subtotal") is not None else None,
            "tax": _cents_to_dollars(s.get("tax")) if s.get("tax") is not None else None,
            "total": _cents_to_dollars(s.get("total")) if s.get("total") is not None else None,
            "payment_method": s.get("payment_method"),
            "card_last4": s.get("payment_last4"),
        }
        info = s.get("information") or {}
        other = info.get("other_info") or {}
        if other.get("merchant_phone"):
            receipt_data["merchant_phone"] = other["merchant_phone"]
        if other.get("purchase_time"):
            receipt_data["purchase_time"] = _purchase_time_to_24h(other["purchase_time"]) or other["purchase_time"]

    if items.data:
        for it in items.data:
            cid = it.get("category_id")
            path = category_path_by_id.get(_norm_cat_key(cid)) if cid else None
            items_data.append({
                "id": str(it["id"]) if it.get("id") else None,
                "product_name": it.get("product_name"),
                "quantity": _quantity_to_display(it.get("quantity")),
                "unit": it.get("unit"),
                "unit_price": _cents_to_dollars(it.get("unit_price")),
                "line_total": _cents_to_dollars(it.get("line_total")),
                "on_sale": it.get("on_sale") or False,
                "original_price": _cents_to_dollars(it.get("original_price")),
                "discount_amount": _cents_to_dollars(it.get("discount_amount")),
                "category_path": path,
                "category_id": str(cid) if cid else None,
                "category_source": it.get("category_source"),
            })

    review_feedback: Optional[str] = None
    review_metadata: Optional[Dict[str, Any]] = None
    if runs_result and runs_result.data and len(runs_result.data) > 0:
        try:
            out = runs_result.data[0].get("output_payload") or {}
            meta = out.get("_metadata") or {}
            notes = (meta.get("sum_check_notes") or "").strip()
            reasoning = (meta.get("reasoning") or "").strip()
            if notes:
                review_feedback = notes
            elif meta.get("validation_status") == "needs_review":
                review_feedback = "Model requested manual review."
            review_metadata = {
                "validation_status": meta.get("validation_status"),
                "reasoning": reasoning or None,
                "sum_check_notes": notes or None,
                "item_count_on_receipt": meta.get("item_count_on_receipt"),
                "item_count_extracted": meta.get("item_count_extracted"),
                "confidence": meta.get("confidence"),
            }
            review_metadata = {k: v for k, v in review_metadata.items() if v is not None}
        except Exception as e:
            logger.debug("Could not load review_feedback for needs_review receipt: %s", e)

    # When store_chain_id is set, store_name in record_summaries was already overwritten with chain name at write time
    chain_name_out = (
        _store_name_to_title_case(s.get("store_name")) if (s and s.get("store_chain_id") and s.get("store_name")) else None
    )
    return {
        "success": True,
        "receipt_id": receipt_id,
        "status": status_row.get("current_status") or "success",
        "review_feedback": review_feedback,
        "review_metadata": review_metadata,
        "data": {
            "receipt": receipt_data,
            "items": items_data,
            "chain_name": chain_name_out,
        },
    }


def update_record_item_category(
    receipt_id: str,
    item_id: str,
    user_id: str,
    category_id: Optional[str],
) -> bool:
    """
    Update record_items.category_id for one item. Verifies receipt belongs to user and item belongs to receipt.
    category_id can be None to clear. Returns True if updated, False if not found or access denied.
    """
    supabase = _get_client()
    rec = supabase.table("receipt_status").select("id").eq("id", receipt_id).eq("user_id", user_id).limit(1).execute()
    if not rec.data:
        return False
    row = supabase.table("record_items").select("id").eq("id", item_id).eq("receipt_id", receipt_id).limit(1).execute()
    if not row.data:
        return False
    if category_id:
        cat = supabase.table("categories").select("id").eq("id", category_id).limit(1).execute()
        if not cat.data:
            return False
    payload: Dict[str, Any] = {"category_id": category_id if category_id else None, "category_source": "user_override"}
    supabase.table("record_items").update(payload).eq("id", item_id).eq("receipt_id", receipt_id).execute()
    return True


def _parse_analytics_period(period: str, value: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse period (month|quarter|year) and value to (start_date, end_date) for filtering receipt_date. Returns (None, None) if invalid."""
    if not period or not value:
        return None, None
    period = (period or "").strip().lower()
    value = (value or "").strip()
    try:
        if period == "month":
            # value e.g. "2026-01"
            if len(value) >= 7 and value[4] == "-":
                y, m = int(value[:4]), int(value[5:7])
                if 1 <= m <= 12:
                    start = f"{y}-{m:02d}-01"
                    if m == 12:
                        end = f"{y + 1}-01-01"
                    else:
                        end = f"{y}-{m + 1:02d}-01"
                    return start, end
        elif period == "quarter":
            # value e.g. "2026-Q1"
            if "Q" in value.upper() and len(value) >= 6:
                parts = value.upper().split("Q")
                y = int(parts[0].strip())
                q = int(parts[1].strip())
                if 1 <= q <= 4:
                    m_start = (q - 1) * 3 + 1
                    start = f"{y}-{m_start:02d}-01"
                    if q == 4:
                        end = f"{y + 1}-01-01"
                    else:
                        end = f"{y}-{m_start + 3:02d}-01"
                    return start, end
        elif period == "year":
            # value e.g. "2026"
            if len(value) == 4 and value.isdigit():
                y = int(value)
                return f"{y}-01-01", f"{y + 1}-01-01"
    except (ValueError, TypeError):
        pass
    return None, None


def get_user_analytics_summary(
    user_id: str,
    period: Optional[str] = None,
    value: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Aggregate spending for the user: by store, by payment card, by category L1/L2/L3.
    If period (month|quarter|year) and value are set, filter by receipt_date within that range.
    Returns amounts in cents; frontend can convert to dollars and compute percentages.
    """
    supabase = _get_client()
    # Receipts owned by user
    recs = (
        supabase.table("receipt_status")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )
    receipt_ids = [r["id"] for r in (recs.data or [])]
    if not receipt_ids:
        return {
            "total_receipts": 0,
            "total_amount_cents": 0,
            "by_store": [],
            "by_payment": [],
            "by_category_l1": [],
            "by_category_l2": [],
            "by_category_l3": [],
            "unclassified_count": 0,
            "unclassified_amount_cents": 0,
        }

    start_date, end_date = _parse_analytics_period(period or "", value or "")

    # Summaries: total (cents), store_chain_id, store_name, payment_method, payment_last4; optionally filter by receipt_date
    sum_q = (
        supabase.table("record_summaries")
        .select("receipt_id, total, store_chain_id, store_name, payment_method, payment_last4")
        .in_("receipt_id", receipt_ids)
    )
    if start_date and end_date:
        sum_q = sum_q.gte("receipt_date", start_date).lt("receipt_date", end_date)
    sum_res = sum_q.execute()
    summaries = sum_res.data or []
    # Restrict to these receipt_ids for category aggregation
    receipt_ids_in_range = [s["receipt_id"] for s in summaries]
    chain_ids = {s.get("store_chain_id") for s in summaries if s.get("store_chain_id")}
    chain_name_by_id: Dict[str, str] = {}
    if chain_ids:
        ch = supabase.table("store_chains").select("id, name").in_("id", list(chain_ids)).execute()
        if ch.data:
            chain_name_by_id = {str(c["id"]): c.get("name", "") for c in ch.data}

    # By store
    store_totals: Dict[str, Dict[str, Any]] = {}
    # By payment
    payment_totals: Dict[str, Dict[str, Any]] = {}
    total_amount_cents = 0
    for s in summaries:
        total_cents = s.get("total")
        if total_cents is not None:
            total_amount_cents += int(total_cents)
        store_key = None
        if s.get("store_chain_id"):
            store_key = chain_name_by_id.get(str(s["store_chain_id"])) or s.get("store_name") or "Unknown"
        else:
            store_key = (s.get("store_name") or "Unknown").strip() or "Unknown"
        if store_key not in store_totals:
            store_totals[store_key] = {"amount_cents": 0, "count": 0}
        store_totals[store_key]["amount_cents"] += int(s.get("total") or 0)
        store_totals[store_key]["count"] += 1

        pay_method = normalize_payment_type(s.get("payment_method") or "")
        raw_last4 = (s.get("payment_last4") or "").strip()
        last4 = "".join(c for c in raw_last4 if c.isdigit())[-4:] if raw_last4 else ""
        pay_key = f"{pay_method} ****{last4}" if (pay_method or last4) else "Other"
        if pay_key not in payment_totals:
            payment_totals[pay_key] = {"amount_cents": 0, "count": 0}
        payment_totals[pay_key]["amount_cents"] += int(s.get("total") or 0)
        payment_totals[pay_key]["count"] += 1

    by_store = [
        {"name": k, "amount_cents": v["amount_cents"], "count": v["count"]}
        for k, v in sorted(store_totals.items(), key=lambda x: -x[1]["amount_cents"])
    ]
    by_payment = [
        {"name": k, "amount_cents": v["amount_cents"], "count": v["count"]}
        for k, v in sorted(payment_totals.items(), key=lambda x: -x[1]["amount_cents"])
    ]

    # By category: from record_items (line_total cents, category_id) — only receipts in selected period
    items_res = (
        supabase.table("record_items")
        .select("line_total, category_id, user_feedback")
        .in_("receipt_id", receipt_ids_in_range)
        .execute()
    )
    # Filter out items the user has dismissed (user_feedback->dismissed = true)
    raw_items = items_res.data or []
    items = [it for it in raw_items if not ((it.get("user_feedback") or {}).get("dismissed"))]
    cat_ids = list({str(it.get("category_id")) for it in items if it.get("category_id")})
    category_path_by_id: Dict[str, str] = {}
    if cat_ids:
        cats = supabase.table("categories").select("id, path").in_("id", cat_ids).execute()
        if cats.data:
            for c in cats.data:
                if c.get("id") is not None and c.get("path") is not None:
                    category_path_by_id[str(c["id"])] = (c["path"] or "").strip()

    l1_totals: Dict[str, int] = {}
    l2_totals: Dict[str, int] = {}
    l3_totals: Dict[str, int] = {}
    for it in items:
        line_cents = it.get("line_total")
        if line_cents is None:
            continue
        line_cents = int(line_cents)
        cid = it.get("category_id")
        path = category_path_by_id.get(str(cid)) if cid else ""
        parts = [p.strip() for p in (path or "").split("/") if p.strip()]
        if parts:
            l1 = parts[0]
            l2 = "/".join(parts[:2]) if len(parts) >= 2 else l1
            l3 = "/".join(parts[:3]) if len(parts) >= 3 else (l2 if len(parts) >= 2 else l1)
            l1_totals[l1] = l1_totals.get(l1, 0) + line_cents
            l2_totals[l2] = l2_totals.get(l2, 0) + line_cents
            l3_totals[l3] = l3_totals.get(l3, 0) + line_cents

    unclassified_count = 0
    unclassified_amount_cents = 0
    for it in items:
        if it.get("category_id"):
            continue
        line_cents = it.get("line_total")
        if line_cents is not None:
            unclassified_amount_cents += int(line_cents)
            unclassified_count += 1

    by_category_l1 = [
        {"name": k, "amount_cents": v} for k, v in sorted(l1_totals.items(), key=lambda x: -x[1])
    ]
    by_category_l2 = [
        {"name": k, "amount_cents": v} for k, v in sorted(l2_totals.items(), key=lambda x: -x[1])
    ]
    by_category_l3 = [
        {"name": k, "amount_cents": v} for k, v in sorted(l3_totals.items(), key=lambda x: -x[1])
    ]

    return {
        "total_receipts": len(summaries),
        "total_amount_cents": total_amount_cents,
        "by_store": by_store,
        "by_payment": by_payment,
        "by_category_l1": by_category_l1,
        "by_category_l2": by_category_l2,
        "by_category_l3": by_category_l3,
        "unclassified_count": unclassified_count,
        "unclassified_amount_cents": unclassified_amount_cents,
    }


def get_user_unclassified_items(user_id: str) -> List[Dict[str, Any]]:
    """
    Return list of unclassified line items (category_id IS NULL) for the user.
    Each item: receipt_id, record_item_id, receipt_date, store_display_name, store_address, product_name, line_total_cents.
    """
    supabase = _get_client()
    recs = (
        supabase.table("receipt_status")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )
    receipt_ids = [r["id"] for r in (recs.data or [])]
    if not receipt_ids:
        return []
    items = (
        supabase.table("record_items")
        .select("id, receipt_id, product_name, line_total, user_marked_idk, user_feedback")
        .in_("receipt_id", receipt_ids)
        .is_("category_id", "null")
        .order("item_index")
        .execute()
    )
    if not items.data:
        return []
    summary_ids = list({r["receipt_id"] for r in items.data})
    summaries = (
        supabase.table("record_summaries")
        .select("receipt_id, receipt_date, store_name, store_chain_id, store_address")
        .in_("receipt_id", summary_ids)
        .execute()
    )
    summary_by_rid: Dict[str, Dict[str, Any]] = {}
    chain_ids = set()
    for s in (summaries.data or []):
        summary_by_rid[str(s["receipt_id"])] = s
        if s.get("store_chain_id"):
            chain_ids.add(s["store_chain_id"])
    chain_name_by_id: Dict[str, str] = {}
    if chain_ids:
        ch = supabase.table("store_chains").select("id, name").in_("id", list(chain_ids)).execute()
        if ch.data:
            chain_name_by_id = {str(c["id"]): c.get("name", "") for c in ch.data}

    out: List[Dict[str, Any]] = []
    for it in items.data:
        # Skip items the user has dismissed
        uf = it.get("user_feedback") or {}
        if uf.get("dismissed"):
            continue
        rid = it.get("receipt_id")
        s = summary_by_rid.get(str(rid)) if rid else {}
        store_name = (s.get("store_name") or "").strip()
        chain_id = s.get("store_chain_id")
        display_name = (chain_name_by_id.get(str(chain_id)) or store_name or "Unknown").strip()
        out.append({
            "receipt_id": str(rid) if rid else None,
            "record_item_id": str(it["id"]) if it.get("id") else None,
            "receipt_date": s.get("receipt_date"),
            "store_display_name": display_name,
            "store_address": s.get("store_address"),
            "product_name": it.get("product_name") or "",
            "line_total_cents": it.get("line_total"),
            "user_marked_idk": bool(it.get("user_marked_idk")),
        })
    return out


def mark_item_idk(user_id: str, record_item_id: str) -> bool:
    """Mark that user said 'I don't know' for this line item. Verifies item belongs to user. Returns True if updated."""
    supabase = _get_client()
    item = (
        supabase.table("record_items")
        .select("id, user_id")
        .eq("id", record_item_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not item.data:
        return False
    try:
        supabase.table("record_items").update({"user_marked_idk": True}).eq("id", record_item_id).execute()
        return True
    except Exception:
        return False


def dismiss_item(user_id: str, record_item_id: str, reason: str, comment: Optional[str]) -> bool:
    """
    Dismiss a record_item from the user's unclassified list.
    - reason: "incorrect_item" | "other"
    - comment: optional freetext; required (and used) when reason == "other"
    - Writes user_feedback JSONB on the record_items row.
    - If reason == "other": also inserts a row in classification_review for admin.
    Returns True on success.
    """
    import datetime
    supabase = _get_client()
    item = (
        supabase.table("record_items")
        .select("id, user_id, product_name, receipt_id")
        .eq("id", record_item_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not item.data:
        return False
    row = item.data[0]

    feedback = {
        "dismissed": True,
        "reason": reason,
        "comment": comment or "",
        "dismissed_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    try:
        supabase.table("record_items").update({"user_feedback": feedback}).eq("id", record_item_id).execute()
    except Exception:
        return False

    # For "other" escalate to classification_review for admin
    if reason == "other" and (comment or "").strip():
        try:
            # Get store_chain_id from record_summaries for this receipt
            chain_id = None
            try:
                sm = (
                    supabase.table("record_summaries")
                    .select("store_chain_id")
                    .eq("receipt_id", row.get("receipt_id"))
                    .limit(1)
                    .execute()
                )
                if sm.data:
                    chain_id = sm.data[0].get("store_chain_id")
            except Exception:
                pass

            note = f"[USER FEEDBACK] {(comment or '').strip()}"
            supabase.table("classification_review").insert({
                "raw_product_name": row.get("product_name") or "",
                "source_record_item_id": record_item_id,
                "store_chain_id": chain_id,
                "status": "pending",
                "normalized_name": note,
                "category_id": None,
                "match_type": None,
            }).execute()
        except Exception:
            pass  # escalation failure is non-fatal

    return True


def get_idk_now_classified(user_id: str) -> List[str]:
    """
    Return record_item_ids that user had marked IDK and that now have category_id set.
    Clears user_marked_idk on those items. Auth required.
    """
    supabase = _get_client()
    items = (
        supabase.table("record_items")
        .select("id")
        .eq("user_id", user_id)
        .eq("user_marked_idk", True)
        .not_.is_("category_id", "null")
        .execute()
    )
    now_classified = [str(r["id"]) for r in (items.data or [])]
    if now_classified:
        try:
            supabase.table("record_items").update({"user_marked_idk": False}).in_("id", now_classified).execute()
        except Exception:
            pass
    return now_classified


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _cents_to_dollars(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return int(val) / 100.0
    except (TypeError, ValueError):
        return None


def _quantity_to_display(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return int(val) / 100.0
    except (TypeError, ValueError):
        return None
