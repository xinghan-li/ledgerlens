"""
Coordinate Extractor: Extract text blocks and amounts with coordinates from Document AI response.

This module processes coordinate data from Document AI to extract:
- Text blocks with their positions
- Amount values with coordinates
- Structured layout information
- Receipt body filter: delegates to receipt_body_detector (content-relative bounds)
"""
from typing import Dict, Any, List, Optional, Tuple
import re
import logging

from .receipt_body_detector import filter_blocks_by_receipt_body

logger = logging.getLogger(__name__)

# Amount pattern: matches currency amounts like $12.34, 12.34, etc.
AMOUNT_PATTERN = re.compile(r'\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)')


def extract_text_blocks_with_coordinates(
    coordinate_data: Dict[str, Any],
    apply_receipt_body_filter: bool = True,
) -> List[Dict[str, Any]]:
    """
    Extract all text blocks with coordinates from Document AI coordinate data.

    Args:
        coordinate_data: Coordinate data from Document AI (from _extract_coordinate_data)
        apply_receipt_body_filter: If True (default), keep only blocks inside estimated receipt body.
            Set False to get all blocks (e.g. for body-detector API to show kept vs dropped).

    Returns:
        List of text blocks, each containing:
        {
            "text": str,
            "x": float,  # normalized (0-1) per page
            "y": float,  # GLOBAL: (page_number-1) + normalized_y, so page 1 [0,1), page 2 [1,2), ...
            "width": float,
            "height": float,
            "center_x": float,
            "center_y": float,  # GLOBAL: (page_number-1) + normalized, same as y
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

        # Check if this is an amount (and if comma was used as decimal - OCR noise)
        is_amount, amount_value, had_comma_decimal = _extract_amount(text)
        pn = block.get("page_number", 1)
        base_y = (pn - 1)  # Global Y: page 1 [0,1), page 2 [1,2), page 3 [2,3), ...
        raw_y = bbox.get("y", 0)
        raw_cy = bbox.get("center_y") or bbox.get("y", 0)
        block_data = {
            "text": text,
            "x": bbox.get("x", 0),
            "y": base_y + raw_y,
            "width": bbox.get("width", 0),
            "height": bbox.get("height", 0),
            "center_x": bbox.get("center_x", 0),
            "center_y": base_y + raw_cy,
            "confidence": block.get("confidence"),
            "is_amount": is_amount,
            "amount": amount_value,
            "page_number": pn
        }
        if had_comma_decimal:
            block_data["comma_decimal_corrected"] = True

        blocks.append(block_data)

    # Sort by Y coordinate (top to bottom), then by X coordinate (left to right)
    blocks.sort(key=lambda b: (b["y"], b["x"]))

    if apply_receipt_body_filter:
        blocks = filter_blocks_by_receipt_body(blocks)

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


def _normalize_comma_decimal(text: str) -> str:
    """
    Normalize comma-as-decimal to dot: $12,88 -> $12.88, 1,19 lb -> 1.19 lb.
    Only replaces XX,YY when it looks like decimal (two digits after comma), not thousands.
    """
    # $xx,xx or x,xx (2 digits after comma) -> dot
    return re.sub(r"(\d),(\d{2})\b", r"\1.\2", text.strip())


def _extract_amount(text: str) -> Tuple[bool, Optional[float], bool]:
    """
    Extract amount value from text.
    App never uses comma as decimal; if OCR returns e.g. 3,99 we normalize to 3.99 and flag.
    Returns:
        (is_amount, amount_value, had_comma_decimal)
    """
    # European-style decimal (comma): 3,99 -> 3.99 (OCR noise; flag it) — check before normalizing
    raw = text.strip()
    eu_match = re.search(r'\$?\s*(\d+),(\d{2})\b', raw)
    if eu_match:
        try:
            amount_value = float(eu_match.group(1) + '.' + eu_match.group(2))
            if 0.01 <= amount_value <= 999999.99:
                return True, amount_value, True
        except (ValueError, AttributeError):
            pass

    # Normalize comma-as-decimal ($xx,xx and x,xx lb) so downstream patterns match
    cleaned = _normalize_comma_decimal(text)
    # Skip if this looks like a phone number, zip code, or other non-amount number
    # Phone patterns: (808) 886-3577, 808-886-3577, 808.886.3577
    phone_pattern = re.compile(r'\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}')
    if phone_pattern.search(cleaned):
        return False, None, False
    
    # Zip code patterns: 96738, 96738-1234, V6X 3X2 (Canadian)
    zip_pattern = re.compile(r'\b\d{5}(?:-\d{4})?\b|\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b')
    if zip_pattern.search(cleaned) and not cleaned.startswith('$'):
        return False, None, False
    
    # Skip if it's a store number or ID (e.g., "#77", "Store #77")
    if re.search(r'(?:store|#|no\.?|number)\s*\d+', cleaned, re.IGNORECASE):
        return False, None, False

    # Skip if it's an operator/cashier ID (e.g., "OPER:48097")
    if re.search(r'(?:oper|operator|cashier|cash|reg|register)[\s:]*\d+', cleaned, re.IGNORECASE):
        return False, None, False

    # Skip if it's a URL or website
    if re.search(r'(?:www\.|http|\.com|\.org|\.net)', cleaned, re.IGNORECASE):
        return False, None, False
    
    # Pattern: $12.34, 12.34, $1,234.56, etc. (comma = thousands separator, not decimal)
    match = AMOUNT_PATTERN.search(cleaned)
    if match:
        try:
            amount_str = match.group(1).replace(',', '')
            amount_value = float(amount_str)
            if 0.01 <= amount_value <= 999999.99:
                has_dollar_sign = '$' in cleaned
                has_receipt_code = bool(re.search(r'[TQ]\d+[FP]?', cleaned, re.IGNORECASE))
                is_standalone_number = len(cleaned.strip()) < 10
                if has_dollar_sign or has_receipt_code or is_standalone_number:
                    return True, amount_value, False
        except (ValueError, AttributeError):
            pass

    return False, None, False


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
    2. Skip header lines (store name, address, date, phone, operator, website)
    3. The first line with an amount that's not in header region is likely the first item
    """
    # Common header patterns to skip
    # User requirement: "能有一个一致的区分把第一区和item区明确区分开"
    # This includes: store info, address, phone, website, transaction/cashier numbers, etc.
    header_patterns = [
        r'store|shop|market|supermarket|grocery',
        r'address|street|road|ave|blvd|hwy|highway',
        r'date|time|receipt|invoice',
        r'phone|tel|call|\(?\d{3}\)?[\s.-]?\d{3}',
        r'cashier|register|lane|oper|operator',
        r'www\.|http|\.com|\.org|\.net',
        r'zip|postal|code|\b\d{5}(?:-\d{4})?\b',
        r'#\s*\d+|store\s*#|no\.?\s*\d+',
        r'transaction|trs#|inv:|inv\s*#|oper\s*#',  # Transaction numbers, invoice numbers
        r'corporate|office|keep\s*in\s*touch',  # Additional header text
        r'^\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}',  # Date/time patterns
    ]
    
    header_pattern = re.compile('|'.join(header_patterns), re.IGNORECASE)
    
    # Track the last header block's Y coordinate
    # Items should start after all header information (including system info like transaction #)
    last_header_y = 0.0
    header_blocks = []
    for block in blocks:
        text = block.get("text", "")
        if text and header_pattern.search(text):
            block_y = block.get("y", 0)
            last_header_y = max(last_header_y, block_y)
            header_blocks.append(block)
    
    # Additional heuristic: if we found header blocks, ensure we have a clear boundary
    # Look for a gap or separator between header and items
    # Items typically start with a product name followed by an amount
    
    # Find first block that:
    # 1. Has an amount (indicating it's a price)
    # 2. Is below the header region (Y coordinate > last_header_y + tolerance)
    # 3. Is not a header pattern
    # 4. Has some text (product name)
    # 5. Amount is reasonable (not a phone number, zip code, etc.)
    # 6. The amount is in a reasonable range for a product price
    for block in blocks:
        if not block.get("is_amount"):
            continue
        
        block_y = block.get("y", 0)
        # Must be below header region with some margin
        # Use larger tolerance to ensure we skip all header/system info
        if block_y <= last_header_y + 0.02:  # Increased from 0.01 to 0.02
            continue
        
        text = block.get("text", "")
        if not text or len(text.strip()) < 3:
            continue
        
        # Skip if matches header pattern
        if header_pattern.search(text):
            continue
        
        # Additional check: amount should be reasonable for a product price
        amount = block.get("amount")
        if amount and (amount > 10000 or amount < 0.01):
            continue
        
        # Check if there's a product name nearby (on the same row or close)
        # Items typically have text before the amount
        has_product_name = False
        block_x = block.get("x", 0)
        for other_block in blocks:
            other_y = other_block.get("y", 0)
            other_x = other_block.get("x", 0)
            # Check if there's text on the same row (similar Y) and to the left (smaller X)
            if (abs(other_y - block_y) < 0.01 and 
                other_x < block_x - 0.05 and  # At least 5% to the left
                not other_block.get("is_amount") and
                len(other_block.get("text", "").strip()) > 2):
                has_product_name = True
                break
        
        # If no product name found, this might still be an item (amount might be standalone)
        # But prefer blocks with product names
        
        # This is likely the first item
        logger.debug(f"Found first item marker: '{text}' at Y={block_y:.3f} (header ended at Y={last_header_y:.3f}, has_product_name={has_product_name})")
        return block
    
    # Fallback: return first block with amount below header
    for block in blocks:
        if block.get("is_amount") and block.get("y", 0) > last_header_y + 0.02:
            return block
    
    return None
