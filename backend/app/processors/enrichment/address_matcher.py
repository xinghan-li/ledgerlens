"""
Address Matcher: Match and correct store addresses using fuzzy matching.

Features:
1. Fuzzy match store names against canonical database
2. Correct common OCR errors (Hwy->Huy, Blvd->Bivd, etc.)
3. Fill in missing address information
4. Standardize address formats
"""
import logging
import re
from typing import Dict, Any, Optional, Tuple, List
from rapidfuzz import fuzz, process
from ...services.database.supabase_client import _get_client
from ...config import settings

logger = logging.getLogger(__name__)

# All locations with address_string (address-first matching; no single overwrite per chain)
_locations_list: List[Dict[str, Any]] = []
_locations_by_chain_name: Dict[str, List[Dict[str, Any]]] = {}
_locations_by_location_name: Dict[str, Dict[str, Any]] = {}
_cache_populated = False


def _normalize_address_for_compare(s: Optional[str]) -> str:
    """Normalize for matching: strip Suite/Unit/Ste, trailing country, expand abbrevs (PK->park, RD->road, etc.)."""
    if not s or not isinstance(s, str):
        return ""
    one = " ".join(s.lower().replace("\n", " ").replace("\r", " ").split())
    one = re.sub(
        r"[,]?\s*(?:suite|unit|ste|apt|#)\s*-?\s*[\d\w-]+",
        " ",
        one,
        flags=re.IGNORECASE,
    )
    one = re.sub(r"\b(?:us|usa|ca|canada)\s*$", "", one, flags=re.IGNORECASE)
    one = " ".join(one.split())
    from .address_abbreviations import expand_address_abbreviations
    return expand_address_abbreviations(one)


def _fix_ocr_address(s: Optional[str]) -> Optional[str]:
    """
    最早层 OCR 纠错：在地址匹配前把常见误识替换掉（如 Huy -> Hwy），
    并统一为与 DB 常用写法一致（Hwy -> Highway）便于模糊匹配。
    只做整词替换，避免误伤。
    """
    if not s or not isinstance(s, str):
        return s
    # Hwy 常被 OCR 成 Huy，先纠错
    s = re.sub(r"\bHuy\b", "Hwy", s, flags=re.IGNORECASE)
    # 统一为 Highway 便于与 DB 里 "highway" 全拼匹配
    s = re.sub(r"\bHwy\b", "Highway", s, flags=re.IGNORECASE)
    return s


def fix_ocr_address(s: Optional[str]) -> Optional[str]:
    """Public alias for _fix_ocr_address (Huy->Hwy, etc.) for use in workflow/normalizer."""
    return _fix_ocr_address(s)


def _street_number_typo_match(addr_norm: str, db_addr: str) -> bool:
    """
    True if the two addresses differ only in the first token (street number) by at most 1–2 characters.
    Handles common OCR errors (e.g. 13109 vs 18109: 1↔8, 0↔9; or single digit 1 vs 8).
    For 5-digit street numbers allow up to 2 char diffs; otherwise 1.
    """
    if not addr_norm or not db_addr:
        return False
    a_tokens = addr_norm.split()
    b_tokens = db_addr.split()
    if len(a_tokens) != len(b_tokens) or len(a_tokens) < 2:
        return False
    if a_tokens[0] == b_tokens[0]:
        return True
    first_a, first_b = a_tokens[0], b_tokens[0]
    if len(first_a) != len(first_b) or len(first_a) < 2:
        return False
    diffs = sum(1 for x, y in zip(first_a, first_b) if x != y)
    max_diffs = 2 if len(first_a) >= 4 else 1
    return diffs <= max_diffs


