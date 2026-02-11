"""
Region Splitting: Split receipt into header, items, totals, and payment regions.

General rule (all receipts): Four sections —
  1) Header: store info at top until timestamp/cashier or the line above first item.
  2) Items: all purchased items.
  3) Totals: subtotal through TOTAL (price calculation).
  4) Payment: from TOTAL downward — payment method and other info.

Supports optional store_config for chain-specific markers (e.g. T&T: items start
after date/time row, or after membership row if present).
"""
from typing import List, Optional, Tuple
import logging
import re
from .receipt_structures import PhysicalRow, ReceiptRegions, RowType

logger = logging.getLogger(__name__)

DEFAULT_SUBTOTAL_MARKERS = ['SUB TOTAL', 'SUBTOTAL', 'SUB-TOTAL']
DEFAULT_PAYMENT_KEYWORDS = [
    'VISA', 'MASTERCARD', 'CARD', 'AMOUNT : USD', 'AMOUNT:USD',
    'AMEX', 'DISCOVER', 'CASH', 'PAYMENT', 'TENDER'
]


def _get_subtotal_markers(store_config: Optional[dict]) -> List[str]:
    if not store_config:
        return DEFAULT_SUBTOTAL_MARKERS
    seq = store_config.get("totals", {}).get("sequence", [])
    markers = []
    for entry in seq:
        if entry.get("label_key") == "subtotal":
            markers.extend(entry.get("markers", []))
    return markers if markers else DEFAULT_SUBTOTAL_MARKERS


def _get_payment_keywords(store_config: Optional[dict]) -> List[str]:
    """Keywords that trigger transition from TOTALS to PAYMENT. Prefer section_start_markers (strict) so Tax/Total rows stay in totals."""
    if not store_config:
        return DEFAULT_PAYMENT_KEYWORDS
    payment = store_config.get("payment", {})
    start = payment.get("section_start_markers", [])
    if start:
        return list(start)
    kw = payment.get("markers", [])
    return list(kw) if kw else DEFAULT_PAYMENT_KEYWORDS


def _is_date_time_or_cashier_row(row: PhysicalRow, store_config: Optional[dict]) -> bool:
    """
    True if row matches header end (date/time pattern ONLY).
    For T&T: date/time format like '02/03/26 11:59:44 AM' or '01/10/26 1:45:58 PM'.
    
    IMPORTANT: Only match actual date/time patterns, not other end_markers like SC-1 or ***.
    """
    if not store_config:
        return False
    
    text = row.text.strip()
    
    # Only match date/time pattern (MM/DD/YY HH:MM:SS AM/PM)
    if re.search(r'\d{2}/\d{2}/\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M', text):
        return True
    
    return False


def _is_membership_row(row: PhysicalRow, store_config: Optional[dict]) -> bool:
    """True if row looks like membership line: ***digits and $0.00 (can be in same or separate rows)."""
    if not store_config:
        return False
    text = row.text.strip()
    if not re.search(r"\*{2,}\d+", text):
        return False
    # Must have $0.00 (or 0.00) for membership line
    if re.search(r"\$?\s*0\.00\b", text):
        return True
    for block in row.get_amount_blocks():
        if block.amount is not None and abs(block.amount) < 0.01:
            return True
    return False


