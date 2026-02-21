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
    if not s or not isinstance(s, str):
        return ""
    return " ".join(s.lower().replace("\n", " ").replace("\r", " ").split())


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
            score = fuzz.ratio(addr_norm, db_addr) / 100.0
            if score > best_score:
                best_score = score
                best_location = loc
        if best_location and best_score >= address_match_threshold:
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
                    "confidence_score": best_score,
                    "location_data": best_location,
                })
                logger.info("[STORE_DEBUG] match_store OUT (address match): matched=True, location_id=%s", result.get("location_id"))
                return result
            logger.debug(f"Address match score {best_score:.2f} but store name mismatch, skipping")
        # Had address but no DB location matched => no match (do not fall back to name; send to store_candidates)
        logger.info(f"Receipt has address but no store_location matched (best score: {best_score:.2f}). Will not assign any location.")
        logger.info("[STORE_DEBUG] match_store OUT (address path, no match): matched=False")
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


def correct_address(
    llm_result: Dict[str, Any],
    auto_correct: bool = True
) -> Dict[str, Any]:
    """
    Correct store address using fuzzy matching and canonical database.
    
    Args:
        llm_result: LLM processing result
        auto_correct: If True, automatically replace address; if False, only add suggestions
    
    Returns:
        Updated LLM result with corrected address (if auto_correct=True)
        or with correction suggestions in tbd section
    """
    receipt = llm_result.get("receipt", {})
    store_name = receipt.get("merchant_name")  # Keep merchant_name for backward compatibility
    store_address = receipt.get("merchant_address")
    _addr_preview = (store_address[:100] + "...") if store_address and len(store_address) > 100 else store_address
    logger.info("[STORE_DEBUG] correct_address IN: merchant_name=%r, merchant_address=%r", store_name, _addr_preview)
    
    if not store_name:
        logger.debug("No store name in receipt, skipping address correction")
        return llm_result
    
    # Match store
    match_result = match_store(store_name, store_address)
    logger.info(
        "[STORE_DEBUG] correct_address match_result: matched=%s, location_id=%s",
        match_result.get("matched"),
        match_result.get("location_id"),
    )
    
    if not match_result.get("matched"):
        logger.debug(f"No canonical address found for: {store_name}")
        return llm_result
    
    matched_location = match_result.get("location_data")
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
        
        # Add metadata about correction
        if "_metadata" not in llm_result:
            llm_result["_metadata"] = {}
        
        llm_result["_metadata"]["address_correction"] = {
            "matched": True,
            "canonical_store_id": matched_location["id"],
            "canonical_store_name": matched_location["store_name"],
            "original_store_name": store_name,
            "original_address": store_address,
            "corrected": True
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
    Uses verified DB values only; for address_line2 (unit/suite) we concat "Unit "
    in front so output is canonical (e.g. "Unit 101") regardless of whether DB
    stored "101" or "Ste 101".
    """
    parts = [location["address_line1"]]
    
    line2 = _format_unit_for_address(location.get("address_line2"))
    if line2:
        parts.append(line2)
    
    # City, State Zip
    city_state_zip = f"{location['city']}, {location['state']} {location['zip_code']}"
    parts.append(city_state_zip)
    
    # Country (if not USA, or always include)
    if location.get("country"):
        parts.append(location["country"])
    
    return "\n".join(parts)


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


def extract_address_components_from_string(address_str: Optional[str]) -> Dict[str, str]:
    """
    Parse address string into components (fallback when no canonical match).
    
    Args:
        address_str: Full address string (may contain newlines)
    
    Returns:
        Dictionary with parsed address components
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
    
    # Split by newlines
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
        components["country"] = lines[-1].upper()
        lines = lines[:-1]
    
    if not lines:
        return components
    
    # First line is address1, but may contain suite/unit info
    import re
    first_line = lines[0]
    
    # Check for suite/unit patterns:
    # Pattern 1: "123 Main St, Suite 101" or "123 Main St, Ste 101"
    suite_match = re.search(r'^(.*?),\s*(Suite|Ste|Unit|Apt|#)\s*(.+)$', first_line, re.IGNORECASE)
    if suite_match:
        components["address1"] = suite_match.group(1).strip()
        components["address2"] = f"{suite_match.group(2)} {suite_match.group(3)}".strip()
    # Pattern 2: Canadian format "#1000-3700 No.3 Rd" (unit-building)
    elif re.match(r'^#\d+[-\s]\d+', first_line):
        unit_match = re.match(r'^(#\d+)[-\s](.+)$', first_line)
        if unit_match:
            components["address2"] = unit_match.group(1).strip()
            components["address1"] = unit_match.group(2).strip()
        else:
            components["address1"] = first_line
    else:
        components["address1"] = first_line
    
    # Last line(s): city, state, zip. Common formats:
    # A) One line: "Kirkland, WA 98034"
    # B) Two lines: "Kirkland, WA" + "98034"
    if len(lines) > 1:
        last_line = lines[-1].strip()
        # Check if last line is zip-only (e.g. "98034" or "98034-1234")
        zip_only = re.match(r'^[A-Z0-9\s\-]{3,12}$', last_line) and re.search(r'\d', last_line)
        if len(lines) >= 2 and zip_only:
            # Format B: second-to-last is "City, ST"
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
            # Format A or single line: "City, ST Zip" or "City, ST"
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
    
    # Middle lines (if any) are address2, ONLY if address2 wasn't already set from suite parsing
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
