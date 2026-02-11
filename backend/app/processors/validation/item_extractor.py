"""
Item Extractor: Extract items using row-based approach with multi-line support.

This module implements Step 4 of the receipt processing pipeline.
- Product name = text from blocks to the LEFT of the amount only (by X), excluding section headers.
  When a row has blocks at different Y (over-merged), we use amount-centric logic: take the
  topmost "name line" above the amount's Y (not the whole row concatenated).
- Left-outlier blocks (center_x < BODY_X_MIN, e.g. photo background) are excluded from names.
- Rows with multiple amounts in the amount column produce one item per amount.
- Optional store_config can add chain-specific section_headers.
"""
from typing import List, Optional, Set, Tuple
import logging
import re
from .receipt_structures import (
    PhysicalRow, ReceiptRegions, AmountColumns, AmountUsageTracker, ExtractedItem, TextBlock
)

logger = logging.getLogger(__name__)

# Y tolerance constants
# Dynamic (computed from average block height in extract_items)
DEFAULT_HALF_LINE_Y_EPS = 0.008  # Fallback if not computed
DEFAULT_LINE_Y_EPS = 0.006  # Fallback for line grouping
DEFAULT_ABOVE_AMOUNT_Y_WINDOW = 0.04  # Fallback max Y range when scanning up from amount

# Section headers that must not appear in product names (grocery category labels)
SECTION_HEADERS = frozenset({'FOOD', 'PRODUCE', 'DELI', 'DAIRY', 'BAKERY', 'MEAT', 'FROZEN', 'GROCERY'})

# Small dictionary of receipt/product words for one-edit-distance correction (OCR typos)
RECEIPT_WORDS = frozenset({
    "TARE", "TAIWANESE", "REMOVED", "SALE", "FOOD", "PRODUCE", "DELI", "MEAT", "BABY", "NAPA",
    "BROCCOLI", "ONION", "GREEN", "DONUTS", "LAMB", "ROLLS", "SHANGHAI", "BOK", "CHOY", "KOREAN",
    "ENOKI", "MUSHROOM", "PAPER", "PACKAGE", "WEIGHT", "HOT", "GROCERY", "CHINESE", "CROWN",
    "PONKAN", "YU-CHOY", "SUM", "SPROUT", "SLICED", "ITEM", "COUNT", "SOYMILK",
})


def _is_y_position_used(y: float, used_y_positions: Set[int], tolerance: float) -> bool:
    """
    Check if a Y position is already used (within tolerance).
    Uses integerized Y (y*10000) with tolerance to handle floating-point / grouping differences
    across code paths (e.g. section_header next_mean_y vs _full_product_name mean_y).
    
    Args:
        y: Float Y coordinate
        used_y_positions: Set of integerized Y coordinates (y * 10000)
        tolerance: Y distance tolerance (e.g. LINE_Y_EPS); positions within this are considered same
    """
    y_int = int(round(y * 10000))
    tol_int = max(1, int(round(tolerance * 10000)))
    for uy in used_y_positions:
        if abs(uy - y_int) <= tol_int:
            return True
    return False


def _edit_distance_one(a: str, b: str) -> bool:
    """True if a and b differ by exactly one character (insert, delete, or substitute)."""
    if abs(len(a) - len(b)) > 1:
        return False
    if a == b:
        return False
    if len(a) > len(b):
        a, b = b, a
    # len(a) <= len(b)
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    if i == len(a):
        return len(b) == len(a) + 1
    # one diff: skip one in b (insert) or substitute
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:]
    return a[i:] == b[i + 1:]


def _one_edit_correct(word: str, dictionary: frozenset) -> Optional[str]:
    """If word is one edit away from exactly one dictionary word, return that word; else None."""
    wu = word.upper()
    if wu in dictionary:
        return None
    candidates = [d for d in dictionary if _edit_distance_one(wu, d)]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _apply_product_name_cleanup(name: str, store_config: Optional[dict]) -> str:
    """Apply typo list (e.g. Tere->Tare) and one-edit-distance correction from small dictionary."""
    if not name or not name.strip():
        return name
    # 0. Built-in typos (always apply): Tere->Tare so it works even without store_config
    name = re.sub(r"\bTere\b", "Tare", name, flags=re.IGNORECASE)
    # n 8 n/$price: OCR often reads @ as 8
    name = re.sub(r"(\d+)\s+8\s+(\d+/\$)", r"\1 @ \2", name, flags=re.IGNORECASE)
    name = re.sub(r"(\d+)\s+8\s+(\d+\s*/\s*\$)", r"\1 @ \2", name, flags=re.IGNORECASE)
    # x.xx 16 -> x.xx lb (decimal then space then 16, often OCR for lb in weight context)
    name = re.sub(r"\b(\d+\.\d{2})\s+16\b", r"\1 lb", name)
    # 1. Store typo list (exact or fuzzy): e.g. [["TAIVANESE", "TAIWANESE"], ["NEAT","MEAT"]]
    typo_map = {}
    if store_config:
        for key in ("items", "wash_data"):
            cfg = store_config.get(key) or {}
            typos = cfg.get("product_name_typos") or cfg.get("typos") or []
            for pair in typos:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    typo_map[pair[0].strip()] = pair[1].strip()
    for wrong, right in typo_map.items():
        name = re.sub(re.escape(wrong), right, name, flags=re.IGNORECASE)
    # 2. One-edit per word (only if exactly one candidate in RECEIPT_WORDS)
    words = name.split()
    out = []
    for w in words:
        if not w:
            out.append(w)
            continue
        corrected = _one_edit_correct(w, RECEIPT_WORDS)
        if corrected:
            # Preserve original case pattern if all caps
            out.append(corrected if w.isupper() else corrected.capitalize() if w[0].isupper() else corrected.lower())
        else:
            out.append(w)
    return " ".join(out)


def _should_skip_row_as_non_item(
    row: PhysicalRow,
    amount_block: TextBlock,
    store_config: Optional[dict]
) -> bool:
    """
    True if this row should not be extracted as an item (e.g. Points 20 $0.00, membership *** $0.00,
    Env fee, Bottle deposit).
    """
    text = (row.text or "").strip()
    if not text:
        return False

    # Fee row patterns: skip rows matching fee labels (Env fee, Bottle deposit, etc.)
    if store_config:
        wash = store_config.get("wash_data", {}) or {}
        fee_patterns = wash.get("fee_row_patterns", [])
        for pat in fee_patterns:
            try:
                if re.search(pat, text, re.IGNORECASE):
                    return True
            except re.error:
                pass

    if amount_block.amount is None:
        return False
    try:
        amt = float(amount_block.amount)
    except (TypeError, ValueError):
        return False
    if amt != 0:
        return False
    # Points N with $0.00 → points earning line, not item
    if store_config:
        items_cfg = store_config.get("items", {}) or {}
        if items_cfg.get("points_line_not_item") and re.search(r"Points\s*\d+", text, re.IGNORECASE):
            return True
        # Membership line: ***digits or "membership: ***digits" with $0.00
        header_cfg = store_config.get("header", {}) or {}
        pat = header_cfg.get("membership_pattern")
        if pat and re.search(pat, text):
            return True
    return False


def extract_fees_from_items_region(
    regions: "ReceiptRegions",
    amount_columns: "AmountColumns",
    store_config: Optional[dict] = None,
) -> List[dict]:
    """
    Extract fee rows from items region (e.g. Bottle deposit $0.10, Env fee $0.01).
    Only runs when store_config has region == "BC" (provincial/state level).
    Returns list of {label, amount} for sumcheck inclusion.
    """
    if not store_config or store_config.get("region") != "BC":
        return []
    wash = store_config.get("wash_data", {}) or {}
    fee_patterns = wash.get("fee_row_patterns", [])
    if not fee_patterns:
        return []
    compiled = []
    for p in fee_patterns:
        try:
            compiled.append(re.compile(p, re.IGNORECASE))
        except re.error:
            pass
    if not compiled:
        return []

    fees = []
    main_x = amount_columns.main_column.center_x
    tolerance = amount_columns.main_column.tolerance

    for row in regions.item_rows:
        text = (row.text or "").strip()
        if not text:
            continue
        for rx in compiled:
            m = rx.search(text)
            if m:
                for block in row.get_amount_blocks():
                    if block.amount is not None and block.amount > 0:
                        if abs(block.center_x - main_x) <= tolerance:
                            label = m.group(0).strip() or text[:50]
                            fees.append({"label": label, "amount": float(block.amount)})
                            logger.debug(f"[BC] Extracted fee from items region: {label} ${block.amount:.2f}")
                break
    return fees


