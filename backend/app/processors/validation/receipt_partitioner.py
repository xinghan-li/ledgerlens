"""
Receipt Partitioner: Partition receipt into 4 regions based on coordinates.

Regions:
1. Header: Store name, address, date/time (until first item)
2. Items: All product items (until SUBTOTAL)
3. Totals: Summation process (SUBTOTAL + TAX + FEES = TOTAL)
4. Payment: Payment information (after TOTAL)
"""
from typing import Dict, Any, List, Optional
import logging
import re

logger = logging.getLogger(__name__)

# Marker text variations
SUBTOTAL_MARKERS = [
    "SUBTOTAL", "SUB-TOTAL", "Subtotal", "Sub-Total", 
    "SUB TOTAL", "Sub Total", "subtotal"
]

TOTAL_MARKERS = [
    "TOTAL", "Total", "TOTAL AMOUNT", "Total Amount",
    "TOTAL DUE", "Total Due", "AMOUNT DUE", "Amount Due",
    "GRAND TOTAL", "Grand Total"
]

PAYMENT_MARKERS = [
    "PAYMENT", "Payment", "CARD", "Card", "VISA", "MASTERCARD",
    "AMEX", "CASH", "Cash", "TRANSACTION", "Transaction",
    "AUTH", "AUTHORIZATION", "REF", "Reference"
]


def partition_receipt(
    blocks: List[Dict[str, Any]],
    coordinate_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Partition receipt into 4 regions based on coordinates.
    
    Args:
        blocks: List of text blocks with coordinates
        coordinate_data: Optional coordinate data from Document AI
        
    Returns:
        Dictionary containing:
        {
            "header": List[blocks],
            "items": List[blocks],
            "totals": List[blocks],
            "payment": List[blocks],
            "markers": {
                "first_item": block,
                "subtotal": block,
                "total": block
            }
        }
    """
    from .coordinate_extractor import find_marker_blocks, find_first_item_marker
    
    # Find key markers
    first_item_block = find_first_item_marker(blocks)
    subtotal_blocks = find_marker_blocks(blocks, SUBTOTAL_MARKERS)
    total_blocks = find_marker_blocks(blocks, TOTAL_MARKERS)
    
    # Get the first subtotal and total (topmost)
    subtotal_block = subtotal_blocks[0] if subtotal_blocks else None
    total_block = total_blocks[0] if total_blocks else None
    
    # If no subtotal found, try to infer from structure
    # Some grocery stores don't have subtotal, items go directly to total
    if not subtotal_block and total_block:
        # Look for the last item before total
        # Items are usually above total, and have amounts
        items_before_total = [
            b for b in blocks 
            if b.get("is_amount") and b.get("y", 1) < total_block.get("y", 0)
        ]
        if items_before_total:
            # The last item's Y coordinate can serve as a boundary
            last_item_y = max(b.get("y", 0) for b in items_before_total)
            # Create a virtual subtotal marker
            subtotal_block = {
                "text": "SUBTOTAL (inferred)",
                "y": last_item_y + 0.01,  # Slightly below last item
                "x": total_block.get("x", 0.5),
                "is_inferred": True
            }
            logger.info("No SUBTOTAL marker found, inferred from last item position")
    
    # Determine boundaries
    first_item_y = first_item_block.get("y", 0) if first_item_block else 0.1
    subtotal_y = subtotal_block.get("y", 0.5) if subtotal_block else 0.5
    total_y = total_block.get("y", 0.9) if total_block else 0.9
    
    # Partition blocks by Y coordinate
    regions = {
        "header": [
            b for b in blocks 
            if b.get("y", 0) < first_item_y
        ],
        "items": [
            b for b in blocks 
            if first_item_y <= b.get("y", 0) < subtotal_y
        ],
        "totals": [
            b for b in blocks 
            if subtotal_y <= b.get("y", 0) < total_y
        ],
        "payment": [
            b for b in blocks 
            if b.get("y", 0) >= total_y
        ],
        "markers": {
            "first_item": first_item_block,
            "subtotal": subtotal_block,
            "total": total_block
        }
    }
    
    # Log partition summary
    logger.info(
        f"Receipt partitioned: "
        f"Header={len(regions['header'])} blocks, "
        f"Items={len(regions['items'])} blocks, "
        f"Totals={len(regions['totals'])} blocks, "
        f"Payment={len(regions['payment'])} blocks"
    )
    
    return regions


def get_region_text(region_blocks: List[Dict[str, Any]]) -> str:
    """Get combined text from a region."""
    return "\n".join(b.get("text", "") for b in region_blocks if b.get("text"))


def get_region_amounts(region_blocks: List[Dict[str, Any]]) -> List[float]:
    """Get all amounts from a region."""
    return [
        b.get("amount") 
        for b in region_blocks 
        if b.get("is_amount") and b.get("amount") is not None
    ]
