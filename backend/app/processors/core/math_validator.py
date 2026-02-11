"""
Math Validator: Validate item math (qty × unit_price = line_total) and totals.

This module implements Step 7 of the receipt processing pipeline.
"""
from typing import List, Optional, Tuple
import logging
import re
from .structures import ExtractedItem, TotalsSequence

logger = logging.getLogger(__name__)

# Tolerance for math validation
MATH_TOLERANCE = 0.02


def validate_item_math(item: ExtractedItem, row_text: str) -> float:
    """
    Validate item math: qty × unit_price = line_total.

    Args:
        item: ExtractedItem to validate
        row_text: Original row text for number extraction

    Returns:
        Confidence score (0.0 to 1.0)
    """
    # If we already have qty and unit_price, validate directly
    if item.quantity is not None and item.unit_price is not None:
        calculated = item.quantity * item.unit_price
        if abs(calculated - item.line_total) < MATH_TOLERANCE:
            item.confidence = 1.0
            logger.debug(
                f"Item math validated: {item.quantity} × ${item.unit_price:.2f} = "
                f"${calculated:.2f} ≈ ${item.line_total:.2f}"
            )
            return 1.0

    # Try to extract all numbers from row text
    numbers = _extract_all_numbers(row_text)

    if len(numbers) < 2:
        return 0.5  # Default confidence if can't validate

    # Try all combinations of two numbers
    for i, a in enumerate(numbers):
        for j, b in enumerate(numbers):
            if i == j:
                continue

            # Try a * b
            if abs(a * b - item.line_total) < MATH_TOLERANCE:
                item.quantity = a
                item.unit_price = b
                item.confidence = 1.0
                logger.debug(
                    f"Item math validated from text: {a} × {b} = ${a * b:.2f} ≈ ${item.line_total:.2f}"
                )
                return 1.0

            # Try b * a (reverse order)
            if abs(b * a - item.line_total) < MATH_TOLERANCE:
                item.quantity = b
                item.unit_price = a
                item.confidence = 1.0
                logger.debug(
                    f"Item math validated from text: {b} × {a} = ${b * a:.2f} ≈ ${item.line_total:.2f}"
                )
                return 1.0

    return 0.5  # Default confidence if validation fails


def validate_totals(
    items: List[ExtractedItem],
    totals_sequence: TotalsSequence,
    fees: List[dict],
    tax: float,
    fees_from_items_region: Optional[List[dict]] = None,
) -> Tuple[bool, dict]:
    """
    Validate totals: items sum = subtotal, subtotal + fees + tax = total.
    For BC (and similar): items_sum + fees_from_items_region (Bottle deposit, Env fee in items) = total.

    Args:
        items: List of extracted items
        totals_sequence: TotalsSequence with subtotal and total
        fees: List of fee dictionaries with 'amount' key (from totals region)
        tax: Tax amount
        fees_from_items_region: Optional list of {label, amount} from items region (BC: Bottle deposit, Env fee)

    Returns:
        Tuple of (is_valid, validation_details)
    """
    validation_details = {
        "items_sum_check": None,
        "totals_sum_check": None,
        "passed": False
    }

    items_sum = sum(item.line_total for item in items)
    total_val = totals_sequence.total.amount if (totals_sequence.total and totals_sequence.total.amount is not None) else None
    subtotal_val = totals_sequence.subtotal.amount if (totals_sequence.subtotal and totals_sequence.subtotal.amount is not None) else None

    # Grocery case: no subtotal, only total — validate items sum [+ fees_from_items] = total
    if not subtotal_val:
        if total_val is not None:
            fees_from_items_sum = sum(
                f.get("amount", 0) for f in (fees_from_items_region or [])
            )
            calculated = round(items_sum + fees_from_items_sum, 2)
            items_diff_total = round(abs(calculated - total_val), 2)
            items_passed = items_diff_total <= 0.03
            note = "grocery: items sum = total (no subtotal)"
            if fees_from_items_sum > 0:
                note += f"; + fees_from_items=${fees_from_items_sum:.2f} (BC)"
            validation_details["items_sum_check"] = {
                "passed": items_passed,
                "calculated": calculated,
                "expected": total_val,
                "difference": items_diff_total,
                "note": note,
            }
            breakdown = {"items_sum": round(items_sum, 2)}
            if fees_from_items_sum > 0:
                breakdown["fees_from_items"] = round(fees_from_items_sum, 2)
            validation_details["totals_sum_check"] = {
                "passed": items_passed,
                "calculated": calculated,
                "expected": total_val,
                "difference": items_diff_total,
                "breakdown": breakdown,
            }
            validation_details["passed"] = items_passed
            return validation_details["passed"], validation_details
        validation_details["items_sum_check"] = {"passed": None, "reason": "no_subtotal"}
        return False, validation_details

    # Standard case: subtotal present
    items_diff = round(abs(items_sum - subtotal_val), 2)
    items_passed = items_diff <= 0.03
    validation_details["items_sum_check"] = {
        "passed": items_passed,
        "calculated": items_sum,
        "expected": subtotal_val,
        "difference": items_diff
    }
    if not items_passed:
        logger.warning(
            f"Items sum check failed: calculated ${items_sum:.2f}, "
            f"expected ${subtotal_val:.2f}, difference ${items_diff:.2f}"
        )

    if not totals_sequence.total or total_val is None:
        validation_details["totals_sum_check"] = {"passed": None, "reason": "no_total"}
        return items_passed, validation_details

    fees_sum = sum(f.get("amount", 0) for f in fees)
    calculated_total = round(subtotal_val + fees_sum + tax, 2)
    totals_diff = round(abs(calculated_total - total_val), 2)
    totals_passed = totals_diff <= 0.03
    validation_details["totals_sum_check"] = {
        "passed": totals_passed,
        "calculated": calculated_total,
        "expected": total_val,
        "difference": totals_diff,
        "breakdown": {
            "subtotal": round(subtotal_val, 2),
            "fees": round(fees_sum, 2),
            "tax": round(tax, 2),
            "sum": calculated_total
        }
    }
    if not totals_passed:
        logger.warning(
            f"Totals sum check failed: calculated ${calculated_total:.2f}, "
            f"expected ${total_val:.2f}, difference ${totals_diff:.2f}"
        )
    validation_details["passed"] = items_passed and totals_passed
    return validation_details["passed"], validation_details


def _extract_all_numbers(text: str) -> List[float]:
    """Extract all numbers from text."""
    pattern = r'\d+\.?\d*'
    matches = re.findall(pattern, text)
    numbers = []
    for match in matches:
        try:
            num = float(match)
            numbers.append(num)
        except ValueError:
            continue
    return numbers
