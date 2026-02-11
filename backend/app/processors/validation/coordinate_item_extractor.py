"""
Coordinate Item Extractor: Extract receipt items directly from coordinate data.

This module extracts items from OCR coordinate data by:
1. Finding item lines (text + amount pairs on the same row)
2. Grouping text blocks that are on the same Y coordinate (same row)
3. Identifying the amount column (rightmost column with amounts)
4. Pairing product names with their prices
"""
from typing import Dict, Any, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Y coordinate tolerance for grouping blocks on the same row
# Reduced tolerance to avoid grouping blocks from different rows
Y_ROW_TOLERANCE = 0.005  # 0.5% tolerance for same-row grouping (reduced from 0.01)

# X coordinate tolerance for identifying amount column
X_COLUMN_TOLERANCE = 0.05  # 5% tolerance for column alignment


def extract_items_from_coordinates(
    blocks: List[Dict[str, Any]],
    subtotal_marker: Optional[Dict[str, Any]] = None,
    total_marker: Optional[Dict[str, Any]] = None,
    subtotal_amount_x: Optional[float] = None
) -> List[Dict[str, Any]]:
    """
    Extract items from coordinate blocks.
    
    Args:
        blocks: All text blocks with coordinates
        subtotal_marker: Optional subtotal marker block
        total_marker: Optional total marker block
        subtotal_amount_x: Optional X coordinate of SUBTOTAL amount (if known)
        
    Returns:
        List of items, each containing:
        {
            "product_name": str,
            "line_total": float,
            "raw_text": str,
            "y": float,  # Y coordinate for sorting
            "x_amount": float  # X coordinate of amount
        }
    """
    from .coordinate_extractor import extract_amount_blocks
    
    # Determine boundaries using relative positioning
    # This handles S-folded receipts where items region may have different offsets
    from .coordinate_extractor import find_first_item_marker
    
    # Find first_item marker for accurate boundary
    first_item_marker = find_first_item_marker(blocks)
    
    def get_y(block: Optional[Dict[str, Any]], default: float) -> float:
        if not block:
            return default
        return block.get("center_y") or block.get("y", default)
    
    y_start = get_y(first_item_marker, 0.0)
    y_end = get_y(subtotal_marker, get_y(total_marker, 1.0))
    
    # If we have the SUBTOTAL amount's X coordinate, use it directly
    # Otherwise, try to identify the amount column
    amount_column_x = subtotal_amount_x
    
    if amount_column_x is None:
        # Filter blocks to items region using relative positioning
        # This ensures items are correctly identified even with S-folding offsets
        from .relative_positioning import filter_blocks_by_relative_position
        
        if first_item_marker and (subtotal_marker or total_marker):
            # Use relative positioning between first_item and subtotal/total
            item_blocks = filter_blocks_by_relative_position(
                blocks, y_start, y_end, tolerance=0.1, use_center_y=True
            )
        else:
            # Fallback to absolute positioning
            item_blocks = [
                b for b in blocks
                if y_start <= (b.get("center_y") or b.get("y", 0)) < y_end
            ]
        
        # Group blocks by row (similar Y coordinate)
        rows = _group_blocks_by_row(item_blocks)
        
        # Identify amount column (rightmost column with consistent amounts)
        amount_column_x = _identify_amount_column(rows)
        
        if amount_column_x is None:
            logger.warning("Could not identify amount column, using rightmost amounts")
    
    # Extract items: find all rows above SUBTOTAL, then extract amount from each row
    # using the identified amount column X coordinate
    amount_blocks = extract_amount_blocks(blocks)
    
    items = []
    if amount_column_x is not None:
        # Use the identified amount column
        # Group blocks by row first, then process each row
        item_region_blocks = [
            b for b in blocks
            if y_start <= b.get("y", 0) < y_end
        ]
        
        rows = _group_blocks_by_row(item_region_blocks)
        
        for row in rows:
            # Check if this row has an amount in the identified column
            row_amount_block = None
            for block in row:
                if block.get("is_amount", False):
                    block_x = block.get("center_x") or block.get("x", 0)
                    if abs(block_x - amount_column_x) <= X_COLUMN_TOLERANCE:
                        row_amount_block = block
                        break
            
            if row_amount_block and row_amount_block.get("amount"):
                # Extract product name from text blocks in this row
                row_text_blocks = [
                    b for b in row
                    if not b.get("is_amount", False) and b.get("text", "").strip()
                ]
                
                # Sort by X coordinate (left to right)
                row_text_blocks.sort(key=lambda b: b.get("x", 0))
                
                # Filter out "Code:" patterns and product codes
                # Product codes are typically on separate lines or after the product name
                filtered_text_blocks = []
                for b in row_text_blocks:
                    text = b.get("text", "").strip()
                    text_lower = text.lower()
                    # Skip "Code:" labels and product codes (typically numeric)
                    if text_lower.startswith("code:") or (text_lower.startswith("code") and len(text) < 20):
                        continue
                    # Skip standalone numeric codes (likely product codes, not product names)
                    if text.isdigit() and len(text) >= 6:  # Product codes are usually 6+ digits
                        continue
                    filtered_text_blocks.append(b)
                
                # Combine text into product name
                product_parts = [b.get("text", "").strip() for b in filtered_text_blocks if b.get("text", "").strip()]
                product_name = " ".join(product_parts)
                
                # Additional check: if product name is too short or looks like a code, skip
                if not product_name or len(product_name.strip()) < 3:
                    logger.debug(f"Skipping row with amount ${row_amount_block.get('amount'):.2f}: product_name too short or empty")
                    continue
                
                # Skip if this looks like a header or summary line
                if product_name and not _is_header_or_summary_line(product_name):
                    items.append({
                        "product_name": product_name,
                        "line_total": row_amount_block.get("amount"),
                        "raw_text": product_name,
                        "y": row_amount_block.get("y", 0),
                        "x_amount": row_amount_block.get("center_x") or row_amount_block.get("x", 0),
                        "x": row_amount_block.get("x", 0),
                        "center_x": row_amount_block.get("center_x"),
                        "center_y": row_amount_block.get("center_y")
                    })
                else:
                    logger.debug(f"Skipping row with amount ${row_amount_block.get('amount'):.2f}: looks like header/summary line")
    else:
        # Fallback: group by row and extract rightmost amount
        item_blocks = [
            b for b in blocks
            if y_start <= b.get("y", 0) < y_end
        ]
        rows = _group_blocks_by_row(item_blocks)
        
        for row in rows:
            item = _extract_item_from_row(row, None)
            if item:
                items.append(item)
    
    # Sort by Y coordinate (top to bottom)
    items.sort(key=lambda i: i.get("y", 0))
    
    if amount_column_x is not None:
        logger.info(f"Extracted {len(items)} items from coordinate data (using amount column X={amount_column_x:.3f})")
    else:
        logger.info(f"Extracted {len(items)} items from coordinate data (using fallback method)")
    
    return items


