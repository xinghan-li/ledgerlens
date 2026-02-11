"""
Skew Correction: Correct receipt skew using reference rows (date/time + cashier).

Uses top row (date + cashier) and bottom row (transaction/terminal area) to detect
skew. If both offsets are same direction and differ by less than half line height,
apply uniform correction. Otherwise still apply but log irregular offset warning.
"""
from typing import List, Optional, Tuple
import re
import logging
from dataclasses import replace

from .receipt_structures import TextBlock

logger = logging.getLogger(__name__)

# Patterns for reference row detection (T&T)
DATE_TIME_PATTERN = re.compile(r"\d{2}/\d{2}/\d{2}\s+\d{1,2}:\d{2}:\d{2}\s*[AP]M", re.IGNORECASE)
CASHIER_PATTERN = re.compile(r"Mei[Cc]hen|Clerk|Cashier", re.IGNORECASE)
TRANSACTION_PATTERN = re.compile(r"Transaction\s+resumed|Trans:\s*\d+", re.IGNORECASE)
TERMINAL_PATTERN = re.compile(r"Terminal:\s*[\d\-]+", re.IGNORECASE)


def _is_left_ref_block(b: TextBlock) -> Optional[str]:
    """Returns 'date' or 'transaction' if block matches left-side reference, else None."""
    t = (b.text or "").strip()
    if DATE_TIME_PATTERN.search(t):
        return "date"
    if TRANSACTION_PATTERN.search(t):
        return "transaction"
    return None


# Right ref: cashier/terminal, or $0.00 (membership row - same structural offset as date row)
MEMBERSHIP_AMOUNT_PATTERN = re.compile(r"^\$0\.00$", re.IGNORECASE)


def _is_right_ref_block(b: TextBlock) -> bool:
    """True if block matches right-side reference (cashier, terminal, or $0.00)."""
    t = (b.text or "").strip()
    return bool(CASHIER_PATTERN.search(t) or TERMINAL_PATTERN.search(t) or MEMBERSHIP_AMOUNT_PATTERN.match(t))


def _find_reference_row(
    blocks: List[TextBlock],
    half_line: float,
    use_top: bool
) -> Optional[Tuple[TextBlock, TextBlock]]:
    """
    Find a reference row with left block (date/transaction) and right block (cashier/terminal).
    Search entire receipt; use_top=True returns topmost match, use_top=False returns bottommost.
    Returns (left_block, right_block) or None.
    """
    if not blocks:
        return None
    # Search full receipt (no 35% cutoff - receipt position in photo is unknown)
    candidates_sorted = sorted(blocks, key=lambda b: b.center_y)
    row_eps = half_line * 2  # full line tolerance for grouping
    # For header: date and $0.00 can be 0.025+ apart (different rows), use looser grouping
    header_row_eps = max(row_eps, 0.04)
    found: Optional[Tuple[TextBlock, TextBlock]] = None

    i = 0
    while i < len(candidates_sorted):
        row_blocks = [candidates_sorted[i]]
        ref = candidates_sorted[i].center_y
        # Use looser eps for top ~15% of receipt (header) to catch date+$0.00
        eps_use = header_row_eps if use_top and ref < 0.6 else row_eps
        for j in range(i + 1, len(candidates_sorted)):
            if abs(candidates_sorted[j].center_y - ref) <= eps_use:
                row_blocks.append(candidates_sorted[j])
            else:
                break

        left_cand = None
        right_candidates = []
        for b in row_blocks:
            lr = _is_left_ref_block(b)
            if lr:
                if left_cand is None or b.center_x < left_cand.center_x:
                    left_cand = b
            if _is_right_ref_block(b):
                right_candidates.append(b)
        # Prefer right candidate that is SAME ROW (small |offset|). date+$0.00 have 0.025 diff = different rows;
        # date+Meichen have ~0.01 diff = same row. Use same-row pair for true skew.
        right_cand = None
        if left_cand and right_candidates:
            valid_right = [r for r in right_candidates if r.center_x > left_cand.center_x]
            if valid_right:
                right_cand = min(valid_right, key=lambda r: abs(r.center_y - left_cand.center_y))

        if left_cand and right_cand and left_cand.center_x < right_cand.center_x:
            found = (left_cand, right_cand)
            if use_top:
                return found  # first match = topmost

        i += len(row_blocks)

    return found  # use_top=False: last match = bottommost; or None