def _get_section_headers(store_config: Optional[dict]) -> frozenset:
    base = set(SECTION_HEADERS)
    if not store_config:
        return frozenset(base)
    extra = store_config.get("items", {}).get("section_headers") or store_config.get("wash_data", {}).get("section_headers") or []
    for h in extra:
        if isinstance(h, str) and h.strip():
            base.add(h.strip().upper())
    return frozenset(base)


def _detect_left_right_boundary(rows: List[PhysicalRow]) -> float:
    """
    Detect the X boundary between left column (product names) and right column (amounts/tax markers).
    Uses gap detection: find the largest gap in X coordinates.
    Returns the X position of the boundary (midpoint of the largest gap).
    """
    if not rows:
        return 0.6  # Fallback default
    
    # Collect all X coordinates from all blocks in item rows
    x_coords = []
    for row in rows:
        for block in row.blocks:
            x_coords.append(block.center_x)
    
    if len(x_coords) < 2:
        return 0.6  # Fallback
    
    # Sort and find the largest gap
    x_coords.sort()
    max_gap = 0.0
    max_gap_left = 0.0
    max_gap_right = 0.0
    
    for i in range(len(x_coords) - 1):
        gap = x_coords[i + 1] - x_coords[i]
        if gap > max_gap:
            max_gap = gap
            max_gap_left = x_coords[i]
            max_gap_right = x_coords[i + 1]
    
    # Boundary is at the midpoint of the largest gap
    boundary = (max_gap_left + max_gap_right) / 2.0
    logger.info(f"[Column Detection] Detected left/right boundary at X={boundary:.4f} (gap: {max_gap_left:.4f} -> {max_gap_right:.4f}, size: {max_gap:.4f})")
    return boundary


