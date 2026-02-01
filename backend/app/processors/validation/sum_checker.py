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
        List of detected package discounts with validation results:
        [
            {
                "pattern": "2/$9.00",
                "quantity": 2,
                "package_price": 9.00,
                "matched_items": [...],  # Items that match this discount
                "item_sum": 9.00,  # Sum of matched items' line_totals
                "valid": True/False  # Whether item_sum matches package_price
            }
        ]
    """
    detected_discounts = []
    
    # Pattern: "2/$9.00", "2 for $9.00", "3/$10", etc.
    patterns = [
        (r'(\d+)/\$(\d+\.?\d*)', 'quantity/$price'),  # "2/$9.00"
        (r'(\d+)\s+for\s+\$(\d+\.?\d*)', 'quantity for $price'),  # "2 for $9.00"
        (r'(\d+)\s+for\s+(\d+\.?\d*)', 'quantity for price'),  # "2 for 9.00"
    ]
    
    raw_text_lower = raw_text.lower()
    
    for pattern, pattern_type in patterns:
        matches = re.finditer(pattern, raw_text_lower, re.IGNORECASE)
        for match in matches:
            quantity = int(match.group(1))
            price = float(match.group(2))
            
            # Find items that might be part of this package deal
            # Look for items with similar product names or nearby items
            matched_items = []
            item_sum = 0.0
            
            # Simple heuristic: if we have exactly `quantity` items with is_on_sale=True,
            # and their sum is close to `price`, they might be the package deal
            sale_items = [item for item in items if item.get("is_on_sale", False)]
            
            if len(sale_items) >= quantity:
                # Try to find a combination of items that sum to the package price
                # For simplicity, take the first `quantity` sale items
                candidate_items = sale_items[:quantity]
                candidate_sum = sum(float(item.get("line_total", 0) or 0) for item in candidate_items)
                
                if abs(candidate_sum - price) <= TOLERANCE:
                    matched_items = candidate_items
                    item_sum = candidate_sum
                else:
                    # Try all combinations (for small quantities)
                    if quantity <= 3:
                        from itertools import combinations
                        for combo in combinations(sale_items, quantity):
                            combo_sum = sum(float(item.get("line_total", 0) or 0) for item in combo)
                            if abs(combo_sum - price) <= TOLERANCE:
                                matched_items = list(combo)
                                item_sum = combo_sum
                                break
            
            # If we found matching items, record the discount
            if matched_items:
                detected_discounts.append({
                    "pattern": match.group(0),
                    "pattern_type": pattern_type,
                    "quantity": quantity,
                    "package_price": price,
                    "matched_items": [
                        {
                            "product_name": item.get("product_name"),
                            "line_total": item.get("line_total"),
                            "quantity": item.get("quantity")
                        }
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
    """
    Check mathematical correctness of receipt.
    
    Args:
        llm_result: Complete JSON result returned by LLM
        
    Returns:
        (is_valid, check_details):
        - is_valid: True if all checks pass, False otherwise
        - check_details: Dictionary containing detailed check results
    """
    receipt = llm_result.get("receipt", {})
    items = llm_result.get("items", [])
    
    # Get raw_text for package discount detection
    raw_text = ""
    if "raw_text" in llm_result:
        raw_text = llm_result["raw_text"]
    elif items:
        # Try to reconstruct from items' raw_text
        raw_text = "\n".join(item.get("raw_text", "") for item in items)
    
    # Detect package price discounts
    package_discounts = detect_package_price_discounts(raw_text, items)
    
    check_details = {
        "line_total_sum": None,
        "subtotal": None,
        "tax": None,
        "total": None,
        "line_total_sum_check": None,
        "subtotal_tax_sum_check": None,
        "package_discounts": package_discounts,
        "errors": []
    }
    
    # Extract values
    subtotal = receipt.get("subtotal")
    tax = receipt.get("tax")
    total = receipt.get("total")
    
    # If tax is null, treat as 0
    if tax is None:
        tax = 0.0
        logger.debug("Tax is null, treating as 0")
    
    # Calculate sum of all line_total
    line_total_sum = 0.0
    deposit_fee_sum = 0.0  # Sum of bottle deposits and environment fees
    valid_line_totals = []
    
    for item in items:
        line_total = item.get("line_total")
        if line_total is not None:
            try:
                line_total_float = float(line_total)
                line_total_sum += line_total_float
                valid_line_totals.append(line_total_float)
                
                # Check if this item is a bottle deposit or environment fee
                product_name = item.get("product_name", "").lower()
                raw_text = item.get("raw_text", "").lower()
                
                # Identify deposit/fee items
                is_deposit_or_fee = (
                    "bottle deposit" in product_name or
                    "bottle deposit" in raw_text or
                    "env fee" in product_name or
                    "env fee" in raw_text or
                    "environmental fee" in product_name or
                    "environmental fee" in raw_text or
                    "crf" in product_name.lower() or
                    "crf" in raw_text.lower()
                )
                
                if is_deposit_or_fee:
                    deposit_fee_sum += line_total_float
                    logger.debug(f"Found deposit/fee item: {product_name} = {line_total_float}")
            except (ValueError, TypeError):
                pass
    
    check_details["line_total_sum"] = round(line_total_sum, 2)
    check_details["deposit_fee_sum"] = round(deposit_fee_sum, 2)
    check_details["subtotal"] = float(subtotal) if subtotal is not None else None
    check_details["tax"] = float(tax)
    check_details["total"] = float(total) if total is not None else None
    
    # Check 1: If subtotal is null, use alternative validation
    if subtotal is None:
        # Alternative validation: line_total_sum should equal total
        # This handles cases where subtotal is not explicitly stated
        if total is not None:
            total_float = float(total)
            line_total_diff = abs(line_total_sum - total_float)
            line_total_check_passed = line_total_diff <= TOLERANCE
            
            check_details["line_total_sum_check"] = {
                "passed": line_total_check_passed,
                "reason": "subtotal_is_null_using_total",
                "calculated": round(line_total_sum, 2),
                "expected": round(total_float, 2),
                "difference": round(line_total_diff, 2),
                "tolerance": TOLERANCE
            }
            
            check_details["subtotal_tax_sum_check"] = None
            
            if not line_total_check_passed:
                error_msg = (
                    f"Line total sum mismatch (subtotal is null, comparing to total): "
                    f"calculated {line_total_sum:.2f}, expected {total_float:.2f}, "
                    f"difference {line_total_diff:.2f} > {TOLERANCE}"
                )
                check_details["errors"].append(error_msg)
                logger.warning(error_msg)
                return False, check_details
            else:
                logger.info("Sum check passed using line_total_sum = total (subtotal is null)")
                return True, check_details
        else:
            # Both subtotal and total are null - cannot validate
            error_msg = "Subtotal and total are both null, cannot perform sum check. Requires backup check."
            check_details["errors"].append(error_msg)
            logger.warning(error_msg)
            check_details["line_total_sum_check"] = {
                "passed": False,
                "reason": "subtotal_and_total_null",
                "calculated": line_total_sum,
                "expected": None
            }
            return False, check_details
    
    subtotal_float = float(subtotal)
    
    # Check 1: sum(line_total) ≈ subtotal
    # IMPORTANT: line_total_sum should equal subtotal (not total)
    # If deposits/fees are included in line items, they should also be in subtotal calculation
    # But typically: subtotal = sum of product line_totals (excluding deposits/fees)
    # So we need to check: sum(product line_totals) ≈ subtotal
    
    # Calculate sum of product line_totals (excluding deposits/fees)
    product_line_total_sum = line_total_sum - deposit_fee_sum
    
    # Primary check: product line_totals should match subtotal
    line_total_diff = abs(product_line_total_sum - subtotal_float)
    line_total_check_passed = line_total_diff <= TOLERANCE
    
    # If that doesn't match, try including deposits/fees (some receipts include them in subtotal)
    if not line_total_check_passed:
        line_total_diff_with_fees = abs(line_total_sum - subtotal_float)
        if line_total_diff_with_fees <= TOLERANCE:
            # Subtotal includes deposits/fees
            line_total_check_passed = True
            logger.info(
                f"Line total sum (including deposits/fees) matches subtotal: "
                f"{line_total_sum:.2f} = {subtotal_float:.2f}"
            )
    
    # Record check details
    check_details["line_total_sum_check"] = {
        "passed": line_total_check_passed,
        "calculated": round(product_line_total_sum, 2),
        "calculated_with_all_items": round(line_total_sum, 2),
        "expected": round(subtotal_float, 2),
        "deposit_fee_sum": round(deposit_fee_sum, 2),
        "difference": round(line_total_diff, 2),
        "tolerance": TOLERANCE,
        "note": "Comparing sum of product line_totals (excluding deposits/fees) to subtotal"
    }
    
    if not line_total_check_passed:
        error_msg = (
            f"Line total sum mismatch: calculated {line_total_sum:.2f}, "
            f"expected {subtotal_float:.2f}, difference {line_total_diff:.2f} > {TOLERANCE}"
        )
        if deposit_fee_sum > 0:
            error_msg += f" (deposits/fees: {deposit_fee_sum:.2f})"
        check_details["errors"].append(error_msg)
        logger.warning(error_msg)
    
    # Check 2: subtotal + tax ≈ total (or line_total_sum + tax ≈ total if line_total_sum ≠ subtotal)
    if total is None:
        error_msg = "Total is null, cannot perform sum check."
        check_details["errors"].append(error_msg)
        check_details["subtotal_tax_sum_check"] = {
            "passed": False,
            "reason": "total_is_null",
            "calculated": subtotal_float + tax,
            "expected": None
        }
        return False, check_details
    
    total_float = float(total)
    
    # If line_total_sum doesn't match subtotal, try using line_total_sum + tax instead
    # This handles cases where subtotal calculation differs from sum of line items
    # but line_total_sum + tax still equals total (e.g., due to rounding, discounts, etc.)
    if not line_total_check_passed:
        # Try alternative: line_total_sum + tax ≈ total
        line_total_plus_tax = line_total_sum + tax
        total_diff_alt = abs(line_total_plus_tax - total_float)
        total_check_passed_alt = total_diff_alt <= TOLERANCE
        
        if total_check_passed_alt:
            # Alternative check passed: line_total_sum + tax = total
            logger.info(
                f"Line total sum doesn't match subtotal, but line_total_sum + tax = total: "
                f"{line_total_sum:.2f} + {tax:.2f} = {line_total_plus_tax:.2f} ≈ {total_float:.2f}"
            )
            check_details["subtotal_tax_sum_check"] = {
                "passed": True,
                "reason": "line_total_sum_plus_tax_equals_total",
                "calculated": round(line_total_plus_tax, 2),
                "expected": round(total_float, 2),
                "difference": round(total_diff_alt, 2),
                "tolerance": TOLERANCE,
                "note": "Used line_total_sum + tax instead of subtotal + tax"
            }
            # If alternative check passes, we can still pass overall validation
            # because the math is correct (line_total_sum + tax = total)
            is_valid = total_check_passed_alt
            if is_valid:
                logger.info("Sum check passed using alternative: line_total_sum + tax = total")
                return True, check_details
        else:
            # Alternative also failed, continue with normal check
            logger.warning(
                f"Alternative check also failed: line_total_sum + tax = {line_total_plus_tax:.2f}, "
                f"expected {total_float:.2f}, difference {total_diff_alt:.2f}"
            )
    
    # Check 2: subtotal + tax + deposits/fees ≈ total
    # This is the correct formula: start from subtotal, add tax, add deposits/fees, should equal total
    subtotal_plus_tax_plus_fees = subtotal_float + tax + deposit_fee_sum
    total_diff = abs(subtotal_plus_tax_plus_fees - total_float)
    total_check_passed = total_diff <= TOLERANCE
    
    if total_check_passed:
        logger.info(
            f"Total check passed: {subtotal_float:.2f} + {tax:.2f} + {deposit_fee_sum:.2f} = {subtotal_plus_tax_plus_fees:.2f} ≈ {total_float:.2f}"
        )
        check_details["subtotal_tax_sum_check"] = {
            "passed": True,
            "calculated": round(subtotal_plus_tax_plus_fees, 2),
            "expected": round(total_float, 2),
            "difference": round(total_diff, 2),
            "deposit_fee_sum": round(deposit_fee_sum, 2),
            "tolerance": TOLERANCE,
            "formula": "subtotal + tax + deposits/fees = total"
        }
    else:
        # If failed, also try without deposits/fees (in case they're already in subtotal)
        subtotal_plus_tax = subtotal_float + tax
        total_diff_no_fees = abs(subtotal_plus_tax - total_float)
        if total_diff_no_fees <= TOLERANCE:
            total_check_passed = True
            logger.info(
                f"Total check passed (deposits/fees included in subtotal): "
                f"{subtotal_float:.2f} + {tax:.2f} = {subtotal_plus_tax:.2f} ≈ {total_float:.2f}"
            )
            check_details["subtotal_tax_sum_check"] = {
                "passed": True,
                "calculated": round(subtotal_plus_tax, 2),
                "calculated_with_fees": round(subtotal_plus_tax_plus_fees, 2),
                "expected": round(total_float, 2),
                "difference": round(total_diff, 2),
                "difference_no_fees": round(total_diff_no_fees, 2),
                "deposit_fee_sum": round(deposit_fee_sum, 2),
                "tolerance": TOLERANCE,
                "formula": "subtotal + tax = total (deposits/fees included in subtotal)"
            }
        else:
            check_details["subtotal_tax_sum_check"] = {
                "passed": False,
                "calculated": round(subtotal_plus_tax_plus_fees, 2),
                "calculated_no_fees": round(subtotal_plus_tax, 2),
                "expected": round(total_float, 2),
                "difference": round(total_diff, 2),
                "difference_no_fees": round(total_diff_no_fees, 2),
                "deposit_fee_sum": round(deposit_fee_sum, 2),
                "tolerance": TOLERANCE,
                "formula": "subtotal + tax + deposits/fees = total"
            }
            error_msg = (
                f"Total sum mismatch: calculated {subtotal_plus_tax_plus_fees:.2f} "
                f"(subtotal {subtotal_float:.2f} + tax {tax:.2f} + fees {deposit_fee_sum:.2f}), "
                f"expected {total_float:.2f}, difference {total_diff:.2f} > {TOLERANCE}"
            )
            # If there's a small unaccounted difference, suggest it might be a fee
            if 0 < total_diff <= 0.10:  # Small difference (likely a fee)
                error_msg += f" (Possible unaccounted fee/deposit: ${total_diff:.2f})"
                logger.warning(f"{error_msg}. Consider checking OCR text for hidden fees.")
            check_details["errors"].append(error_msg)
            logger.warning(error_msg)
    
    # All checks passed
    is_valid = line_total_check_passed and total_check_passed
    
    if is_valid:
        logger.info("Sum check passed: all calculations match")
    else:
        logger.warning(f"Sum check failed: {len(check_details['errors'])} errors")
    
    return is_valid, check_details


def apply_field_conflicts_resolution(llm_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    If sum check passes but field_conflicts has values, replace from_raw_text with from_trusted_hints.
    
    Args:
        llm_result: Complete JSON result returned by LLM
        
    Returns:
        Corrected JSON result
    """
    tbd = llm_result.get("tbd", {})
    field_conflicts = tbd.get("field_conflicts", {})
    
    if not field_conflicts:
        return llm_result
    
    receipt = llm_result.get("receipt", {})
    resolved_fields = []
    
    # Iterate all conflict fields, replace with trusted_hints
    for field_name, conflict_info in field_conflicts.items():
        from_trusted_hints = conflict_info.get("from_trusted_hints")
        
        # If from_trusted_hints is not None/empty, replace
        if from_trusted_hints is not None:
            # Map field name (field name in tbd may differ from receipt)
            receipt_field_name = _map_conflict_field_to_receipt_field(field_name)
            
            if receipt_field_name and receipt_field_name in receipt:
                old_value = receipt[receipt_field_name]
                receipt[receipt_field_name] = from_trusted_hints
                resolved_fields.append({
                    "field": field_name,
                    "old_value": old_value,
                    "new_value": from_trusted_hints,
                    "source": "trusted_hints"
                })
                logger.info(f"Resolved field conflict: {field_name} = {from_trusted_hints} (was {old_value})")
    
    # Update tbd, mark resolved conflicts
    if resolved_fields:
        tbd["resolved_conflicts"] = resolved_fields
        # Clear field_conflicts (resolved)
        tbd["field_conflicts"] = {}
        llm_result["tbd"] = tbd
    
    return llm_result


def _map_conflict_field_to_receipt_field(conflict_field: str) -> Optional[str]:
    """Map field names in tbd.field_conflicts to field names in receipt."""
    mapping = {
        "merchant_name": "merchant_name",
        "total": "total",
        "subtotal": "subtotal",
        "tax": "tax",
        "purchase_date": "purchase_date",
        "purchase_time": "purchase_time",
        "currency": "currency",
        "payment_method": "payment_method",
        "card_last4": "card_last4",
    }
    return mapping.get(conflict_field)
