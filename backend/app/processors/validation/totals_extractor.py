"""
Totals Sequence Extractor: Extract subtotal, fees, tax, and total.

This module implements Step 5 of the receipt processing pipeline.
"""
from typing import List, Optional, Tuple
import logging
from .receipt_structures import (
    PhysicalRow, ReceiptRegions, AmountColumns, AmountUsageTracker,
    TotalsSequence, TextBlock
)

logger = logging.getLogger(__name__)


def find_subtotal_and_total(
    regions: ReceiptRegions,
    amount_columns: AmountColumns,
    tracker: AmountUsageTracker
) -> TotalsSequence:
    """
    Find subtotal and total rows and amounts in totals_rows.
    
    Args:
        regions: ReceiptRegions with totals_rows populated
        amount_columns: AmountColumns with detected columns
        tracker: AmountUsageTracker to mark used blocks
        
    Returns:
        TotalsSequence with subtotal and total identified
    """
    subtotal = None
    total = None
    subtotal_row = None
    total_row = None
    
    main_x = amount_columns.main_column.center_x
    tolerance = amount_columns.main_column.tolerance
    
    logger.debug(f"[Totals] Scanning {len(regions.totals_rows)} totals_rows, main_x={main_x:.4f}, tolerance={tolerance:.4f}")
    for row in regions.totals_rows:
        logger.debug(f"[Totals] Row {row.row_id}: Y={row.y_center:.4f}, text='{row.text}', amounts={[f'${b.amount:.2f}@X={b.center_x:.4f}' for b in row.get_amount_blocks()]}")
        normalized = _fuzzy_normalize(row.text)
        
        # Look for subtotal
        if subtotal is None and _fuzzy_contains(normalized, ['SUB TOTAL', 'SUBTOTAL', 'SUB-TOTAL']):
            block = _find_amount_in_row(row, main_x, tolerance, tracker)
            if block:
                subtotal = block
                subtotal_row = row
                tracker.mark_used(block, role="SUBTOTAL", row_id=row.row_id)
                logger.info(f"Found SUBTOTAL: ${block.amount:.2f} at row {row.row_id}")
        
        # Look for total (must not be subtotal row — e.g. "SUB TOTAL" contains "TOTAL")
        if total is None and _fuzzy_contains(normalized, ['TOTAL SALES', 'TOTAL', 'GRAND TOTAL', 'TOTAL DUE']):
            logger.debug(f"[Totals] Row {row.row_id} contains 'TOTAL' keyword: '{row.text}'")
            if _fuzzy_contains(normalized, ['SUB TOTAL', 'SUBTOTAL', 'SUB-TOTAL']):
                logger.debug(f"[Totals] Row {row.row_id} is SUBTOTAL, skipping")
                pass  # this is subtotal row, not total row
            else:
                block = _find_amount_in_row(row, main_x, tolerance, tracker)
                logger.debug(f"[Totals] Row {row.row_id}: _find_amount_in_row returned {block}")
                if not block:
                    block = _find_any_unused_amount_in_row(row, tracker)
                    logger.debug(f"[Totals] Row {row.row_id}: _find_any_unused_amount_in_row returned {block}")
                if block:
                    total = block
                    total_row = row
                    tracker.mark_used(block, role="TOTAL", row_id=row.row_id)
                    logger.info(f"Found TOTAL: ${block.amount:.2f} at row {row.row_id}")
                else:
                    logger.warning(f"[Totals] Row {row.row_id} contains 'TOTAL' but no amount block found")
    
    # Fallback: if we still don't have total, scan again for any row with TOTAL (not SUB) and any unused amount
    if total is None and regions.totals_rows:
        for i, row in enumerate(regions.totals_rows):
            normalized = _fuzzy_normalize(row.text)
            if _fuzzy_contains(normalized, ['TOTAL']) and not _fuzzy_contains(normalized, ['SUB TOTAL', 'SUBTOTAL', 'SUB-TOTAL']):
                block = _find_any_unused_amount_in_row(row, tracker)
                if block:
                    total = block
                    total_row = row
                    tracker.mark_used(block, role="TOTAL", row_id=row.row_id)
                    logger.info(f"Found TOTAL (fallback): ${block.amount:.2f} at row {row.row_id}")
                    break
                else:
                    # CRITICAL: If TOTAL row has no amount, check the next row (might be split by row_reconstructor)
                    if i + 1 < len(regions.totals_rows):
                        next_row = regions.totals_rows[i + 1]
                        block = _find_any_unused_amount_in_row(next_row, tracker)
                        if block:
                            total = block
                            total_row = row  # Use TOTAL row as the row, but amount from next row
                            tracker.mark_used(block, role="TOTAL", row_id=next_row.row_id)
                            logger.info(f"Found TOTAL (next row fallback): ${block.amount:.2f} at row {next_row.row_id} (TOTAL text at row {row.row_id})")
                            break
    
    if total is None and regions.totals_rows:
        logger.warning("TOTAL row/amount not found in totals_rows; check region split and amount column")
    
    return TotalsSequence(
        subtotal=subtotal,
        subtotal_row=subtotal_row,
        total=total,
        total_row=total_row
    )