def _populate_store_cache():
    """Populate: list of all locations + address_string; index by chain/location name (multi-location chains not overwritten)."""
    global _cache_populated, _locations_list, _locations_by_chain_name, _locations_by_location_name

    if _cache_populated:
        return
    try:
        supabase = _get_client()
        locations_response = supabase.table("store_locations").select("*").eq("is_active", True).execute()
        chains_response = supabase.table("store_chains").select("*").eq("is_active", True).execute()
        chains_by_id = {c["id"]: c for c in (chains_response.data or [])}

        if not locations_response.data:
            logger.warning("No store locations found in database")
            _cache_populated = True
            return

        for location in locations_response.data:
            chain_id = location.get("chain_id")
            chain = chains_by_id.get(chain_id, {}) if chain_id else {}
            chain_name_raw = chain.get("name", "")
            chain_name = (chain_name_raw or "").lower()
            location_name = (location.get("name") or "").lower()

            location_data = {
                "store_name": location.get("name", ""),
                "chain_name": chain_name_raw,
                "store_aliases": chain.get("aliases", []),
                "address_line1": location.get("address_line1"),
                "address_line2": location.get("address_line2"),
                "city": location.get("city"),
                "state": location.get("state"),
                "country": location.get("country_code"),
                "zip_code": location.get("zip_code"),
                "phone": location.get("phone"),
                "id": location.get("id"),
                "chain_id": location.get("chain_id"),
            }
            addr_parts = [location_data["address_line1"] or ""]
            if location_data.get("address_line2"):
                addr_parts.append(str(location_data["address_line2"]).strip())
            if location_data.get("city") and location_data.get("state") and location_data.get("zip_code"):
                addr_parts.append(f"{location_data['city']}, {location_data['state']} {location_data['zip_code']}")
            if location_data.get("country"):
                addr_parts.append(location_data["country"])
            location_data["address_string"] = "\n".join(p for p in addr_parts if p)

            _locations_list.append(location_data)
            if chain_name:
                _locations_by_chain_name.setdefault(chain_name, []).append(location_data)
            if location_name:
                _locations_by_location_name[location_name] = location_data
            if chain and chain.get("aliases"):
                for alias in chain.get("aliases", []):
                    _locations_by_chain_name.setdefault(alias.lower(), []).append(location_data)

        _cache_populated = True
        logger.info(f"Loaded {len(_locations_list)} store locations (address-first matching)")
    except Exception as e:
        logger.error(f"Failed to load store locations: {type(e).__name__}: {e}", exc_info=True)