def extract_items(
    regions: ReceiptRegions,
    amount_columns: AmountColumns,
    tracker: AmountUsageTracker,
    store_config: Optional[dict] = None,
    half_line_tolerance: Optional[float] = None,
    error_log: Optional[List[str]] = None
) -> List[ExtractedItem]:
    """
    Extract items from item_rows using row-based approach.
    Uses only text blocks to the left of each amount; excludes section headers.
    Supports multiple amounts per row (one item per amount).
    """
    # Use dynamic half-line tolerance, or fallback to default
    HALF_LINE_Y_EPS = half_line_tolerance if half_line_tolerance is not None else DEFAULT_HALF_LINE_Y_EPS
    LINE_Y_EPS = HALF_LINE_Y_EPS * 0.75  # Line merge tolerance = 75% of half-line
    ABOVE_AMOUNT_WINDOW = HALF_LINE_Y_EPS * 8.0  # Dynamic window = ~8 half-lines (produce layout: name row + qty/unit row above amount)
    
    items = []
    main_x = amount_columns.main_column.center_x
    tolerance = amount_columns.main_column.tolerance
    section_headers = _get_section_headers(store_config)
    rows = regions.item_rows
    last_amount_y: Optional[float] = None  # 上一笔已处理金额的 y，往上扫时到此为止
    used_name_y_positions: Set[int] = set()  # 消消乐：追踪已使用的品名行的 Y 坐标（integerized: y * 10000）
    used_qty_unit_y_positions: Set[int] = set()  # 消消乐：追踪已使用的 qty/unit 行的 Y 坐标（独立于产品名）
    prev_section_header_used_row_index: List[Optional[int]] = [None]  # [0]=row index whose product was used for prev section-header amount

    # Detect left/right column boundary using gap detection
    LEFT_RIGHT_BOUNDARY = _detect_left_right_boundary(rows)
    logger.info(f"[Column Detection] Using X={LEFT_RIGHT_BOUNDARY:.4f} as left/right cutoff for all item extraction")

    i = 0
    while i < len(rows):
        row = rows[i]

        # All unused amount blocks in this row (sorted by center_y so topmost amount first)
        amount_blocks = _find_all_amounts_in_row(row, main_x, tolerance, tracker)

        logger.debug(f"[消消乐] Row {row.row_id}: Y_center={row.y_center:.4f}, text='{row.text[:80]}', {len(row.blocks)} blocks, {len(amount_blocks)} amounts")
        for idx, amount_block in enumerate(amount_blocks):
            logger.debug(f"[消消乐] === Processing row_id={row.row_id}, amount #{idx+1}/{len(amount_blocks)}: ${amount_block.amount:.2f} at Y={amount_block.center_y:.4f} ===")
            # Skip rows that are not items: Points N with $0.00, or membership *** with $0.00 (store_config)
            if _should_skip_row_as_non_item(row, amount_block, store_config):
                tracker.mark_used(amount_block, role="SKIP_NON_ITEM", row_id=row.row_id)
                logger.debug(f"Skipped non-item row: '{row.text[:50]}' amount={amount_block.amount}")
                continue

            # Base: text to the left of this amount in current row (using detected boundary)
            row_name_part = _product_name_left_of_amount(row, amount_block, amount_blocks, section_headers, LEFT_RIGHT_BOUNDARY)
            if not row_name_part.strip():
                row_name_part = _remove_amount_from_text(row.text, amount_block.text)
            row_name_part = _strip_fp_and_amounts(row_name_part).strip()
            logger.debug(f"[消消乐] row_name_part (left of amount in current row): '{row_name_part}'")

            # 每行左边必须有内容：品名或 qty/unit。若当前行没有左侧块，说明 row_reconstructor 把本应同行的左右拆开了。
            left_blocks_in_row = [b for b in row.blocks if b.center_x < LEFT_RIGHT_BOUNDARY]
            if not left_blocks_in_row:
                tracker.mark_used(amount_block, role="SKIP_ROW_NO_LEFT", row_id=row.row_id)
                logger.warning(f"[消消乐] Skip amount ${amount_block.amount:.2f}: row has no left-side blocks (row_reconstructor may have split same line)")
                continue

            # 每个金额独立解析 name；已用过的品名不再使用（消消乐，基于 Y 坐标追踪）
            name_y_position = None  # Track Y position of the name line for 消消乐
            auxiliary_y_positions = []  # Track auxiliary lines (qty/unit lines) to mark as used
            logger.debug(f"[消消乐] Processing amount ${amount_block.amount:.2f} at Y={amount_block.center_y:.4f}, used_Y={sorted(used_name_y_positions)}")

            # Section header row + amount: amount belongs to NEXT row's first product (e.g. "DELI" + $4.99 -> AFC SOYMILK)
            # OR: prev amount used this row's product (section header case), so this amount -> row BELOW (e.g. $5.99 -> GYG)
            full_name = None
            if prev_section_header_used_row_index[0] == i and i + 1 < len(rows):
                # Current row's product was already used for prev amount; this amount belongs to row below
                below_row = rows[i + 1]
                below_left = [b for b in below_row.blocks if b.center_x < LEFT_RIGHT_BOUNDARY]
                if below_left:
                    below_text = " ".join(b.text.strip() for b in below_left).strip()
                    if below_text and not _is_section_header_row_from_text(below_text, section_headers) and not _row_looks_like_qty_unit_line(below_text):
                        below_mean_y = sum(b.center_y for b in below_left) / len(below_left)
                        if not _is_y_position_used(below_mean_y, used_name_y_positions, LINE_Y_EPS):
                            full_name = (_remove_sku_from_name(below_text), below_mean_y, [])
                            logger.info(f"[消消乐] Amount ${amount_block.amount:.2f} -> row below product (prev was section-header) at Y={below_mean_y:.4f}")
                prev_section_header_used_row_index[0] = None  # consumed
            elif _is_section_header_row_from_text(row_name_part, section_headers) and i + 1 < len(rows):
                next_row = rows[i + 1]
                next_left = [b for b in next_row.blocks if b.center_x < LEFT_RIGHT_BOUNDARY]
                if next_left:
                    next_text = " ".join(b.text.strip() for b in next_left).strip()
                    if next_text and not _is_section_header_row_from_text(next_text, section_headers) and not _row_looks_like_qty_unit_line(next_text):
                        next_mean_y = sum(b.center_y for b in next_left) / len(next_left)
                        if not _is_y_position_used(next_mean_y, used_name_y_positions, LINE_Y_EPS):
                            full_name = (_remove_sku_from_name(next_text), next_mean_y, [])
                            prev_section_header_used_row_index[0] = i + 1  # mark that we used next row's product
                            logger.info(f"[消消乐] Section-header row: amount ${amount_block.amount:.2f} -> next row product at Y={next_mean_y:.4f}")

            if full_name is None:
                prev_section_header_used_row_index[0] = None  # clear when not using section-header path
                full_name = _full_product_name_above_amount(
                row, amount_block, amount_blocks, rows, i, section_headers,
                prev_amount_y=last_amount_y, used_name_y_positions=used_name_y_positions,
                half_line_eps=HALF_LINE_Y_EPS, line_y_eps=LINE_Y_EPS, above_amount_window=ABOVE_AMOUNT_WINDOW,
                left_right_boundary=LEFT_RIGHT_BOUNDARY
            )
            if full_name:
                product_name, name_y_position, auxiliary_y_positions = full_name  # Returns (name, y_position, auxiliary_ys) tuple
                logger.debug(f"[消消乐] full_name path: name='{product_name}', Y={name_y_position:.4f}, auxiliary_Ys={auxiliary_y_positions}")
                # Build combined_for_parse: collect all left blocks (including qty/unit lines) for parsing
                left_blocks = _left_blocks_above_and_at_amount(
                    row, amount_block, amount_blocks, rows, i, last_amount_y, HALF_LINE_Y_EPS, ABOVE_AMOUNT_WINDOW, LEFT_RIGHT_BOUNDARY
                )
                combined_for_parse = " ".join(b.text.strip() for b in left_blocks).strip() if left_blocks else row.text
            else:
                logger.debug(f"[消消乐] full_name returned None, trying fallback paths")
                # Fallback: topmost name line (current row only) or previous-row lookup
                topmost_result = _topmost_name_line_above_amount(row, amount_block, amount_blocks, section_headers, LINE_Y_EPS, used_name_y_positions)
                if topmost_result:
                    topmost_name, name_y_position, auxiliary_y_positions = topmost_result  # Returns (name, y_position, auxiliary_ys) tuple
                    logger.info(f"[消消乐] topmost_name path: name='{topmost_name}', Y={name_y_position:.4f}")
                    product_name = _strip_qty_unit_pattern_from_name(topmost_name).strip() or topmost_name
                    
                    # Build combined_for_parse: collect all left blocks (including qty/unit lines) for parsing
                    left_blocks = _left_blocks_above_and_at_amount(
                        row, amount_block, amount_blocks, rows, i, last_amount_y, HALF_LINE_Y_EPS, ABOVE_AMOUNT_WINDOW, LEFT_RIGHT_BOUNDARY
                    )
                    combined_for_parse = " ".join(b.text.strip() for b in left_blocks).strip() if left_blocks else row.text
                else:
                    logger.info(f"[消消乐] topmost_name also returned None, trying deep fallback")
                    # Deep fallback: try looking DOWN for next all-caps product name
                    # This handles cases where:
                    # 1. Current row only has amount (e.g. "FP $6.50")
                    # 2. Above is section header ("FOOD") or boundary
                    # 3. Real product name is below (e.g. "EGG TRAY BUN")
                    product_name = None
                    name_y_position = None
                    combined_for_parse = None
                    auxiliary_y_positions = []  # Initialize auxiliary Y positions for deep fallback
                    
                    # Look down for next all-caps name (within 3-5 rows, skipping section headers)
                    for next_idx in range(i + 1, min(i + 6, len(rows))):
                        next_row = rows[next_idx]
                        
                        # Get text from left side only (using boundary)
                        # Don't filter by is_amount - left side blocks can have is_amount=True (e.g. qty/unit blocks)
                        next_left_blocks = [b for b in next_row.blocks if b.center_x < LEFT_RIGHT_BOUNDARY]
                        if not next_left_blocks:
                            # No left blocks, check if row has amounts (another item started)
                            if next_row.get_amount_blocks():
                                logger.debug(f"[消消乐] Row {next_idx} has only amounts (no left text), stopping search")
                                break
                            continue
                        
                        next_text = " ".join(b.text.strip() for b in next_left_blocks).strip()
                        
                        # Skip section headers (DELI, FOOD, etc.) - continue searching
                        if _is_section_header_row_from_text(next_text, section_headers):
                            logger.debug(f"[消消乐] Row {next_idx} is section header '{next_text}', skipping")
                            continue
                        
                        # Skip qty/unit lines - continue searching
                        if _row_looks_like_qty_unit_line(next_text):
                            logger.debug(f"[消消乐] Row {next_idx} is qty/unit line '{next_text}', skipping")
                            continue
                        
                        # Check if it's an all-caps name
                        if next_text and _row_looks_like_all_caps_name(next_text):
                            next_mean_y = sum(b.center_y for b in next_left_blocks) / len(next_left_blocks)
                            if not _is_y_position_used(next_mean_y, used_name_y_positions, LINE_Y_EPS):
                                # Remove SKU codes from product name (but keep full text for combined_for_parse)
                                product_name = _remove_sku_from_name(next_text)
                                name_y_position = next_mean_y
                                combined_for_parse = next_text  # Keep SKU in combined_for_parse for context
                                logger.info(f"[消消乐] Deep fallback: found name in next row {next_idx}: '{product_name}' at Y={name_y_position:.4f}")
                                
                                # Check if the row AFTER the product name has qty/unit info (e.g. "1.20 lb @ $1.38/lb")
                                qty_unit_idx = next_idx + 1
                                if qty_unit_idx < len(rows):
                                    qty_unit_row = rows[qty_unit_idx]
                                    # Get left blocks, including those marked as is_amount (qty/unit blocks like "1.20 lb @ $1.38/lb" contain amounts)
                                    # Only exclude blocks that are clearly in the amount column (right side)
                                    qty_unit_left_blocks = [b for b in qty_unit_row.blocks if b.center_x < LEFT_RIGHT_BOUNDARY]
                                    if qty_unit_left_blocks:
                                        qty_unit_text = " ".join(b.text.strip() for b in qty_unit_left_blocks).strip()
                                        # Check if this is a qty/unit line (e.g. "1.20 lb @ $1.38/lb")
                                        if qty_unit_text and _row_looks_like_qty_unit_line(qty_unit_text):
                                            qty_unit_mean_y = sum(b.center_y for b in qty_unit_left_blocks) / len(qty_unit_left_blocks)
                                            if not _is_y_position_used(qty_unit_mean_y, used_name_y_positions, LINE_Y_EPS):
                                                # Add qty/unit text to combined_for_parse for extraction
                                                combined_for_parse = product_name + " " + qty_unit_text
                                                # Mark qty/unit line Y as used (消消乐)
                                                auxiliary_y_positions.append(qty_unit_mean_y)
                                                logger.info(f"[消消乐] Deep fallback: found qty/unit in row {qty_unit_idx}: '{qty_unit_text}' at Y={qty_unit_mean_y:.4f}")
                                break
                    
                    # If still no name found, use row.text as last resort - MUST check used (用后即焚)
                    if not product_name:
                        left_in_row = [b for b in row.blocks if b.center_x < LEFT_RIGHT_BOUNDARY]
                        row_mean_y = sum(b.center_y for b in left_in_row) / len(left_in_row) if left_in_row else row.y_center
                        if not _is_y_position_used(row_mean_y, used_name_y_positions, LINE_Y_EPS):
                            product_name = row.text or ""
                            name_y_position = row_mean_y
                            combined_for_parse = row.text or ""
                            logger.info(f"[消消乐] Deep fallback: using row.text='{product_name}', Y={name_y_position:.4f}")
                        else:
                            logger.warning(f"[消消乐] Row Y={row_mean_y:.4f} already used, no unused name for ${amount_block.amount:.2f} - skip (用后即焚)")
                            tracker.mark_used(amount_block, role="SKIP_NO_UNUSED_NAME", row_id=row.row_id)
                            continue

            # 先去掉 +1/0 等 points 噪声、qty/unit pattern、首尾 section header 词（如末尾的 FOOD）
            product_name = _strip_points_and_noise_from_product_name(product_name)
            product_name = _strip_qty_unit_pattern_from_name(product_name)  # Remove qty/unit info from name
            product_name = _strip_leading_trailing_section_header_words(product_name, section_headers)
            # Remove trailing " /lb", " /kg" (OCR/parsing residue from partial qty line)
            product_name = re.sub(r'\s+/(?:lb|kg|oz)\s*$', '', product_name, flags=re.IGNORECASE).strip()
            
            # Extract (SALE) prefix if present
            on_sale = False
            if product_name.strip().upper().startswith("(SALE)"):
                on_sale = True
                product_name = re.sub(r"^\(SALE\)\s*", "", product_name, flags=re.IGNORECASE).strip()
            
            # Typo and one-edit correction (Tere->Tare, etc.)
            product_name = _apply_product_name_cleanup(product_name, store_config)
            # 消消乐：追踪已使用的品名行的 Y 坐标（唯一且不受字符串清理影响）
            if name_y_position is not None:
                name_y_int = int(round(name_y_position * 10000))
                used_name_y_positions.add(name_y_int)
                logger.debug(f"[消消乐] Marked product name y={name_y_position:.4f} as used (cannot be used as product name again)")
            else:
                logger.warning(f"[消消乐] WARNING: name_y_position is None for '{product_name}' (amount=${amount_block.amount:.2f})! Cannot track for 消消乐.")
            
            # Mark auxiliary Y positions (qty/unit lines found during name search) as "used for product name"
            # This prevents them from being selected as product names for future items
            # BUT they can still be used for qty/unit extraction (different tracking set)
            for aux_y in auxiliary_y_positions:
                aux_y_int = int(round(aux_y * 10000))
                used_name_y_positions.add(aux_y_int)
                logger.debug(f"[消消乐] Marked auxiliary line (qty/unit) y={aux_y:.4f} as used (cannot be used as product name)")

            # Extract qty/unit price/unit: use left_blocks to find the closest qty/unit to amount's Y
            # Build left_blocks for this amount (includes up to +2 rows below)
            left_blocks = _left_blocks_above_and_at_amount(
                row, amount_block, amount_blocks, rows, i, last_amount_y, HALF_LINE_Y_EPS, ABOVE_AMOUNT_WINDOW, LEFT_RIGHT_BOUNDARY
            )
            qty, unit_price_cents, unit, qty_unit_y, qty_unit_text = _extract_qty_and_price_from_blocks(
                left_blocks, amount_block, HALF_LINE_Y_EPS, used_qty_unit_y_positions
            )
            # _extract_qty_and_price returns unit_price in cents; ExtractedItem expects dollars
            unit_price = (unit_price_cents / 100.0) if unit_price_cents is not None else None
            
            # If found qty/unit, mark its Y coordinate as used (消消乐) - separate from product name tracking
            if qty_unit_y is not None:
                qty_unit_y_int = int(round(qty_unit_y * 10000))
                used_qty_unit_y_positions.add(qty_unit_y_int)
                logger.debug(f"[消消乐] Marked qty/unit line y={qty_unit_y:.4f} as used for qty/unit extraction")
                # Weight items: if qty/unit text lacks /lb suffix (e.g. "0.92 lb @ $1.99") but qty*up validates, escalate
                # /1b is OCR typo for /lb, count as present
                if error_log is not None and unit and "lb" in str(unit).lower() and qty_unit_text:
                    if "/lb" not in qty_unit_text and "/1b" not in qty_unit_text and "/kg" not in qty_unit_text:
                        err = f"qty/unit '{qty_unit_text[:50]}' missing /lb suffix, math validates"
                        error_log.append(err)
                        logger.info(f"[消消乐] {err}")
            
            # For debugging: also show combined text
            combined_text = " ".join(b.text.strip() for b in left_blocks).strip() if left_blocks else row.text
            logger.info(f"[消消乐] '{product_name}' (${amount_block.amount:.2f}): qty={qty}, unit={unit}, up={unit_price} from '{combined_text[:80]}'")
            
            # If no qty/unit_price parsed, default quantity to 1
            if qty is None and unit_price is None:
                qty = 1.0
            
            # For weight-based items: keep qty in BASE unit (e.g. 2.68 lb)
            # Pipeline output will do int(round(qty*100)) to get hundredths (268)
            # Do NOT convert here - output expects base units and multiplies by 100
            final_qty = qty

            product_name_final = product_name or row.text
            item = ExtractedItem(
                product_name=product_name_final,
                line_total=amount_block.amount,
                amount_block_id=amount_block.block_id,
                row_id=row.row_id,
                quantity=final_qty,
                unit_price=unit_price,
                unit=unit,
                raw_text=row.text,
                confidence=1.0,
                on_sale=on_sale
            )
            if qty and qty != 1.0:
                logger.info(f"[消消乐] Created item '{product_name_final}': qty={qty} (type={type(qty).__name__}), unit={unit}, unit_price={unit_price}")
            items.append(item)
            tracker.mark_used(amount_block, role="ITEM", row_id=row.row_id)
            last_amount_y = amount_block.center_y
            logger.debug(
                f"Extracted item: '{product_name_final}' = ${amount_block.amount:.2f} "
                f"(row {row.row_id}, block {amount_block.block_id})"
            )
        
        i += 1
    
    logger.info(f"Extracted {len(items)} items from {len(rows)} item rows")
    return items