def _group_blocks_by_row(blocks: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """
    Group blocks that are on the same row (similar Y coordinate).
    
    Returns:
        List of rows, each row is a list of blocks
    """
    if not blocks:
        return []
    
    # Sort by Y coordinate
    sorted_blocks = sorted(blocks, key=lambda b: b.get("y", 0))
    
    rows = []
    current_row = [sorted_blocks[0]]
    current_y = sorted_blocks[0].get("y", 0)
    
    for block in sorted_blocks[1:]:
        block_y = block.get("y", 0)
        
        # If Y coordinate is within tolerance, add to current row
        if abs(block_y - current_y) <= Y_ROW_TOLERANCE:
            current_row.append(block)
        else:
            # Start new row
            if current_row:
                rows.append(current_row)
            current_row = [block]
            current_y = block_y
    
    # Add last row
    if current_row:
        rows.append(current_row)
    
    return rows


def _identify_amount_column(rows: List[List[Dict[str, Any]]]) -> Optional[float]:
    """
    Identify the amount column by finding the rightmost column with consistent amounts.
    
    Strategy:
    1. For each row, find the rightmost amount
    2. Group amounts by X coordinate (within tolerance)
    3. The X coordinate with the most amount occurrences is the amount column
    """
    from .coordinate_extractor import extract_amount_blocks
    
    # Collect all amounts from rows
    amount_positions = []
    
    for row in rows:
        # Find amounts in this row
        row_amounts = [b for b in row if b.get("is_amount", False)]
        if row_amounts:
            # Get the rightmost amount (highest X coordinate)
            rightmost = max(row_amounts, key=lambda b: b.get("center_x", b.get("x", 0)))
            amount_positions.append(rightmost.get("center_x", rightmost.get("x", 0)))
    
    if not amount_positions:
        return None
    
    # Group positions by X coordinate (within tolerance)
    position_groups = {}
    for pos in amount_positions:
        # Find existing group within tolerance
        found_group = None
        for group_x in position_groups:
            if abs(pos - group_x) <= X_COLUMN_TOLERANCE:
                found_group = group_x
                break
        
        if found_group:
            position_groups[found_group].append(pos)
        else:
            position_groups[pos] = [pos]
    
    # Find the group with most occurrences (most consistent column)
    if not position_groups:
        return None
    
    best_group = max(position_groups.items(), key=lambda g: len(g[1]))
    # Return the average X coordinate of the group
    avg_x = sum(best_group[1]) / len(best_group[1])
    
    logger.debug(f"Identified amount column at X={avg_x:.3f} with {len(best_group[1])} occurrences")
    
    return avg_x


def _extract_item_from_row(
    row: List[Dict[str, Any]],
    amount_column_x: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    Extract item information from a row of blocks.
    
    Args:
        row: List of blocks on the same row
        amount_column_x: Optional X coordinate of amount column
        
    Returns:
        Item dictionary or None if not a valid item
    """
    if not row:
        return None
    
    # Find amount in this row
    amount_block = None
    
    if amount_column_x is not None:
        # Find amount near the identified column
        for block in row:
            if block.get("is_amount", False):
                block_x = block.get("center_x", block.get("x", 0))
                if abs(block_x - amount_column_x) <= X_COLUMN_TOLERANCE:
                    amount_block = block
                    break
    else:
        # Fallback: use rightmost amount
        row_amounts = [b for b in row if b.get("is_amount", False)]
        if row_amounts:
            amount_block = max(row_amounts, key=lambda b: b.get("center_x", b.get("x", 0)))
    
    if not amount_block or amount_block.get("amount") is None:
        return None
    
    # Collect all text blocks (excluding the amount block)
    text_blocks = [
        b for b in row
        if b != amount_block and not b.get("is_amount", False)
    ]
    
    # Sort by X coordinate (left to right)
    text_blocks.sort(key=lambda b: b.get("x", 0))
    
    # Filter out "Code:" patterns and product codes
    # Product codes are typically on separate lines or after the product name
    filtered_text_blocks = []
    for b in text_blocks:
        text = b.get("text", "").strip()
        text_lower = text.lower()
        # Skip "Code:" labels and product codes (typically numeric)
        if text_lower.startswith("code:") or (text_lower.startswith("code") and len(text) < 20):
            continue
        # Skip standalone numeric codes (likely product codes, not product names)
        if text.isdigit() and len(text) >= 6:  # Product codes are usually 6+ digits
            continue
        filtered_text_blocks.append(b)
    
    # Combine text blocks into product name
    product_parts = [b.get("text", "").strip() for b in filtered_text_blocks if b.get("text", "").strip()]
    product_name = " ".join(product_parts)
    
    if not product_name:
        return None
    
    # Skip if this looks like a header or summary line
    if _is_header_or_summary_line(product_name):
        return None
    
    return {
        "product_name": product_name,
        "line_total": amount_block.get("amount"),
        "raw_text": product_name,  # Can be enhanced with full row text
        "y": row[0].get("y", 0),  # Use first block's Y coordinate
        "x_amount": amount_block.get("center_x", amount_block.get("x", 0))
    }


def _is_header_or_summary_line(text: str) -> bool:
    """
    Check if a line is a header or summary line (not an item).
    """
    text_lower = text.lower()
    
    # Common header/summary patterns
    patterns = [
        "subtotal", "sub-total", "sub total",
        "total", "total sales", "total amount",
        "tax", "tax [", "tax:",
        "bottle deposit", "environment fee", "env fee",
        "discount", "saving", "markdown",
        "payment", "card", "visa", "cash",
        "item", "qty", "quantity", "price",
        "transaction", "invoice", "receipt"
    ]
    
    for pattern in patterns:
        if pattern in text_lower:
            return True
    
    return False
