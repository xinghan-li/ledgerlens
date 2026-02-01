"""
Address Matcher: Match and correct store addresses using fuzzy matching.

Features:
1. Fuzzy match store names against canonical database
2. Correct common OCR errors (Hwy->Huy, Blvd->Bivd, etc.)
3. Fill in missing address information
4. Standardize address formats
"""
import logging
from typing import Dict, Any, Optional, Tuple
from rapidfuzz import fuzz, process
from ...services.database.supabase_client import _get_client
from ...config import settings

logger = logging.getLogger(__name__)

# Cache for store locations
_store_locations_cache: Dict[str, Dict[str, Any]] = {}
_cache_populated = False


def _populate_store_cache():
    """Populate store locations cache from database."""
    global _cache_populated, _store_locations_cache
    
    if _cache_populated:
        return
    
    try:
        supabase = _get_client()
        
        # Query store_locations
        locations_response = supabase.table("store_locations").select("*").eq("is_active", True).execute()
        
        # Query store_chains
        chains_response = supabase.table("store_chains").select("*").eq("is_active", True).execute()
        
        # Build chain lookup
        chains_by_id = {}
        if chains_response.data:
            for chain in chains_response.data:
                chains_by_id[chain["id"]] = chain
        
        if locations_response.data:
            for location in locations_response.data:
                chain_id = location.get("chain_id")
                chain = chains_by_id.get(chain_id, {}) if chain_id else {}
                
                chain_name = chain.get("name", "").lower() if chain else ""
                location_name = location.get("name", "").lower()
                
                # Build location data structure
                location_data = {
                    "store_name": location.get("name", ""),  # Location name for matching
                    "chain_name": chain.get("name", ""),  # Chain name
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
                
                # Index by chain name
                if chain_name:
                    _store_locations_cache[chain_name] = location_data
                
                # Also index by location name
                if location_name:
                    _store_locations_cache[location_name] = location_data
                
                # Index by chain aliases
                if chain and chain.get("aliases"):
                    for alias in chain.get("aliases", []):
                        _store_locations_cache[alias.lower()] = location_data
            
            _cache_populated = True
            logger.info(f"Loaded {len(locations_response.data)} store locations into cache")
        else:
            logger.warning("No store locations found in database")
    
    except Exception as e:
        logger.error(
            f"Failed to load store locations from database: {type(e).__name__}: {e}",
            exc_info=True
        )


def match_store(
    store_name: Optional[str],
    store_address: Optional[str] = None,
    high_confidence_threshold: float = 0.85,
    low_confidence_threshold: float = 0.50
) -> Dict[str, Any]:
    """
    Match store name against canonical database using fuzzy matching.
    
    Args:
        store_name: OCR-extracted store name
        store_address: OCR-extracted address (optional, for disambiguation)
        high_confidence_threshold: Threshold for high confidence match (0.0-1.0), default 0.85
        low_confidence_threshold: Threshold for low confidence match (0.0-1.0), default 0.50
    
    Returns:
        Dict with:
        - 'matched': bool - Whether a high confidence match was found
        - 'chain_id': Optional[str] - Matched chain_id (only if high confidence)
        - 'location_id': Optional[str] - Matched location_id (only if high confidence)
        - 'suggested_chain_id': Optional[str] - Suggested chain_id (if low confidence)
        - 'suggested_location_id': Optional[str] - Suggested location_id (if low confidence)
        - 'confidence_score': Optional[float] - Confidence score (0.0-1.0)
        - 'location_data': Optional[Dict] - Full location data (if any match found)
    """
    result = {
        "matched": False,
        "chain_id": None,
        "location_id": None,
        "suggested_chain_id": None,
        "suggested_location_id": None,
        "confidence_score": None,
        "location_data": None
    }
    
    if not store_name:
        return result
    
    # Ensure cache is populated
    _populate_store_cache()
    
    if not _store_locations_cache:
        logger.warning("Store locations cache is empty")
        return result
    
    # Normalize input
    store_name_lower = store_name.lower().strip()
    
    # Exact match first
    if store_name_lower in _store_locations_cache:
        matched_location = _store_locations_cache[store_name_lower]
        logger.info(f"Exact match found for store: {store_name}")
        result.update({
            "matched": True,
            "chain_id": matched_location.get("chain_id"),
            "location_id": matched_location.get("id"),
            "confidence_score": 1.0,
            "location_data": matched_location
        })
        return result
    
    # Fuzzy match
    # Build list of all searchable names
    searchable_names = list(_store_locations_cache.keys())
    
    # Use rapidfuzz to find best match (with low threshold to get any match)
    fuzzy_result = process.extractOne(
        store_name_lower,
        searchable_names,
        scorer=fuzz.ratio,
        score_cutoff=low_confidence_threshold * 100  # rapidfuzz uses 0-100 scale
    )
    
    if fuzzy_result:
        matched_name, score, _ = fuzzy_result
        matched_location = _store_locations_cache[matched_name]
        confidence = score / 100.0  # Convert to 0.0-1.0 scale
        
        if confidence >= high_confidence_threshold:
            # High confidence match - use directly
            logger.info(
                f"High confidence match found for '{store_name}': "
                f"'{matched_location['store_name']}' (score: {score:.1f}%)"
            )
            result.update({
                "matched": True,
                "chain_id": matched_location.get("chain_id"),
                "location_id": matched_location.get("id"),
                "confidence_score": confidence,
                "location_data": matched_location
            })
        else:
            # Low confidence match - return as suggestion
            logger.info(
                f"Low confidence match found for '{store_name}': "
                f"'{matched_location['store_name']}' (score: {score:.1f}%) - will be saved as suggestion"
            )
            result.update({
                "matched": False,  # Not matched, but has suggestion
                "chain_id": None,  # Not high confidence, don't use directly
                "location_id": None,
                "confidence_score": confidence,
                "location_data": matched_location,
                "suggested_chain_id": matched_location.get("chain_id"),
                "suggested_location_id": matched_location.get("id")
            })
        return result
    
    # No match found - provide detailed context for debugging
    num_candidates = len(searchable_names)
    logger.warning(
        f"No match found for store '{store_name}'. "
        f"Searched {num_candidates} candidates with threshold {low_confidence_threshold * 100:.1f}%. "
        f"Consider adding this store to the database."
    )
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
    
    if not store_name:
        logger.debug("No store name in receipt, skipping address correction")
        return llm_result
    
    # Match store
    match_result = match_store(store_name, store_address)
    
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


def build_address_string(location: Dict[str, Any]) -> str:
    """
    Build standardized address string from location dict.
    
    Args:
        location: Store location dict from database
    
    Returns:
        Formatted address string
    """
    parts = [location["address_line1"]]
    
    if location.get("address_line2"):
        parts.append(location["address_line2"])
    
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
    
    # Second to last line is usually city, state, zip
    if len(lines) > 1:
        city_state_zip = lines[-1]
        
        # Pattern 1: "City, ST Zipcode" (e.g., "Fremont, CA 94555")
        match = re.search(r'^(.*?),\s*([A-Z]{2})\s+([A-Z0-9\s\-]+)$', city_state_zip)
        if match:
            components["city"] = match.group(1).strip()
            components["state"] = match.group(2).strip()
            components["zipcode"] = match.group(3).strip()
        else:
            # Pattern 2: "City, State" (no zipcode)
            match = re.search(r'^(.*?),\s*([A-Z]{2})$', city_state_zip)
            if match:
                components["city"] = match.group(1).strip()
                components["state"] = match.group(2).strip()
            else:
                # Can't parse, put whole line in city
                components["city"] = city_state_zip
    
    # Middle lines (if any) are address2, ONLY if address2 wasn't already set from suite parsing
    if len(lines) > 2 and not components["address2"]:
        components["address2"] = ", ".join(lines[1:-1])
    
    return components


def clear_cache():
    """Clear store locations cache (for testing or after updates)."""
    global _cache_populated, _store_locations_cache
    _store_locations_cache.clear()
    _cache_populated = False
    logger.info("Store locations cache cleared")


# Backward compatibility alias
match_merchant = match_store
