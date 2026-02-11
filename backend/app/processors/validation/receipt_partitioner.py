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
    "GRAND TOTAL", "Grand Total",
    "TOTAL SALES", "Total Sales", "TOTAL SALES:", "Total Sales:"
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
    
    # Determine boundaries (use center_y if available, otherwise y)
    def get_y(block: Optional[Dict[str, Any]], default: float) -> float:
        if not block:
            return default
        return block.get("center_y") or block.get("y", default)
    
    first_item_y = get_y(first_item_block, 0.1)
    subtotal_y = get_y(subtotal_block, 0.5)
    total_y = get_y(total_block, 0.9)
    
    # CRITICAL: If first_item is None, try to infer it from amount blocks
    # Items region should contain blocks with amounts that are above subtotal
    if not first_item_block and subtotal_block:
        # Find the first amount block above subtotal that looks like an item
        # Items typically have amounts in a reasonable range ($0.01 - $1000)
        from .coordinate_extractor import extract_amount_blocks
        amount_blocks = extract_amount_blocks(blocks)
        
        for block in amount_blocks:
            block_y = get_y(block, 1.0)
            amount = block.get("amount", 0)
            
            # Must be above subtotal
            if block_y >= subtotal_y:
                continue
            
            # Amount should be reasonable for a product price
            if not (0.01 <= amount <= 1000):
                continue
            
            # Check if there's text nearby (product name)
            block_x = block.get("x", 0)
            has_text_nearby = False
            for other_block in blocks:
                other_y = other_block.get("y", 0)
                other_x = other_block.get("x", 0)
                if (abs(other_y - block_y) < 0.01 and 
                    other_x < block_x - 0.05 and
                    not other_block.get("is_amount") and
                    len(other_block.get("text", "").strip()) > 2):
                    has_text_nearby = True
                    break
            
            # This looks like the first item
            first_item_block = block
            first_item_y = get_y(first_item_block, 0.1)
            logger.info(f"Inferred first_item from amount block: '{block.get('text', '')}' at Y={first_item_y:.4f}")
            break
    
    # Use relative positioning to handle S-folded receipts
    # This ensures each region is correctly identified even with different offsets
    from .relative_positioning import partition_by_relative_position
    
    markers_dict = {
        "first_item": first_item_block,
        "subtotal": subtotal_block,
        "total": total_block
    }
    
    # Partition using relative positioning (handles S-folding offsets)
    regions = partition_by_relative_position(blocks, markers_dict, use_relative=True)
    regions["markers"] = markers_dict
    
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
