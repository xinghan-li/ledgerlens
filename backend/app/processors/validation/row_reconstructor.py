"""
Row Reconstruction: Build physical rows from OCR text blocks.

This module implements Step 1 of the receipt processing pipeline.
"""
from collections import Counter
from typing import List, Optional
import logging
from .receipt_structures import TextBlock, PhysicalRow, RowType

logger = logging.getLogger(__name__)

# eps = epsilon (small tolerance threshold)
# Default row height tolerance - keep small so adjacent receipt lines don't merge
DEFAULT_ROW_HEIGHT_EPS = 0.0025
# Cap as multiple of typical block height: 0.5 = half-line, allows same-line left+right to merge.
MAX_ROW_HEIGHT_EPS_MULTIPLIER = 0.5


def _compute_avg_block_height(blocks: List[TextBlock]) -> float:
    """
    Typical block height from first 10 blocks: bin by rounded height, take mode bucket, then average.
    More robust than full average when outliers exist.
    """
    sample = blocks[:10]
    heights = []
    for b in sample:
        if b.height is not None and b.height > 0:
            heights.append(b.height)
        elif b.center_y > b.y:
            heights.append(2 * (b.center_y - b.y))
    if not heights:
        return 0.02
    # Round to 0.001, find mode (most frequent bucket), avg heights in that bucket
    rounded = [round(h, 3) for h in heights]
    mode_val = Counter(rounded).most_common(1)[0][0]
    in_bucket = [h for h, r in zip(heights, rounded) if r == mode_val]
    return sum(in_bucket) / len(in_bucket)


def _block_row_tolerance(block: TextBlock, max_eps: float) -> float:
    """Per-block Y tolerance: half line height, capped by max_eps (relative to avg block height)."""
    if block.height is not None and block.height > 0:
        half = block.height / 2.0
        eps = max(half, DEFAULT_ROW_HEIGHT_EPS)
    elif block.center_y > block.y:
        half = block.center_y - block.y
        eps = max(half, DEFAULT_ROW_HEIGHT_EPS)
    else:
        eps = DEFAULT_ROW_HEIGHT_EPS
    return min(eps, max_eps)


def build_physical_rows(
    blocks: List[TextBlock],
    row_height_eps: Optional[float] = None
) -> List[PhysicalRow]:
    """
    Build physical rows from text blocks by clustering blocks with similar Y coordinates.
    Uses dynamic row eps per block; cap is relative to avg block height (0.5x = half-line).
    
    Args:
        blocks: List of TextBlock objects
        row_height_eps: Y coordinate tolerance; if None, use dynamic eps with relative cap
        
    Returns:
        List of PhysicalRow objects, sorted by Y coordinate (top to bottom)
    """
    if not blocks:
        return []
    
    use_dynamic_eps = row_height_eps is None
    if row_height_eps is None:
        row_height_eps = DEFAULT_ROW_HEIGHT_EPS
    
    # Relative cap: multiple of avg block height
    avg_height = _compute_avg_block_height(blocks)
    max_eps = avg_height * MAX_ROW_HEIGHT_EPS_MULTIPLIER
    
    # Sort blocks by center_y (top to bottom)
    blocks_sorted = sorted(blocks, key=lambda b: b.center_y)
    
    rows = []
    current_row_blocks = [blocks_sorted[0]]
    
    for block in blocks_sorted[1:]:
        # CRITICAL: Compare with the FIRST block in current_row to avoid chain-merging
        # (If we compare with last block, blocks can incrementally join even if far from first block)
        first_block = current_row_blocks[0]
        first_block_y = first_block.center_y
        y_diff = abs(block.center_y - first_block_y)
        
        if use_dynamic_eps:
            eps = max(_block_row_tolerance(first_block, max_eps), _block_row_tolerance(block, max_eps))
        else:
            eps = row_height_eps
        
        if y_diff <= eps:
            # Same row - add to current row
            current_row_blocks.append(block)
        else:
            # New row - finalize current row and start new one
            if current_row_blocks:
                row = _make_physical_row(current_row_blocks, len(rows))
                rows.append(row)
            current_row_blocks = [block]
    
    # Don't forget the last row
    if current_row_blocks:
        row = _make_physical_row(current_row_blocks, len(rows))
        rows.append(row)
    
    logger.info(f"Built {len(rows)} physical rows from {len(blocks)} blocks")
    return rows


def _make_physical_row(blocks_in_row: List[TextBlock], row_id: int) -> PhysicalRow:
    """
    Create a PhysicalRow from a list of blocks on the same row.
    
    Args:
        blocks_in_row: List of TextBlock objects on the same physical row
        row_id: Unique row identifier
        
    Returns:
        PhysicalRow object
    """
    if not blocks_in_row:
        raise ValueError("Cannot create row from empty block list")
    
    # Calculate row boundaries
    y_top = min(b.y for b in blocks_in_row)
    y_bottom = max(b.center_y for b in blocks_in_row)
    y_center = (y_top + y_bottom) / 2
    
    # Sort blocks by X coordinate (left to right) for text reconstruction
    blocks_sorted_by_x = sorted(blocks_in_row, key=lambda b: b.x)
    
    # Reconstruct text by joining block texts (left to right)
    text_parts = [b.text for b in blocks_sorted_by_x if b.text.strip()]
    text = " ".join(text_parts)
    
    return PhysicalRow(
        row_id=row_id,
        blocks=blocks_sorted_by_x,
        y_top=y_top,
        y_bottom=y_bottom,
        y_center=y_center,
        text=text,
        row_type=RowType.UNKNOWN
    )


def find_amount_in_row(
    row: PhysicalRow,
    column_x: float,
    tolerance: float,
    tracker: "AmountUsageTracker"
) -> TextBlock:
    """
    Find an amount block in a row that matches the column and hasn't been used.
    
    Args:
        row: PhysicalRow to search
        column_x: X coordinate of the amount column
        tolerance: X coordinate tolerance
        tracker: AmountUsageTracker to check if block is already used
        
    Returns:
        TextBlock if found and not used, None otherwise
    """
    for block in row.get_amount_blocks():
        if tracker.is_used(block):
            continue
        
        if abs(block.center_x - column_x) <= tolerance:
            return block
    
    return None
