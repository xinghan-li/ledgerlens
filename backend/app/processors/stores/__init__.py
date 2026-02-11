"""
Store-specific receipt processors.

All use OCR→rule-based extraction (no LLM). Costco has dedicated block processors.
T&T uses generic validation pipeline with store_config. clean_tnt_receipt_items
is for the legacy LLM path (workflow_processor).
"""
from .costco_ca.digital.processor import process_costco_ca_digital
from .costco_us.digital.processor import process_costco_us_digital
from .costco_us.physical.processor import process_costco_us_physical
from .trader_joes.processor import process_trader_joes
from .tnt_supermarket.processor import clean_tnt_receipt_items

__all__ = [
    "process_costco_ca_digital",
    "process_costco_us_digital",
    "process_costco_us_physical",
    "process_trader_joes",
    "clean_tnt_receipt_items",
]