def _find_all_amounts_in_row(
    row: PhysicalRow,
    column_x: float,
    tolerance: float,
    tracker: AmountUsageTracker
) -> List[TextBlock]:
    """All unused amount blocks in row that match the column, sorted by center_y (top first) then center_x."""
    out = []
    for block in row.get_amount_blocks():
        if tracker.is_used(block):
            continue
        if abs(block.center_x - column_x) <= tolerance:
            out.append(block)
    out.sort(key=lambda b: (b.center_y, b.center_x))
    return out


def _product_name_left_of_amount(
    row: PhysicalRow,
    amount_block: TextBlock,
    all_amount_blocks_in_row: List[TextBlock],
    section_headers: Optional[frozenset] = None,
    left_right_boundary: float = 0.6
) -> str:
    """
    Text for product name = non-amount blocks to the left of this amount.
    Uses detected left/right boundary instead of hardcoded padding.
    """
    headers = section_headers if section_headers is not None else SECTION_HEADERS
    prev_amount_x = None
    for a in all_amount_blocks_in_row:
        if a.block_id == amount_block.block_id:
            break
        prev_amount_x = a.center_x
    left_x_cutoff = prev_amount_x if prev_amount_x is not None else -1.0
    # Use detected left/right boundary
    right_x_cutoff = left_right_boundary
    parts = []
    for b in row.blocks:
        if b.is_amount:
            continue
        # Removed BODY_X_MIN check - rely on receipt_body_detector filtering
        if b.center_x <= left_x_cutoff:
            continue
        if b.center_x >= right_x_cutoff:
            break
        # Only skip a block that is a section header when the whole row is section-header-only (e.g. "FOOD" alone); don't remove "FOOD" from "HOT FOOD BY WEIGHT"
        if _is_section_header_block(b.text, headers) and _is_section_header_row(row, section_headers):
            continue
        # Skip vertical text (e.g. background paper with vertical text that OCR merged into same row by Y)
        if b.width and b.height and b.width > 0 and b.height > b.width * 1.5:
            continue
        parts.append(b.text.strip())
    return " ".join(parts).strip()


