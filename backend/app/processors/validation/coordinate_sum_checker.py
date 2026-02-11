"""
Coordinate-based Sum Checker: Use coordinates for precise sum validation.

This module implements sum checking using coordinate information:
1. Find SUBTOTAL position
2. Sum amounts above SUBTOTAL with same X coordinate (items)
3. Sum amounts below SUBTOTAL in sequence (subtotal + tax + fees = total)
"""
from typing import Dict, Any, List, Optional, Tuple
import logging
import re
from .fuzzy_label_matcher import fuzzy_match_label

logger = logging.getLogger(__name__)


def _is_debug_enabled() -> bool:
    """Check if debug logging is enabled via environment variable."""
    try:
        from ...config import settings
        return settings.enable_debug_logs
    except Exception:
        # Default to True if config is not available (for backward compatibility)
        return True


def _debug_log(level: str, message: str, *args, **kwargs):
    """
    Conditional debug logging based on environment setting.
    
    Args:
        level: Log level ('info', 'debug', 'warning')
        message: Log message
        *args, **kwargs: Additional arguments for logger
    """
    if not _is_debug_enabled():
        return
    
    if level == 'info':
        logger.info(message, *args, **kwargs)
    elif level == 'debug':
        logger.debug(message, *args, **kwargs)
    elif level == 'warning':
        logger.warning(message, *args, **kwargs)

# X coordinate tolerance for vertical alignment (5-10% as requested)
X_TOLERANCE = 0.075  # 7.5% tolerance (middle of 5-10% range)

# Y coordinate tolerance for sequential amounts
Y_TOLERANCE = 0.02  # 2% tolerance for vertical spacing

# Y coordinate tolerance for grouping blocks on the same row
# DEPRECATED: Use _calculate_y_tolerance() instead for dynamic tolerance based on text height
Y_ROW_TOLERANCE = 0.01  # 1% tolerance for same-row grouping (fallback)


def _calculate_y_tolerance(block: Dict[str, Any]) -> float:
    """
    Calculate Y coordinate tolerance based on text block height.
    
    Tolerance is half the text height (center_y - y), which represents approximately
    half a letter height. This allows for natural variation in OCR positioning
    while preventing matches across different rows.
    
    Args:
        block: Text block with 'y', 'center_y', and optionally 'height' fields
        
    Returns:
        Y coordinate tolerance (normalized 0-1)
    """
    # Try to get height directly if available
    height = block.get("height")
    if height and height > 0:
        return height / 2.0
    
    # Calculate from y and center_y difference
    y = block.get("y", 0)
    center_y = block.get("center_y")
    if center_y is not None and center_y > y:
        # center_y - y is approximately half the height (from top to center)
        # So the full height is (center_y - y) * 2
        # Tolerance is half the height = center_y - y (which is already half)
        return center_y - y
    
    # Fallback to default tolerance
    return Y_ROW_TOLERANCE


def _get_hundredths_aligned_x(block: Dict[str, Any]) -> float:
    """
    Get the hundredths (百分位) aligned X coordinate for a block.
    
    For right-aligned numbers (like $36.75), the hundredths digit (小数点后第二位) aligns.
    For example, in "$36.75", the "5" (hundredths digit) should align with other amounts.
    
    Strategy:
    1. Extract the amount value from text
    2. Find the position of the hundredths digit in the text
    3. Calculate its X coordinate based on character position
    
    Args:
        block: Block dictionary with x, width, center_x, text
        
    Returns:
        Hundredths-aligned X coordinate
    """
    text = block.get("text", "")
    x = block.get("x", 0)
    width = block.get("width", 0)
    center_x = block.get("center_x", x)
    
    # Extract amount value to determine format
    import re
    amount_match = re.search(r'\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', text)
    if not amount_match:
        # Fallback to right edge if no amount pattern found
        return x + width if width > 0 else center_x
    
    amount_str = amount_match.group(1).replace(',', '')
    
    # Check if amount has decimal part (hundredths)
    if '.' in amount_str:
        # Find the position of the hundredths digit (second digit after decimal)
        # For "36.75", we want the position of "5"
        decimal_pos = amount_str.find('.')
        if decimal_pos >= 0 and len(amount_str) > decimal_pos + 2:
            # Calculate character position of hundredths digit
            # In "$36.75", "5" is at position 5 (0-indexed: $, 3, 6, ., 7, 5)
            # But we need to account for "$" and spaces in the original text
            amount_start = amount_match.start()
            hundredths_char_pos = amount_start + decimal_pos + 2  # +2 for decimal point and first decimal digit
            
                    # Calculate X coordinate: assume uniform character width
            if width > 0 and len(text) > 0:
                char_width = width / len(text)
                # X coordinate of hundredths digit = x + (hundredths_char_pos * char_width)
                hundredths_x = x + (hundredths_char_pos * char_width)
                logger.debug(f"DEBUG hundredths alignment: text='{text}', amount_str='{amount_str}', decimal_pos={decimal_pos}, amount_start={amount_start}, hundredths_char_pos={hundredths_char_pos}, char_width={char_width:.6f}, x={x:.4f}, width={width:.4f}, hundredths_x={hundredths_x:.4f}")
                return hundredths_x
    
    # Fallback: if no decimal or can't calculate, use right edge
    return x + width if width > 0 else center_x


