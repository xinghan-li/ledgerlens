"""
Payment Types: Defines valid payment method categories.

All payment types extracted from receipts must be normalized to one of these categories.
"""
from typing import List, Dict, Optional

# Valid payment type categories (used for By payment card aggregation; keep consistent)
VALID_PAYMENT_TYPES = [
    "Visa",
    "MasterCard",
    "AmEx",
    "Discover",
    "Gift Card",
    "Cash",
    "Other",
]

# Payment type mapping: keywords -> normalized type
PAYMENT_TYPE_MAPPING: Dict[str, str] = {
    # Visa
    "visa": "Visa",
    "visa card": "Visa",
    "visa debit": "Visa",
    "visa credit": "Visa",
    # MasterCard
    "master": "MasterCard",
    "mastercard": "MasterCard",
    "master card": "MasterCard",
    "mc": "MasterCard",
    # AmEx
    "american express": "AmEx",
    "amex": "AmEx",
    "americanexpress": "AmEx",
    "american express credit": "AmEx",
    # Discover (DISC/DSVR/DCVR = Discover abbreviations on receipts)
    "discover": "Discover",
    "discover card": "Discover",
    "dcvr": "Discover",
    "disc": "Discover",
    "dsvr": "Discover",
    # Cash
    "cash": "Cash",
    # Gift Card
    "gift card": "Gift Card",
    "giftcard": "Gift Card",
    "gift": "Gift Card",
    "store card": "Gift Card",
}


def normalize_payment_type(payment_method: Optional[str]) -> str:
    """
    Normalize payment method to one of the valid categories.
    
    Args:
        payment_method: Raw payment method string from receipt
    
    Returns:
        Normalized payment type (one of VALID_PAYMENT_TYPES)
    """
    if not payment_method:
        return "Other"
    
    # Convert to lowercase for matching
    payment_lower = payment_method.lower().strip()
    
    # Try exact match first
    if payment_lower in PAYMENT_TYPE_MAPPING:
        return PAYMENT_TYPE_MAPPING[payment_lower]
    
    # Try partial match (check if any keyword is in the payment method)
    for keyword, normalized_type in PAYMENT_TYPE_MAPPING.items():
        if keyword in payment_lower:
            return normalized_type
    
    # If no match found, check if it's a known "other" type
    other_keywords = ["debit", "ebt", "paypal", "apple pay", "google pay", "venmo", "zelle", "credit", "card"]
    if any(keyword in payment_lower for keyword in other_keywords):
        return "Other"
    
    return "Other"


def is_valid_payment_type(payment_type: str) -> bool:
    """
    Check if a payment type is valid.
    
    Args:
        payment_type: Payment type to validate
    
    Returns:
        True if valid, False otherwise
    """
    return payment_type in VALID_PAYMENT_TYPES


def get_all_payment_types() -> List[str]:
    """
    Get list of all valid payment types.
    
    Returns:
        List of valid payment type strings
    """
    return VALID_PAYMENT_TYPES.copy()