def collect_middle_amounts(
    regions: ReceiptRegions,
    totals_sequence: TotalsSequence,
    amount_columns: AmountColumns,
    tracker: AmountUsageTracker
) -> TotalsSequence:
    """
    Collect middle amounts (fees and tax) between subtotal and total.
    
    Args:
        regions: ReceiptRegions with totals_rows populated
        totals_sequence: TotalsSequence with subtotal and total already found
        amount_columns: AmountColumns with detected columns
        tracker: AmountUsageTracker to check used blocks
        
    Returns:
        TotalsSequence with middle_amounts populated
    """
    if not totals_sequence.subtotal_row:
        return totals_sequence
    
    # Get rows between subtotal and total (document order: smaller y = top)
    # Costco digital: TOTAL at top (small y), SUBTOTAL at bottom (large y) — so use min/max
    y_sub = totals_sequence.subtotal_row.y_center
    y_tot = totals_sequence.total_row.y_center if totals_sequence.total_row else (y_sub + 1.0)
    y_low, y_high = min(y_sub, y_tot), max(y_sub, y_tot)

    rows_between = [
        row for row in regions.totals_rows
        if y_low < row.y_center < y_high
    ]
    
    main_x = amount_columns.main_column.center_x
    tolerance = amount_columns.main_column.tolerance
    
    middle_amounts = []
    middle_rows = []
    
    for row in rows_between:
        for block in row.get_amount_blocks():
            if tracker.is_used(block):
                continue
            
            # Check if block is in main column or right half of page
            if abs(block.center_x - main_x) <= tolerance or block.center_x > 0.4:
                middle_amounts.append(block)
                middle_rows.append(row)
                # Don't mark as used here - let extract_tax_and_fees do it
                logger.debug(
                    f"Found middle amount: ${block.amount:.2f} at row {row.row_id} "
                    f"(text: '{row.text}')"
                )
    
    totals_sequence.middle_amounts = middle_amounts
    totals_sequence.middle_rows = middle_rows
    
    logger.info(f"Collected {len(middle_amounts)} middle amounts between subtotal and total")
    
    return totals_sequence


def _find_amount_in_row(
    row: PhysicalRow,
    column_x: float,
    tolerance: float,
    tracker: AmountUsageTracker
) -> Optional[TextBlock]:
    """Find an unused amount block in row that matches the column."""
    for block in row.get_amount_blocks():
        if tracker.is_used(block):
            continue
        if abs(block.center_x - column_x) <= tolerance:
            return block
    return None


def _find_any_unused_amount_in_row(
    row: PhysicalRow,
    tracker: AmountUsageTracker
) -> Optional[TextBlock]:
    """Find any unused amount block in row (e.g. for TOTAL when main column is slightly off)."""
    for block in row.get_amount_blocks():
        if tracker.is_used(block):
            continue
        return block
    return None


def _fuzzy_normalize(text: str) -> str:
    """Normalize text for fuzzy matching."""
    import re
    return re.sub(r'[.\s\-_]', '', text.upper())


def _fuzzy_contains(text: str, keywords: List[str]) -> bool:
    """Check if text contains any keyword (fuzzy matching)."""
    for keyword in keywords:
        keyword_norm = _fuzzy_normalize(keyword)
        if keyword_norm in text:
            return True
    return False
