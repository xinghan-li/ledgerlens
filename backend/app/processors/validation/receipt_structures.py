"""
Re-export from processors.core.structures for backward compatibility.
"""
from ..core.structures import (
    RowType, TextBlock, PhysicalRow, ReceiptRegions,
    AmountColumn, AmountColumns, AmountUsageTracker,
    ExtractedItem, TotalsSequence,
)
__all__ = [
    "RowType", "TextBlock", "PhysicalRow", "ReceiptRegions",
    "AmountColumn", "AmountColumns", "AmountUsageTracker",
    "ExtractedItem", "TotalsSequence",
]