def match_store(
    store_name: Optional[str],
    store_address: Optional[str] = None,
    high_confidence_threshold: float = 0.85,
    low_confidence_threshold: float = 0.50,
    address_match_threshold: float = 0.90,
) -> Dict[str, Any]:
    """
    Match store: **address-first** (receipt address fuzzy vs DB addresses; high confidence => that store).
    If no address or address match fails, fall back to name matching (single-location chains only).
    """
    result = {
        "matched": False,
        "chain_id": None,
        "location_id": None,
        "suggested_chain_id": None,
        "suggested_location_id": None,
        "confidence_score": None,
        "location_data": None,
    }
    if not store_name:
        return result
    store_address = _fix_ocr_address(store_address)
    _addr_preview = (store_address[:100] + "...") if store_address and len(store_address) > 100 else store_address
    logger.info("[STORE_DEBUG] match_store IN: store_name=%r, store_address=%r", store_name, _addr_preview)

    _populate_store_cache()
    if not _locations_list:
        logger.warning("Store locations list is empty")
        return result

    store_name_lower = store_name.lower().strip()
    addr_norm = _normalize_address_for_compare(store_address) if store_address else ""
    logger.info("[STORE_DEBUG] match_store: addr_norm has %s chars (address path=%s)", len(addr_norm), bool(addr_norm))

    # 1) When receipt has address: ONLY match by address. No match => do NOT fall back to name (never assign another location of same chain).
    if addr_norm:
        best_score = 0
        best_location: Optional[Dict[str, Any]] = None
        for loc in _locations_list:
            db_addr = _normalize_address_for_compare(loc.get("address_string"))
            if not db_addr:
                continue
            score = fuzz.token_sort_ratio(addr_norm, db_addr) / 100.0
            if score > best_score:
                best_score = score
                best_location = loc
        # Accept match if above threshold, OR if just below threshold but only street number typo (e.g. 13109 vs 18109)
        db_addr_best = _normalize_address_for_compare(best_location.get("address_string")) if best_location else ""
        street_number_typo_ok = bool(
            best_location and db_addr_best and _street_number_typo_match(addr_norm, db_addr_best)
        )
        if best_location and (best_score >= address_match_threshold or street_number_typo_ok):
            if street_number_typo_ok and best_score < address_match_threshold:
                logger.info(
                    "[STORE_DEBUG] Near-miss (score %.2f) accepted via street number typo match: addr_norm=%r vs db=%r",
                    best_score, addr_norm[:60], db_addr_best[:60],
                )
            chain_lower = (best_location.get("chain_name") or "").lower()
            loc_name_lower = (best_location.get("store_name") or "").lower()
            name_ok = (
                fuzz.ratio(store_name_lower, chain_lower) >= 80
                or fuzz.ratio(store_name_lower, loc_name_lower) >= 80
                or store_name_lower in chain_lower
                or chain_lower in store_name_lower
            )
            if name_ok:
                logger.info(
                    f"Address match: '{store_name}' + address -> {best_location.get('store_name')} (score: {best_score:.2f})"
                )
                result.update({
                    "matched": True,
                    "chain_id": best_location.get("chain_id"),
                    "location_id": best_location.get("id"),
                    "confidence_score": best_score if best_score >= address_match_threshold else address_match_threshold,
                    "location_data": best_location,
                })
                logger.info("[STORE_DEBUG] match_store OUT (address match): matched=True, location_id=%s", result.get("location_id"))
                return result
            logger.debug(f"Address match score {best_score:.2f} but store name mismatch, skipping")
        # Had address but no DB location matched => no match (caller may use best_score + phone for address correction)
        logger.info(f"Receipt has address but no store_location matched (best score: {best_score:.2f}). Will not assign any location.")
        if best_location and best_score >= 0.80:
            logger.info(
                "[STORE_DEBUG] near-miss: addr_norm=%r | db_addr=%r (compare lengths/tokens to see why score < 0.90)",
                addr_norm[:80], db_addr_best[:80],
            )
        result["best_score"] = best_score
        result["best_location"] = best_location
        logger.info("[STORE_DEBUG] match_store OUT (address path, no match): matched=False, best_score=%s", best_score)
        return result

    # 2) No address on receipt: name-only (location name or single-location chain only)
    if store_name_lower in _locations_by_location_name:
        matched_location = _locations_by_location_name[store_name_lower]
        logger.info(f"Exact location name match: {store_name} -> {matched_location.get('store_name')}")
        result.update({
            "matched": True,
            "chain_id": matched_location.get("chain_id"),
            "location_id": matched_location.get("id"),
            "confidence_score": 1.0,
            "location_data": matched_location,
        })
        logger.info("[STORE_DEBUG] match_store OUT (exact location name): matched=True, location_id=%s", result.get("location_id"))
        return result

    # Fuzzy by location names
    loc_names = list(_locations_by_location_name.keys())
    fuzzy_one = process.extractOne(store_name_lower, loc_names, scorer=fuzz.ratio, score_cutoff=low_confidence_threshold * 100)
    if fuzzy_one:
        name_key, score, _ = fuzzy_one
        matched_location = _locations_by_location_name[name_key]
        conf = score / 100.0
        if conf >= high_confidence_threshold:
            logger.info(f"Fuzzy location name match: '{store_name}' -> '{matched_location.get('store_name')}' ({score:.1f}%)")
            result.update({
                "matched": True,
                "chain_id": matched_location.get("chain_id"),
                "location_id": matched_location.get("id"),
                "confidence_score": conf,
                "location_data": matched_location,
            })
            logger.info("[STORE_DEBUG] match_store OUT (fuzzy location name): matched=True, location_id=%s", result.get("location_id"))
            return result

    # By chain name: only accept if this chain has exactly one location (no disambiguation without address)
    chain_names = list(_locations_by_chain_name.keys())
    fuzzy_chain = process.extractOne(store_name_lower, chain_names, scorer=fuzz.ratio, score_cutoff=low_confidence_threshold * 100)
    if fuzzy_chain:
        chain_key, score, _ = fuzzy_chain
        locations_for_chain = _locations_by_chain_name[chain_key]
        conf = score / 100.0
        if len(locations_for_chain) == 1 and conf >= high_confidence_threshold:
            matched_location = locations_for_chain[0]
            logger.info(f"Single-location chain match: '{store_name}' -> {matched_location.get('store_name')} ({score:.1f}%)")
            result.update({
                "matched": True,
                "chain_id": matched_location.get("chain_id"),
                "location_id": matched_location.get("id"),
                "confidence_score": conf,
                "location_data": matched_location,
            })
            logger.info("[STORE_DEBUG] match_store OUT (single-location chain): matched=True, location_id=%s", result.get("location_id"))
            return result
        if len(locations_for_chain) > 1:
            logger.info(
                f"Chain '{chain_key}' has {len(locations_for_chain)} locations; need address to disambiguate (have address: {bool(addr_norm)})"
            )
            if not addr_norm and conf >= low_confidence_threshold:
                result["suggested_chain_id"] = locations_for_chain[0].get("chain_id")
                result["suggested_location_id"] = locations_for_chain[0].get("id")
                result["confidence_score"] = conf
                result["location_data"] = locations_for_chain[0]
                logger.info("[STORE_DEBUG] match_store OUT (multi-location chain, no address): suggested_location_id=%s", result.get("suggested_location_id"))
                return result

    logger.warning(f"No match for store '{store_name}' (address provided: {bool(addr_norm)}). Consider adding to database.")
    logger.info("[STORE_DEBUG] match_store OUT (no match): matched=False")
    return result


