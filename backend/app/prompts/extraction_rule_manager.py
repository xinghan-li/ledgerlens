"""
Extraction Rule Manager: Manage merchant-specific price extraction rules.

Similar to RAG system, loads merchant-specific extraction rules from database for price extraction.
"""
from typing import Dict, Any, Optional, List
import logging
import re
from ..services.database.supabase_client import _get_client
from ..config import settings

logger = logging.getLogger(__name__)

# Rule cache
_rule_cache: Dict[str, Dict[str, Any]] = {}


def get_merchant_extraction_rules(
    merchant_name: Optional[str] = None,
    merchant_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get merchant-specific extraction rules.
    
    Args:
        merchant_name: Merchant name
        merchant_id: Optional merchant ID
        
    Returns:
        Extraction rules dictionary, containing price_patterns, skip_patterns, special_rules
    """
    # Check cache
    cache_key = (merchant_name or "").lower().strip()
    if cache_key in _rule_cache:
        logger.debug(f"Using cached extraction rules for merchant: {merchant_name}")
        return _rule_cache[cache_key]
    
    supabase = _get_client()
    
    try:
        # Get rules from merchant_prompts table
        query = supabase.table("merchant_prompts").select("extraction_rules, merchant_name").eq("is_active", True)
        
        if merchant_id:
            query = query.eq("merchant_id", merchant_id)
        elif merchant_name:
            query = query.ilike("merchant_name", f"%{merchant_name}%")
        else:
            return get_default_extraction_rules()
        
        res = query.order("version", desc=True).limit(1).execute()
        
        if res.data and len(res.data) > 0:
            rules_data = res.data[0].get("extraction_rules")
            if rules_data:
                # Cache result
                _rule_cache[cache_key] = rules_data
                logger.info(f"Loaded extraction rules for merchant: {merchant_name}")
                return rules_data
        
        # If not found, return default rules
        logger.warning(f"No custom extraction rules found for merchant: {merchant_name}, using default")
        return get_default_extraction_rules()
        
    except Exception as e:
        logger.error(f"Failed to load extraction rules for merchant {merchant_name}: {e}")
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
