"""
Coordinate-based Sum Checker: Use coordinates for precise sum validation.

This module implements sum checking using coordinate information:
1. Find SUBTOTAL position
2. Sum amounts above SUBTOTAL with same X coordinate (items)
3. Sum amounts below SUBTOTAL in sequence (subtotal + tax + fees = total)
"""
from typing import Dict, Any, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# X coordinate tolerance for vertical alignment (5-10% as requested)
X_TOLERANCE = 0.075  # 7.5% tolerance (middle of 5-10% range)

# Y coordinate tolerance for sequential amounts
Y_TOLERANCE = 0.02  # 2% tolerance for vertical spacing


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
        llm_result: LLM parsing result
        
    Returns:
        (is_valid, check_details)
    """
    from .coordinate_extractor import extract_amount_blocks
    
    check_details = {
        "method": "coordinate_based",
        "items_sum_check": None,
        "totals_sequence_check": None,
        "formatted_output": None,
        "errors": []
    }
    
    receipt = llm_result.get("receipt", {})
    items = llm_result.get("items", [])
    
    # Get expected values
    expected_subtotal = receipt.get("subtotal")
    expected_tax = receipt.get("tax") or 0.0
    expected_total = receipt.get("total")
    
    # Extract amount blocks
    amount_blocks = extract_amount_blocks(blocks)
    
    # Get markers
    subtotal_marker = regions.get("markers", {}).get("subtotal")
    total_marker = regions.get("markers", {}).get("total")
    
    # Check 1: Items sum (amounts above SUBTOTAL, aligned vertically)
    if subtotal_marker:
        items_sum_result = _check_items_sum(
            amount_blocks,
            subtotal_marker,
            expected_subtotal,
            items
        )
        check_details["items_sum_check"] = items_sum_result
    else:
        # No subtotal marker - this is a grocery store without subtotal
        logger.info("No SUBTOTAL marker found - likely a grocery store without subtotal")
        check_details["items_sum_check"] = {
            "passed": None,
            "reason": "no_subtotal_marker",
            "note": "Grocery store format - no subtotal column"
        }
    
    # Check 2: Totals sequence (subtotal + tax + fees = total)
    if subtotal_marker and total_marker:
        totals_sequence_result = _check_totals_sequence(
            amount_blocks,
            subtotal_marker,
            total_marker,
            expected_subtotal,
            expected_tax,
            expected_total,
            regions.get("totals", [])
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
    
    # Generate formatted output for debugging
    check_details["formatted_output"] = _generate_formatted_output(
        items,
        expected_subtotal,
        expected_tax,
        expected_total,
        check_details
    )
    
    # Determine overall validity
    items_check_passed = check_details["items_sum_check"].get("passed")
    totals_check_passed = check_details["totals_sequence_check"].get("passed")
    
    # If either check explicitly failed, return False
    if items_check_passed is False or totals_check_passed is False:
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
    1. Find SUBTOTAL's X coordinate
    2. Find all amounts above SUBTOTAL with similar X coordinate
    3. Sum them and compare to expected subtotal
    """
    if expected_subtotal is None:
        return {
            "passed": None,
            "reason": "no_expected_subtotal",
            "note": "LLM did not extract subtotal"
        }
    
    x_subtotal = subtotal_marker.get("center_x") or subtotal_marker.get("x", 0.5)
    y_subtotal = subtotal_marker.get("y", 0.5)
    
    # Find amounts above subtotal with similar X coordinate
    aligned_amounts = []
    for block in amount_blocks:
        block_y = block.get("y", 1)
        block_x = block.get("center_x") or block.get("x", 0)
        
        # Must be above subtotal
        if block_y >= y_subtotal:
            continue
        
        # X coordinate must be within tolerance
        x_diff = abs(block_x - x_subtotal)
        if x_diff <= X_TOLERANCE:
            amount = block.get("amount")
            if amount is not None:
                aligned_amounts.append({
                    "amount": amount,
                    "text": block.get("text", ""),
                    "x": block_x,
                    "y": block_y
                })
    
    # Sort by Y coordinate (top to bottom)
    aligned_amounts.sort(key=lambda a: a["y"])
    
    # Sum amounts
    calculated_sum = sum(a["amount"] for a in aligned_amounts)
    
    # Compare
    difference = abs(calculated_sum - expected_subtotal)
    tolerance = 0.03
    passed = difference <= tolerance
    
    result = {
        "passed": passed,
        "calculated_sum": round(calculated_sum, 2),
        "expected_subtotal": round(expected_subtotal, 2),
        "difference": round(difference, 2),
        "tolerance": tolerance,
        "aligned_amounts_count": len(aligned_amounts),
        "aligned_amounts": [
            {"text": a["text"], "amount": round(a["amount"], 2)} 
            for a in aligned_amounts[:10]  # Limit to first 10 for brevity
        ]
    }
    
    if not passed:
        result["error"] = (
            f"Items sum mismatch: calculated {calculated_sum:.2f}, "
            f"expected {expected_subtotal:.2f}, difference {difference:.2f} > {tolerance}"
        )
    
    logger.info(
        f"Items sum check: {calculated_sum:.2f} vs {expected_subtotal:.2f}, "
        f"difference {difference:.2f}, passed={passed}"
    )
    
    return result


