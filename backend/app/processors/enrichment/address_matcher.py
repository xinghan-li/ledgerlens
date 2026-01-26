"""
Address Matcher: Match and correct merchant addresses using fuzzy matching.

Features:
1. Fuzzy match merchant names against canonical database
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

# Cache for merchant locations
_merchant_locations_cache: Dict[str, Dict[str, Any]] = {}
_cache_populated = False


def _populate_merchant_cache():
    """Populate merchant locations cache from database."""
    global _cache_populated, _merchant_locations_cache
    
    if _cache_populated:
        return
    
    try:
        supabase = _get_client()
        response = supabase.table("merchant_locations").select("*").eq("is_active", True).execute()
        
        if response.data:
            for location in response.data:
                # Index by canonical name
                _merchant_locations_cache[location["merchant_name"].lower()] = location
                
                # Also index by aliases
                if location.get("merchant_aliases"):
                    for alias in location["merchant_aliases"]:
                        _merchant_locations_cache[alias.lower()] = location
            
            _cache_populated = True
            logger.info(f"Loaded {len(response.data)} merchant locations into cache")
        else:
            logger.warning("No merchant locations found in database")
    
    except Exception as e:
        logger.error(f"Failed to load merchant locations: {e}")


def match_merchant(
    merchant_name: Optional[str],
    merchant_address: Optional[str] = None,
    threshold: float = 0.85
) -> Optional[Dict[str, Any]]:
    """
    Match merchant name against canonical database using fuzzy matching.
    
    Args:
        merchant_name: OCR-extracted merchant name
        merchant_address: OCR-extracted address (optional, for disambiguation)
        threshold: Fuzzy match threshold (0.0-1.0)
    
    Returns:
        Matched merchant location dict, or None if no match
    """
    if not merchant_name:
        return None
    
    # Ensure cache is populated
    _populate_merchant_cache()
    
    if not _merchant_locations_cache:
        logger.warning("Merchant locations cache is empty")
        return None
    
    # Normalize input
    merchant_name_lower = merchant_name.lower().strip()
    
    # Exact match first
    if merchant_name_lower in _merchant_locations_cache:
        logger.info(f"Exact match found for merchant: {merchant_name}")
        return _merchant_locations_cache[merchant_name_lower]
    
    # Fuzzy match
    # Build list of all searchable names
    searchable_names = list(_merchant_locations_cache.keys())
    
    # Use rapidfuzz to find best match
    result = process.extractOne(
        merchant_name_lower,
        searchable_names,
        scorer=fuzz.ratio,
        score_cutoff=threshold * 100  # rapidfuzz uses 0-100 scale
    )
    
    if result:
        matched_name, score, _ = result
        matched_location = _merchant_locations_cache[matched_name]
        
        logger.info(
            f"Fuzzy match found for '{merchant_name}': "
            f"'{matched_location['merchant_name']}' (score: {score:.1f}%)"
        )
        
        return matched_location
    
    logger.warning(f"No match found for merchant: {merchant_name}")
    return None


def correct_address(
    llm_result: Dict[str, Any],
    auto_correct: bool = True
) -> Dict[str, Any]:
    """
    Correct merchant address using fuzzy matching and canonical database.
    
    Args:
        llm_result: LLM processing result
        auto_correct: If True, automatically replace address; if False, only add suggestions
    
    Returns:
        Updated LLM result with corrected address (if auto_correct=True)
        or with correction suggestions in tbd section
    """
    receipt = llm_result.get("receipt", {})
    merchant_name = receipt.get("merchant_name")
    merchant_address = receipt.get("merchant_address")
    
    if not merchant_name:
        logger.debug("No merchant name in receipt, skipping address correction")
        return llm_result
    
    # Match merchant
    matched_location = match_merchant(merchant_name, merchant_address)
    
    if not matched_location:
        logger.debug(f"No canonical address found for: {merchant_name}")
        return llm_result
    
    # Build canonical address
    canonical_address = build_address_string(matched_location)
    
    # Compare with OCR address
    if merchant_address:
        # Normalize for comparison
        ocr_normalized = merchant_address.lower().replace("\n", " ").replace("  ", " ")
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
        receipt["merchant_name"] = matched_location["merchant_name"]
        receipt["merchant_address"] = canonical_address
        receipt["merchant_phone"] = matched_location.get("phone")
        
        # CRITICAL: Always set country from canonical database, even if LLM extracted it
        receipt["country"] = matched_location["country"]
        
        # Add metadata about correction
        if "_metadata" not in llm_result:
            llm_result["_metadata"] = {}
        
        llm_result["_metadata"]["address_correction"] = {
            "matched": True,
            "canonical_merchant_id": matched_location["id"],
            "canonical_merchant_name": matched_location["merchant_name"],
            "original_merchant_name": merchant_name,
            "original_address": merchant_address,
            "corrected": True
        }
        
        logger.info(f"Address corrected for: {merchant_name}")
    else:
        # Add suggestion to tbd
        if "tbd" not in llm_result:
            llm_result["tbd"] = {}
        
        llm_result["tbd"]["address_suggestion"] = {
            "canonical_merchant_name": matched_location["merchant_name"],
            "canonical_address": canonical_address,
            "reason": "Fuzzy match found canonical address"
        }
        
        logger.info(f"Address suggestion added for: {merchant_name}")
    
    return llm_result


def build_address_string(location: Dict[str, Any]) -> str:
    """
    Build standardized address string from location dict.
    
    Args:
        location: Merchant location dict from database
    
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
        location: Merchant location dict from database or receipt
    
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
    """Clear merchant locations cache (for testing or after updates)."""
    global _cache_populated, _merchant_locations_cache
    _merchant_locations_cache.clear()
    _cache_populated = False
    logger.info("Merchant locations cache cleared")
