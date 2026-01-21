"""
Sum Checker: 验证收据数据的数学正确性。

验证规则：
1. sum(line_total) ≈ subtotal（误差容忍度 ±0.03）
2. subtotal + tax ≈ total（误差容忍度 ±0.03）
3. 如果 subtotal 为 null，无法验证，返回需要 backup check
4. 如果 tax 为 null，视为 0
"""
from typing import Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

TOLERANCE = 0.03  # 误差容忍度


def check_receipt_sums(llm_result: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    检查收据的数学正确性。
    
    Args:
        llm_result: LLM 返回的完整 JSON 结果
        
    Returns:
        (is_valid, check_details):
        - is_valid: True 如果所有检查通过，False 否则
        - check_details: 包含详细检查结果的字典
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
    
    # 提取值
    subtotal = receipt.get("subtotal")
    tax = receipt.get("tax")
    total = receipt.get("total")
    
    # 如果 tax 为 null，视为 0
    if tax is None:
        tax = 0.0
        logger.debug("Tax is null, treating as 0")
    
    # 计算所有 line_total 的总和
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
    
    # 检查 1: 如果 subtotal 为 null，无法验证，需要 backup check
    if subtotal is None:
        error_msg = "Subtotal is null, cannot perform sum check. Requires backup check."
        check_details["errors"].append(error_msg)
        logger.warning(error_msg)
        check_details["line_total_sum_check"] = {
            "passed": False,
            "reason": "subtotal_is_null",
            "calculated": line_total_sum,
            "expected": None
        }
        return False, check_details
    
    subtotal_float = float(subtotal)
    
    # 检查 1: sum(line_total) ≈ subtotal
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
    
    # 检查 2: subtotal + tax ≈ total
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
    
    # 所有检查都通过
    is_valid = line_total_check_passed and total_check_passed
    
    if is_valid:
        logger.info("Sum check passed: all calculations match")
    else:
        logger.warning(f"Sum check failed: {len(check_details['errors'])} errors")
    
    return is_valid, check_details


def apply_field_conflicts_resolution(llm_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    如果 sum check 通过但 field_conflicts 有值，用 from_trusted_hints 替代 from_raw_text。
    
    Args:
        llm_result: LLM 返回的完整 JSON 结果
        
    Returns:
        修正后的 JSON 结果
    """
    tbd = llm_result.get("tbd", {})
    field_conflicts = tbd.get("field_conflicts", {})
    
    if not field_conflicts:
        return llm_result
    
    receipt = llm_result.get("receipt", {})
    resolved_fields = []
    
    # 遍历所有冲突字段，用 trusted_hints 替代
    for field_name, conflict_info in field_conflicts.items():
        from_trusted_hints = conflict_info.get("from_trusted_hints")
        
        # 如果 from_trusted_hints 不为 None/空，则替代
        if from_trusted_hints is not None:
            # 映射字段名（tbd 中的字段名可能和 receipt 中的不同）
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
    
    # 更新 tbd，标记已解决的冲突
    if resolved_fields:
        tbd["resolved_conflicts"] = resolved_fields
        # 清空 field_conflicts（已解决）
        tbd["field_conflicts"] = {}
        llm_result["tbd"] = tbd
    
    return llm_result


def _map_conflict_field_to_receipt_field(conflict_field: str) -> Optional[str]:
    """将 tbd.field_conflicts 中的字段名映射到 receipt 中的字段名。"""
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
