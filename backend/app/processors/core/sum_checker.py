"""
Sum Checker: Validate mathematical correctness of receipt data.

Validation rules:
1. sum(line_total) ≈ subtotal (tolerance ±0.03)
2. subtotal + tax ≈ total (tolerance ±0.03)
3. If subtotal is null, cannot validate, return requires backup check
4. If tax is null, treat as 0
5. Package price discounts (e.g., "2/$9.00") are valid if items sum to package price
"""
from typing import Dict, Any, Optional, Tuple, List
import logging
import re

logger = logging.getLogger(__name__)

TOLERANCE = 0.03  # Error tolerance


def detect_package_price_discounts(
    raw_text: str,
    items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Detect package price discounts from raw text and validate against items.

    Examples:
        - "2/$9.00" or "2 for $9.00" → buy 2 items for $9.00 total
        - "3/$10" → buy 3 items for $10.00 total

    Args:
        raw_text: Original receipt text
        items: List of items from LLM result

    Returns:
        List of detected package discounts with validation results
    """
    detected_discounts = []
    patterns = [
        (r'(\d+)/\$(\d+\.?\d*)', 'quantity/$price'),
        (r'(\d+)\s+for\s+\$(\d+\.?\d*)', 'quantity for $price'),
        (r'(\d+)\s+for\s+(\d+\.?\d*)', 'quantity for price'),
    ]
    raw_text_lower = raw_text.lower()
    for pattern, pattern_type in patterns:
        matches = re.finditer(pattern, raw_text_lower, re.IGNORECASE)
        for match in matches:
            quantity = int(match.group(1))
            price = float(match.group(2))
            matched_items = []
            item_sum = 0.0
            sale_items = [item for item in items if item.get("is_on_sale", False)]
            if len(sale_items) >= quantity:
                candidate_items = sale_items[:quantity]
                candidate_sum = sum(float(item.get("line_total", 0) or 0) for item in candidate_items)
                if abs(candidate_sum - price) <= TOLERANCE:
                    matched_items = candidate_items
                    item_sum = candidate_sum
                elif quantity <= 3:
                    from itertools import combinations
                    for combo in combinations(sale_items, quantity):
                        combo_sum = sum(float(item.get("line_total", 0) or 0) for item in combo)
                        if abs(combo_sum - price) <= TOLERANCE:
                            matched_items = list(combo)
                            item_sum = combo_sum
                            break
            if matched_items:
                detected_discounts.append({
                    "pattern": match.group(0),
                    "pattern_type": pattern_type,
                    "quantity": quantity,
                    "package_price": price,
                    "matched_items": [
                        {"product_name": item.get("product_name"), "line_total": item.get("line_total"), "quantity": item.get("quantity")}
                        for item in matched_items
                    ],
                    "item_sum": round(item_sum, 2),
                    "valid": abs(item_sum - price) <= TOLERANCE
                })
                logger.info(
                    f"Detected package discount: {quantity} for ${price:.2f}, "
                    f"matched {len(matched_items)} items, sum={item_sum:.2f}, valid={abs(item_sum - price) <= TOLERANCE}"
                )
    return detected_discounts


def check_receipt_sums(llm_result: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Check mathematical correctness of receipt."""
    receipt = llm_result.get("receipt", {})
    items = llm_result.get("items", [])
    raw_text = llm_result.get("raw_text", "") or "\n".join(item.get("raw_text", "") for item in items)
    package_discounts = detect_package_price_discounts(raw_text, items)
    check_details = {
        "line_total_sum": None, "subtotal": None, "tax": None, "total": None,
        "line_total_sum_check": None, "subtotal_tax_sum_check": None,
        "package_discounts": package_discounts, "errors": []
    }
    subtotal = receipt.get("subtotal")
    tax = receipt.get("tax") or 0.0
    total = receipt.get("total")
    line_total_sum = 0.0
    deposit_fee_sum = 0.0
    for item in items:
        line_total = item.get("line_total")
        if line_total is not None:
            try:
                line_total_float = float(line_total)
                line_total_sum += line_total_float
                product_name = item.get("product_name", "").lower()
                raw_t = item.get("raw_text", "").lower()
                is_deposit_or_fee = (
                    "bottle deposit" in product_name or "bottle deposit" in raw_t or
                    "env fee" in product_name or "env fee" in raw_t or
                    "environmental fee" in product_name or "environmental fee" in raw_t or
                    "crf" in product_name or "crf" in raw_t
                )
                if is_deposit_or_fee:
                    deposit_fee_sum += line_total_float
            except (ValueError, TypeError):
                pass
    check_details["line_total_sum"] = round(line_total_sum, 2)
    check_details["deposit_fee_sum"] = round(deposit_fee_sum, 2)
    check_details["subtotal"] = float(subtotal) if subtotal is not None else None
    check_details["tax"] = float(tax)
    check_details["total"] = float(total) if total is not None else None
    if subtotal is None:
        if total is not None:
            total_float = float(total)
            line_total_diff = abs(line_total_sum - total_float)
            line_total_check_passed = line_total_diff <= TOLERANCE
            check_details["line_total_sum_check"] = {
                "passed": line_total_check_passed,
                "reason": "subtotal_is_null_using_total",
                "calculated": round(line_total_sum, 2), "expected": round(total_float, 2),
                "difference": round(line_total_diff, 2), "tolerance": TOLERANCE
            }
            check_details["subtotal_tax_sum_check"] = None
            if not line_total_check_passed:
                check_details["errors"].append(
                    f"Line total sum mismatch (subtotal is null): calculated {line_total_sum:.2f}, expected {total_float:.2f}"
                )
                return False, check_details
            return True, check_details
        check_details["errors"].append("Subtotal and total are both null, cannot perform sum check.")
        check_details["line_total_sum_check"] = {"passed": False, "reason": "subtotal_and_total_null", "calculated": line_total_sum, "expected": None}
        return False, check_details
    subtotal_float = float(subtotal)
    product_line_total_sum = line_total_sum - deposit_fee_sum
    line_total_diff = abs(product_line_total_sum - subtotal_float)
    line_total_check_passed = line_total_diff <= TOLERANCE
    if not line_total_check_passed and abs(line_total_sum - subtotal_float) <= TOLERANCE:
        line_total_check_passed = True
    check_details["line_total_sum_check"] = {
        "passed": line_total_check_passed,
        "calculated": round(product_line_total_sum, 2),
        "calculated_with_all_items": round(line_total_sum, 2),
        "expected": round(subtotal_float, 2),
        "deposit_fee_sum": round(deposit_fee_sum, 2),
        "difference": round(line_total_diff, 2), "tolerance": TOLERANCE,
        "note": "Comparing sum of product line_totals (excluding deposits/fees) to subtotal"
    }
    if not line_total_check_passed:
        check_details["errors"].append(f"Line total sum mismatch: calculated {line_total_sum:.2f}, expected {subtotal_float:.2f}")
    if total is None:
        check_details["errors"].append("Total is null, cannot perform sum check.")
        check_details["subtotal_tax_sum_check"] = {"passed": False, "reason": "total_is_null", "calculated": subtotal_float + tax, "expected": None}
        return False, check_details
    total_float = float(total)
    if not line_total_check_passed:
        line_total_plus_tax = line_total_sum + tax
        if abs(line_total_plus_tax - total_float) <= TOLERANCE:
            check_details["subtotal_tax_sum_check"] = {
                "passed": True, "reason": "line_total_sum_plus_tax_equals_total",
                "calculated": round(line_total_plus_tax, 2), "expected": round(total_float, 2),
                "difference": round(abs(line_total_plus_tax - total_float), 2), "tolerance": TOLERANCE
            }
            return True, check_details
    subtotal_plus_tax_plus_fees = subtotal_float + tax + deposit_fee_sum
    total_diff = abs(subtotal_plus_tax_plus_fees - total_float)
    total_check_passed = total_diff <= TOLERANCE
    if not total_check_passed:
        if abs(subtotal_float + tax - total_float) <= TOLERANCE:
            total_check_passed = True
            check_details["subtotal_tax_sum_check"] = {
                "passed": True, "calculated": round(subtotal_float + tax, 2),
                "expected": round(total_float, 2), "deposit_fee_sum": round(deposit_fee_sum, 2),
                "tolerance": TOLERANCE, "formula": "subtotal + tax = total (deposits/fees included in subtotal)"
            }
        else:
            check_details["subtotal_tax_sum_check"] = {
                "passed": False,
                "calculated": round(subtotal_plus_tax_plus_fees, 2),
                "expected": round(total_float, 2),
                "difference": round(total_diff, 2),
                "deposit_fee_sum": round(deposit_fee_sum, 2),
                "tolerance": TOLERANCE,
                "formula": "subtotal + tax + deposits/fees = total"
            }
            check_details["errors"].append(
                f"Total sum mismatch: calculated {subtotal_plus_tax_plus_fees:.2f}, expected {total_float:.2f}"
            )
    else:
        check_details["subtotal_tax_sum_check"] = {
            "passed": True, "calculated": round(subtotal_plus_tax_plus_fees, 2),
            "expected": round(total_float, 2), "difference": round(total_diff, 2),
            "deposit_fee_sum": round(deposit_fee_sum, 2), "tolerance": TOLERANCE,
            "formula": "subtotal + tax + deposits/fees = total"
        }
    is_valid = line_total_check_passed and total_check_passed
    return is_valid, check_details


def apply_field_conflicts_resolution(llm_result: Dict[str, Any]) -> Dict[str, Any]:
    """If sum check passes but field_conflicts has values, replace from_raw_text with from_trusted_hints."""
    tbd = llm_result.get("tbd", {})
    field_conflicts = tbd.get("field_conflicts", {})
    if not field_conflicts:
        return llm_result
    receipt = llm_result.get("receipt", {})
    mapping = {"merchant_name": "merchant_name", "total": "total", "subtotal": "subtotal", "tax": "tax",
               "purchase_date": "purchase_date", "purchase_time": "purchase_time", "currency": "currency",
               "payment_method": "payment_method", "card_last4": "card_last4"}
    resolved_fields = []
    for field_name, conflict_info in field_conflicts.items():
        from_trusted_hints = conflict_info.get("from_trusted_hints")
        if from_trusted_hints is not None:
            receipt_field_name = mapping.get(field_name)
            if receipt_field_name and receipt_field_name in receipt:
                old_value = receipt[receipt_field_name]
                receipt[receipt_field_name] = from_trusted_hints
                resolved_fields.append({"field": field_name, "old_value": old_value, "new_value": from_trusted_hints, "source": "trusted_hints"})
    if resolved_fields:
        tbd["resolved_conflicts"] = resolved_fields
        tbd["field_conflicts"] = {}
        llm_result["tbd"] = tbd
    return llm_result
