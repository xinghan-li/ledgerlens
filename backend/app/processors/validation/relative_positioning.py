"""
Relative Positioning Helper: Handle S-folded receipts with different section offsets.

This module provides utilities for relative positioning that work even when
different sections of a receipt have different Y-coordinate offsets due to
S-folding or OCR distortions.
"""
from typing import Dict, Any, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Relative position tolerance (10% buffer above and below)
RELATIVE_TOLERANCE = 0.1


def is_within_relative_bounds(
    block_y: float,
    reference_start_y: float,
    reference_end_y: float,
    tolerance: float = RELATIVE_TOLERANCE
) -> Tuple[bool, float]:
    """
    Check if a block's Y coordinate is within relative bounds between two reference points.
    
    This handles S-folded receipts where different sections may have different offsets.
    Instead of using absolute Y coordinates, we calculate relative position (0-1)
    between two reference points (e.g., first_item and subtotal).
    
    Args:
        block_y: Y coordinate of the block to check
        reference_start_y: Y coordinate of the start reference point (e.g., first_item)
        reference_end_y: Y coordinate of the end reference point (e.g., subtotal)
        tolerance: Relative tolerance (default 0.1 = 10% buffer)
        
    Returns:
        Tuple of (is_within_bounds, relative_position)
        - is_within_bounds: True if block is within the relative range
        - relative_position: Relative position (0 = at start, 1 = at end, negative = before start, >1 = after end)
    """
    # Calculate the range between reference points
    total_range = reference_end_y - reference_start_y
    
    # If range is too small, fall back to absolute positioning
    if total_range < 0.01:
        logger.debug(f"Range too small ({total_range:.4f}), using absolute positioning")
        is_within = reference_start_y <= block_y <= reference_end_y
        relative_pos = 0.5 if is_within else (block_y - reference_start_y) / 0.01
        return is_within, relative_pos
    
    # Calculate relative position: 0 = at start, 1 = at end
    relative_position = (block_y - reference_start_y) / total_range
    
    # Include blocks between -tolerance and 1+tolerance (with buffer)
    # This allows for blocks slightly above start or below end
    is_within = (-tolerance <= relative_position <= 1 + tolerance)
    
    return is_within, relative_position


def filter_blocks_by_relative_position(
    blocks: List[Dict[str, Any]],
    reference_start_y: float,
    reference_end_y: float,
    tolerance: float = RELATIVE_TOLERANCE,
    use_center_y: bool = True
) -> List[Dict[str, Any]]:
    """
    Filter blocks that are within relative bounds between two reference points.
    
    Args:
        blocks: List of blocks to filter
        reference_start_y: Y coordinate of start reference point
        reference_end_y: Y coordinate of end reference point
        tolerance: Relative tolerance (default 0.1)
        use_center_y: If True, use center_y; otherwise use y
        
    Returns:
        Filtered list of blocks within relative bounds
    """
    filtered = []
    for block in blocks:
        block_y = block.get("center_y" if use_center_y else "y", 0)
        is_within, relative_pos = is_within_relative_bounds(
            block_y, reference_start_y, reference_end_y, tolerance
        )
        if is_within:
            filtered.append(block)
    
    return filtered


def partition_by_relative_position(
    blocks: List[Dict[str, Any]],
    markers: Dict[str, Optional[Dict[str, Any]]],
    use_relative: bool = True
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Partition blocks into 4 regions using relative positioning.
    
    Regions:
    1. Header: Before first_item
    2. Items: Between first_item and subtotal
    3. Totals: Between subtotal and total
    4. Payment: After total
    
    Args:
        blocks: All blocks to partition
        markers: Dictionary with 'first_item', 'subtotal', 'total' markers
        use_relative: If True, use relative positioning; otherwise use absolute
        
    Returns:
        Dictionary with 'header', 'items', 'totals', 'payment' lists
    """
    first_item = markers.get("first_item")
    subtotal = markers.get("subtotal")
    total = markers.get("total")
    
    # Get Y coordinates (use center_y if available, otherwise y)
    def get_y(block: Optional[Dict[str, Any]], default: float) -> float:
        if not block:
            return default
        return block.get("center_y") or block.get("y", default)
    
    first_item_y = get_y(first_item, 0.1)
    subtotal_y = get_y(subtotal, 0.5)
    total_y = get_y(total, 0.9)
    
    if use_relative:
        # Use relative positioning for each region
        header_blocks = [
            b for b in blocks
            if (b.get("center_y") or b.get("y", 0)) < first_item_y
        ]
        
        # Items region: between first_item and subtotal (relative)
        items_blocks = filter_blocks_by_relative_position(
            blocks, first_item_y, subtotal_y, tolerance=RELATIVE_TOLERANCE
        )
        
        # Totals region: between subtotal and total (relative)
        totals_blocks = filter_blocks_by_relative_position(
            blocks, subtotal_y, total_y, tolerance=RELATIVE_TOLERANCE
        )
        
        # Payment region: after total
        payment_blocks = [
            b for b in blocks
            if (b.get("center_y") or b.get("y", 0)) >= total_y
        ]
    else:
        # Fallback to absolute positioning
        header_blocks = [
            b for b in blocks
            if (b.get("center_y") or b.get("y", 0)) < first_item_y
        ]
        items_blocks = [
            b for b in blocks
            if first_item_y <= (b.get("center_y") or b.get("y", 0)) < subtotal_y
        ]
        totals_blocks = [
            b for b in blocks
            if subtotal_y <= (b.get("center_y") or b.get("y", 0)) < total_y
        ]
        payment_blocks = [
            b for b in blocks
            if (b.get("center_y") or b.get("y", 0)) >= total_y
        ]
    
    return {
        "header": header_blocks,
        "items": items_blocks,
        "totals": totals_blocks,
        "payment": payment_blocks
    }
