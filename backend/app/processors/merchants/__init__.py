"""
Merchant processors (legacy / alternate pattern).

NOTE: Store-specific processors have been consolidated under processors/stores/.
- T&T Supermarket: stores.tnt_supermarket (clean_tnt_receipt_items)
- Costco: stores.costco_digital, stores.costco_usa_physical

This module keeps MerchantProcessor base class and registry for potential future use
(e.g. Walmart, Target post-processors that follow the class-based pattern).
"""
from .base import MerchantProcessor
from .registry import apply_merchant_processors, register_processor

__all__ = ["apply_merchant_processors", "register_processor", "MerchantProcessor"]
