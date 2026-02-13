"""
Extraction Rule Manager: Manage merchant-specific price extraction rules.

Uses default rules. Future: can load extraction rules from prompt_library (content_role='extraction_rule').
"""
from typing import Dict, Any, Optional, List
import logging
import re
import json

logger = logging.getLogger(__name__)


def get_merchant_extraction_rules(
    merchant_name: Optional[str] = None,
    merchant_id: Optional[str] = None,
    location_id: Optional[str] = None,
    country_code: Optional[str] = None,
    raw_text: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get extraction rules for price extraction from raw receipt text.
    
    Currently returns default rules. Future: can resolve chain/location-specific
    rules from prompt_library when extraction_rule type is added.
    
    Args:
        merchant_name: Store chain name (for future use)
        merchant_id: Optional chain_id (for future use)
        location_id: Optional location_id (for future use)
        country_code: Optional country code (for future use)
        raw_text: Optional raw OCR text (for future use)
        
    Returns:
        Extraction rules dictionary: price_patterns, skip_patterns, special_rules
    """
    logger.debug(f"Using default extraction rules for merchant: {merchant_name}")
    return get_default_extraction_rules()


def get_default_extraction_rules() -> Dict[str, Any]:
    """
    Return default extraction rules (generic rules).
    """
    return {
        "price_patterns": [
            {
                "pattern": r'FP\s+\$(\d+\.\d{2})',
                "priority": 1,
                "description": "FP price format (T&T, etc.)",
                "flags": "IGNORECASE"
            },
            {
                "pattern": r'\$(\d+\.\d{2})',
                "priority": 2,
                "description": "Generic dollar price format"
            },
            {
                "pattern": r'\b(\d+\.\d{2})\b',
                "priority": 3,
                "description": "Plain number price format",
                "requires_context": True  # Requires context judgment
            }
        ],
        "skip_patterns": [
            r'^TOTAL',
            r'^Subtotal',
            r'^Tax',
            r'^Points',
            r'^Reference',
            r'^Trans:',
            r'^Terminal:',
            r'^CLERK',
            r'^INVOICE:',
            r'^REFERENCE:',
            r'^AMOUNT',
            r'^APPROVED',
            r'^AUTH CODE',
            r'^APPLICATION',
            r'^Visa',
            r'^VISA',
            r'^Mastercard',
            r'^Credit Card',
            r'^CREDIT CARD',
            r'^Customer Copy',
            r'^STORE:',
            r'^Ph:',
            r'^www\.',
            r'^\d{2}/\d{2}/\d{2}',
            r'^\*{3,}',
            r'^Not A Member',
            r'^立即下載',
            r'^Get Exclusive',
            r'^Enjoy Online',
        ],
        "special_rules": {
            "use_global_fp_match": True,
            "min_fp_count": 3,
            "category_identifiers": []
        }
    }


def apply_extraction_rules(
    raw_text: str,
    rules: Dict[str, Any]
) -> List[float]:
    """
    Apply extraction rules to extract prices from raw_text.
    
    Args:
        raw_text: Original receipt text
        rules: Extraction rules dictionary
        
    Returns:
        List of extracted prices
    """
    special_rules = rules.get("special_rules", {})
    price_patterns = rules.get("price_patterns", [])
    skip_patterns = rules.get("skip_patterns", [])
    
    # Special rule: global FP matching (T&T, etc.)
    if special_rules.get("use_global_fp_match", False):
        min_fp_count = special_rules.get("min_fp_count", 3)
        
        # Find FP price pattern (usually the first pattern)
        fp_pattern = None
        for pattern_config in price_patterns:
            if "FP" in pattern_config.get("pattern", ""):
                fp_pattern = pattern_config["pattern"]
                flags = pattern_config.get("flags", "")
                break
        
        if fp_pattern:
            regex_flags = re.IGNORECASE if "IGNORECASE" in flags else 0
            fp_matches = list(re.finditer(fp_pattern, raw_text, regex_flags))
            fp_prices = [float(m.group(1)) for m in fp_matches]
            
            if len(fp_prices) >= min_fp_count:
                logger.info(f"Using global FP match: found {len(fp_prices)} prices")
                return fp_prices
    
    # Otherwise, analyze line by line
    lines = raw_text.split('\n')
    prices = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Check if should skip
        should_skip = False
        for skip_pattern in skip_patterns:
            if re.match(skip_pattern, line, re.IGNORECASE):
                should_skip = True
                break
        
        if should_skip:
            continue
        
        # Try to match price patterns by priority
        line_price = None
        for pattern_config in sorted(price_patterns, key=lambda x: x.get("priority", 999)):
            pattern = pattern_config["pattern"]
            flags = pattern_config.get("flags", "")
            requires_context = pattern_config.get("requires_context", False)
            
            regex_flags = re.IGNORECASE if "IGNORECASE" in flags else 0
            
            if requires_context:
                # Requires context judgment (e.g., contains letters)
                if not re.search(r'[A-Za-z]', line):
                    continue
            
            matches = list(re.finditer(pattern, line, regex_flags))
            if matches:
                # If multiple matches, take the last one (usually line total)
                line_price = float(matches[-1].group(1))
                
                # Validate price range
                if 0.01 <= line_price <= 999.99:
                    break
                else:
                    line_price = None
        
        if line_price is not None:
            prices.append(line_price)
    
    # Deduplicate
    unique_prices = []
    seen = set()
    for price in prices:
        rounded = round(price, 2)
        if rounded not in seen:
            seen.add(rounded)
            unique_prices.append(price)
    
    logger.info(f"Extracted {len(unique_prices)} prices using extraction rules")
    return unique_prices