def _left_blocks_in_body(row: PhysicalRow, amount_block: TextBlock, all_amount_blocks_in_row: List[TextBlock]) -> List[TextBlock]:
    """Non-amount blocks to the left of amount, sorted by center_y (relies on receipt_body_detector for X filtering)."""
    prev_amount_x = None
    for a in all_amount_blocks_in_row:
        if a.block_id == amount_block.block_id:
            break
        prev_amount_x = a.center_x
    left_x_cutoff = prev_amount_x if prev_amount_x is not None else -1.0
    # Use larger padding (0.05) to exclude tax/fee markers (FP, P, T)
    right_x_cutoff = amount_block.center_x - 0.05
    out = []
    for b in row.blocks:
        if b.is_amount:
            continue
        # Removed BODY_X_MIN check - rely on receipt_body_detector filtering
        if b.center_x <= left_x_cutoff:
            continue
        if b.center_x >= right_x_cutoff:
            break
        out.append(b)
    out.sort(key=lambda b: b.center_y)
    return out


# (Deprecated constants - now computed dynamically in extract_items from average block height)


def _left_blocks_above_and_at_amount(
    row: PhysicalRow,
    amount_block: TextBlock,
    all_amount_blocks_in_row: List[TextBlock],
    rows: List[PhysicalRow],
    row_index: int,
    prev_amount_y: Optional[float],
    half_line_eps: float,
    above_amount_window: float = None,
    left_right_boundary: float = 0.6
) -> List[TextBlock]:
    """
    金额左侧、y 在 [amount_y - WINDOW, amount_y + 2*半行] 的块（包括下一行的 qty/unit）。
    使用检测到的左右列边界，而不是硬编码的 padding。
    
    Args:
        half_line_eps: Dynamic half-line tolerance from pipeline
        above_amount_window: Dynamic window for scanning above amount (based on half_line_eps)
        left_right_boundary: Detected X boundary between left (names) and right (amounts/taxes) columns
    """
    if above_amount_window is None:
        above_amount_window = DEFAULT_ABOVE_AMOUNT_Y_WINDOW
    
    # Use detected left/right boundary instead of hardcoded padding
    right_x_cutoff = left_right_boundary
    amount_y = amount_block.center_y
    y_min = amount_y - above_amount_window
    y_max = amount_y + (half_line_eps * 2)  # Include next line for qty/unit (e.g. "1.20 lb @ $1.38/lb")
    out = []
    # Scan ±2 rows (produce layout won't be more skewed than that)
    scan_start = max(0, row_index - 2)
    scan_end = min(len(rows), row_index + 3)
    logger.debug(
        f"[left_blocks] amount_y={amount_y:.4f} y_min={y_min:.4f} y_max={y_max:.4f} right_x={right_x_cutoff:.4f} "
        f"scan_rows={scan_start}-{scan_end}"
    )
    for r in rows[scan_start : scan_end]:
        for b in r.blocks:
            # 左侧 blocks：不管 is_amount 标记，只要在左侧就包含（可能是 qty/unit 信息）
            # 右侧 amount 列的金额会被 X 坐标过滤掉（b.center_x >= right_x_cutoff）
            skip_reason = None
            if b.center_x >= right_x_cutoff:
                skip_reason = f"x={b.center_x:.4f}>=right_x"
            elif b.center_y > y_max:
                skip_reason = f"y={b.center_y:.4f}>y_max={y_max:.4f}"
            elif b.center_y < y_min:
                skip_reason = f"y={b.center_y:.4f}<y_min={y_min:.4f}"
            if skip_reason:
                logger.debug(f"[left_blocks] SKIP '{b.text[:35]}' cx={b.center_x:.4f} cy={b.center_y:.4f}: {skip_reason}")
                continue
            out.append(b)
    logger.debug(f"[left_blocks] Included {len(out)} blocks: {[b.text[:30] for b in out]}")
    out.sort(key=lambda b: b.center_y)
    return out


def _group_into_lines(blocks: List[TextBlock], line_y_eps: float) -> List[Tuple[float, List[TextBlock]]]:
    """
    Group blocks by similar center_y; return list of (mean_y, blocks) sorted by mean_y ascending.
    
    Args:
        line_y_eps: Y tolerance for grouping blocks into same line (dynamic)
    """
    if not blocks:
        return []
    lines = []
    current = [blocks[0]]
    for b in blocks[1:]:
        if abs(b.center_y - current[-1].center_y) <= line_y_eps:
            current.append(b)
        else:
            mean_y = sum(c.center_y for c in current) / len(current)
            lines.append((mean_y, current))
            current = [b]
    if current:
        mean_y = sum(c.center_y for c in current) / len(current)
        lines.append((mean_y, current))
    return lines


def _topmost_name_line_above_amount(
    row: PhysicalRow,
    amount_block: TextBlock,
    all_amount_blocks_in_row: List[TextBlock],
    section_headers: frozenset,
    line_y_eps: float,
    used_name_y_positions: Optional[Set[int]] = None,
) -> Optional[Tuple[str, float, List[float]]]:
    """
    When the row has blocks at different Y (over-merged), return the product name as the
    topmost "name line" above the amount's Y. Name line = not section-header-only, not qty line, not suffix (Tare removed).
    
    Args:
        line_y_eps: Dynamic line Y tolerance for grouping blocks
        used_name_y_positions: Set of Y positions already used for item names (消消乐)
    
    Returns:
        (product_name, y_position, auxiliary_y_positions) tuple, or None if not found
    """
    used_y = used_name_y_positions if used_name_y_positions is not None else set()
    left_blocks = _left_blocks_in_body(row, amount_block, all_amount_blocks_in_row)
    if not left_blocks:
        return None
    lines = _group_into_lines(left_blocks, line_y_eps)
    if not lines:
        return None
    amount_y = amount_block.center_y
    logger.debug(f"[消消乐] _topmost_name: amount_y={amount_y:.4f}, found {len(lines)} lines, used_y={sorted(used_y)}")
    for idx, (mean_y, blks) in enumerate(lines[:5]):  # Show first 5 lines
        line_text = " ".join(b.text.strip() for b in blks).strip()
        logger.debug(f"  Line {idx}: Y={mean_y:.4f}, text='{line_text[:50]}'")
    # Line at the amount's Y = the one with mean_y closest to amount_y
    amount_line_idx = min(range(len(lines)), key=lambda idx: abs(lines[idx][0] - amount_y))
    # Walk upward (smaller idx) to find first line that looks like a product name and is not used
    for idx in range(amount_line_idx, -1, -1):
        mean_y, blks = lines[idx]
        line_text = " ".join(b.text.strip() for b in blks).strip()
        if not line_text:
            continue
        if _is_section_header_row_from_text(line_text, section_headers):
            continue
        if _row_looks_like_qty_unit_line(line_text):
            continue
        if _row_looks_like_suffix(line_text):
            continue
        # 消消乐：检查 Y 坐标是否已用过 (with tolerance for mean_y variation, use line_y_eps)
        if _is_y_position_used(mean_y, used_y, line_y_eps):
            logger.debug(f"[消消乐] _topmost_name SKIP: '{line_text}' at Y={mean_y:.4f} already used")
            continue
        # Remove SKU codes before returning
        line_text = _remove_sku_from_name(line_text)
        logger.debug(f"[消消乐] _topmost_name found: '{line_text}' at Y={mean_y:.4f}")
        return (line_text, mean_y, [])  # No auxiliary lines in this path
    return None