def _detect_and_extract_membership(item_rows: List[PhysicalRow], store_config: Optional[dict]) -> Tuple[Optional[str], List[PhysicalRow]]:
    """
    Detect and extract membership from first 1-2 rows of items section.
    
    For T&T: If items start with ***[digits] (left) + $0.00 (right), extract membership ID.
    The membership can be:
    - Single row: "***600032371" + "$0.00" in same row
    - Two rows: Row 1 "$0.00", Row 2 "***600032371"
    
    If membership is detected, also remove the last row if it's "Points [number]" + "$0.00"
    (membership receipt footer).
    
    Returns:
        (membership_id, filtered_item_rows): membership ID if found, and item_rows with membership rows removed
    """
    pipeline = (store_config or {}).get("pipeline", {}) or {}
    if not pipeline.get("membership_extraction", False):
        return None, item_rows
    
    if not item_rows or len(item_rows) < 1:
        return None, item_rows
    
    membership_id = None
    rows_to_remove = []
    
    # Check first row
    first_row = item_rows[0]
    first_text = first_row.text.strip()
    
    # Case 1: Single row with both *** and $0.00
    membership_match = re.search(r"\*{2,}(\d+)", first_text)
    has_zero = re.search(r"\$?\s*0\.00\b", first_text) or any(
        b.amount is not None and abs(b.amount) < 0.01 for b in first_row.get_amount_blocks()
    )
    
    if membership_match and has_zero:
        membership_id = membership_match.group(1)
        rows_to_remove.append(0)
        logger.info(f"Detected membership (single row): {membership_id}")
    
    # Case 2: Two rows - first is $0.00, second is ***digits
    elif len(item_rows) >= 2:
        second_row = item_rows[1]
        second_text = second_row.text.strip()
        
        # Check if first row has $0.00 and second has ***
        first_has_zero = re.search(r"\$?\s*0\.00\b", first_text) or any(
            b.amount is not None and abs(b.amount) < 0.01 for b in first_row.get_amount_blocks()
        )
        second_match = re.search(r"\*{2,}(\d+)", second_text)
        
        if first_has_zero and second_match:
            membership_id = second_match.group(1)
            rows_to_remove = [0, 1]
            logger.info(f"Detected membership (two rows): {membership_id}")
    
    # If membership found, also check last row for "Points [number]" + "$0.00"
    if membership_id and len(item_rows) > len(rows_to_remove):
        last_idx = len(item_rows) - 1
        last_row = item_rows[last_idx]
        last_text = last_row.text.strip()
        
        # Check if last row has "Points" + number + $0.00
        if re.search(r"Points?\s+\d+", last_text, re.IGNORECASE):
            last_has_zero = re.search(r"\$?\s*0\.00\b", last_text) or any(
                b.amount is not None and abs(b.amount) < 0.01 for b in last_row.get_amount_blocks()
            )
            if last_has_zero:
                rows_to_remove.append(last_idx)
                logger.info(f"Detected membership footer (Points line): '{last_text[:60]}'")
    
    # Remove membership rows from item_rows
    if rows_to_remove:
        filtered_rows = [row for idx, row in enumerate(item_rows) if idx not in rows_to_remove]
        return membership_id, filtered_rows
    
    return None, item_rows


def _get_tnt_items_start_index(rows: List[PhysicalRow], store_config: Optional[dict]) -> Optional[int]:
    """
    For T&T (SIMPLIFIED): Header ends at date/time row.
    
    Logic:
    1. Find row with date/time pattern (e.g. '01/10/26 1:45:58 PM')
    2. Header ALWAYS ends at this row (max Y of date/time/clerk ID blocks)
    3. Items section starts immediately after
    4. Membership (if present) will be detected separately in items section
    
    Returns index of first row that should be ITEM, or None if not using this rule.
    """
    pipeline = (store_config or {}).get("pipeline", {}) or {}
    if not pipeline.get("membership_extraction", False):
        return None

    for i, row in enumerate(rows):
        if not _is_date_time_or_cashier_row(row, store_config):
            continue
        
        # Found date/time row at index i - header ends here
        logger.info(f"T&T header ends at date/time row {i} (y={row.y_center:.4f}): '{row.text[:60]}'")
        return i + 1
    
    return None