def correct_skew(
    text_blocks: List[TextBlock],
    half_line_height: float,
    store_config: Optional[dict] = None
) -> Tuple[List[TextBlock], List[str]]:
    """
    Apply skew correction to text blocks using reference rows.

    Logic:
    1. Find top reference row (date + cashier)
    2. Find bottom reference row (transaction/terminal area)
    3. Compute offset for each (y_right - y_left)
    4. If same direction and |offset_top - offset_bottom| < half_line: uniform skew
    5. Apply shear correction to all blocks between the two reference rows
    6. If not uniform: still apply, add error to error_log

    Returns:
        (corrected_blocks, error_log_entries)
    """
    error_log: List[str] = []

    if not text_blocks or len(text_blocks) < 2:
        return text_blocks, error_log

    # Only run if pipeline.skew_correction is enabled for this chain
    pipeline = (store_config or {}).get("pipeline", {}) or {}
    if not pipeline.get("skew_correction", False):
        logger.debug("[Skew] Pipeline skew_correction disabled, skipping")
        return text_blocks, error_log

    top_ref = _find_reference_row(text_blocks, half_line_height, use_top=True)
    bottom_ref = _find_reference_row(text_blocks, half_line_height, use_top=False)

    if not top_ref:
        logger.debug("[Skew] No top reference row found, skip correction")
        return text_blocks, error_log

    left_top, right_top = top_ref
    offset_top = right_top.center_y - left_top.center_y
    logger.info(f"[Skew] Top ref: left='{left_top.text[:30]}' cy={left_top.center_y:.4f}, right='{right_top.text[:30]}' cy={right_top.center_y:.4f}, offset={offset_top:.4f}")
    x_left = left_top.center_x
    x_right = right_top.center_x
    x_span = x_right - x_left
    if abs(x_span) < 0.01:
        logger.debug("[Skew] Top reference x_span too small, skip")
        return text_blocks, error_log

    offset_bottom = offset_top  # default
    if bottom_ref:
        left_bot, right_bot = bottom_ref
        offset_bottom = right_bot.center_y - left_bot.center_y

        same_direction = (offset_top >= 0) == (offset_bottom >= 0)
        diff_ok = abs(offset_top - offset_bottom) < half_line_height
        uniform_skew = same_direction and diff_ok

        if not uniform_skew:
            error_log.append("Irregular skew: top and bottom ref rows have different offset direction")
            logger.warning(
                f"[Skew] Irregular offset: top={offset_top:.4f}, bottom={offset_bottom:.4f}, "
                f"half_line={half_line_height:.4f}, same_dir={same_direction}, diff_ok={diff_ok}"
            )
    else:
        logger.debug("[Skew] No bottom reference row, using top offset only")

    # Use top row's geometry for correction.
    # offset_top = y_right - y_left > 0 means right is lower. To straighten: use RIGHT as reference,
    # add to left blocks so they align down. correction = offset * (x_right - x) / x_span.
    # Left blocks get large add (move down), right blocks get ~0 (stay). PEAR 0.5505 + 0.024 -> 0.5745 ≈ 0.5730.
    def apply_shear(b: TextBlock) -> TextBlock:
        x = b.center_x
        correction = offset_top * (x_right - x) / x_span
        new_center_y = b.center_y + correction
        new_y = b.y + correction
        return replace(
            b,
            y=new_y,
            center_y=new_center_y,
            raw_data={**b.raw_data, "_skew_corrected": True}
        )

    out = [apply_shear(b) for b in text_blocks]
    logger.info(f"[Skew] Applied correction: offset_top={offset_top:.4f}, corrected {len(out)} blocks")
    return out, error_log