def _phone_10_digits(s: Optional[str]) -> str:
    """Extract exactly 10 digits from phone string (strip parentheses, dashes, spaces). For 11-digit (e.g. 1-xxx) use last 10."""
    if not s or not isinstance(s, str):
        return ""
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def correct_address(
    llm_result: Dict[str, Any],
    auto_correct: bool = True,
    phone_assist_threshold: float = 0.6,
) -> Dict[str, Any]:
    """
    Correct store address using fuzzy matching and canonical database.
    Used after first-round vision: if address match > phone_assist_threshold and
    receipt phone (10 digits) equals location phone (10 digits), accept and correct
    so that slightly damaged addresses still match.

    Args:
        llm_result: LLM processing result
        auto_correct: If True, automatically replace address; if False, only add suggestions
        phone_assist_threshold: When not matched, accept best candidate if score >= this and 10-digit phone match (default 0.6)
    Returns:
        Updated LLM result with corrected address (if auto_correct=True)
        or with correction suggestions in tbd section
    """
    receipt = llm_result.get("receipt", {})
    store_name = receipt.get("merchant_name")  # Keep merchant_name for backward compatibility
    store_address = _fix_ocr_address(receipt.get("merchant_address"))
    _addr_preview = (store_address[:100] + "...") if store_address and len(store_address) > 100 else store_address
    logger.info("[STORE_DEBUG] correct_address IN: merchant_name=%r, merchant_address=%r", store_name, _addr_preview)

    if not store_name:
        logger.debug("No store name in receipt, skipping address correction")
        return llm_result

    # Match store (address + name; may return best_score / best_location when not matched)
    match_result = match_store(store_name, store_address)
    logger.info(
        "[STORE_DEBUG] correct_address match_result: matched=%s, location_id=%s, best_score=%s",
        match_result.get("matched"),
        match_result.get("location_id"),
        match_result.get("best_score"),
    )

    matched_location = match_result.get("location_data")
    phone_assisted = False
    if not match_result.get("matched"):
        # Phone-assisted match: score > threshold and 10-digit phone full match => still correct address (e.g. damaged 13109 vs 18109)
        best_score = match_result.get("best_score") or 0
        best_location = match_result.get("best_location")
        if best_location and best_score >= phone_assist_threshold:
            receipt_10 = _phone_10_digits(receipt.get("merchant_phone"))
            loc_10 = _phone_10_digits(best_location.get("phone"))
            if receipt_10 and loc_10 and receipt_10 == loc_10:
                matched_location = best_location
                phone_assisted = True
                logger.info(
                    "[STORE_DEBUG] correct_address: accepting by phone match (score=%.2f, 10-digit phone match)",
                    best_score,
                )
        if not matched_location:
            logger.debug("No canonical address found for: %s", store_name)
            return llm_result

    if not matched_location:
        return llm_result

    # Build canonical address
    canonical_address = build_address_string(matched_location)
    
    # Compare with OCR address
    if store_address:
        # Normalize for comparison
        ocr_normalized = store_address.lower().replace("\n", " ").replace("  ", " ")
        canonical_normalized = canonical_address.lower().replace("\n", " ").replace("  ", " ")
        
        # Calculate similarity
        similarity = fuzz.ratio(ocr_normalized, canonical_normalized)
        
        if similarity >= 95:
            logger.info(f"Address already correct (similarity: {similarity}%)")
            return llm_result
        elif similarity >= 70:
            logger.info(
                f"Address has minor differences (similarity: {similarity}%), "
                f"auto-correcting: {auto_correct}"
            )
        else:
            logger.warning(
                f"Address has major differences (similarity: {similarity}%), "
                f"may need manual review"
            )
    else:
        logger.info(f"No OCR address, filling in canonical address")
    
    # Update receipt with canonical information (ensure country is set from database)
    if auto_correct:
        receipt["merchant_name"] = matched_location["store_name"]
        receipt["merchant_address"] = canonical_address
        receipt["merchant_phone"] = matched_location.get("phone")

        # CRITICAL: Always set country from canonical database, even if LLM extracted it
        receipt["country"] = matched_location["country"]

        # Also overwrite the structured address fields so build_merchant_address_from_structured
        # (called in categorize_receipt) does not reconstruct an incorrect address from
        # the LLM-hallucinated address_line1 / city / state / zip_code values.
        receipt["address_line1"] = matched_location.get("address_line1") or ""
        receipt["address_line2"] = matched_location.get("address_line2") or ""
        receipt["city"] = matched_location.get("city") or ""
        receipt["state"] = matched_location.get("state") or ""
        receipt["zip_code"] = matched_location.get("zip_code") or ""

        # Add metadata about correction
        if "_metadata" not in llm_result:
            llm_result["_metadata"] = {}

        llm_result["_metadata"]["address_correction"] = {
            "matched": True,
            "canonical_store_id": matched_location["id"],
            "canonical_store_name": matched_location["store_name"],
            "chain_id": matched_location.get("chain_id"),
            "location_id": matched_location.get("id"),
            "original_store_name": store_name,
            "original_address": store_address,
            "corrected": True,
            "phone_assisted": phone_assisted,
        }

        logger.info(f"Address corrected for: {store_name}")
    else:
        # Add suggestion to tbd
        if "tbd" not in llm_result:
            llm_result["tbd"] = {}
        
        llm_result["tbd"]["address_suggestion"] = {
            "canonical_store_name": matched_location["store_name"],
            "canonical_address": canonical_address,
            "reason": "Fuzzy match found canonical address"
        }
        
        logger.info(f"Address suggestion added for: {store_name}")
    
    return llm_result