def _split_regions_costco_digital(
    rows: List[PhysicalRow], store_config: Optional[dict]
) -> Optional[ReceiptRegions]:
    """
    Costco digital layout: TOTAL at top, items between Member/tax and SUBTOTAL.
    Header = rows before first TOTAL; Items = product rows between TOTAL and SUBTOTAL;
    Totals = TOTAL + tax + SUBTOTAL; Payment = after SUBTOTAL.
    """
    if not store_config or store_config.get("layout") != "costco_ca_digital":
        return None

    header_rows = []
    item_rows = []
    totals_rows = []
    payment_rows = []

    payment_keywords = _get_payment_keywords(store_config)
    costco_product_pattern = re.compile(r"^\d{6,7}\s+\w+|\d{6,7}\s+[A-Z]", re.IGNORECASE)
    tax_markers = ["(A) HST", "(B) 5% GST", "TOTAL TAX", "TAX", "H=HST"]
    skip_item_markers = ["INSTANT SAVINGS", "TPD/", "Thank You", "Please Come", "TOTAL NUMBER", "Items Sold"]

    total_idx = None
    subtotal_idx = None

    for i, row in enumerate(rows):
        text = (row.text or "").strip()
        norm = _fuzzy_normalize(text.upper())
        if total_idx is None and _row_is_total_line(text.upper(), norm) and row.get_amount_blocks():
            total_idx = i
        if subtotal_idx is None and "SUBTOTAL" in norm and "SUB" in text.upper():
            subtotal_idx = i
        # Do not break — need both indices (SUBTOTAL may come before TOTAL on page 1 bottom)

    if subtotal_idx is None:
        logger.debug("[Costco] No SUBTOTAL found, fallback to default split")
        return None

    # Totals end = later of SUBTOTAL/TOTAL; payment starts after that
    totals_end_idx = max(i for i in (total_idx, subtotal_idx) if i is not None)
    # Header: rows before first TOTAL (when TOTAL is at top); else 0 so all rows get classified
    header_end = total_idx if (total_idx is not None and total_idx < subtotal_idx) else 0

    for i in range(header_end):
        rows[i].row_type = RowType.HEADER
        header_rows.append(rows[i])

    for i in range(header_end, len(rows)):
        text = (rows[i].text or "").strip()
        text_upper = text.upper()
        norm = _fuzzy_normalize(text_upper)
        has_amount = bool(rows[i].get_amount_blocks())

        if i == total_idx:
            rows[i].row_type = RowType.TOTALS
            totals_rows.append(rows[i])
        elif i == subtotal_idx:
            rows[i].row_type = RowType.TOTALS
            totals_rows.append(rows[i])
        elif i > totals_end_idx:
            rows[i].row_type = RowType.PAYMENT
            payment_rows.append(rows[i])
        elif any(m in text_upper for m in tax_markers):
            rows[i].row_type = RowType.TOTALS
            totals_rows.append(rows[i])
        elif any(m in text_upper for m in skip_item_markers):
            rows[i].row_type = RowType.TOTALS
            totals_rows.append(rows[i])
        elif _fuzzy_contains(norm, payment_keywords) or re.search(r"Member\s*\d+", text, re.IGNORECASE):
            rows[i].row_type = RowType.PAYMENT
            payment_rows.append(rows[i])
        elif has_amount and (costco_product_pattern.search(text) or re.search(r"\d{6,7}\s+\S+", text)):
            rows[i].row_type = RowType.ITEM
            item_rows.append(rows[i])
        elif has_amount and len(text) > 8:
            rows[i].row_type = RowType.ITEM
            item_rows.append(rows[i])
        else:
            rows[i].row_type = RowType.PAYMENT
            payment_rows.append(rows[i])

    membership_id = None
    for row in header_rows + item_rows + payment_rows:
        m = re.search(r"Member\s*(\d{10,12})", (row.text or ""), re.IGNORECASE)
        if m:
            membership_id = m.group(1)
            break

    regions = ReceiptRegions(
        header_rows=header_rows,
        item_rows=item_rows,
        totals_rows=totals_rows,
        payment_rows=payment_rows,
    )
    regions.membership_id = membership_id

    logger.info(
        f"Costco digital region split: Header={len(header_rows)}, "
        f"Items={len(item_rows)}, Totals={len(totals_rows)}, Payment={len(payment_rows)}"
    )
    return regions