def coordinate_based_sum_check(
    blocks: List[Dict[str, Any]],
    regions: Dict[str, Any],
    llm_result: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Perform sum check using coordinate information.
    
    Args:
        blocks: All text blocks with coordinates
        regions: Partitioned regions from receipt_partitioner
        llm_result: LLM parsing result (used for expected values only)
        
    Returns:
        (is_valid, check_details)
    """
    from .coordinate_extractor import extract_amount_blocks
    from .coordinate_item_extractor import extract_items_from_coordinates
    
    check_details = {
        "method": "coordinate_based",
        "items_sum_check": None,
        "items_count_check": None,
        "totals_sequence_check": None,
        "formatted_output": None,
        "errors": []
    }
    
    receipt = llm_result.get("receipt", {})
    
    # Get expected values from LLM result
    expected_subtotal = receipt.get("subtotal")
    expected_tax = receipt.get("tax") or 0.0
    expected_total = receipt.get("total")
    
    # Extract amount blocks
    amount_blocks = extract_amount_blocks(blocks)
    
    # Debug: log total amount blocks found
    logger.debug(f"Total amount blocks extracted: {len(amount_blocks)}")
    # Log small amounts specifically
    small_amounts = [b for b in amount_blocks if b.get("amount") and 0 < b.get("amount") < 1.0]
    if small_amounts:
        logger.debug(f"Found {len(small_amounts)} small amounts (< $1.00):")
        for b in small_amounts:
            logger.debug(f"  - ${b.get('amount'):.2f} at Y={b.get('y', 0):.4f}, text='{b.get('text', '')}'")
    
    # Get markers
    subtotal_marker = regions.get("markers", {}).get("subtotal")
    total_marker = regions.get("markers", {}).get("total")
    
    # Step 1: Find SUBTOTAL amount and its X coordinate (temporary call to get X coordinate)
    subtotal_amount_x = None
    items = []
    if subtotal_marker:
        # First, do a quick check to get SUBTOTAL amount and its X coordinate
        temp_items_sum_result = _check_items_sum(
            amount_blocks,
            subtotal_marker,
            expected_subtotal,
            []  # Empty items for now, just to get SUBTOTAL X coordinate
        )
        
        # Extract the X coordinate of SUBTOTAL amount for item extraction
        subtotal_amount_x = temp_items_sum_result.get("subtotal_x_coordinate")
        # Also get the hundredths-aligned X coordinate
        subtotal_amount_x_hundredths = temp_items_sum_result.get("subtotal_x_coordinate_hundredths")
        if subtotal_amount_x:
            logger.info(f"Using SUBTOTAL amount column X={subtotal_amount_x:.3f} for item extraction")
        
        # Step 2: Extract items using the SUBTOTAL amount's X coordinate
        items = extract_items_from_coordinates(blocks, subtotal_marker, total_marker, subtotal_amount_x)
        
        # Step 3: Now re-run items_sum_check with the extracted items
        items_sum_result = _check_items_sum(
            amount_blocks,
            subtotal_marker,
            expected_subtotal,
            items  # Use extracted items for accurate sum calculation
        )
        check_details["items_sum_check"] = items_sum_result
        
        # Check 1.5: Item count verification (if item count is present on receipt)
        items_count_result = _check_items_count(blocks, items, total_marker)
        check_details["items_count_check"] = items_count_result
    else:
        # No subtotal marker - this is a grocery store without subtotal
        logger.info("No SUBTOTAL marker found - likely a grocery store without subtotal")
        check_details["items_sum_check"] = {
            "passed": None,
            "reason": "no_subtotal_marker",
            "note": "Grocery store format - no subtotal column"
        }
        # Extract items without subtotal marker (will use fallback logic)
        items = extract_items_from_coordinates(blocks, subtotal_marker, total_marker, None)
        
        # Check item count even if no subtotal
        items_count_result = _check_items_count(blocks, items, total_marker)
        check_details["items_count_check"] = items_count_result
    
    # CRITICAL: Filter out item amount blocks from amount_blocks before totals sequence check
    # This prevents item amounts (like $1.89 for AVOCADO) from being mistaken as subtotal/total amounts
    # Use Y coordinate as unique ID to match item blocks
    item_y_coordinates = set()
    for item in items:
        item_y = item.get("y")
        if item_y is not None:
            # Use Y coordinate with small tolerance (0.001) to handle floating point precision
            item_y_coordinates.add(round(item_y, 3))
    
    # Filter amount_blocks: exclude those that match item Y coordinates
    totals_amount_blocks = []
    excluded_count = 0
    for block in amount_blocks:
        block_y = block.get("y") or block.get("center_y", 0)
        block_y_rounded = round(block_y, 3)
        
        # Check if this block's Y coordinate matches any item's Y coordinate
        is_item_block = any(abs(block_y_rounded - item_y) < 0.002 for item_y in item_y_coordinates)
        
        if is_item_block:
            excluded_count += 1
            logger.debug(f"  ✗ Excluded item block: ${block.get('amount', 0):.2f} at Y={block_y:.4f} (matches item Y)")
        else:
            totals_amount_blocks.append(block)
    
    if excluded_count > 0:
        logger.info(f"Filtered out {excluded_count} item amount blocks from totals sequence check (remaining: {len(totals_amount_blocks)})")
    
    # Check 2: Totals sequence (subtotal + tax + fees = total)
    # Use subtotal_from_receipt from items_sum_check result
    subtotal_from_receipt = None
    if check_details.get("items_sum_check") and check_details["items_sum_check"].get("subtotal_from_receipt"):
        subtotal_from_receipt = check_details["items_sum_check"]["subtotal_from_receipt"]
    
    if subtotal_marker and total_marker:
        totals_sequence_result = _check_totals_sequence(
            blocks,  # Pass all blocks to find labels
            totals_amount_blocks,  # Use filtered amount_blocks (excluding items)
            subtotal_marker,
            total_marker,
            subtotal_from_receipt,  # Use actual subtotal from receipt, not expected
            expected_total,
            regions.get("totals", []),
            subtotal_amount_x,  # Pass the X coordinate from items_sum_check
            subtotal_amount_x_hundredths  # Pass the hundredths-aligned X coordinate
        )
        check_details["totals_sequence_check"] = totals_sequence_result
    elif total_marker:
        # No subtotal, but has total - items should sum to total
        totals_sequence_result = _check_items_to_total(
            amount_blocks,
            total_marker,
            expected_total,
            items
        )
        check_details["totals_sequence_check"] = totals_sequence_result
    else:
        check_details["totals_sequence_check"] = {
            "passed": False,
            "reason": "no_total_marker",
            "error": "Cannot find TOTAL marker"
        }
        check_details["errors"].append("Cannot find TOTAL marker for sum check")
    
    # Extract tax and fees from totals_sequence_check result
    tax_amount = 0.0
    fees = []
    if check_details.get("totals_sequence_check"):
        sequence = check_details["totals_sequence_check"].get("sequence", [])
        middle_amounts = check_details["totals_sequence_check"].get("middle_amounts", [])
        
        _debug_log('info', f"DEBUG: Extracting tax and fees from sequence:")
        for item in sequence:
            _debug_log('info', f"  - Label: '{item.get('label', 'N/A')}', Amount: ${item.get('amount', 0):.2f}")
        
        # Extract tax and fees from sequence (everything between Subtotal and Total Sales)
        # IMPORTANT: Process in order (by Y coordinate) to match labels correctly
        # Track whether we have an explicit tax label (like "Tax [4.712%]") vs generic (like "Fee/Tax 1")
        current_tax_label = None
        current_tax_is_explicit = False
        
        for item in sequence:
            if item["label"] not in ["Subtotal", "Total Sales"]:
                label_lower = item["label"].lower()
                amount = item["amount"]
                
                # Check for tax (must contain "tax")
                # CRITICAL: Prefer explicit tax labels (like "Tax [4.712%]") over generic labels (like "Fee/Tax 1")
                if "tax" in label_lower:
                    # Check if this is an explicit tax label (contains "tax" but NOT "fee/tax")
                    is_explicit_tax = "tax" in label_lower and "fee/tax" not in label_lower
                    
                    if tax_amount == 0.0:
                        # No tax found yet, use this one
                        tax_amount = amount
                        current_tax_label = item["label"]
                        current_tax_is_explicit = is_explicit_tax
                        logger.info(f"  ✓ Identified TAX: ${amount:.2f} from label '{item['label']}' (explicit={is_explicit_tax})")
                    elif is_explicit_tax and not current_tax_is_explicit:
                        # This is explicit tax, current is generic - replace
                        # Move current generic tax to fees
                        fees.append({"label": current_tax_label or "Tax (generic)", "amount": tax_amount})
                        tax_amount = amount
                        current_tax_label = item["label"]
                        current_tax_is_explicit = True
                        logger.info(f"  ✓ Replaced generic tax with explicit TAX: ${amount:.2f} from label '{item['label']}'")
                    elif not is_explicit_tax and current_tax_is_explicit:
                        # Current is explicit, this is generic - ignore this one, add to fees
                        fees.append({
                            "label": item["label"],
                            "amount": item["amount"]
                        })
                        logger.info(f"  ✓ Ignored generic tax label '{item['label']}' (explicit tax already found), added to fees")
                    else:
                        # Both are same type (both explicit or both generic)
                        # Keep the first one found, add this to fees
                        fees.append({
                            "label": item["label"],
                            "amount": item["amount"]
                        })
                        logger.info(f"  ✓ Tax already identified (${tax_amount:.2f} from '{current_tax_label}'), added '{item['label']}' to fees")
                else:
                    # Everything else is a fee (deposit, environmental fee, etc.)
                    fees.append({
                        "label": item["label"],
                        "amount": item["amount"]
                    })
                    logger.info(f"  ✓ Identified FEE: ${item['amount']:.2f} from label '{item['label']}'")
        
        # CRITICAL: Validate tax amount - tax should be less than 20% of subtotal
        if tax_amount > 0 and subtotal_from_receipt and subtotal_from_receipt > 0:
            tax_percentage = (tax_amount / subtotal_from_receipt) * 100
            if tax_percentage > 20.0:
                logger.warning(f"⚠ Tax validation failed: Tax ${tax_amount:.2f} is {tax_percentage:.1f}% of subtotal ${subtotal_from_receipt:.2f} (expected < 20%)")
                # This might be a fee, not tax - move to fees
                fees.append({
                    "label": current_tax_label or "Tax (invalid - >20%)",
                    "amount": tax_amount
                })
                tax_amount = 0.0
                logger.warning(f"  → Moved to fees, tax reset to $0.00")
            else:
                logger.info(f"✓ Tax validation passed: Tax ${tax_amount:.2f} is {tax_percentage:.1f}% of subtotal ${subtotal_from_receipt:.2f}")
        
        _debug_log('info', f"DEBUG: Final extraction - Tax: ${tax_amount:.2f}, Fees: {len(fees)} items")
        for fee in fees:
            _debug_log('info', f"  - {fee['label']}: ${fee['amount']:.2f}")
    
    # Get subtotal_from_receipt for formatted output
    subtotal_from_receipt = None
    if check_details.get("items_sum_check"):
        subtotal_from_receipt = check_details["items_sum_check"].get("subtotal_from_receipt")
    
    # Generate formatted output for debugging (using coordinate-extracted items)
    # If item count check failed, include its formatted output
    items_count_output = ""
    if check_details.get("items_count_check") and check_details["items_count_check"].get("passed") is False:
        items_count_output = check_details["items_count_check"].get("formatted_output", "")
    
    check_details["formatted_output"] = _generate_formatted_output(
        items,
        subtotal_from_receipt,  # Use actual subtotal from receipt
        tax_amount,
        fees,
        expected_total,
        check_details,
        items_count_output  # Include item count check output if failed
    )
    
    # Determine overall validity
    items_check_passed = check_details["items_sum_check"].get("passed")
    items_count_check_passed = check_details.get("items_count_check", {}).get("passed")
    totals_check_passed = check_details["totals_sequence_check"].get("passed")
    
    # If item count check exists and passed, that's the primary validation
    if items_count_check_passed is True:
        is_valid = True
        logger.info("Item count check passed - receipt validation successful")
    # If item count check failed, return False
    elif items_count_check_passed is False:
        is_valid = False
        logger.warning("Item count check failed - receipt validation failed")
    # Otherwise, fall back to sum checks
    elif items_check_passed is False or totals_check_passed is False:
        is_valid = False
    # If both passed or one is None (no subtotal), return True
    elif items_check_passed is True and totals_check_passed is True:
        is_valid = True
    elif items_check_passed is None and totals_check_passed is True:
        # No subtotal but totals check passed
        is_valid = True
    else:
        # Uncertain - default to False for safety
        is_valid = False
    
    return is_valid, check_details


def _check_items_sum(
    amount_blocks: List[Dict[str, Any]],
    subtotal_marker: Dict[str, Any],
    expected_subtotal: Optional[float],
    items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Check if items above SUBTOTAL sum to subtotal.
    
    Strategy:
    1. Find SUBTOTAL row and extract the amount value ($36.75)
    2. Find this amount's X coordinate (the amount column)
    3. Find all amounts above SUBTOTAL with the same X coordinate
    4. Sum them and compare to the SUBTOTAL amount
    """
    y_subtotal = subtotal_marker.get("y", 0.5)
    
    # Step 1: Find the amount on the SUBTOTAL row
    # Look for amounts near the subtotal marker's Y coordinate
    subtotal_row_amounts = []
    for block in amount_blocks:
        block_y = block.get("y", 0)
        # Find amounts on the same row as SUBTOTAL (within Y tolerance)
        if abs(block_y - y_subtotal) <= Y_ROW_TOLERANCE:
            subtotal_row_amounts.append(block)
    
    if not subtotal_row_amounts:
        return {
            "passed": None,
            "reason": "no_subtotal_amount_found",
            "note": "Cannot find amount on SUBTOTAL row"
        }
    
    # Step 2: Identify the SUBTOTAL amount (usually the rightmost/largest amount on that row)
    # Strategy: 
    # 1. If expected_subtotal is provided, try to match it exactly
    # 2. Otherwise, use the rightmost (highest X) amount on the row
    # 3. If multiple amounts exist, prefer the one that's closest to expected_subtotal
    subtotal_amount_block = None
    if expected_subtotal:
        # First, try exact match
        for block in subtotal_row_amounts:
            block_amount = block.get("amount", 0)
            if abs(block_amount - expected_subtotal) < 0.01:
                subtotal_amount_block = block
                logger.info(f"Matched SUBTOTAL amount: ${block_amount:.2f} (expected: ${expected_subtotal:.2f})")
                break
        
        # If no exact match, find the closest to expected_subtotal
        if not subtotal_amount_block:
            best_match = None
            min_diff = float('inf')
            for block in subtotal_row_amounts:
                block_amount = block.get("amount", 0)
                diff = abs(block_amount - expected_subtotal)
                if diff < min_diff:
                    min_diff = diff
                    best_match = block
            
            if best_match and min_diff < 5.0:  # Within $5 tolerance
                subtotal_amount_block = best_match
                logger.info(f"Closest SUBTOTAL match: ${best_match.get('amount', 0):.2f} (expected: ${expected_subtotal:.2f}, diff: ${min_diff:.2f})")
    
    # If still not found, use the rightmost amount (highest X coordinate)
    if not subtotal_amount_block:
        subtotal_amount_block = max(subtotal_row_amounts, key=lambda b: b.get("center_x", b.get("x", 0)))
        logger.info(f"Using rightmost amount on SUBTOTAL row: ${subtotal_amount_block.get('amount', 0):.2f}")
    
    subtotal_amount = subtotal_amount_block.get("amount")
    # Use hundredths-aligned X coordinate for subtotal (百分位对齐)
    x_subtotal_hundredths = _get_hundredths_aligned_x(subtotal_amount_block)
    x_subtotal = subtotal_amount_block.get("center_x") or subtotal_amount_block.get("x", 0.5)
    
    logger.info(f"Found SUBTOTAL amount: ${subtotal_amount:.2f} at X={x_subtotal:.3f} (hundredths-aligned X={x_subtotal_hundredths:.4f})")
    
    # Step 3: Use items from extract_items_from_coordinates (already filtered to exclude headers)
    # This is more accurate than summing all aligned_amounts, which may include header amounts
    if items:
        # Use the items extracted by coordinate_item_extractor
        # These are already filtered to exclude headers and summary lines
        calculated_sum = sum(item.get("line_total", 0) for item in items)
        aligned_amounts = [
            {
                "amount": item.get("line_total", 0),
                "text": item.get("product_name", ""),
                "x": item.get("x", 0),
                "x_right": item.get("x_amount", 0),  # X coordinate of amount
                "y": item.get("y", 0)
            }
            for item in items
        ]
    else:
        # Fallback: Find all amounts above SUBTOTAL with the same right-aligned X coordinate
        aligned_amounts = []
        for block in amount_blocks:
            block_y = block.get("y", 0)
            
            # Must be above subtotal row
            if block_y >= y_subtotal - Y_ROW_TOLERANCE:
                continue
            
            # Use hundredths-aligned X coordinate for comparison (百分位对齐)
            block_x_hundredths = _get_hundredths_aligned_x(block)
            x_diff = abs(block_x_hundredths - x_subtotal_hundredths)
            if x_diff <= X_TOLERANCE:
                amount = block.get("amount")
                if amount is not None:
                    aligned_amounts.append({
                        "amount": amount,
                        "text": block.get("text", ""),
                        "x": block.get("center_x") or block.get("x", 0),
                        "x_hundredths": block_x_hundredths,  # Hundredths-aligned X coordinate
                        "y": block_y
                    })
        
        # Sort by Y coordinate (top to bottom)
        aligned_amounts.sort(key=lambda a: a["y"])
        
        # Step 4: Sum amounts and compare to SUBTOTAL
        calculated_sum = sum(a["amount"] for a in aligned_amounts)
    
    # Compare to the actual SUBTOTAL amount found on the receipt (not expected_subtotal)
    # expected_subtotal is only used to help find the correct SUBTOTAL amount, not for comparison
    subtotal_from_receipt = subtotal_amount
    if subtotal_from_receipt is None:
        return {
            "passed": None,
            "reason": "no_subtotal_value",
            "note": "Cannot determine SUBTOTAL value from receipt"
        }
    
    difference = abs(calculated_sum - subtotal_from_receipt)
    tolerance = 0.03
    passed = difference <= tolerance
    
    result = {
        "passed": passed,
        "calculated_sum": round(calculated_sum, 2),
        "subtotal_from_receipt": round(subtotal_from_receipt, 2),
        "expected_subtotal": round(expected_subtotal, 2) if expected_subtotal else None,  # For reference only
        "difference": round(difference, 2),
        "tolerance": tolerance,
        "subtotal_x_coordinate": round(x_subtotal, 3),
        "subtotal_x_coordinate_hundredths": round(x_subtotal_hundredths, 4),
        "aligned_amounts_count": len(aligned_amounts),
        "aligned_amounts": [
            {
                "text": a["text"], 
                "amount": round(a["amount"], 2), 
                "x": round(a.get("x", 0), 4),
                "y": round(a["y"], 4),
                "center_x": round(a.get("center_x", 0), 4) if a.get("center_x") else None,
                "center_y": round(a.get("center_y", 0), 4) if a.get("center_y") else None
            } 
            for a in aligned_amounts
        ]
    }
    
    if not passed:
        result["error"] = (
            f"Items sum mismatch: calculated {calculated_sum:.2f}, "
            f"subtotal from receipt {subtotal_from_receipt:.2f}, difference {difference:.2f} > {tolerance}"
        )
    
    logger.info(
        f"Items sum check: {calculated_sum:.2f} vs {subtotal_from_receipt:.2f} (from receipt), "
        f"difference {difference:.2f}, passed={passed}, found {len(aligned_amounts)} items"
    )
    
    return result


def _check_items_count(
    blocks: List[Dict[str, Any]],
    items: List[Dict[str, Any]],
    total_marker: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Check if the number of extracted items matches the item count on the receipt.
    
    Strategy:
    1. Search for "Item count", "Item", "Items", "Iten count" etc. patterns in blocks
    2. Extract the count number
    3. Compare with the number of extracted items
    4. If count check passes, return passed=True
    5. If count check fails, generate formatted output showing each item for debugging
    
    Args:
        blocks: All text blocks with coordinates
        items: List of extracted items
        total_marker: Optional total marker to limit search region
        
    Returns:
        Dictionary with:
        {
            "passed": bool or None (None if no count found),
            "expected_count": int or None,
            "actual_count": int,
            "formatted_output": str (if failed, shows all items for debugging)
        }
    """
    import re
    
    # Search for item count patterns
    # Common patterns: "Item count: 7", "Items: 7", "Iten count: 7", etc.
    count_patterns = [
        r'item\s*count\s*:?\s*(\d+)',
        r'items?\s*:?\s*(\d+)',
        r'iten\s*count\s*:?\s*(\d+)',  # OCR typo: "Iten" instead of "Item"
        r'count\s*:?\s*(\d+)',
    ]
    
    # Limit search to payment region (after total) or entire receipt if no total
    search_blocks = blocks
    if total_marker:
        total_y = total_marker.get("y", 1.0)
        # Search in payment region (after total) and also near total
        search_blocks = [
            b for b in blocks
            if b.get("y", 0) >= total_y - 0.05  # Include area near total
        ]
    
    expected_count = None
    count_block = None
    
    for block in search_blocks:
        text = block.get("text", "").lower()
        for pattern in count_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    expected_count = int(match.group(1))
                    count_block = block
                    logger.info(f"Found item count: {expected_count} in text '{block.get('text', '')}'")
                    break
                except (ValueError, IndexError):
                    continue
        if expected_count is not None:
            break
    
    if expected_count is None:
        return {
            "passed": None,
            "reason": "no_item_count_found",
            "note": "No item count found on receipt",
            "actual_count": len(items)
        }
    
    actual_count = len(items)
    passed = (actual_count == expected_count)
    
    result = {
        "passed": passed,
        "expected_count": expected_count,
        "actual_count": actual_count,
        "difference": abs(actual_count - expected_count)
    }
    
    if not passed:
        # Generate formatted output showing all items for debugging
        # Format: like printing a receipt, one item per line
        lines = []
        lines.append(f"Item Count Check Failed:")
        lines.append(f"Expected: {expected_count} items")
        lines.append(f"Actual: {actual_count} items")
        lines.append(f"Difference: {abs(actual_count - expected_count)}")
        lines.append("")
        lines.append("Extracted Items (for debugging):")
        lines.append("-" * 50)
        
        for i, item in enumerate(items, 1):
            product_name = item.get("product_name", item.get("raw_text", "Unknown"))
            line_total = item.get("line_total")
            if line_total is not None:
                # Truncate long product names
                if len(product_name) > 40:
                    product_name = product_name[:37] + "..."
                lines.append(f"{i:2d}. {product_name:<40} ${line_total:>8.2f}")
            else:
                lines.append(f"{i:2d}. {product_name}")
        
        result["formatted_output"] = "\n".join(lines)
        result["error"] = f"Item count mismatch: expected {expected_count}, found {actual_count}"
        logger.warning(f"Item count check failed: expected {expected_count}, found {actual_count}")
    else:
        logger.info(f"Item count check passed: {actual_count} items")
    
    return result


def _check_totals_sequence(
    blocks: List[Dict[str, Any]],
    amount_blocks: List[Dict[str, Any]],
    subtotal_marker: Dict[str, Any],
    total_marker: Dict[str, Any],
    subtotal_from_receipt: Optional[float],
    expected_total: Optional[float],
    totals_region: List[Dict[str, Any]],
    subtotal_amount_x: Optional[float] = None,
    subtotal_amount_x_hundredths: Optional[float] = None
) -> Dict[str, Any]:
    """
    Check totals sequence: subtotal_from_receipt + all middle amounts = total.
    
    Strategy:
    1. Use subtotal_from_receipt from items_sum_check (the actual SUBTOTAL found on receipt)
    2. Find TOTAL SALES amount on the TOTAL row
    3. Find all amounts between SUBTOTAL and TOTAL with the same X coordinate
    4. Verify: subtotal_from_receipt + all middle amounts = total
    """
    if subtotal_from_receipt is None:
        return {
            "passed": False,
            "reason": "no_subtotal_from_receipt",
            "error": "Items sum check must pass first to get subtotal_from_receipt"
        }
    
    if expected_total is None:
        return {
            "passed": False,
            "reason": "no_expected_total",
            "error": "LLM did not extract total"
        }
    
    # Use center_y for more accurate matching (subtotal marker center, not top-left corner)
    y_subtotal = subtotal_marker.get("center_y") or subtotal_marker.get("y", 0.5)
    # CRITICAL: Don't use total_marker.get("y") directly - it might be wrong!
    # Instead, we'll find the actual TOTAL amount first, then use its Y coordinate
    y_total_initial = total_marker.get("center_y") or total_marker.get("y", 0.9)
    
    _debug_log('info', f"DEBUG: subtotal_marker center_y={y_subtotal:.4f}, total_marker center_y={y_total_initial:.4f}")
    
    # Step 1: Find SUBTOTAL amount and its X coordinate (if not provided)
    if subtotal_amount_x is None or subtotal_amount_x_hundredths is None:
        subtotal_row_amounts = []
        for block in amount_blocks:
            # Use center_y for more accurate row matching
            block_center_y = block.get("center_y") or block.get("y", 0)
            # Use dynamic tolerance based on text block height
            tolerance = _calculate_y_tolerance(block)
            if abs(block_center_y - y_subtotal) <= tolerance:
                subtotal_row_amounts.append(block)
        
        if subtotal_row_amounts:
            subtotal_amount_block = max(subtotal_row_amounts, key=lambda b: b.get("center_x", b.get("x", 0)))
            subtotal_amount_x = subtotal_amount_block.get("center_x") or subtotal_amount_block.get("x", 0.5)
            subtotal_amount_x_hundredths = _get_hundredths_aligned_x(subtotal_amount_block)
    
    if subtotal_amount_x is None or subtotal_amount_x_hundredths is None:
        return {
            "passed": False,
            "reason": "no_subtotal_x_coordinate",
            "error": "Cannot determine SUBTOTAL amount column X coordinate"
        }
    
    # Use the hundredths-aligned X coordinate for matching (百分位对齐)
    x_subtotal_hundredths = subtotal_amount_x_hundredths
    
    # Step 2: Find TOTAL SALES amount
    # CRITICAL: Don't rely on total_marker Y coordinate - it might be wrong!
    # Instead, search ALL amount_blocks below subtotal for the expected_total
    # This ensures we find the correct TOTAL even if the marker is misidentified
    
    _debug_log('info', f"DEBUG: Searching for TOTAL amount (expected: ${expected_total:.2f}) below subtotal Y={y_subtotal:.4f}")
    
    # Search all amounts below subtotal (not just near total_marker)
    # The TOTAL should be the largest amount below subtotal that matches expected_total
    candidate_total_blocks = []
    for block in amount_blocks:
        block_y = block.get("y", 0)
        block_amount = block.get("amount", 0)
        # Must be below subtotal
        if block_y > y_subtotal + 0.01:  # Small buffer to avoid matching subtotal itself
            candidate_total_blocks.append(block)
            _debug_log('debug', f"DEBUG: Candidate TOTAL: ${block_amount:.2f} at Y={block_y:.4f}, text='{block.get('text', '')}'")
    
    if not candidate_total_blocks:
        return {
            "passed": False,
            "reason": "no_total_amount",
            "error": "Cannot find any amounts below SUBTOTAL"
        }
    
    # Find TOTAL amount (CRITICAL: must match expected_total)
    total_amount_block = None
    if expected_total:
        # First, try to match expected_total exactly
        for block in candidate_total_blocks:
            if abs(block.get("amount", 0) - expected_total) < 0.01:
                total_amount_block = block
                logger.info(f"✓ Matched TOTAL amount: ${block.get('amount', 0):.2f} (expected: ${expected_total:.2f}) at Y={block.get('y', 0):.4f}")
                break
        
        # If no exact match, find the closest to expected_total (within reasonable tolerance)
        if not total_amount_block:
            best_match = None
            min_diff = float('inf')
            for block in candidate_total_blocks:
                block_amount = block.get("amount", 0)
                diff = abs(block_amount - expected_total)
                if diff < min_diff:
                    min_diff = diff
                    best_match = block
            
            # Use stricter tolerance: must be within $2 to avoid matching wrong amount
            if best_match and min_diff < 2.0:
                total_amount_block = best_match
                logger.info(f"✓ Closest TOTAL match: ${best_match.get('amount', 0):.2f} (expected: ${expected_total:.2f}, diff: ${min_diff:.2f}) at Y={best_match.get('y', 0):.4f}")
            else:
                logger.warning(f"✗ No TOTAL amount found matching expected ${expected_total:.2f} (closest diff: ${min_diff:.2f})")
                # List all candidates for debugging
                _debug_log('warning', f"DEBUG: All candidate totals below subtotal:")
                for b in sorted(candidate_total_blocks, key=lambda x: x.get('y', 0)):
                    logger.warning(f"  - ${b.get('amount', 0):.2f} at Y={b.get('y', 0):.4f}, text='{b.get('text', '')}'")
    
    # If still not found and expected_total is None, use the largest amount below subtotal
    if not total_amount_block:
        if expected_total is None:
            total_amount_block = max(candidate_total_blocks, key=lambda b: b.get("amount", 0))
            logger.info(f"Using largest amount below subtotal (no expected_total): ${total_amount_block.get('amount', 0):.2f}")
        else:
            # This should not happen if expected_total is provided
            logger.error(f"Failed to find TOTAL amount matching expected ${expected_total:.2f}")
            return {
                "passed": False,
                "reason": "total_not_found",
                "error": f"Cannot find TOTAL amount matching expected ${expected_total:.2f}",
                "sequence_amounts_debug": []
            }
    
    total_amount = total_amount_block.get("amount")
    # Use hundredths-aligned X coordinate for total (百分位对齐)
    x_total_hundredths = _get_hundredths_aligned_x(total_amount_block)
    # CRITICAL: Use the actual TOTAL amount's Y coordinate, not the marker's Y
    y_total = total_amount_block.get("y", y_total_initial)
    logger.info(f"Found TOTAL amount: ${total_amount:.2f} at Y={y_total:.4f}, X={total_amount_block.get('center_x', total_amount_block.get('x', 0)):.3f} (hundredths-aligned X={x_total_hundredths:.4f})")
    _debug_log('info', f"DEBUG: Using actual TOTAL Y={y_total:.4f} (was marker Y={y_total_initial:.4f})")
    
    # Step 3: Find all amounts between SUBTOTAL and TOTAL rows
    # Use right-aligned X coordinate for matching (rightmost digits align)
    # All amounts in totals region should be right-aligned with subtotal/total (within tolerance)
    # This ensures we only include amounts that are actually part of the totals sequence
    sequence_amounts = []
    
    # Debug: log all amount blocks to see what we have
    _debug_log('info', f"============================================================")
    _debug_log('info', f"DEBUG: Searching for amounts between Y={y_subtotal:.4f} and Y={y_total:.4f}")
    _debug_log('info', f"DEBUG: Subtotal hundredths-aligned X={x_subtotal_hundredths:.4f}, Total hundredths-aligned X={x_total_hundredths:.4f}")
    _debug_log('info', f"DEBUG: Total amount_blocks available: {len(amount_blocks)}")
    
    # First, let's check ALL blocks (not just amount_blocks) in the totals region
    # Expand search range to include a buffer below subtotal and above total
    # This ensures we catch all tax/fees even if they're slightly outside the exact Y coordinates
    # Use dynamic buffer based on text block height (half letter height)
    subtotal_height_buffer = _calculate_y_tolerance(subtotal_marker)
    total_height_buffer = _calculate_y_tolerance(total_marker) if total_marker else subtotal_height_buffer
    search_y_lower = y_subtotal - subtotal_height_buffer  # Dynamic buffer above subtotal
    search_y_upper = y_total + total_height_buffer      # Dynamic buffer below total
    
    all_blocks_in_region = [
        b for b in blocks
        if search_y_lower <= b.get("y", 0) <= search_y_upper
    ]
    _debug_log('info', f"DEBUG: ============================================================")
    _debug_log('info', f"DEBUG: Searching for ALL blocks between Y={search_y_lower:.4f} and Y={search_y_upper:.4f}")
    _debug_log('info', f"DEBUG: (Subtotal Y={y_subtotal:.4f}, Total Y={y_total:.4f})")
    _debug_log('info', f"DEBUG: Found {len(all_blocks_in_region)} total blocks (all types) in expanded totals region:")
    for b in sorted(all_blocks_in_region, key=lambda x: x.get('y', 0)):
        _debug_log('info', f"  - Y={b.get('y', 0):.4f}, X={b.get('x', 0):.4f}, center_x={b.get('center_x', 'N/A')}, width={b.get('width', 'N/A')}, text='{b.get('text', '')}', is_amount={b.get('is_amount', False)}, amount={b.get('amount')}")
    _debug_log('info', f"DEBUG: ============================================================")
    
    # Also check if there are blocks with amounts that weren't recognized as is_amount=True
    # Try to extract amounts from text blocks that might contain fees/deposits
    from .coordinate_extractor import _extract_amount
    potential_amount_blocks = []
    for b in all_blocks_in_region:
        if not b.get("is_amount", False) or b.get("amount") is None:
            text = b.get("text", "")
            # Check if this text might contain an amount (like "$0.05", "0.01", etc.)
            is_amount, amount_value = _extract_amount(text)
            if is_amount and amount_value:
                # This block has an amount but wasn't recognized - add it to potential_amount_blocks
                b_copy = b.copy()
                b_copy["is_amount"] = True
                b_copy["amount"] = amount_value
                potential_amount_blocks.append(b_copy)
                _debug_log('info', f"DEBUG: Found unrecognized amount in text block: '{text}' -> ${amount_value:.2f} at Y={b.get('y', 0):.4f}")
    
    # Add potential_amount_blocks to amount_blocks for processing
    if potential_amount_blocks:
        _debug_log('info', f"DEBUG: Adding {len(potential_amount_blocks)} unrecognized amount blocks to processing list")
        amount_blocks.extend(potential_amount_blocks)
    
    # CRITICAL: Use RELATIVE positioning instead of absolute Y coordinates
    # This handles S-folded receipts where different sections may have different offsets
    # Strategy: Calculate relative position (0-1) between subtotal and total markers
    # This way, even if the entire section shifts, the relative positions remain correct
    
    # Find the actual subtotal amount's Y coordinate (may be above or below marker)
    actual_subtotal_y = y_subtotal  # Default to marker Y
    if subtotal_amount_x_hundredths is not None:
        for block in amount_blocks:
            block_amount = block.get("amount")
            if block_amount and abs(block_amount - subtotal_from_receipt) < 0.01:
                block_x_hundredths = _get_hundredths_aligned_x(block)
                if abs(block_x_hundredths - x_subtotal_hundredths) <= X_TOLERANCE:
                    actual_subtotal_y = block.get("center_y") or block.get("y", y_subtotal)
                    _debug_log('info', f"DEBUG: Found actual subtotal amount Y: {actual_subtotal_y:.4f} (marker Y: {y_subtotal:.4f})")
                    break
    
    # Find the actual total amount's Y coordinate (may be above or below marker)
    actual_total_y = y_total  # Default to marker Y
    if total_amount_block:
        actual_total_y = total_amount_block.get("center_y") or total_amount_block.get("y", y_total)
        _debug_log('info', f"DEBUG: Found actual total amount Y: {actual_total_y:.4f} (marker Y: {y_total:.4f})")
    
    # Calculate the range between subtotal and total
    # Use the minimum of marker and actual amount Y for subtotal (to include amounts above marker)
    # Use the maximum of marker and actual amount Y for total (to include amounts below marker)
    reference_subtotal_y = min(y_subtotal, actual_subtotal_y)
    reference_total_y = max(y_total, actual_total_y)
    
    # Calculate the range (distance between subtotal and total)
    total_range = reference_total_y - reference_subtotal_y
    
    # If range is too small or negative, fall back to absolute positioning
    if total_range < 0.01:
        _debug_log('warning', f"DEBUG: Total range too small ({total_range:.4f}), falling back to absolute positioning")
        subtotal_height_buffer = _calculate_y_tolerance(subtotal_marker)
        total_block_for_buffer = total_amount_block if total_amount_block else (total_marker if total_marker else subtotal_marker)
        total_height_buffer = _calculate_y_tolerance(total_block_for_buffer)
        y_lower_bound = reference_subtotal_y - subtotal_height_buffer
        # CRITICAL: Do NOT include buffer below total - amounts below total are in payment region
        y_upper_bound = reference_total_y  # Strict upper bound at total (no buffer below)
        use_relative_positioning = False
    else:
        # Use relative positioning: amounts within the range with small buffer
        # Buffer should be proportional to the range, not fixed
        # Use half a line height as buffer (approximately 1/10 of the range for typical receipts)
        buffer_ratio = max(0.05, min(0.1, total_range * 0.1))  # 5-10% of range, but at least 0.05
        relative_lower_bound = -buffer_ratio  # Small buffer above subtotal
        # CRITICAL: Do NOT include buffer above 1.0 - amounts above 1.0 are below total (in payment region)
        relative_upper_bound = 1.0  # Strict upper bound at total (no buffer below)
        use_relative_positioning = True
        _debug_log('info', f"DEBUG: Using relative positioning: range={total_range:.4f}, buffer_ratio={buffer_ratio:.4f}, subtotal_ref={reference_subtotal_y:.4f}, total_ref={reference_total_y:.4f}, bounds={relative_lower_bound:.3f} to {relative_upper_bound:.3f}")
    
    # CRITICAL: Find the actual subtotal amount block that matches subtotal_from_receipt
    # This ensures we always include the subtotal, even if it's slightly outside Y bounds
    subtotal_amount_block_in_sequence = None
    if subtotal_amount_x_hundredths is not None:
        for block in amount_blocks:
            block_amount = block.get("amount")
            if block_amount and abs(block_amount - subtotal_from_receipt) < 0.01:
                block_x_hundredths = _get_hundredths_aligned_x(block)
                if abs(block_x_hundredths - x_subtotal_hundredths) <= X_TOLERANCE:
                    subtotal_amount_block_in_sequence = block
                    _debug_log('info', f"DEBUG: Found subtotal amount block: ${block_amount:.2f} at Y={block.get('y', 0):.4f} (center_y={block.get('center_y', 0):.4f})")
                    break
    
    _debug_log('info', f"DEBUG: Checking {len(amount_blocks)} amount_blocks for alignment...")
    if use_relative_positioning:
        _debug_log('info', f"DEBUG: Using RELATIVE positioning: range={total_range:.4f}, subtotal_ref={reference_subtotal_y:.4f}, total_ref={reference_total_y:.4f}, bounds={relative_lower_bound:.2f} to {relative_upper_bound:.2f}")
    else:
        _debug_log('info', f"DEBUG: Using ABSOLUTE positioning: Y bounds: {y_lower_bound:.4f} to {y_upper_bound:.4f} (subtotal marker center_y={y_subtotal:.4f}, total center_y={y_total:.4f})")
    for block in amount_blocks:
        # Use center_y for more accurate row matching
        block_center_y = block.get("center_y") or block.get("y", 0)
        block_y = block.get("y", 0)  # Keep for logging
        block_x = block.get("center_x") or block.get("x", 0)
        block_x_hundredths = _get_hundredths_aligned_x(block)
        amount = block.get("amount")
        text = block.get("text", "")
        
        # Must be between subtotal and total rows (including both)
        # Use center_y for comparison to match amounts on the same visual row
        # Include a small buffer above subtotal marker to catch the actual subtotal amount
        # CRITICAL: Always include the actual subtotal amount block, even if slightly outside Y bounds
        # User requirement: "在sub total一直到total之间的数字都求和了就好"
        is_actual_subtotal = (subtotal_amount_block_in_sequence is not None and 
                             block.get("amount") == subtotal_amount_block_in_sequence.get("amount") and
                             abs(block_x_hundredths - x_subtotal_hundredths) <= X_TOLERANCE)
        
        # CRITICAL: Check Y position using relative or absolute positioning
        # Relative positioning handles S-folded receipts with different section offsets
        # CRITICAL: Must be STRICTLY between subtotal and total (not below total)
        if use_relative_positioning:
            # Calculate relative position: 0 = at subtotal, 1 = at total
            relative_position = (block_center_y - reference_subtotal_y) / total_range
            # Include amounts between -buffer and 1.0 (strictly at or before total)
            is_within_relative_bounds = relative_lower_bound <= relative_position <= relative_upper_bound
            
            # CRITICAL: Also check if this is the actual total amount (should be included)
            is_actual_total = (total_amount_block is not None and 
                             block.get("amount") == total_amount and
                             abs(block_x_hundredths - x_total_hundredths) <= X_TOLERANCE)
            
            if not is_actual_subtotal and not is_actual_total and not is_within_relative_bounds:
                # Log why it was skipped (only if it's close to the boundary)
                if amount is not None and (abs(relative_position - relative_lower_bound) < 0.05 or abs(relative_position - relative_upper_bound) < 0.05):
                    logger.info(f"  ✗ SKIPPED (relative Y): ${amount:.2f} at relative_pos={relative_position:.3f} (bounds: {relative_lower_bound:.2f} to {relative_upper_bound:.2f})")
                continue
        else:
            # Fallback to absolute positioning
            # CRITICAL: Also check if this is the actual total amount (should be included)
            is_actual_total = (total_amount_block is not None and 
                             block.get("amount") == total_amount and
                             abs(block_x_hundredths - x_total_hundredths) <= X_TOLERANCE)
            
            if not is_actual_subtotal and not is_actual_total and (block_center_y < y_lower_bound or block_center_y > y_upper_bound):
                # Log why it was skipped (only if it's close to the boundary)
                if amount is not None and (abs(block_center_y - y_lower_bound) < 0.01 or abs(block_center_y - y_upper_bound) < 0.01):
                    logger.info(f"  ✗ SKIPPED (absolute Y): ${amount:.2f} at center_y={block_center_y:.4f} (bounds: {y_lower_bound:.4f} to {y_upper_bound:.4f})")
                continue
        
        # CRITICAL: Include amounts that are hundredths-aligned with subtotal/total
        # OR amounts that are in a different column but still in the totals region
        # Tax and fees may be in a different column than subtotal/total
        # User requirement: "所有小票右边数字部分都是百分位对齐的"
        x_diff_subtotal = abs(block_x_hundredths - x_subtotal_hundredths)
        x_diff_total = abs(block_x_hundredths - x_total_hundredths)
        
        # Must be aligned with subtotal/total column (hundredths-aligned X coordinate)
        # OR be in the right half of the page (likely a tax/fee amount in a different column)
        is_aligned_with_subtotal_total = x_diff_subtotal <= X_TOLERANCE or x_diff_total <= X_TOLERANCE
        is_in_right_half = block_x_hundredths > 0.4  # Right half of page (tax/fees are usually on the right)
        is_aligned = is_aligned_with_subtotal_total or is_in_right_half
        
        # Additional filters: exclude product codes, points, and other non-receipt amounts
        # Check if text contains "Code:" which indicates a product code
        is_product_code = "code:" in text.lower()
        
        # CRITICAL: Exclude amounts that are clearly not part of totals sequence
        # - Points balance (e.g., ": 420", "points", "balance")
        # - Store codes (e.g., "SC-1")
        # - Dates/times (e.g., "01/10/26 1:45:58 PM")
        text_lower = text.lower()
        is_points = any(keyword in text_lower for keyword in ["points", "balance", ": 420", ": 20"])
        is_store_code = any(pattern in text_lower for pattern in ["sc-", "store code", "terminal:"])
        is_date_time = bool(re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', text) or re.search(r'\d{1,2}:\d{2}:\d{2}', text))
        
        # CRITICAL: Exclude amounts that don't start with $ or are clearly not currency
        # Points balance like ": 420" should not be included
        is_currency_format = text.strip().startswith("$") or "usd$" in text_lower or re.search(r'\$\s*\d+\.\d{2}', text)
        
        if amount is not None and is_aligned and not is_product_code and not is_points and not is_store_code and not is_date_time and is_currency_format:
            # Include center_y for more accurate label matching
            block_center_y = block.get("center_y") or block_y
            sequence_amounts.append({
                "amount": amount,
                "text": text,
                "y": block_y,
                "center_y": block_center_y,  # Include center_y for label matching
                "x": block_x,
                "center_x": block.get("center_x") or block_x,  # Include center_x for label matching
                "x_hundredths": block_x_hundredths,  # Hundredths-aligned X coordinate
                "is_subtotal_total_column": x_diff_subtotal <= X_TOLERANCE
            })
            
            alignment_reason = []
            if is_actual_subtotal:
                alignment_reason.append("actual subtotal (forced inclusion)")
            if is_aligned_with_subtotal_total:
                alignment_reason.append("aligned with subtotal/total")
            elif is_in_right_half:
                alignment_reason.append("in right half (likely tax/fee)")
            logger.info(f"  ✓ INCLUDED (aligned): ${amount:.2f} at Y={block_y:.4f} (center_y={block_center_y:.4f}), X_hundredths={block_x_hundredths:.4f}, text='{text}' - {', '.join(alignment_reason)}")
        else:
            if amount is not None:
                skip_reason = []
                if not is_aligned_with_subtotal_total and not is_in_right_half:
                    skip_reason.append(f"NOT ALIGNED (diff from subtotal: {x_diff_subtotal:.4f}, diff from total: {x_diff_total:.4f}, tolerance={X_TOLERANCE}, X={block_x_hundredths:.4f} < 0.4)")
                if is_product_code:
                    skip_reason.append("product code")
                logger.info(f"  ✗ SKIPPED: ${amount:.2f} at Y={block_y:.4f}, X_hundredths={block_x_hundredths:.4f}, text='{text}' - {', '.join(skip_reason)}")
            else:
                logger.debug(f"  Skipped (no amount): Y={block_y:.4f}, text='{text}'")
    
    # Sort by Y coordinate (top to bottom)
    sequence_amounts.sort(key=lambda a: a["y"])
    
    _debug_log('info', f"============================================================")
    _debug_log('info', f"Found {len(sequence_amounts)} amounts in totals region (between SUBTOTAL and TOTAL):")
    for idx, seq_amt in enumerate(sequence_amounts):
        x_hundredths = seq_amt.get('x_hundredths', seq_amt['x'])
        center_y = seq_amt.get('center_y', seq_amt.get('y', 0))
        _debug_log('info', f"  [{idx}] ${seq_amt['amount']:.2f} at Y={seq_amt['y']:.4f} (center_y={center_y:.4f}), X={seq_amt['x']:.4f}, X_hundredths={x_hundredths:.4f}, text='{seq_amt.get('text', '')}'")
    _debug_log('info', f"============================================================")
    
    # CRITICAL: Allow empty sequence_amounts - some grocery stores have no tax/fee
    # In this case, subtotal should equal total
    if not sequence_amounts:
        # Check if subtotal equals total (no tax/fee case)
        if subtotal_from_receipt and total_amount and abs(subtotal_from_receipt - total_amount) < 0.03:
            logger.info("No amounts between SUBTOTAL and TOTAL - grocery store format (subtotal = total, no tax/fee)")
            return {
                "passed": True,
                "sequence": [
                    {"label": "Subtotal", "amount": round(subtotal_from_receipt, 2)},
                    {"label": "Total Sales", "amount": round(total_amount, 2)}
                ],
                "calculated_total": round(subtotal_from_receipt, 2),
                "total_from_receipt": round(total_amount, 2),
                "expected_total": round(expected_total, 2) if expected_total else None,
                "difference": 0.0,
                "tolerance": 0.03,
                "middle_amounts": [],
                "note": "Grocery store format - no tax/fee, subtotal equals total",
                "sequence_amounts_debug": []
            }
        else:
            return {
                "passed": False,
                "reason": "no_amounts_in_totals_region",
                "error": "Cannot find amounts between SUBTOTAL and TOTAL",
                "sequence_amounts_debug": []
            }
    
    # Step 4: Extract sequence
    # Use subtotal_from_receipt (from items_sum_check) as the starting point
    # Find all amounts between SUBTOTAL and TOTAL (excluding SUBTOTAL and TOTAL themselves)
    # These are tax and fees
    
    # Identify which amounts are subtotal and total by comparing with known values and right-aligned X coordinates
    # Subtotal and total are usually in the same column (right-aligned)
    # Tax and fees may be in a different column
    subtotal_seq_idx = None
    total_seq_idx = None
    
    # First, try to find subtotal and total by matching both value and hundredths-aligned X coordinate
    for i, seq_amt in enumerate(sequence_amounts):
        seq_x_hundredths = seq_amt.get("x_hundredths", seq_amt["x"])
        seq_amount = seq_amt["amount"]
        
        # Check if this is subtotal (value matches AND hundredths-aligned X coordinate matches)
        if subtotal_seq_idx is None:
            value_match = abs(seq_amount - subtotal_from_receipt) < 0.01  # Stricter tolerance: 1 cent
            x_match = abs(seq_x_hundredths - x_subtotal_hundredths) <= X_TOLERANCE
            if value_match and x_match:
                subtotal_seq_idx = i
                logger.info(f"✓ Found subtotal at index {i}: ${seq_amount:.2f} (expected ${subtotal_from_receipt:.2f}) at hundredths-aligned X={seq_x_hundredths:.4f}")
        
        # Check if this is total (value matches AND hundredths-aligned X coordinate matches)
        if total_seq_idx is None:
            value_match = abs(seq_amount - total_amount) < 0.01  # Stricter tolerance: 1 cent
            x_match = abs(seq_x_hundredths - x_total_hundredths) <= X_TOLERANCE
            if value_match and x_match:
                total_seq_idx = i
                logger.info(f"✓ Found total at index {i}: ${seq_amount:.2f} (expected ${total_amount:.2f}) at hundredths-aligned X={seq_x_hundredths:.4f}")
    
    # Fallback: if not found by value+X, try by value only (with strict tolerance)
    if subtotal_seq_idx is None:
        logger.warning(f"⚠ Subtotal not found by value+X match, trying value-only match (expected: ${subtotal_from_receipt:.2f})")
        for i, seq_amt in enumerate(sequence_amounts):
            if abs(seq_amt["amount"] - subtotal_from_receipt) < 0.01:  # Stricter: 1 cent
                subtotal_seq_idx = i
                logger.info(f"✓ Found subtotal at index {i} by value only: ${seq_amt['amount']:.2f}")
                break
    
    if total_seq_idx is None:
        logger.warning(f"⚠ Total not found by value+X match, trying value-only match (expected: ${total_amount:.2f})")
        for i, seq_amt in enumerate(sequence_amounts):
            if abs(seq_amt["amount"] - total_amount) < 0.01:  # Stricter: 1 cent
                total_seq_idx = i
                logger.info(f"✓ Found total at index {i} by value only: ${seq_amt['amount']:.2f}")
                break
    
    # Final fallback: use first and last (but only if we have a reasonable match)
    # Don't use fallback if we have a clear subtotal match but no total match
    if subtotal_seq_idx is None:
        subtotal_seq_idx = 0
        logger.warning(f"⚠ Using first amount as subtotal fallback: ${sequence_amounts[0]['amount']:.2f}")
    if total_seq_idx is None:
        # Use the last amount as total, but log a warning
        total_seq_idx = len(sequence_amounts) - 1
        logger.warning(f"⚠ Using last amount as total fallback: ${sequence_amounts[total_seq_idx]['amount']:.2f} (expected: ${total_amount:.2f})")
    
    _debug_log('info', f"============================================================")
    _debug_log('info', f"Identified subtotal at index {subtotal_seq_idx} (${sequence_amounts[subtotal_seq_idx]['amount']:.2f} at hundredths-aligned X={sequence_amounts[subtotal_seq_idx].get('x_hundredths', sequence_amounts[subtotal_seq_idx]['x']):.4f})")
    _debug_log('info', f"Identified total at index {total_seq_idx} (${sequence_amounts[total_seq_idx]['amount']:.2f} at hundredths-aligned X={sequence_amounts[total_seq_idx].get('x_hundredths', sequence_amounts[total_seq_idx]['x']):.4f})")
    _debug_log('info', f"All amounts in sequence_amounts (before filtering):")
    for idx, seq_amt in enumerate(sequence_amounts):
        is_subtotal = idx == subtotal_seq_idx
        is_total = idx == total_seq_idx
        status = "SUBTOTAL" if is_subtotal else ("TOTAL" if is_total else "MIDDLE")
        _debug_log('info', f"  [{idx}] {status}: ${seq_amt['amount']:.2f} at Y={seq_amt['y']:.4f}, text='{seq_amt.get('text', '')}'")
    _debug_log('info', f"============================================================")
    
    # CRITICAL: "消消乐" logic - each amount can only be used once
    # Use Y coordinate as unique ID to track used amounts (as requested by user)
    # This ensures that amounts at the same Y coordinate are only used once
    used_y_coordinates = set()  # Set of Y coordinates (rounded to 3 decimals) that have been used
    
    # Mark subtotal as used (using Y coordinate as unique ID)
    subtotal_amt = sequence_amounts[subtotal_seq_idx]
    subtotal_y = round(subtotal_amt.get("center_y") or subtotal_amt.get("y", 0), 3)
    used_y_coordinates.add(subtotal_y)
    logger.info(f"✓ Marked SUBTOTAL as used: ${subtotal_amt['amount']:.2f} at Y={subtotal_y:.3f} (X={subtotal_amt.get('x_hundredths', subtotal_amt['x']):.4f})")
    
    # Mark total as used (using Y coordinate as unique ID)
    total_amt = sequence_amounts[total_seq_idx]
    total_y = round(total_amt.get("center_y") or total_amt.get("y", 0), 3)
    used_y_coordinates.add(total_y)
    logger.info(f"✓ Marked TOTAL as used: ${total_amt['amount']:.2f} at Y={total_y:.3f} (X={total_amt.get('x_hundredths', total_amt['x']):.4f})")
    
    middle_amounts = []
    middle_amounts_with_labels = []
    
    # Track which label texts have been used (to avoid duplicates)
    # Each label text can only be used once (e.g., "Bottle Deposit" can only match one amount)
    used_label_texts = set()  # Set of label texts that have already been assigned
    
    # Find labels for middle amounts by looking at text blocks near each amount
    # Process amounts in Y coordinate order (top to bottom) to ensure no inversion
    # For each amount in sequence_amounts between subtotal and total, try to find its label
    _debug_log('info', f"DEBUG: Finding labels for middle amounts (excluding subtotal and total)")
    
    # Sort middle amounts by Y coordinate (top to bottom) to ensure proper order
    # CRITICAL: Process in Y order (top to bottom) to ensure no inversion
    # CRITICAL: Exclude subtotal, total, AND any amounts that match used amounts (消消乐)
    middle_amount_indices = []
    for i in range(len(sequence_amounts)):
        if i == subtotal_seq_idx or i == total_seq_idx:
            continue  # Skip subtotal and total indices
        
        seq_amt = sequence_amounts[i]
        seq_y = round(seq_amt.get("center_y") or seq_amt.get("y", 0), 3)
        
        # CRITICAL: Check if this Y coordinate has already been used (消消乐 logic using Y as unique ID)
        if seq_y in used_y_coordinates:
            _debug_log('info', f"  ✗ SKIPPED (Y coordinate already used): ${seq_amt['amount']:.2f} at Y={seq_y:.3f}, X={seq_amt.get('x_hundredths', seq_amt['x']):.4f}")
            continue
        
        # CRITICAL: Also check if this amount matches the subtotal or total value
        # Even if it's at a different index, if it's the same amount as subtotal/total, skip it
        # This prevents duplicate subtotal/total amounts from being processed as middle amounts
        if abs(seq_amt["amount"] - subtotal_from_receipt) < 0.01:
            _debug_log('info', f"  ✗ SKIPPED (matches subtotal value): ${seq_amt['amount']:.2f} at Y={seq_y:.3f}, X={seq_amt.get('x_hundredths', seq_amt['x']):.4f}")
            continue
        
        if total_amount and abs(seq_amt["amount"] - total_amount) < 0.01:
            _debug_log('info', f"  ✗ SKIPPED (matches total value): ${seq_amt['amount']:.2f} at Y={seq_y:.3f}, X={seq_amt.get('x_hundredths', seq_amt['x']):.4f}")
            continue
        
        middle_amount_indices.append(i)
    # Sort by Y coordinate (top to bottom)
    middle_amount_indices.sort(key=lambda i: sequence_amounts[i]["y"])
    
    _debug_log('info', f"DEBUG: Processing {len(middle_amount_indices)} middle amounts in Y order:")
    for idx, i in enumerate(middle_amount_indices):
        seq_amt = sequence_amounts[i]
        _debug_log('info', f"  [{idx+1}] ${seq_amt['amount']:.2f} at Y={seq_amt['y']:.4f}")
    
    for i in middle_amount_indices:
        seq_amt = sequence_amounts[i]
        seq_y = seq_amt["y"]
        seq_amount = seq_amt["amount"]
        seq_x = seq_amt.get("x", 0)
        
        # Use center_y if available (more accurate for label matching), otherwise fall back to y
        # Document AI uses normalized coordinates (0-1), where Y=0 is top of page, Y=1 is bottom
        seq_center_y = seq_amt.get("center_y") or seq_y
        _debug_log('info', f"DEBUG: Looking for label for amount ${seq_amount:.2f} at Y={seq_y:.4f} (center_y={seq_center_y:.4f}), X={seq_x:.4f}")
        
        # Find text blocks on the same row to get the label
        # Strategy: Look for text blocks on the same row (similar Y) and to the left (smaller X)
        label = None
        label_candidates = []
        
        # Look in all blocks for text blocks on the same row
        for block in blocks:
            # Use center_y if available (more accurate), otherwise fall back to y
            block_y = block.get("center_y") or block.get("y", 0)
            block_x = block.get("center_x") or block.get("x", 0)
            text = block.get("text", "").strip()
            
            # CRITICAL: Exclude subtotal and total marker texts from label matching
            # These markers should not be used as labels for middle amounts
            text_lower = text.lower()
            is_subtotal_marker = any(marker in text_lower for marker in ["subtotal", "sub-total", "sub total"])
            is_total_marker = any(marker in text_lower for marker in ["total sales", "total amount", "total due", "grand total", "total:"])
            if is_subtotal_marker or is_total_marker:
                continue  # Skip subtotal/total markers
            
            # Must be on the same row (similar Y coordinate)
            # Use dynamic tolerance: take the maximum of both blocks' half-height tolerances
            # This ensures we match labels even if one block is taller than the other
            block_tolerance = _calculate_y_tolerance(block)
            seq_tolerance = _calculate_y_tolerance(seq_amt)
            label_y_tolerance = max(block_tolerance, seq_tolerance)  # Use larger tolerance
            y_diff = abs(block_y - seq_center_y)
            if y_diff <= label_y_tolerance:
                # Must be to the left of the amount (or very close)
                # Labels are typically to the left of amounts
                if block_x < seq_x + 0.1:  # Allow small overlap
                    if text and not block.get("is_amount", False):
                        text_lower = text.lower()
                        # Check if this text contains tax/fee keywords
                        # Handle OCR errors: "env.ronment" should match "environment"
                        normalized_text = text_lower.replace(".", "").replace(" ", "")
                        has_keyword = any(
                            keyword in text_lower or keyword in normalized_text
                            for keyword in ["tax", "deposit", "fee", "environment", "environmental", "bottle", "crf", "env"]
                        )
                        # Specifically check for environment fee (even with OCR errors)
                        is_environment_fee = (
                            "env" in normalized_text and "fee" in text_lower
                        ) or "environment" in normalized_text
                        
                        label_candidates.append({
                            "text": text,
                            "x": block_x,
                            "y": block_y,
                            "has_keyword": has_keyword,
                            "is_environment_fee": is_environment_fee,
                            "distance": abs(block_x - seq_x),
                            "y_distance": abs(block_y - seq_center_y)
                        })
                        logger.debug(f"  Candidate label: '{text}' at X={block_x:.4f}, Y={block_y:.4f}, Y_diff={abs(block_y - seq_center_y):.4f}, has_keyword={has_keyword}, is_env_fee={is_environment_fee}, distance={abs(block_x - seq_x):.4f}")
        
        # Select the best label candidate
        # General rule: X-axis aligned fields with Y-axis tolerance, but Y must be below previous entries
        # Each label type can only be used once (no reuse)
        label = None
        normalized_label = None  # Standardized label from fuzzy matching
        
        if label_candidates:
            # Prefer labels with keywords
            keyword_labels = [c for c in label_candidates if c["has_keyword"]]
            
            if keyword_labels:
                # Classify labels by type
                env_labels = []
                bottle_labels = []
                tax_labels = []
                
                for c in keyword_labels:
                    text_lower = c["text"].lower()
                    normalized = text_lower.replace(".", "").replace(" ", "")
                    
                    # Check for environment fee (handle OCR errors like "Env.ronment")
                    if c.get("is_environment_fee", False) or "environment" in normalized or ("env" in normalized and "fee" in text_lower):
                        env_labels.append(c)
                    # Check for bottle deposit (but not if it's actually environment fee)
                    elif ("bottle" in text_lower or "deposit" in text_lower) and not c.get("is_environment_fee", False):
                        bottle_labels.append(c)
                    # Check for tax
                    elif "tax" in text_lower:
                        tax_labels.append(c)
                
                # Select label based on availability
                # General rule: Each label text can only be used once (no reuse of same label text)
                # Filter out labels that have already been used
                available_tax_labels = [c for c in tax_labels if c["text"] not in used_label_texts]
                available_env_labels = [c for c in env_labels if c["text"] not in used_label_texts]
                available_bottle_labels = [c for c in bottle_labels if c["text"] not in used_label_texts]
                available_keyword_labels = [c for c in keyword_labels if c["text"] not in used_label_texts]
                available_label_candidates = [c for c in label_candidates if c["text"] not in used_label_texts]
                
                # Select the first available label (no priority, just use what's available and not used)
                # CRITICAL: Match labels based on Y coordinate proximity first (same row), then X distance
                # This ensures labels are matched to amounts on the same row
                
                # Combine all available labels and sort by Y distance (same row first), then X distance
                all_available_labels = []
                if available_tax_labels:
                    all_available_labels.extend([(c, "tax") for c in available_tax_labels])
                if available_env_labels:
                    all_available_labels.extend([(c, "env") for c in available_env_labels])
                if available_bottle_labels:
                    all_available_labels.extend([(c, "bottle") for c in available_bottle_labels])
                if available_keyword_labels:
                    all_available_labels.extend([(c, "keyword") for c in available_keyword_labels])
                if available_label_candidates:
                    all_available_labels.extend([(c, "candidate") for c in available_label_candidates])
                
                if all_available_labels:
                    # Select the label closest in Y coordinate (same row), then X distance
                    closest_candidate, label_category = min(all_available_labels, key=lambda x: (x[0]["y_distance"], x[0]["distance"]))
                    raw_label = closest_candidate["text"]
                    
                    # CRITICAL: Use fuzzy matching to standardize the label
                    # This handles OCR errors like "Bot le Deposit" → "Bottle Deposit"
                    # and "Env.ronment fee" → "Environmental Fee"
                    context = {
                        "region": "TOTALS",
                        "has_amount_on_right": True,
                        "column_role": "FEE_OR_TAX"
                    }
                    fuzzy_match_result = fuzzy_match_label(raw_label, context=context)
                    
                    if fuzzy_match_result:
                        normalized_label, match_score = fuzzy_match_result
                        logger.info(f"  ✓ Fuzzy matched '{raw_label}' → '{normalized_label}' (score={match_score:.3f})")
                        # Use normalized label for tracking uniqueness
                        label = normalized_label
                        # Track both raw and normalized to prevent duplicates
                        used_label_texts.add(raw_label)  # Prevent same raw text from being reused
                        used_label_texts.add(normalized_label)  # Prevent same normalized label from being reused
                    else:
                        # No fuzzy match found, use raw label
                        label = raw_label
                        used_label_texts.add(label)
                    
                    logger.info(f"  ✓ Selected label ({label_category}): '{label}' (raw: '{raw_label}') for ${seq_amount:.2f} at Y={seq_y:.4f} (label Y={closest_candidate['y']:.4f}, Y_diff={closest_candidate['y_distance']:.4f})")
                else:
                    # All labels have been used, or no candidates found
                    # Create a generic label
                    label = f"Fee/Tax {len(middle_amounts_with_labels) + 1}"
                    logger.warning(f"  ⚠ All labels used or no candidates - created generic label: '{label}' for ${seq_amount:.2f}")
            else:
                # No keyword labels, use the closest one that hasn't been used
                available_candidates = [c for c in label_candidates if c["text"] not in used_label_texts]
                if available_candidates:
                    closest = min(available_candidates, key=lambda c: (c["y_distance"], c["distance"]))
                    raw_label = closest["text"]
                    
                    # Try fuzzy matching even for non-keyword labels
                    context = {
                        "region": "TOTALS",
                        "has_amount_on_right": True,
                        "column_role": "FEE_OR_TAX"
                    }
                    fuzzy_match_result = fuzzy_match_label(raw_label, context=context)
                    
                    if fuzzy_match_result:
                        normalized_label, match_score = fuzzy_match_result
                        logger.info(f"  ✓ Fuzzy matched '{raw_label}' → '{normalized_label}' (score={match_score:.3f})")
                        label = normalized_label
                        used_label_texts.add(raw_label)
                        used_label_texts.add(normalized_label)
                    else:
                        label = raw_label
                        used_label_texts.add(label)
                    
                    logger.info(f"  ✓ Selected label (closest, no keyword): '{label}' (raw: '{raw_label}')")
                else:
                    # All candidates have been used
                    label = f"Fee/Tax {len(middle_amounts_with_labels) + 1}"
                    logger.warning(f"  ⚠ All label candidates used - created generic label: '{label}' for ${seq_amount:.2f}")
        else:
            logger.warning(f"  ✗ No label found for ${seq_amount:.2f} at Y={seq_y:.4f}")
        
        # CRITICAL: Mark this Y coordinate as used (消消乐 logic using Y as unique ID) BEFORE adding to middle_amounts
        seq_y_rounded = round(seq_center_y, 3)
        used_y_coordinates.add(seq_y_rounded)
        logger.info(f"  ✓ Marked Y coordinate as used: ${seq_amount:.2f} at Y={seq_y_rounded:.3f} (X={seq_amt.get('x_hundredths', seq_amt['x']):.4f})")
        
        # CRITICAL: Always add the amount to middle_amounts, even if no label was found
        # This ensures all amounts between subtotal and total are included
        middle_amounts.append(seq_amt["amount"])
        
        # Use the normalized label if available, otherwise use the found label, or create a generic one
        final_label = normalized_label or label or f"Fee/Tax {len(middle_amounts_with_labels) + 1}"
        
        middle_amounts_with_labels.append({
            "label": final_label,
            "amount": seq_amt["amount"],
            "text": seq_amt.get("text", ""),
            "y": seq_y
        })
        _debug_log('info', f"  ========================================")
        _debug_log('info', f"  Final: ${seq_amount:.2f} -> '{final_label}' (Y={seq_y:.4f}, center_y={seq_amt.get('center_y', 'N/A')})")
        _debug_log('info', f"  ========================================")
    
    # Find TOTAL amount from receipt
    total_from_receipt = total_amount
    if total_from_receipt is None:
        total_from_receipt = expected_total
    
    if total_from_receipt is None:
        return {
            "passed": False,
            "reason": "no_total_from_receipt",
            "error": "Cannot determine TOTAL amount from receipt"
        }
    
    # Calculate: subtotal_from_receipt + all middle amounts = total
    calculated_total = subtotal_from_receipt + sum(middle_amounts)
    
    difference = abs(calculated_total - total_from_receipt)
    tolerance = 0.03
    passed = difference <= tolerance
    
    # Build sequence for display
    sequence = [{"label": "Subtotal", "amount": round(subtotal_from_receipt, 2)}]
    sequence.extend([
        {"label": amt["label"], "amount": round(amt["amount"], 2)} 
        for amt in middle_amounts_with_labels
    ])
    sequence.append({"label": "Total Sales", "amount": round(total_from_receipt, 2)})
    
    result = {
        "passed": passed,
        "sequence": sequence,
        "calculated_total": round(calculated_total, 2),
        "total_from_receipt": round(total_from_receipt, 2),
        "expected_total": round(expected_total, 2) if expected_total else None,
        "difference": round(difference, 2),
        "tolerance": tolerance,
        "middle_amounts": middle_amounts_with_labels,  # Include detailed info for formatted output
        "sequence_amounts_debug": [  # Include all found amounts with coordinates for debugging
            {
                "amount": round(amt["amount"], 2),
                "y": round(amt["y"], 4),
                "x": round(amt["x"], 4),
                "text": amt.get("text", ""),
                "is_subtotal": i == subtotal_seq_idx,
                "is_total": i == total_seq_idx
            }
            for i, amt in enumerate(sequence_amounts)
        ]
    }
    
    if not passed:
        result["error"] = (
            f"Totals sequence mismatch: calculated {calculated_total:.2f}, "
            f"total from receipt {total_from_receipt:.2f}, difference {difference:.2f} > {tolerance}"
        )
    
    logger.info(
        f"Totals sequence check: {calculated_total:.2f} vs {total_from_receipt:.2f} (from receipt), "
        f"difference {difference:.2f}, passed={passed}"
    )
    
    return result


def _check_items_to_total(
    amount_blocks: List[Dict[str, Any]],
    total_marker: Dict[str, Any],
    expected_total: Optional[float],
    items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Check if items sum directly to total (no subtotal case).
    """
    if expected_total is None:
        return {
            "passed": False,
            "reason": "no_expected_total",
            "error": "LLM did not extract total"
        }
    
    y_total = total_marker.get("y", 0.9)
    x_total = total_marker.get("center_x") or total_marker.get("x", 0.5)
    
    # Find all amounts above total with similar X coordinate
    aligned_amounts = []
    for block in amount_blocks:
        block_y = block.get("y", 1)
        block_x = block.get("center_x") or block.get("x", 0)
        
        if block_y >= y_total:
            continue
        
        x_diff = abs(block_x - x_total)
        if x_diff <= X_TOLERANCE:
            amount = block.get("amount")
            if amount is not None:
                aligned_amounts.append(amount)
    
    calculated_sum = sum(aligned_amounts)
    difference = abs(calculated_sum - expected_total)
    tolerance = 0.03
    passed = difference <= tolerance
    
    return {
        "passed": passed,
        "calculated_sum": round(calculated_sum, 2),
        "expected_total": round(expected_total, 2),
        "difference": round(difference, 2),
        "tolerance": tolerance,
        "items_count": len(aligned_amounts),
        "note": "No subtotal - items sum directly to total"
    }


def _extract_tax_and_fees_from_totals_region(
    blocks: List[Dict[str, Any]],
    totals_region: List[Dict[str, Any]],
    subtotal_marker: Optional[Dict[str, Any]],
    total_marker: Optional[Dict[str, Any]]
) -> Tuple[Optional[float], List[Dict[str, Any]]]:
    """
    Extract tax and fees from totals region.
    
    Returns:
        (tax_amount, fees_list)
        fees_list contains: [{"label": "Bottle Deposit", "amount": 0.05}, ...]
    """
    from .coordinate_extractor import extract_amount_blocks
    
    if not subtotal_marker or not total_marker:
        return None, []
    
    y_subtotal = subtotal_marker.get("y", 0.5)
    y_total = total_marker.get("y", 0.9)
    
    # Find all blocks in totals region
    totals_blocks = [
        b for b in blocks
        if y_subtotal < b.get("y", 0) < y_total
    ]
    
    # Sort by Y coordinate
    totals_blocks.sort(key=lambda b: b.get("y", 0))
    
    tax_amount = None
    fees = []
    
    # Look for tax and fee labels
    for i, block in enumerate(totals_blocks):
        text = block.get("text", "").lower()
        
        # Check for tax
        if "tax" in text and not tax_amount:
            # Look for amount in nearby blocks
            for j in range(max(0, i-2), min(len(totals_blocks), i+3)):
                nearby = totals_blocks[j]
                if nearby.get("is_amount") and nearby.get("amount"):
                    tax_amount = nearby.get("amount")
                    break
        
        # Check for fees
        elif any(fee_word in text for fee_word in ["bottle deposit", "environment fee", "env fee", "deposit"]):
            fee_label = block.get("text", "").strip()
            # Look for amount in nearby blocks
            for j in range(max(0, i-2), min(len(totals_blocks), i+3)):
                nearby = totals_blocks[j]
                if nearby.get("is_amount") and nearby.get("amount"):
                    fees.append({
                        "label": fee_label,
                        "amount": nearby.get("amount")
                    })
                    break
    
    return tax_amount, fees


def _generate_formatted_output(
    items: List[Dict[str, Any]],
    subtotal_from_receipt: Optional[float],
    tax: float,
    fees: List[Dict[str, Any]],
    expected_total: Optional[float],
    check_details: Dict[str, Any],
    items_count_output: str = ""
) -> str:
    """
    Generate formatted vertical addition output for debugging.
    
    Format:
    item name                    $ amount
    item name                    $ amount
    ...
    ----------------------------
    SUBTOTAL                     $ amount
    TAX                          $ amount
    BOTTLE DEPOSIT               $ amount
    ENVIRONMENT FEE              $ amount
    ----------------------------
    TOTAL                        $ amount
    """
    lines = []
    
    # If item count check failed, include its formatted output first
    if items_count_output:
        lines.append(items_count_output)
        lines.append("")
        lines.append("=" * 50)
        lines.append("")
    
    # Add items
    for item in items:
        product_name = item.get("product_name", item.get("raw_text", "Unknown"))
        line_total = item.get("line_total")
        
        if line_total is not None:
            # Truncate long product names
            if len(product_name) > 40:
                product_name = product_name[:37] + "..."
            
            lines.append(f"{product_name:<40} ${line_total:>8.2f}")
    
    # Separator
    if items:
        lines.append("-" * 50)
    
    # Calculate actual subtotal from items
    calculated_subtotal = sum(item.get("line_total", 0) for item in items if item.get("line_total"))
    
    # Subtotal (use subtotal_from_receipt if available, otherwise calculated)
    if subtotal_from_receipt is not None:
        if abs(calculated_subtotal - subtotal_from_receipt) > 0.01:
            # Show both calculated and from receipt
            lines.append(f"{'SUBTOTAL (calculated)':<40} ${calculated_subtotal:>8.2f}")
            lines.append(f"{'SUBTOTAL (from receipt)':<40} ${subtotal_from_receipt:>8.2f}")
        else:
            lines.append(f"{'SUBTOTAL':<40} ${subtotal_from_receipt:>8.2f}")
    else:
        lines.append(f"{'SUBTOTAL':<40} ${calculated_subtotal:>8.2f}")
    
    # Tax
    if tax and tax > 0:
        lines.append(f"{'TAX':<40} ${tax:>8.2f}")
    
    # Fees
    for fee in fees:
        fee_label = fee.get("label", "FEE")
        fee_amount = fee.get("amount", 0)
        if fee_amount > 0:
            # Truncate long labels
            if len(fee_label) > 40:
                fee_label = fee_label[:37] + "..."
            lines.append(f"{fee_label:<40} ${fee_amount:>8.2f}")
    
    # Separator
    lines.append("-" * 50)
    
    # Total
    if expected_total is not None:
        lines.append(f"{'TOTAL':<40} ${expected_total:>8.2f}")
    else:
        # Calculate total
        total = calculated_subtotal + tax + sum(f.get("amount", 0) for f in fees)
        lines.append(f"{'TOTAL':<40} ${total:>8.2f}")
    
    return "\n".join(lines)