def _format_unit_for_address(address_line2: Optional[str]) -> Optional[str]:
    """
    From verified DB we have a single value (e.g. 101). Always output as "Unit 101"
    so we don't depend on DB storing "Ste 101" vs "101". If DB already has a prefix
    (Suite/Ste/Unit/Apt), normalize to "Unit <number>" for consistency.
    """
    if not address_line2 or not str(address_line2).strip():
        return None
    line2 = str(address_line2).strip()
    # Already "Unit 101" / "Suite 101" / "Ste 101" / "Apt 101" / "#101" → extract number, output "Unit 101"
    m = re.search(r"(?:Suite|Ste|Unit|Apt|#)\s*(\d+[\w-]*)", line2, re.I)
    if m:
        return f"Unit {m.group(1).strip()}"
    # Bare number (e.g. "101") → "Unit 101"
    if re.match(r"^\d+[\w-]*$", line2):
        return f"Unit {line2}"
    # Other (e.g. "Building B"): keep as-is
    return line2


def build_address_string(location: Dict[str, Any]) -> str:
    """
    Build standardized address string from location dict.
    First line: address2-address1 (unit-street) when both present for readability.
    """
    line1 = (location.get("address_line1") or "").strip()
    line2_raw = (location.get("address_line2") or "").strip()
    # Extract number for "101-19715 Highway 99" style
    line2_num = None
    if line2_raw:
        m = re.search(r"(?:Suite|Ste|Unit|Apt|#)\s*(\d+[\w-]*)", line2_raw, re.I)
        line2_num = m.group(1).strip() if m else (line2_raw if re.match(r"^\d+[\w-]*$", line2_raw) else line2_raw)
    if line1 and line2_num:
        first_line = f"{line2_num}-{line1}"
    elif line1:
        first_line = line1
    elif line2_num:
        first_line = f"Unit {line2_num}" if re.match(r"^\d+[\w-]*$", str(line2_num)) else str(line2_num)
    else:
        first_line = ""
    parts = [first_line] if first_line else []
    city_state_zip = f"{location.get('city', '')}, {location.get('state', '')} {location.get('zip_code', '')}".strip(", ")
    if city_state_zip.strip():
        parts.append(city_state_zip)
    if location.get("country"):
        parts.append(location["country"])
    return "\n".join(p for p in parts if p)


