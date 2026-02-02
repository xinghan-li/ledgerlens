"""
Coordinate Extractor: Extract text blocks and amounts with coordinates from Document AI response.

This module processes coordinate data from Document AI to extract:
- Text blocks with their positions
- Amount values with coordinates
- Structured layout information
"""
from typing import Dict, Any, List, Optional, Tuple
import re
import logging

logger = logging.getLogger(__name__)

# Amount pattern: matches currency amounts like $12.34, 12.34, etc.
AMOUNT_PATTERN = re.compile(r'\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)')


def extract_text_blocks_with_coordinates(coordinate_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract all text blocks with coordinates from Document AI coordinate data.
    
    Args:
        coordinate_data: Coordinate data from Document AI (from _extract_coordinate_data)
        
    Returns:
        List of text blocks, each containing:
        {
            "text": str,
            "x": float,  # normalized (0-1)
            "y": float,  # normalized (0-1)
            "width": float,
            "height": float,
            "center_x": float,
            "center_y": float,
            "confidence": float,
            "is_amount": bool,
            "amount": Optional[float],
            "page_number": int
        }
    """
    blocks = []
    
    # Extract from text_blocks (tokens)
    for block in coordinate_data.get("text_blocks", []):
        bbox = block.get("bounding_box")
        if not bbox:
            continue
        
        text = block.get("text", "").strip()
        if not text:
            continue
        
        # Check if this is an amount
        is_amount, amount_value = _extract_amount(text)
        
        block_data = {
            "text": text,
            "x": bbox.get("x", 0),
            "y": bbox.get("y", 0),
            "width": bbox.get("width", 0),
            "height": bbox.get("height", 0),
            "center_x": bbox.get("center_x", 0),
            "center_y": bbox.get("center_y", 0),
            "confidence": block.get("confidence"),
            "is_amount": is_amount,
            "amount": amount_value,
            "page_number": block.get("page_number", 1)
        }
        
        blocks.append(block_data)
    
    # Sort by Y coordinate (top to bottom), then by X coordinate (left to right)
    blocks.sort(key=lambda b: (b["y"], b["x"]))
    
    logger.debug(f"Extracted {len(blocks)} text blocks, {sum(1 for b in blocks if b['is_amount'])} amounts")
    
    return blocks


def extract_amount_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract only amount blocks from text blocks.
    
    Args:
        blocks: List of text blocks from extract_text_blocks_with_coordinates
        
    Returns:
        List of amount blocks (filtered and sorted)
    """
    amount_blocks = [b for b in blocks if b.get("is_amount", False)]
    
    # Sort by Y coordinate (top to bottom)
    amount_blocks.sort(key=lambda b: b["y"])
    
    return amount_blocks


def _extract_amount(text: str) -> Tuple[bool, Optional[float]]:
    """
    Extract amount value from text.
    
    Returns:
        (is_amount, amount_value)
    """
    # Remove common prefixes/suffixes that might interfere
    cleaned = text.strip()
    
    # Pattern: $12.34, 12.34, $1,234.56, etc.
    match = AMOUNT_PATTERN.search(cleaned)
    if match:
        try:
            # Remove commas and convert to float
            amount_str = match.group(1).replace(',', '')
            amount_value = float(amount_str)
            
            # Only consider reasonable amounts (between $0.01 and $999,999.99)
            if 0.01 <= amount_value <= 999999.99:
                return True, amount_value
        except (ValueError, AttributeError):
            pass
    
    return False, None


def find_marker_blocks(
    blocks: List[Dict[str, Any]], 
    marker_texts: List[str],
    case_sensitive: bool = False
) -> List[Dict[str, Any]]:
    """
    Find blocks that match marker texts.
    
    Args:
        blocks: List of text blocks
        marker_texts: List of marker text patterns (e.g., ["SUBTOTAL", "SUB-TOTAL"])
        case_sensitive: Whether matching is case sensitive
        
    Returns:
        List of matching blocks
    """
    matches = []
    
    if not case_sensitive:
        marker_texts = [m.lower() for m in marker_texts]
    
    for block in blocks:
        text = block.get("text", "")
        if not case_sensitive:
            text = text.lower()
        
        for marker in marker_texts:
            if marker in text:
                matches.append(block)
                break
    
    return matches


def find_first_item_marker(blocks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Find the first item marker (first product line, usually has a price).
    
    Strategy:
    1. Look for lines that contain both text and an amount
    2. Skip header lines (store name, address, date)
    3. The first line with an amount that's not in header region is likely the first item
    """
    # Common header patterns to skip
    header_patterns = [
        r'store|shop|market|supermarket|grocery',
        r'address|street|road|ave|blvd',
        r'date|time|receipt|invoice',
        r'phone|tel|call',
        r'cashier|register|lane'
    ]
    
    header_pattern = re.compile('|'.join(header_patterns), re.IGNORECASE)
    
    # Find first block that:
    # 1. Has an amount
    # 2. Is not a header pattern
    # 3. Has some text (product name)
    for block in blocks:
        if not block.get("is_amount"):
            continue
        
        text = block.get("text", "")
        if not text or len(text.strip()) < 3:
            continue
        
        # Skip if matches header pattern
        if header_pattern.search(text):
            continue
        
        # This is likely the first item
        return block
    
    # Fallback: return first block with amount
    for block in blocks:
        if block.get("is_amount"):
            return block
    
    return None