def _full_product_name_above_amount(
    row: PhysicalRow,
    amount_block: TextBlock,
    all_amount_blocks_in_row: List[TextBlock],
    rows: List[PhysicalRow],
    row_index: int,
    section_headers: frozenset,
    prev_amount_y: Optional[float] = None,
    used_name_y_positions: Optional[Set[int]] = None,
    half_line_eps: float = 0.008,
    line_y_eps: float = 0.006,
    above_amount_window: float = None,
    left_right_boundary: float = 0.6
) -> Optional[Tuple[str, float, List[float]]]:
    """
    以金额 y 为基准、半行容错，往上扫：
    1. 全大写 → 命中 item name，返回（若该 Y 坐标已用过则跳过，继续找）。
    2. x lb @ $y/lb → 再往上一行即 item name，返回（若该 Y 坐标已用过则跳过）。
    3. 否则继续往上，直到「上一个已处理金额」的 y 停止。
    消消乐：used_name_y_positions 里已有过的 Y 坐标不再返回。
    
    Args:
        half_line_eps: Dynamic half-line tolerance (from average block height)
        line_y_eps: Dynamic line grouping tolerance (also used for Y position matching in 消消乐)
        used_name_y_positions: Set of Y positions already used for item names
        above_amount_window: Dynamic window for scanning above amount (based on half_line_eps)
        left_right_boundary: Detected X boundary between left and right columns
    
    Returns:
        (product_name, name_y_position, auxiliary_y_positions) tuple, or None if not found
        auxiliary_y_positions: Y coordinates of qty/unit lines or other auxiliary lines to mark as used
    """
    used_y = used_name_y_positions if used_name_y_positions is not None else set()
    if above_amount_window is None:
        above_amount_window = DEFAULT_ABOVE_AMOUNT_Y_WINDOW
    left_blocks = _left_blocks_above_and_at_amount(
        row, amount_block, all_amount_blocks_in_row, rows, row_index, prev_amount_y, half_line_eps, above_amount_window, left_right_boundary
    )
    if not left_blocks:
        return None
    lines = _group_into_lines(left_blocks, line_y_eps)
    if not lines:
        return None
    amount_y = amount_block.center_y
    # 和金额同一行（半行容错内）：优先选「上方」的全大写品名行（Y <= amount_y + half_line），避免选下方的
    in_band_above = [idx for idx in range(len(lines)) if lines[idx][0] <= amount_y and amount_y - lines[idx][0] <= half_line_eps]
    in_band_below = [idx for idx in range(len(lines)) if lines[idx][0] > amount_y and lines[idx][0] - amount_y <= half_line_eps]
    in_band = in_band_above if in_band_above else in_band_below
    all_caps_in_band = []
    for idx in in_band:
        mean_y, blks = lines[idx]
        line_text = " ".join(b.text.strip() for b in blks).strip()
        # Check Y position instead of text string for 消消乐 (with tolerance for mean_y variation, use line_y_eps)
        if line_text and _row_looks_like_all_caps_name(line_text) and not _is_section_header_row_from_text(line_text, section_headers) and not _is_y_position_used(mean_y, used_y, line_y_eps):
            all_caps_in_band.append(idx)
    if all_caps_in_band:
        amount_line_idx = min(all_caps_in_band, key=lambda idx: abs(lines[idx][0] - amount_y))
    else:
        amount_line_idx = min(range(len(lines)), key=lambda idx: abs(lines[idx][0] - amount_y))
    # 金额所在行本身就是全大写品名且未用过 → 直接返回
    at_mean_y, blks_at = lines[amount_line_idx]
    at_text = " ".join(b.text.strip() for b in blks_at).strip()
    # Check Y position instead of text string for 消消乐 (with tolerance for mean_y variation, use line_y_eps)
    if at_text and _row_looks_like_all_caps_name(at_text) and not _is_section_header_row_from_text(at_text, section_headers):
        if not _is_y_position_used(at_mean_y, used_y, line_y_eps):
            # Remove trailing tax/fee markers and SKU codes before returning
            at_text = _remove_tax_markers_from_name(at_text)
            at_text = _remove_sku_from_name(at_text)
            logger.debug(f"[消消乐] Found name at amount line: '{at_text}' at Y={at_mean_y:.4f}")
            return (at_text, at_mean_y, [])  # No auxiliary lines
        else:
            logger.debug(f"[消消乐] SKIP: '{at_text}' at Y={at_mean_y:.4f} already used")
    
    # **NEW**: Check if amount line itself is qty/unit line → look one line above for product name
    if at_text and _row_looks_like_qty_unit_line(at_text):
        logger.debug(f"[消消乐] Amount line is qty/unit: '{at_text}' at Y={at_mean_y:.4f}, looking one line above")
        if amount_line_idx >= 1:
            mean_y_above, blks_above = lines[amount_line_idx - 1]
            if prev_amount_y is None or mean_y_above > prev_amount_y:
                above_text = " ".join(b.text.strip() for b in blks_above).strip()
                if above_text and not _is_section_header_row_from_text(above_text, section_headers):
                    if not _is_y_position_used(mean_y_above, used_y, line_y_eps):
                        # OCR correction then remove tax/fee markers from qty/unit line before concatenation
                        logger.debug(f"[消消乐] Found name above qty/unit (at amount line): '{above_text}' at Y={mean_y_above:.4f}, qty/unit line at Y={at_mean_y:.4f}, marking qty/unit Y as used")
                        # Return only product name (no concatenation), but mark qty/unit line Y as used
                        above_text = _remove_sku_from_name(above_text)
                        return (above_text, mean_y_above, [at_mean_y])  # Mark qty/unit line as used
                    else:
                        logger.debug(f"[消消乐] SKIP: '{above_text}' at Y={mean_y_above:.4f} already used")
    
    # 从 amount 行往上扫（idx 递减）
    idx = amount_line_idx - 1
    while idx >= 0:
        mean_y, blks = lines[idx]
        line_text = " ".join(b.text.strip() for b in blks).strip()
        # 碰到上一笔金额的 y 就停，不进入上一件商品
        if prev_amount_y is not None and mean_y <= prev_amount_y:
            break
        if not line_text:
            idx -= 1
            continue
        if _is_section_header_row_from_text(line_text, section_headers):
            idx -= 1
            continue
        if _row_looks_like_all_caps_name(line_text):
            # Check Y position instead of text string for 消消乐 (with tolerance for mean_y variation, use line_y_eps)
            if not _is_y_position_used(mean_y, used_y, line_y_eps):
                # Remove trailing tax/fee markers and SKU codes before returning
                line_text = _remove_tax_markers_from_name(line_text)
                line_text = _remove_sku_from_name(line_text)
                logger.debug(f"[消消乐] Found name above amount: '{line_text}' at Y={mean_y:.4f}")
                return (line_text, mean_y, [])  # No auxiliary lines
            else:
                logger.debug(f"[消消乐] SKIP: '{line_text}' at Y={mean_y:.4f} already used")
            idx -= 1
            continue
        if _row_looks_like_qty_unit_line(line_text):
            logger.debug(f"[消消乐] Found qty/unit line: '{line_text}' at Y={mean_y:.4f}, looking one line above")
            if idx >= 1:
                mean_y_above, blks_above = lines[idx - 1]
                if prev_amount_y is None or mean_y_above > prev_amount_y:
                    above_text = " ".join(b.text.strip() for b in blks_above).strip()
                    # Check Y position instead of text string for 消消乐 (with tolerance for mean_y variation, use line_y_eps)
                    if above_text and not _is_section_header_row_from_text(above_text, section_headers):
                        if not _is_y_position_used(mean_y_above, used_y, line_y_eps):
                            # OCR correction then remove tax/fee markers from qty/unit line before concatenation
                            logger.debug(f"[消消乐] Found name above qty/unit: '{above_text}' at Y={mean_y_above:.4f}, qty/unit line at Y={mean_y:.4f}, marking qty/unit Y as used")
                            # Return only product name (no concatenation), but mark qty/unit line Y as used
                            above_text = _remove_sku_from_name(above_text)
                            return (above_text, mean_y_above, [mean_y])  # Mark qty/unit line as used
                        else:
                            logger.debug(f"[消消乐] SKIP: '{above_text}' at Y={mean_y_above:.4f} already used")
            break
        idx -= 1
    return None


def _is_section_header_row_from_text(text: str, section_headers_set: frozenset) -> bool:
    """True if text is only section header word(s)."""
    if not text or not text.strip():
        return False
    stripped = _strip_section_headers(text, section_headers_set).strip()
    return not stripped


def _is_section_header_block(text: str, section_headers_set: Optional[frozenset] = None) -> bool:
    """True if this block is only a section header (FOOD, PRODUCE, DELI, etc.)."""
    headers = section_headers_set if section_headers_set is not None else SECTION_HEADERS
    t = text.strip().upper()
    return t in headers


def _is_section_header_row(row: PhysicalRow, section_headers_set: Optional[frozenset] = None) -> bool:
    """True if row text is only section header(s) (e.g. FOOD, PRODUCE, DELI)."""
    return bool(row.text.strip() and not _strip_section_headers(row.text, section_headers_set).strip())


