"""
Sum Checker: Validate mathematical correctness of receipt data.

All amounts (subtotal, tax, total, line_total) are in CENTS (LLM and pipelines output cents).
Tolerance: max(3 cents, 1% of reference amount) — never use a bare number like 3.
Validation rules:
1. sum(line_total) ≈ subtotal (within tolerance)
2. subtotal + tax ≈ total (within tolerance)
3. If subtotal is null, compare line_total sum to total; if both null, fail
4. If tax is null, treat as 0
5. Package price discounts (e.g., "2/$9.00") are valid if items sum to package price
"""
from typing import Dict, Any, Optional, Tuple, List
import logging
import re

logger = logging.getLogger(__name__)

TOLERANCE_CENTS = 3  # Minimum error tolerance in cents
TOLERANCE_DOLLARS = 0.03  # Minimum in dollars (3 cents); also for package discount in raw text
TOLERANCE_PERCENT = 0.01  # 1% of reference amount (for larger receipts)


def _effective_tolerance(subtotal: Any, total: Any, line_total_sum: float) -> float:
    """
    Return tolerance in the same unit as the amounts: max(3 cents, 1% of reference).
    - Prevents mis-pass when LLM returns dollars but we compare against a literal number.
    - Small receipts: at least 3 cents (0.03 dollars); large: 1% of total/subtotal.
    """
    ref = None
    if total is not None:
        try:
            ref = float(total)
        except (TypeError, ValueError):
            pass
    if ref is None and subtotal is not None:
        try:
            ref = float(subtotal)
        except (TypeError, ValueError):
            pass
    if ref is None:
        ref = line_total_sum
    ref = abs(ref)
    # Values typically < 1000 are dollars; >= 1000 are cents
    if ref < 1000:
        # Dollars: max(0.03, 1% of ref)
        return max(TOLERANCE_DOLLARS, ref * TOLERANCE_PERCENT)
    # Cents: max(3, 1% of ref)
    return max(float(TOLERANCE_CENTS), ref * TOLERANCE_PERCENT)


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
                # line_total is in cents; price from raw text is in dollars
                candidate_sum_cents = sum(float(item.get("line_total", 0) or 0) for item in candidate_items)
                candidate_sum_dollars = candidate_sum_cents / 100.0
                if abs(candidate_sum_dollars - price) <= TOLERANCE_DOLLARS:
                    matched_items = candidate_items
                    item_sum = candidate_sum_dollars
                elif quantity <= 3:
                    from itertools import combinations
                    for combo in combinations(sale_items, quantity):
                        combo_sum_cents = sum(float(item.get("line_total", 0) or 0) for item in combo)
                        combo_sum_dollars = combo_sum_cents / 100.0
                        if abs(combo_sum_dollars - price) <= TOLERANCE_DOLLARS:
                            matched_items = list(combo)
                            item_sum = combo_sum_dollars
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
                    "valid": abs(item_sum - price) <= TOLERANCE_DOLLARS
                })
                logger.info(
                    f"Detected package discount: {quantity} for ${price:.2f}, "
                    f"matched {len(matched_items)} items, sum=${item_sum:.2f}, valid={abs(item_sum - price) <= TOLERANCE_DOLLARS}"
                )
    return detected_discounts


def _extract_receipt_item_count(raw_text: str) -> Optional[int]:
    """Extract expected item count from receipt text (e.g. 'Item count: 9', 'Iten count: 9')."""
    if not raw_text or not isinstance(raw_text, str):
        return None
    patterns = [
        r'item\s*count\s*:?\s*(\d+)',
        r'iten\s*count\s*:?\s*(\d+)',  # OCR typo on T&T
        r'items?\s*:?\s*(\d+)\s*$',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text, re.IGNORECASE | re.MULTILINE)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                continue
    return None