def _check_totals_sequence(
    amount_blocks: List[Dict[str, Any]],
    subtotal_marker: Dict[str, Any],
    total_marker: Dict[str, Any],
    expected_subtotal: Optional[float],
    expected_tax: float,
    expected_total: Optional[float],
    totals_region: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Check totals sequence: subtotal + tax + fees = total.
    
    Strategy:
    1. Find amounts between SUBTOTAL and TOTAL
    2. Extract sequence: subtotal, tax, fees, total
    3. Verify: subtotal + tax + fees = total
    """
    if expected_total is None:
        return {
            "passed": False,
            "reason": "no_expected_total",
            "error": "LLM did not extract total"
        }
    
    y_subtotal = subtotal_marker.get("y", 0.5)
    y_total = total_marker.get("y", 0.9)
    
    # Find amounts between subtotal and total
    sequence_amounts = []
    for block in amount_blocks:
        block_y = block.get("y", 0)
        if y_subtotal <= block_y <= y_total:
            amount = block.get("amount")
            if amount is not None:
                sequence_amounts.append({
                    "amount": amount,
                    "text": block.get("text", ""),
                    "y": block_y
                })
    
    # Sort by Y coordinate
    sequence_amounts.sort(key=lambda a: a["y"])
    
    if not sequence_amounts:
        return {
            "passed": False,
            "reason": "no_amounts_in_totals_region",
            "error": "Cannot find amounts between SUBTOTAL and TOTAL"
        }
    
    # Extract sequence
    # First amount should be subtotal, last should be total
    # Middle amounts are tax and fees
    subtotal_amount = sequence_amounts[0]["amount"] if sequence_amounts else None
    total_amount = sequence_amounts[-1]["amount"] if sequence_amounts else None
    middle_amounts = [a["amount"] for a in sequence_amounts[1:-1]] if len(sequence_amounts) > 2 else []
    
    # Calculate sum
    calculated_total = subtotal_amount + sum(middle_amounts) if subtotal_amount else None
    
    # Compare
    if calculated_total is None or total_amount is None:
        return {
            "passed": False,
            "reason": "incomplete_sequence",
            "error": "Cannot extract complete totals sequence"
        }
    
    difference = abs(calculated_total - expected_total)
    tolerance = 0.03
    passed = difference <= tolerance
    
    result = {
        "passed": passed,
        "sequence": [
            {"label": "Subtotal", "amount": round(subtotal_amount, 2)},
            *[{"label": f"Fee/Tax {i+1}", "amount": round(amt, 2)} for i, amt in enumerate(middle_amounts)],
            {"label": "Total", "amount": round(total_amount, 2)}
        ],
        "calculated_total": round(calculated_total, 2),
        "expected_total": round(expected_total, 2),
        "difference": round(difference, 2),
        "tolerance": tolerance
    }
    
    if not passed:
        result["error"] = (
            f"Totals sequence mismatch: calculated {calculated_total:.2f}, "
            f"expected {expected_total:.2f}, difference {difference:.2f} > {tolerance}"
        )
    
    logger.info(
        f"Totals sequence check: {calculated_total:.2f} vs {expected_total:.2f}, "
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


def _generate_formatted_output(
    items: List[Dict[str, Any]],
    expected_subtotal: Optional[float],
    expected_tax: float,
    expected_total: Optional[float],
    check_details: Dict[str, Any]
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
    ----------------------------
    TOTAL                        $ amount
    """
    lines = []
    
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
    
    # Subtotal
    if expected_subtotal is not None:
        lines.append(f"{'SUBTOTAL':<40} ${expected_subtotal:>8.2f}")
    else:
        lines.append(f"{'SUBTOTAL':<40} {'N/A':>10}")
    
    # Tax
    if expected_tax and expected_tax > 0:
        lines.append(f"{'TAX':<40} ${expected_tax:>8.2f}")
    
    # Separator
    lines.append("-" * 50)
    
    # Total
    if expected_total is not None:
        lines.append(f"{'TOTAL':<40} ${expected_total:>8.2f}")
    else:
        lines.append(f"{'TOTAL':<40} {'N/A':>10}")
    
    return "\n".join(lines)
