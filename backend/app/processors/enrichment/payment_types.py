"""
Payment Types: Defines valid payment method categories.

All payment types extracted from receipts must be normalized to one of these categories.
"""
from typing import List, Dict, Optional

# Valid payment type categories
VALID_PAYMENT_TYPES = [
    "Visa",
    "Master",
    "American Express",
    "Discover",
    "Cash",
    "Gift Card",
    "Others",
    "Unknown"
]

# Payment type mapping: keywords -> normalized type
PAYMENT_TYPE_MAPPING: Dict[str, str] = {
    # Visa
    "visa": "Visa",
    "visa card": "Visa",
    "visa debit": "Visa",
    "visa credit": "Visa",
    
    # Mastercard
    "master": "Master",
    "mastercard": "Master",
    "master card": "Master",
    "mc": "Master",
    
    # American Express
    "american express": "American Express",
    "amex": "American Express",
    "americanexpress": "American Express",
    
    # Discover
    "discover": "Discover",
    "discover card": "Discover",
    
    # Cash
    "cash": "Cash",
    
    # Gift Card
    "gift card": "Gift Card",
    "giftcard": "Gift Card",
    "gift": "Gift Card",
    "store card": "Gift Card",
    
    # Others (for other payment methods that don't fit above categories)
    # Examples: Debit, EBT, PayPal, etc.
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
        return "Unknown"
    
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
    other_keywords = ["debit", "ebt", "paypal", "apple pay", "google pay", "venmo", "zelle"]
    if any(keyword in payment_lower for keyword in other_keywords):
        return "Others"
    
    # Default to Unknown if no match
    return "Unknown"


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