def get_address_components(location: Dict[str, Any]) -> Dict[str, str]:
    """
    Get address components as separate fields for CSV export.
    
    Args:
        location: Store location dict from database or receipt
    
    Returns:
        Dictionary with address components
    """
    return {
        "address1": location.get("address_line1", ""),
        "address2": location.get("address_line2", ""),
        "city": location.get("city", ""),
        "state": location.get("state", ""),
        "country": location.get("country", ""),
        "zipcode": location.get("zip_code", "")
    }


def parse_full_address_to_components(full_address: Optional[str]) -> Dict[str, str]:
    """
    Parse a single-line full address into address1, address2, city, state, zip.
    Used for store_candidates metadata so frontend can show split fields.

    Rules:
    1. Leading numbers with "-": e.g. "#3000-10153 King George Blvd" or "Suite 101-123 Main St"
       -> Left of "-" (digits only, strip Suite/Unit/Apt/Ste) -> address2; rest -> address1 + city/state/zip.
    2. address1 = street (first segment before comma, or after stripping address2 prefix).
    3. After last comma: "City, ST Zip" -> city from second-to-last segment, state = 2-letter (strip .), zip = rest.
    """
    out = {
        "address1": "",
        "address2": "",
        "city": "",
        "state": "",
        "country": "",
        "zipcode": "",
    }
    if not full_address or not isinstance(full_address, str):
        return out
    raw = " ".join(full_address.replace("\n", " ").split()).strip()
    if not raw:
        return out

    # Optional: trailing country
    if raw.upper().endswith(" USA") or raw.upper().endswith(", USA"):
        out["country"] = "US"
        raw = re.sub(r",?\s*USA\s*$", "", raw, flags=re.IGNORECASE).strip()
    elif raw.upper().endswith(" US") or raw.upper().endswith(", US"):
        out["country"] = "US"
        raw = re.sub(r",?\s*US\s*$", "", raw, flags=re.IGNORECASE).strip()
    elif raw.upper().endswith(" CANADA") or raw.upper().endswith(", CANADA"):
        out["country"] = "CA"
        raw = re.sub(r",?\s*CANADA\s*$", "", raw, flags=re.IGNORECASE).strip()
    elif raw.upper().endswith(" CA") or raw.upper().endswith(", CA"):
        out["country"] = "CA"
        raw = re.sub(r",?\s*CA\s*$", "", raw, flags=re.IGNORECASE).strip()

    # 1) Leading unit: (#|Suite|Unit|Apt|Ste)? digits "-" -> address2 = digits only
    unit_match = re.match(
        r"^\s*(?:\#|(?:Suite|Unit|Apt|Ste)\s*)?(\d+)\s*-\s*(.+)$",
        raw,
        re.IGNORECASE,
    )
    if unit_match:
        out["address2"] = unit_match.group(1)
        raw = unit_match.group(2).strip()

    # 2) Split by comma: "Street, City, ST Zip" or "Street, City, ST"
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return out
    if len(parts) >= 3:
        out["address1"] = parts[0]
        out["city"] = parts[-2]
        state_zip = parts[-1]
    elif len(parts) == 2:
        out["address1"] = parts[0]
        state_zip = parts[1]
    else:
        out["address1"] = parts[0]
        return out

    # 3) State: 2-letter (optional .); Zip: rest (Canadian can be "V6X 3L9")
    state_zip_match = re.match(r"^([A-Za-z]{2})\.?\s*(.*)$", state_zip.strip())
    if state_zip_match:
        out["state"] = state_zip_match.group(1).strip().upper().replace(".", "")
        zip_part = state_zip_match.group(2).strip()
        if zip_part:
            out["zipcode"] = zip_part
    if not out["country"] and out["zipcode"]:
        if re.match(r"^[A-Z]\d[A-Z]\s*\d[A-Z]\d$", out["zipcode"].replace(" ", "")):
            out["country"] = "CA"
        elif re.match(r"^\d{5}(-\d{4})?$", out["zipcode"]):
            out["country"] = "US"
    return out