def split_regions(rows: List[PhysicalRow], store_config: Optional[dict] = None) -> ReceiptRegions:
    """
    Split receipt rows into regions based on marker patterns.

    Args:
        rows: List of PhysicalRow objects (should be sorted top to bottom)
        store_config: Optional store receipt config for chain-specific markers
    Returns:
        ReceiptRegions object with partitioned rows
    """
    costco_regions = _split_regions_costco_digital(rows, store_config)
    if costco_regions is not None:
        return costco_regions

    header_rows = []
    item_rows = []
    totals_rows = []
    payment_rows = []

    subtotal_markers = _get_subtotal_markers(store_config)
    payment_keywords = _get_payment_keywords(store_config)
    mode = 'HEADER'

    # T&T: force items to start at this index (after date/time or after membership row)
    tnt_items_start = _get_tnt_items_start_index(rows, store_config)

    for i, row in enumerate(rows):
        text_upper = row.text.upper()
        normalized = _fuzzy_normalize(text_upper)

        # Check for subtotal marker (transition from items to totals)
        if mode in ['HEADER', 'ITEM'] and _fuzzy_contains(normalized, subtotal_markers):
            mode = 'TOTALS'
            row.row_type = RowType.TOTALS
            totals_rows.append(row)
            logger.debug(f"Row {row.row_id}: Transition to TOTALS region (found subtotal marker)")
            continue

        # Grocery receipts may have no subtotal, only "TOTAL $X.XX" - transition to TOTALS on that
        if mode in ['HEADER', 'ITEM'] and _row_is_total_line(text_upper, normalized):
            mode = 'TOTALS'
            row.row_type = RowType.TOTALS
            totals_rows.append(row)
            logger.debug(f"Row {row.row_id}: Transition to TOTALS region (found total line)")
            continue

        # Check for payment markers (transition from totals to payment)
        if mode == 'TOTALS' and _fuzzy_contains(normalized, payment_keywords):
            mode = 'PAYMENT'
            row.row_type = RowType.PAYMENT
            payment_rows.append(row)
            logger.debug(f"Row {row.row_id}: Transition to PAYMENT region (found payment marker)")
            continue
        
        # T&T rule: at items-start index, switch to ITEM (before assigning to header)
        if tnt_items_start is not None and i == tnt_items_start and mode == 'HEADER':
            mode = 'ITEM'
            row.row_type = RowType.ITEM
            item_rows.append(row)
            logger.debug(f"Row {row.row_id}: T&T items start (index {i})")
            continue

        # Assign row to current region
        if mode == 'HEADER':
            row.row_type = RowType.HEADER
            header_rows.append(row)
        elif mode == 'ITEM':
            row.row_type = RowType.ITEM
            item_rows.append(row)
        elif mode == 'TOTALS':
            row.row_type = RowType.TOTALS
            totals_rows.append(row)
        elif mode == 'PAYMENT':
            row.row_type = RowType.PAYMENT
            payment_rows.append(row)
        
        # Auto-transition: if we're in HEADER and see what looks like an item, switch to ITEM
        # BUT: skip auto-transition if using T&T explicit items-start rule
        if mode == 'HEADER' and tnt_items_start is None and _looks_like_item_row(row):
            mode = 'ITEM'
            row.row_type = RowType.ITEM
            # Move this row from header to items
            if header_rows and header_rows[-1] == row:
                header_rows.pop()
            item_rows.append(row)
    
    # Detect and extract membership from first 1-2 rows of items (for T&T)
    membership_id, filtered_item_rows = _detect_and_extract_membership(item_rows, store_config)
    if membership_id:
        logger.info(f"Extracted membership ID: {membership_id}, removed {len(item_rows) - len(filtered_item_rows)} rows from items")
        item_rows = filtered_item_rows
    
    regions = ReceiptRegions(
        header_rows=header_rows,
        item_rows=item_rows,
        totals_rows=totals_rows,
        payment_rows=payment_rows
    )
    
    logger.info(
        f"Region split: Header={len(header_rows)} rows, "
        f"Items={len(item_rows)} rows, "
        f"Totals={len(totals_rows)} rows, "
        f"Payment={len(payment_rows)} rows"
    )
    
    # Store membership as a dynamic attribute (not in dataclass)
    regions.membership_id = membership_id
    
    return regions


def _fuzzy_normalize(text: str) -> str:
    """
    Normalize text for fuzzy matching (remove spaces, dots, special chars).
    
    Args:
        text: Input text
        
    Returns:
        Normalized text
    """
    # Remove dots, spaces, and common punctuation
    normalized = re.sub(r'[.\s\-_]', '', text.upper())
    return normalized


def _row_is_total_line(text_upper: str, normalized: str) -> bool:
    """
    True if this row is a standalone TOTAL line (e.g. "TOTAL $22.77", "TOTAL SALES").
    Must not match "SUB TOTAL" (handled above).
    """
    if 'SUB' in text_upper and 'TOTAL' in text_upper:
        return False
    return _fuzzy_contains(normalized, ['TOTAL', 'TOTALSALES', 'TOTAL SALES'])


def _fuzzy_contains(text: str, keywords: List[str]) -> bool:
    """
    Check if text contains any of the keywords (fuzzy matching).
    
    Args:
        text: Text to search (should be normalized)
        keywords: List of keywords to search for
        
    Returns:
        True if any keyword is found
    """
    for keyword in keywords:
        keyword_norm = _fuzzy_normalize(keyword)
        if keyword_norm in text:
            return True
    return False


def _looks_like_item_row(row: PhysicalRow) -> bool:
    """
    Heuristic to determine if a row looks like an item row.
    
    Args:
        row: PhysicalRow to check
        
    Returns:
        True if row appears to be an item
    """
    # Check if row has an amount block (items typically have prices)
    if row.get_amount_blocks():
        return True
    
    # Check if text looks like a product name (not a header marker)
    text = row.text.upper()
    header_markers = ['STORE', 'ADDRESS', 'PHONE', 'DATE', 'TIME', 'RECEIPT', 'INVOICE']
    if any(marker in text for marker in header_markers):
        return False
    
    # If it has substantial text and no header markers, likely an item
    if len(text.strip()) > 5:
        return True
    
    return False


def rows_between_y(
    rows: List[PhysicalRow],
    y_start: float,
    y_end: float
) -> List[PhysicalRow]:
    """
    Get rows between two Y coordinates.
    
    Args:
        rows: List of PhysicalRow objects
        y_start: Start Y coordinate
        y_end: End Y coordinate
        
    Returns:
        List of rows with y_center between y_start and y_end
    """
    return [
        row for row in rows
        if y_start <= row.y_center <= y_end
    ]
