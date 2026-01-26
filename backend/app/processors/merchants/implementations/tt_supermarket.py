"""
T&T Receipt Cleaner: Special post-processing rules for T&T Supermarket receipts.

T&T receipts often contain:
1. Membership card number as a $0.00 line item
2. Points transaction as "Points xx $0.00" at the end

These items should be removed from the items list, but the membership number
should be preserved as a separate field.
"""
import re
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def clean_tt_receipt_items(llm_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean T&T receipt items by removing membership card and points entries.
    
    Rules:
    1. Remove items with amount = 0.00 and product_name contains membership card patterns
    2. Remove items with product_name containing "Points" and amount = 0.00
    3. Extract membership card number and store in a separate field
    
    Args:
        llm_result: LLM processing result containing items
    
    Returns:
        Cleaned LLM result with filtered items and extracted membership info
    """
    # Check if merchant is T&T (also matches TNT which is often OCR error)
    merchant_name = llm_result.get("merchant_name", "").lower()
    is_tnt_receipt = any(pattern in merchant_name for pattern in ["t&t", "t & t", "tnt", "t and t"])
    
    if not is_tnt_receipt:
        logger.debug(f"Not a T&T receipt (merchant: {merchant_name}), skipping T&T cleaning")
        return llm_result
    
    logger.info(f"Applying T&T receipt cleaning rules for merchant: {merchant_name}")
    
    # Get items
    items = llm_result.get("items", [])
    if not items:
        logger.warning("No items found in LLM result")
        return llm_result
    
    # Track removed items for logging
    removed_items = []
    cleaned_items = []
    membership_number = None
    
    for item in items:
        product_name = item.get("product_name", "")
        line_total = item.get("line_total", 0)
        
        # Convert line_total to float for comparison
        try:
            if isinstance(line_total, str):
                # Remove dollar sign and convert
                line_total_float = float(line_total.replace("$", "").strip())
            else:
                line_total_float = float(line_total)
        except (ValueError, AttributeError):
            line_total_float = 0.0
        
        # Rule 1: Check for membership card number (amount = $0.00)
        if line_total_float == 0.0 and _is_membership_card_line(product_name):
            # Extract membership number
            extracted_number = _extract_membership_number(product_name)
            if extracted_number:
                membership_number = extracted_number
                logger.info(f"Extracted membership number: {membership_number}")
            removed_items.append({"product_name": product_name, "reason": "membership_card"})
            continue
        
        # Rule 2: Check for Points transaction (amount = $0.00)
        if line_total_float == 0.0 and _is_points_line(product_name):
            removed_items.append({"product_name": product_name, "reason": "points_transaction"})
            continue
        
        # Keep this item
        cleaned_items.append(item)
    
    # Update result
    llm_result["items"] = cleaned_items
    
    # Add membership info if found
    if membership_number:
        llm_result["membership_number"] = membership_number
    
    # Log cleaning results
    logger.info(f"T&T cleaning: Removed {len(removed_items)} items, kept {len(cleaned_items)} items")
    if removed_items:
        for removed in removed_items:
            logger.debug(f"  Removed ({removed['reason']}): {removed['product_name']}")
    
    return llm_result


def _is_membership_card_line(product_name: str) -> bool:
    """
    Check if product name indicates a membership card line.
    
    Patterns:
    - Masked card number (e.g., "***600032371")
    - Long sequence of digits (10+ digits, likely a card number)
    - Contains membership-related keywords with numbers
    
    Args:
        product_name: Product name to check
    
    Returns:
        True if this is likely a membership card line
    """
    if not product_name:
        return False
    
    product_lower = product_name.lower().strip()
    
    # Check for masked card number pattern (e.g., "***600032371", "****1234567890")
    # Pattern: starts with multiple asterisks followed by digits
    is_masked_card = bool(re.match(r'^\*{3,}\d{4,}$', product_name.strip()))
    
    # Check for membership-related keywords
    membership_keywords = [
        "member",
        "card",
        "会员",
        "卡号",
        "membership",
        "account",
    ]
    
    # Check if it's a long sequence of digits (likely a bare card number)
    # Pattern: 10 or more consecutive digits
    has_long_number = bool(re.search(r'\d{10,}', product_name))
    
    # Check if contains membership keywords AND some numbers
    has_membership_keyword = any(keyword in product_lower for keyword in membership_keywords)
    has_numbers = bool(re.search(r'\d{4,}', product_name))  # At least 4 consecutive digits
    
    # Return True if:
    # 1. It's a masked card number (***xxxxx), OR
    # 2. It's a long number (10+ digits), OR
    # 3. It has membership keywords AND numbers
    return is_masked_card or has_long_number or (has_membership_keyword and has_numbers)


def _is_points_line(product_name: str) -> bool:
    """
    Check if product name indicates a points transaction line.
    
    Patterns:
    - Contains "Points"
    - Contains "积分" (Chinese for points)
    
    Args:
        product_name: Product name to check
    
    Returns:
        True if this is likely a points line
    """
    if not product_name:
        return False
    
    product_lower = product_name.lower().strip()
    
    points_keywords = [
        "points",
        "point",
        "积分",
        "pts",
    ]
    
    return any(keyword in product_lower for keyword in points_keywords)


def _extract_membership_number(product_name: str) -> Optional[str]:
    """
    Extract membership card number from product name.
    
    Handles masked numbers (e.g., "***600032371") and regular numbers.
    
    Args:
        product_name: Product name containing membership number
    
    Returns:
        Extracted membership number (including masked format), or None if not found
    """
    if not product_name:
        return None
    
    # Check for masked card number pattern first
    masked_match = re.match(r'^(\*{3,}\d{4,})$', product_name.strip())
    if masked_match:
        return masked_match.group(1)
    
    # Try to find a sequence of digits (typically 10+ digits for membership cards)
    # Pattern: Find longest sequence of digits
    digit_sequences = re.findall(r'\d{4,}', product_name)
    
    if digit_sequences:
        # Return the longest sequence (likely the card number)
        return max(digit_sequences, key=len)
    
    return None