def _strip_section_headers(text: str, section_headers_set: Optional[frozenset] = None) -> str:
    """Remove section header words only when the entire text is section headers (e.g. 'FOOD' or 'PRODUCE'). Do not remove 'FOOD' from 'HOT FOOD BY WEIGHT'."""
    headers = section_headers_set if section_headers_set is not None else SECTION_HEADERS
    words = text.upper().split()
    if not words:
        return text
    if all(w in headers for w in words):
        return ""
    return text


def _strip_leading_trailing_section_header_words(text: str, section_headers_set: Optional[frozenset] = None) -> str:
    """Strip leading and trailing whole words that are section headers only. Keeps 'FOOD' in 'HOT FOOD BY WEIGHT'."""
    if not text or not text.strip():
        return text
    headers = section_headers_set if section_headers_set is not None else SECTION_HEADERS
    words = text.split()
    while words and words[0].upper() in headers:
        words.pop(0)
    while words and words[-1].upper() in headers:
        words.pop()
    return " ".join(words).strip()


def _strip_points_and_noise_from_product_name(text: str) -> str:
    """Remove points/membership noise from product name: leading '+1 0', '+1', standalone '0' (X 验证)."""
    if not text or not text.strip():
        return text
    t = text.strip()
    # +1 0 ... (points line residue)
    t = re.sub(r"^\s*\+1\s+0\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*\+1\s+", "", t, flags=re.IGNORECASE)
    # Leading standalone 0 (not 0.xx)
    t = re.sub(r"^\s*0\s+", "", t)
    return t.strip()


def _strip_fp_and_amounts(text: str) -> str:
    """Remove 'FP', 'FP $X.XX', and standalone $X.XX from product name."""
    t = text.strip()
    t = re.sub(r'\bFP\s*\$?\d*\.?\d*\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\$?\d+\.\d{2}\b', '', t).strip()
    return t


def _find_amount_in_row(
    row: PhysicalRow,
    column_x: float,
    tolerance: float,
    tracker: AmountUsageTracker
) -> Optional["TextBlock"]:
    """Find an unused amount block in row that matches the column."""
    for block in row.get_amount_blocks():
        if tracker.is_used(block):
            continue
        
        if abs(block.center_x - column_x) <= tolerance:
            return block
    
    return None


def _is_potential_name_only_row(
    row: PhysicalRow,
    column_x: float,
    tolerance: float,
    tracker: AmountUsageTracker
) -> bool:
    """
    Check if a row looks like a name-only row (no amount, just text).
    
    Args:
        row: PhysicalRow to check
        column_x: X coordinate of amount column
        tolerance: X coordinate tolerance
        
    Returns:
        True if row appears to be name-only
    """
    # If row has no amount blocks, it's likely name-only
    if not row.get_amount_blocks():
        return True
    
    # If row has amount blocks but they're all used or not in the main column, it's name-only
    for block in row.get_amount_blocks():
        if not tracker.is_used(block):
            if abs(block.center_x - column_x) <= tolerance:
                return False  # Has unused amount in main column
    
    return True


def _remove_amount_from_text(text: str, amount_text: str) -> str:
    """Remove amount text from row text to get product name."""
    text_cleaned = text.replace(amount_text, "").strip()
    text_cleaned = re.sub(r'\$?\d+\.\d{2}', '', text_cleaned).strip()
    return text_cleaned


# Pattern: "x.xx lb @ $y.yy/lb" or "x lb @ $y/lb" (quantity @ unit price per lb)
_RE_QTY_UNIT_LINE = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*(?:lb|kg|oz)\s*@\s*\$?\d+(?:[.,]\d+)?\s*(?:/lb|/kg)?\s*$",
    re.IGNORECASE
)


def _row_looks_like_qty_unit_line(text: str) -> bool:
    """True if row text is essentially 'x lb @ $y /lb' or 'n @ n/$price' (quantity and unit price line)."""
    if not text or not text.strip():
        return False
    t = text.strip()
    # OCR typo: "1b" -> "lb" (e.g. $2.88/1b)
    t = re.sub(r'/1b\b', '/lb', t, flags=re.IGNORECASE)
    t = re.sub(r'\s1b\s', ' lb ', t, flags=re.IGNORECASE)
    t = re.sub(r'\s1b@', ' lb@', t, flags=re.IGNORECASE)
    # OCR correction: "3 83/$" -> "3@3/$" (@ symbol misread), avoid matching SKU codes
    t = re.sub(r'\b(\d{1,2})\s+(\d)\s*(\d+)\s*/\s*\$', r'\1@\3/$', t)
    if _RE_QTY_UNIT_LINE.search(t):
        return True
    if re.search(r"\d+(?:\.\d+)?\s*(?:lb|kg|oz)\s*@\s*\$?\d+(?:[.,]\d+)?\s*(?:/lb|/kg)?", t, re.IGNORECASE):
        return True
    # e.g. "3 @ 3/$1.98", "2 @2/$6.00", limit to 1-2 digits to avoid matching SKU codes
    if re.search(r"\b\d{1,2}\s*@\s*\d+\s*/\s*\$?[\d.,]+", t):
        return True
    return False


def _row_looks_like_all_caps_name(text: str) -> bool:
    """True if row is mostly all-caps words (category/product name), no qty @ unit pattern."""
    if not text or not text.strip():
        return False
    t = text.strip()
    if _row_looks_like_qty_unit_line(t):
        return False
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper >= 0.8 * len(letters)


def _row_looks_like_suffix(text: str) -> bool:
    """True if row is a suffix line like 'Tare removed' (not the product name)."""
    if not text or not text.strip():
        return False
    t = text.strip().upper()
    if re.match(r"^TARE\s+REMOVED", t):
        return True
    if re.match(r"^REMOVED\s*$", t):
        return True
    return False


def _remove_sku_from_name(text: str) -> str:
    """Remove SKU codes (5-7 digit numbers) from product name."""
    if not text:
        return text
    # Remove 5-7 digit numbers (SKU codes) - can be at beginning, middle, or end
    text = re.sub(r'\b\d{5,7}\b', '', text)
    # Clean up extra spaces
    return " ".join(text.split()).strip()


def _remove_tax_markers_from_name(text: str) -> str:
    """Remove trailing tax/fee markers (FP, P, T, etc.) from product name or qty/unit line."""
    if not text:
        return text
    # Remove standalone tax/fee codes at the end (case insensitive)
    # Common markers: FP (Final Price), P (Taxable), T (Tax), F, N, E
    # Use word boundaries to avoid removing letters from actual words
    words = text.split()
    while words and len(words[-1]) <= 2 and words[-1].upper() in ('FP', 'P', 'T', 'F', 'N', 'E'):
        words.pop()
    return " ".join(words).strip()


def _strip_qty_unit_pattern_from_name(text: str) -> str:
    """Remove 'x lb @ $y /lb' and 'n @ n/$price' from product name so name is just the name."""
    if not text:
        return text
    
    # OCR typo: "1b" -> "lb" (same correction as in _extract_qty_and_price)
    text = re.sub(r'/1b\b', '/lb', text, flags=re.IGNORECASE)
    text = re.sub(r'\s1b\s', ' lb ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s1b@', ' lb@', text, flags=re.IGNORECASE)
    
    t = re.sub(
        r"\d+(?:\.\d+)?\s*(?:lb|kg|oz)\s*@\s*\$?\d+(?:[.,]\d+)?\s*(?:/lb|/kg)?\s*",
        " ",
        text,
        flags=re.IGNORECASE
    )
    t = re.sub(r"\d+\s*@\s*\d+\s*/\s*\$?[\d.,]+\s*", " ", t)
    return " ".join(t.split()).strip()


def _normalize_decimal(s: str) -> str:
    """Replace comma used as decimal separator with dot (OCR noise). App never uses comma decimals."""
    if "," in s and re.search(r"\d,\d{2}\b", s):
        return s.replace(",", ".", 1)  # only first comma in a number
    return s