def check_receipt_sums(llm_result: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Check mathematical correctness of receipt."""
    receipt = llm_result.get("receipt", {})
    items = llm_result.get("items", [])
    raw_text = llm_result.get("raw_text", "") or "\n".join(item.get("raw_text", "") for item in items)
    package_discounts = detect_package_price_discounts(raw_text, items)
    check_details = {
        "line_total_sum": None, "subtotal": None, "tax": None, "total": None,
        "line_total_sum_check": None, "subtotal_tax_sum_check": None,
        "package_discounts": package_discounts, "errors": [],
        "item_count_check": None,
    }
    # Item count: if receipt states "Item count: N" and we have fewer than N items, fail (missing items)
    actual_item_count = len([i for i in items if (i.get("product_name") or i.get("line_total"))])
    expected_item_count = _extract_receipt_item_count(raw_text)
    if expected_item_count is not None:
        item_count_passed = actual_item_count >= expected_item_count
        check_details["item_count_check"] = {
            "passed": item_count_passed,
            "expected": expected_item_count,
            "actual": actual_item_count,
            "reason": "fewer_items_than_receipt" if actual_item_count < expected_item_count else "ok",
        }
        if actual_item_count < expected_item_count:
            check_details["errors"].append(
                f"Item count mismatch: receipt states {expected_item_count} items, only {actual_item_count} parsed (missing items)"
            )
    subtotal = receipt.get("subtotal")
    tax = receipt.get("tax") or 0.0
    total = receipt.get("total")
    line_total_sum = 0.0
    deposit_fee_sum = 0.0
    reward_credit_sum = 0.0  # CC Rewards etc. (negative line); excluded when comparing to pre-reward subtotal
    for item in items:
        line_total = item.get("line_total")
        if line_total is not None:
            try:
                line_total_float = float(line_total)
                line_total_sum += line_total_float
                product_name = (item.get("product_name") or "").lower()
                raw_t = (item.get("raw_text") or "").lower()
                is_deposit_or_fee = (
                    "bottle deposit" in product_name or "bottle deposit" in raw_t or
                    "env fee" in product_name or "env fee" in raw_t or
                    "environmental fee" in product_name or "environmental fee" in raw_t or
                    "crf" in product_name or "crf" in raw_t
                )
                is_reward = (
                    "cc reward" in product_name or "cc reward" in raw_t or
                    "credit card reward" in product_name or "credit card reward" in raw_t or
                    line_total_float < 0
                )
                if is_deposit_or_fee:
                    deposit_fee_sum += line_total_float
                elif is_reward:
                    reward_credit_sum += line_total_float
            except (ValueError, TypeError):
                pass
    check_details["line_total_sum"] = round(line_total_sum, 2)
    check_details["deposit_fee_sum"] = round(deposit_fee_sum, 2)
    check_details["subtotal"] = float(subtotal) if subtotal is not None else None
    check_details["tax"] = float(tax)
    check_details["total"] = float(total) if total is not None else None
    # Costco USA CC Rewards: receipt.subtotal/total are set to pre-reward total; items include reward (negative). Compare to sum of products only.
    is_costco_usa = "costco" in (receipt.get("merchant_name") or receipt.get("store") or "").lower() and "canada" not in (receipt.get("country") or "").lower()
    if is_costco_usa and reward_credit_sum < 0:
        product_line_total_sum = line_total_sum - deposit_fee_sum - reward_credit_sum  # = sum of positive product items
    else:
        product_line_total_sum = line_total_sum - deposit_fee_sum
    # Programmatic totals from items only (for UI to show "computed sum" vs "model subtotal/total" — never trust model numbers alone).
    tax_float = float(tax)
    check_details["subtotal_computed_from_items"] = round(product_line_total_sum, 2)
    check_details["total_expected_from_items_plus_tax"] = round(product_line_total_sum + tax_float, 2)
    if subtotal is None:
        if total is not None:
            total_float = float(total)
            tol = _effective_tolerance(subtotal, total, line_total_sum)
            # When subtotal is null, total usually includes tax: check line_total_sum + tax ≈ total
            line_total_plus_tax = line_total_sum + tax_float
            line_total_diff = abs(line_total_plus_tax - total_float)
            line_total_check_passed = line_total_diff <= tol
            check_details["line_total_sum_check"] = {
                "passed": line_total_check_passed,
                "reason": "subtotal_is_null_compare_items_plus_tax_to_total",
                "calculated": round(line_total_plus_tax, 2),
                "line_total_sum": round(line_total_sum, 2),
                "tax": round(tax_float, 2),
                "expected": round(total_float, 2),
                "difference": round(line_total_diff, 2),
                "tolerance": tol,
            }
            check_details["subtotal_tax_sum_check"] = None
            if not line_total_check_passed:
                check_details["errors"].append(
                    f"Line total sum + tax mismatch (subtotal is null): calculated {line_total_plus_tax:.2f}, expected {total_float:.2f}"
                )
                return False, check_details
            return True, check_details
        check_details["errors"].append("Subtotal and total are both null, cannot perform sum check.")
        check_details["line_total_sum_check"] = {"passed": False, "reason": "subtotal_and_total_null", "calculated": line_total_sum, "expected": None}
        return False, check_details
    subtotal_float = float(subtotal)
    total_float = float(total) if total is not None else None
    tol = _effective_tolerance(subtotal, total, line_total_sum)
    line_total_diff = abs(product_line_total_sum - subtotal_float)
    line_total_check_passed = line_total_diff <= tol
    if not line_total_check_passed and abs(line_total_sum - subtotal_float) <= tol:
        line_total_check_passed = True
    check_details["line_total_sum_check"] = {
        "passed": line_total_check_passed,
        "calculated": round(product_line_total_sum, 2),
        "calculated_with_all_items": round(line_total_sum, 2),
        "expected": round(subtotal_float, 2),
        "deposit_fee_sum": round(deposit_fee_sum, 2),
        "difference": round(line_total_diff, 2), "tolerance": tol,
        "note": "Comparing sum of product line_totals (excluding deposits/fees) to subtotal"
    }
    if not line_total_check_passed:
        check_details["errors"].append(f"Line total sum mismatch: calculated {line_total_sum:.2f}, expected {subtotal_float:.2f}")
    if total is None:
        check_details["errors"].append("Total is null, cannot perform sum check.")
        check_details["subtotal_tax_sum_check"] = {"passed": False, "reason": "total_is_null", "calculated": subtotal_float + tax, "expected": None}
        return False, check_details
    if total_float is None:
        total_float = float(total)
    if not line_total_check_passed:
        line_total_plus_tax = line_total_sum + tax
        if abs(line_total_plus_tax - total_float) <= tol:
            check_details["subtotal_tax_sum_check"] = {
                "passed": True, "reason": "line_total_sum_plus_tax_equals_total",
                "calculated": round(line_total_plus_tax, 2), "expected": round(total_float, 2),
                "difference": round(abs(line_total_plus_tax - total_float), 2), "tolerance": tol
            }
            return True, check_details
    subtotal_plus_tax_plus_fees = subtotal_float + tax + deposit_fee_sum
    total_diff = abs(subtotal_plus_tax_plus_fees - total_float)
    total_check_passed = total_diff <= tol
    if not total_check_passed:
        if abs(subtotal_float + tax - total_float) <= tol:
            total_check_passed = True
            check_details["subtotal_tax_sum_check"] = {
                "passed": True, "calculated": round(subtotal_float + tax, 2),
                "expected": round(total_float, 2), "deposit_fee_sum": round(deposit_fee_sum, 2),
                "tolerance": tol, "formula": "subtotal + tax = total (deposits/fees included in subtotal)"
            }
        else:
            check_details["subtotal_tax_sum_check"] = {
                "passed": False,
                "calculated": round(subtotal_plus_tax_plus_fees, 2),
                "expected": round(total_float, 2),
                "difference": round(total_diff, 2),
                "deposit_fee_sum": round(deposit_fee_sum, 2),
                "tolerance": tol,
                "formula": "subtotal + tax + deposits/fees = total"
            }
            check_details["errors"].append(
                f"Total sum mismatch: calculated {subtotal_plus_tax_plus_fees:.2f}, expected {total_float:.2f}"
            )
    else:
        check_details["subtotal_tax_sum_check"] = {
            "passed": True, "calculated": round(subtotal_plus_tax_plus_fees, 2),
            "expected": round(total_float, 2), "difference": round(total_diff, 2),
            "deposit_fee_sum": round(deposit_fee_sum, 2), "tolerance": tol,
            "formula": "subtotal + tax + deposits/fees = total"
        }
    is_valid = line_total_check_passed and total_check_passed
    # Fail if receipt states item count and we parsed fewer items (missing lines → needs_review)
    item_count_info = check_details.get("item_count_check")
    if item_count_info and item_count_info.get("passed") is False:
        is_valid = False
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
        if not isinstance(conflict_info, dict):
            continue
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
