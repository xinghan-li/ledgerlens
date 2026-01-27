"""
Sum Checker: Validate mathematical correctness of receipt data.

Validation rules:
1. sum(line_total) ≈ subtotal (tolerance ±0.03)
2. subtotal + tax ≈ total (tolerance ±0.03)
3. If subtotal is null, cannot validate, return requires backup check
4. If tax is null, treat as 0
"""
from typing import Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

TOLERANCE = 0.03  # Error tolerance


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
    
    check_details = {
        "line_total_sum": None,
        "subtotal": None,
        "tax": None,
        "total": None,
        "line_total_sum_check": None,
        "subtotal_tax_sum_check": None,
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
    valid_line_totals = []
    for item in items:
        line_total = item.get("line_total")
        if line_total is not None:
            try:
                line_total_float = float(line_total)
                line_total_sum += line_total_float
                valid_line_totals.append(line_total_float)
            except (ValueError, TypeError):
                pass
    
    check_details["line_total_sum"] = round(line_total_sum, 2)
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
    line_total_diff = abs(line_total_sum - subtotal_float)
    line_total_check_passed = line_total_diff <= TOLERANCE
    
    check_details["line_total_sum_check"] = {
        "passed": line_total_check_passed,
        "calculated": round(line_total_sum, 2),
        "expected": round(subtotal_float, 2),
        "difference": round(line_total_diff, 2),
        "tolerance": TOLERANCE
    }
    
    if not line_total_check_passed:
        error_msg = (
            f"Line total sum mismatch: calculated {line_total_sum:.2f}, "
            f"expected {subtotal_float:.2f}, difference {line_total_diff:.2f} > {TOLERANCE}"
        )
        check_details["errors"].append(error_msg)
        logger.warning(error_msg)
    
    # Check 2: subtotal + tax ≈ total
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
    subtotal_plus_tax = subtotal_float + tax
    total_diff = abs(subtotal_plus_tax - total_float)
    total_check_passed = total_diff <= TOLERANCE
    
    check_details["subtotal_tax_sum_check"] = {
        "passed": total_check_passed,
        "calculated": round(subtotal_plus_tax, 2),
        "expected": round(total_float, 2),
        "difference": round(total_diff, 2),
        "tolerance": TOLERANCE
    }
    
    if not total_check_passed:
        error_msg = (
            f"Total sum mismatch: calculated {subtotal_plus_tax:.2f}, "
            f"expected {total_float:.2f}, difference {total_diff:.2f} > {TOLERANCE}"
        )
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