def _extract_qty_and_price_from_blocks(
    blocks: List[TextBlock], 
    amount_block: TextBlock, 
    half_line_eps: float,
    used_qty_unit_y_positions: Set[int]
) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[float]]:
    """
    Extract qty/unit/price from blocks, choosing the pattern CLOSEST to amount's Y coordinate.
    Only consider blocks within ± half_line_eps (half a full line height, i.e. y to center_y) of the amount.
    
    Primary: Y coordinate distance (choose closest, not already used for qty/unit)
    Secondary: Amount validation (as tiebreaker when Y distances are similar)
    
    Args:
        blocks: Left-side TextBlock list (sorted by Y)
        amount_block: The amount block we're matching to
        half_line_eps: Half line height (y to center_y), used as y_tolerance
        used_qty_unit_y_positions: Set of Y coordinates already used FOR QTY/UNIT (separate from product names)
    
    Returns:
        (qty, unit_price, unit, qty_unit_y) tuple - qty_unit_y is the Y coordinate to mark as used
    """
    if not blocks or amount_block.amount is None:
        return None, None, None, None, None
    
    amount_y = amount_block.center_y
    # amount_block.amount is in dollars (from OCR); _extract_qty_and_price expects cents
    line_total_dollars = amount_block.amount
    line_total_cents = line_total_dollars * 100
    # 1.5x half-line: allow qty/unit block on adjacent row (produce: "2.68 lb @ $2.88/lb" often on row above amount)
    y_tolerance = half_line_eps * 1.5
    
    # Find all blocks with qty/unit patterns, calculate Y distance and validation score
    candidates = []
    
    logger.info(f"[qty/unit extraction] Checking {len(blocks)} blocks for amount=${line_total_dollars:.2f} at y={amount_y:.4f}, y_tolerance={y_tolerance:.4f}")
    
    for block in blocks:
        # Skip blocks already used by previous items FOR QTY/UNIT extraction
        block_y_int = int(round(block.center_y * 10000))
        if block_y_int in used_qty_unit_y_positions:
            logger.info(f"[qty/unit] Skipping already-used qty/unit block at y={block.center_y:.4f}: '{block.text[:30]}'")
            continue
        
        # Only consider blocks close to amount's Y
        y_dist = abs(block.center_y - amount_y)
        logger.info(f"[qty/unit] Block at y={block.center_y:.4f}, y_dist={y_dist:.4f}, text='{block.text[:40]}'")
        if y_dist > y_tolerance:
            logger.info(f"[qty/unit]   → Skipped: y_dist > tolerance")
            continue
        
        text = block.text.strip()
        if not text:
            logger.info(f"[qty/unit]   → Skipped: empty text")
            continue
        
        # Try to extract qty/unit from this block
        qty, unit_price, unit = _extract_qty_and_price(text, line_total_cents)
        logger.info(f"[qty/unit]   → Extraction result: qty={qty}, unit_price={unit_price}, unit={unit}")
        if qty is not None and unit_price is not None:
            # Calculate validation score (lower is better)
            # qty is in base unit (e.g., 1.48 lb), unit_price is in cents per base unit (e.g., 138 cents/lb)
            # So qty * unit_price should equal line_total_cents
            validation_error = abs(qty * unit_price - line_total_cents)
            candidates.append((y_dist, validation_error, qty, unit_price, unit, block.center_y, text))
            logger.info(f"[qty/unit]   → Added to candidates: validation_error=${validation_error:.2f}")
    
    # If found candidates, pick the one with:
    # 1. Smallest Y distance (primary)
    # 2. Best validation score (secondary tiebreaker)
    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]))  # Sort by (y_dist, validation_error)
        best = candidates[0]
        logger.info(f"[qty/unit extraction] Found {len(candidates)} candidates, picked: y_dist={best[0]:.4f}, validation_err=${best[1]:.2f}, text='{best[6][:40]}'")
        return best[2], best[3], best[4], best[5], best[6]  # qty, unit_price, unit, y_coord, text
    
    logger.info(f"[qty/unit extraction] No candidates found, returning None")
    return None, None, None, None, None


def _extract_qty_and_price(text: str, line_total: Optional[float]) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Try to extract quantity, unit price, and unit from row text.
    Supports "x.xx lb @ $y.yy/lb" and comma-as-decimal (normalized to dot).
    Returns (qty, unit_price, unit) where unit is "1/100 lb" for weight-based items.
    """
    if line_total is None:
        return None, None, None
    line_total = float(line_total)
    
    # Remove SKU codes (5-7 digit numbers at the beginning) before parsing qty/unit
    text = re.sub(r'^\s*\d{5,7}\s+', '', text)
    
    # Normalize European-style decimal (3,99 -> 3.99)
    text = _normalize_decimal(text)
    # OCR typo: "1b" -> "lb" (common OCR mistake where lowercase L looks like 1)
    text = re.sub(r'/1b\b', '/lb', text, flags=re.IGNORECASE)
    text = re.sub(r'\s1b\s', ' lb ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s1b@', ' lb@', text, flags=re.IGNORECASE)
    # OCR typo: "3 83/$" -> "3@3/$" (@ symbol misread as 8 or other digits)
    # Pattern: single/double digit space single digit space digit(s) /$ -> single/double digit @ digit(s) /$
    # Use word boundary \b to avoid matching SKU codes like "573791 3 83/$1.98"
    text = re.sub(r'\b(\d{1,2})\s+(\d)\s*(\d+)\s*/\s*\$', r'\1@\3/$', text)
    
    # Pattern with unit (e.g. "1.27 lb @ $10.99/lb")
    unit_patterns = [
        (r'(\d+(?:\.\d+)?)\s*(kg|lb|oz|g|ml|l)\s*@\s*\$?(\d+(?:\.\d+)?)\s*(?:/lb|/kg|/oz)?', 2),  # "1.27 lb @ $10.99/lb"
        (r'(\d+(?:\.\d+)?)\s*(kg|lb|oz|g|ml|l)\s*@\s*\$?(\d+(?:\.\d+)?)', 2),  # "0.5 kg @ $2.14" no /lb
    ]
    for pattern, unit_group_idx in unit_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                qty_in_base_unit = float(match.group(1))  # e.g., 1.48 lb
                unit_str = match.group(unit_group_idx).lower()
                unit_price_dollars = float(_normalize_decimal(match.group(3)))
                unit_price_cents = unit_price_dollars * 100  # Convert to cents per base unit
            except (ValueError, IndexError):
                continue
            # Allow up to $0.10 tolerance (or 2% of line_total, whichever is larger) for rounding errors
            tolerance_cents = max(10, line_total * 0.02)  # 10 cents = $0.10
            if abs(qty_in_base_unit * unit_price_cents - line_total) < tolerance_cents:
                # Return qty in BASE UNIT (1.48 lb), not hundredths
                # Caller will convert to hundredths if needed for JSON output
                return qty_in_base_unit, unit_price_cents, f"1/100 {unit_str}"
    
    # Pattern without unit (e.g. "2 @ $4.99")
    simple_patterns = [
        r'(\d+(?:\.\d+)?)\s*@\s*\$?(\d+(?:\.\d+)?)',  # "2 @ $4.99"
    ]
    for pattern in simple_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                qty = float(match.group(1))
                unit_price_dollars = float(_normalize_decimal(match.group(2)))
                unit_price_cents = unit_price_dollars * 100  # Convert to cents
            except (ValueError, IndexError):
                continue
            tolerance_cents = 5  # $0.05 tolerance
            if abs(qty * unit_price_cents - line_total) < tolerance_cents:
                return qty, unit_price_cents, None
    # "3 @ 3/$1.98" -> qty=3, total=1.98, unit_price=1.98/3
    # "2 @ 2/$6.00" -> qty=2, total=6.00, unit_price=6.00/2=3.00
    # Use word boundary and limit to 1-2 digits to avoid matching SKU codes
    x_for_y = re.search(r'\b(\d{1,2})\s*@\s*\d+\s*/\s*\$?([\d.,]+)', text)
    if x_for_y:
        try:
            qty = float(x_for_y.group(1))
            total_dollars = float(_normalize_decimal(x_for_y.group(2)))
            total_cents = total_dollars * 100  # Convert to cents (our standard unit)
            if qty > 0 and abs(total_cents - line_total) < 5:  # Allow $0.05 tolerance
                unit_price_cents = total_cents / qty
                return qty, unit_price_cents, None
        except (ValueError, ZeroDivisionError):
            pass
    return None, None, None
