"""
Processors Core: Shared data structures and validation logic.

Used by both validation pipeline and store-specific processors.
"""
from .structures import (
    RowType, TextBlock, PhysicalRow, ReceiptRegions,
    AmountColumn, AmountColumns, AmountUsageTracker,
    ExtractedItem, TotalsSequence,
)
from .math_validator import validate_item_math, validate_totals
from .sum_checker import check_receipt_sums, apply_field_conflicts_resolution

__all__ = [
    "RowType", "TextBlock", "PhysicalRow", "ReceiptRegions",
    "AmountColumn", "AmountColumns", "AmountUsageTracker",
    "ExtractedItem", "TotalsSequence",
    "validate_item_math", "validate_totals",
    "check_receipt_sums", "apply_field_conflicts_resolution",
]