def extract_address_components_from_string(address_str: Optional[str]) -> Dict[str, str]:
    """
    Parse address string into components (fallback when no canonical match).
    Prefers single-line comma format via parse_full_address_to_components when applicable.
    
    Args:
        address_str: Full address string (may contain newlines)
    
    Returns:
        Dictionary with parsed address components (address1, address2, city, state, country, zipcode)
    """
    if not address_str:
        return {
            "address1": "",
            "address2": "",
            "city": "",
            "state": "",
            "country": "",
            "zipcode": ""
        }

    one_line = " ".join(address_str.replace("\n", " ").split()).strip()
    if one_line and "," in one_line:
        parsed = parse_full_address_to_components(one_line)
        if parsed.get("address1") or parsed.get("city") or parsed.get("state") or parsed.get("zipcode"):
            return parsed

    # Split by newlines for multi-line format
    lines = [line.strip() for line in address_str.split("\n") if line.strip()]
    
    components = {
        "address1": "",
        "address2": "",
        "city": "",
        "state": "",
        "country": "",
        "zipcode": ""
    }
    
    if not lines:
        return components
    
    # Last line might be country
    if len(lines) > 0 and lines[-1].upper() in ["USA", "CANADA", "US", "CA"]:
        components["country"] = "US" if lines[-1].upper() in ("USA", "US") else "CA"
        lines = lines[:-1]
    
    if not lines:
        return components
    
    first_line = lines[0]
    
    # Check for suite/unit patterns:
    suite_match = re.search(r'^(.*?),\s*(Suite|Ste|Unit|Apt|#)\s*(.+)$', first_line, re.IGNORECASE)
    if suite_match:
        components["address1"] = suite_match.group(1).strip()
        components["address2"] = f"{suite_match.group(2)} {suite_match.group(3)}".strip()
    elif re.match(r'^#\d+[-\s]\d+', first_line):
        unit_match = re.match(r'^(#\d+)[-\s](.+)$', first_line)
        if unit_match:
            components["address2"] = unit_match.group(1).strip()
            components["address1"] = unit_match.group(2).strip()
        else:
            components["address1"] = first_line
    else:
        components["address1"] = first_line
    
    if len(lines) > 1:
        last_line = lines[-1].strip()
        zip_only = re.match(r'^[A-Z0-9\s\-]{3,12}$', last_line) and re.search(r'\d', last_line)
        if len(lines) >= 2 and zip_only:
            city_state_line = lines[-2].strip()
            match = re.search(r'^(.*?),\s*([A-Za-z]{2})\s*$', city_state_line, re.IGNORECASE)
            if match:
                components["city"] = match.group(1).strip()
                components["state"] = match.group(2).strip().upper()
                components["zipcode"] = last_line
            else:
                components["city"] = city_state_line
                components["zipcode"] = last_line
        else:
            city_state_zip = last_line
            match = re.search(r'^(.*?),\s*([A-Z]{2})\s+([A-Z0-9\s\-]+)$', city_state_zip)
            if match:
                components["city"] = match.group(1).strip()
                components["state"] = match.group(2).strip()
                components["zipcode"] = match.group(3).strip()
            else:
                match = re.search(r'^(.*?),\s*([A-Z]{2})\s*$', city_state_zip)
                if match:
                    components["city"] = match.group(1).strip()
                    components["state"] = match.group(2).strip()
                else:
                    components["city"] = city_state_zip
    
    if len(lines) > 2 and not components["address2"]:
        components["address2"] = ", ".join(lines[1:-1])
    
    return components


def clear_cache():
    """Clear store locations cache (for testing or after updates)."""
    global _cache_populated, _locations_list, _locations_by_chain_name, _locations_by_location_name
    _locations_list.clear()
    _locations_by_chain_name.clear()
    _locations_by_location_name.clear()
    _cache_populated = False
    logger.info("Store locations cache cleared")


# Backward compatibility alias
match_merchant = match_store
