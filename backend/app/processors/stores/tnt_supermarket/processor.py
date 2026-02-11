"""
T&T Supermarket: Dedicated processor (US + Canada) and post-processing for LLM path.

- process_tnt_supermarket: Dedicated route for T&T receipts. Runs the generic
  validation pipeline with store_config (tnt_supermarket_us / tnt_supermarket_ca)
  so both T&T US and T&T CA use the same rule-based extraction (regions, items,
  totals, tax/fees, membership).

- clean_tnt_receipt_items: Post-processing when T&T goes through LLM path
  (workflow_processor) - removes membership card and points lines from LLM items.
"""
import re
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def process_tnt_supermarket(
    blocks: List[Dict[str, Any]],
    store_config: Dict[str, Any],
    merchant_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    T&T dedicated processor: run generic validation pipeline with T&T store config.
    Ensures both tnt_supermarket_us and tnt_supermarket_ca go through this route.
    """
    from ...validation.pipeline import _run_generic_validation_pipeline
    return _run_generic_validation_pipeline(
        blocks, {}, store_config, merchant_name
    )


def clean_tnt_receipt_items(llm_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean T&T receipt items by removing membership card and points entries.
    Applies to both T&T US and T&T Canada (same rules).

    Rules:
    1. Remove items with amount = 0.00 and product_name contains membership card patterns
    2. Remove items with product_name containing "Points" and amount = 0.00
    3. Extract membership card number and store in a separate field
    """
    merchant_name = (
        llm_result.get("merchant_name") or llm_result.get("receipt", {}).get("merchant_name", "")
    ).lower()
    is_tnt_receipt = any(
        pattern in merchant_name for pattern in ["t&t", "t & t", "tnt", "t and t"]
    )

    if not is_tnt_receipt:
        logger.debug(f"Not a T&T receipt (merchant: {merchant_name}), skipping T&T cleaning")
        return llm_result

    logger.info(f"Applying T&T receipt cleaning rules for merchant: {merchant_name}")

    items = llm_result.get("items", [])
    if not items:
        logger.warning("No items found in LLM result")
        return llm_result

    removed_items = []
    cleaned_items = []
    membership_number = None

    for item in items:
        product_name = item.get("product_name", "")
        line_total = item.get("line_total", 0)
        try:
            line_total_float = float(line_total.replace("$", "").strip() if isinstance(line_total, str) else line_total)
        except (ValueError, AttributeError, TypeError):
            line_total_float = 0.0

        if line_total_float == 0.0 and _is_membership_card_line(product_name):
            extracted_number = _extract_membership_number(product_name)
            if extracted_number:
                membership_number = extracted_number
                logger.info(f"Extracted membership number: {membership_number}")
            removed_items.append({"product_name": product_name, "reason": "membership_card"})
            continue

        if line_total_float == 0.0 and _is_points_line(product_name):
            removed_items.append({"product_name": product_name, "reason": "points_transaction"})
            continue

        cleaned_items.append(item)

    llm_result["items"] = cleaned_items
    if membership_number:
        llm_result["membership_number"] = membership_number

    logger.info(f"T&T cleaning: Removed {len(removed_items)} items, kept {len(cleaned_items)} items")
    if removed_items:
        for removed in removed_items:
            logger.debug(f"  Removed ({removed['reason']}): {removed['product_name']}")

    return llm_result


def _is_membership_card_line(product_name: str) -> bool:
    if not product_name:
        return False
    product_lower = product_name.lower().strip()
    is_masked_card = bool(re.match(r"^\*{3,}\d{4,}$", product_name.strip()))
    membership_keywords = ["member", "card", "会员", "卡号", "membership", "account"]
    has_long_number = bool(re.search(r"\d{10,}", product_name))
    has_membership_keyword = any(kw in product_lower for kw in membership_keywords)
    has_numbers = bool(re.search(r"\d{4,}", product_name))
    return is_masked_card or has_long_number or (has_membership_keyword and has_numbers)


def _is_points_line(product_name: str) -> bool:
    if not product_name:
        return False
    return any(kw in product_name.lower() for kw in ["points", "point", "积分", "pts"])


def _extract_membership_number(product_name: str) -> Optional[str]:
    if not product_name:
        return None
    masked_match = re.match(r"^(\*{3,}\d{4,})$", product_name.strip())
    if masked_match:
        return masked_match.group(1)
    digit_sequences = re.findall(r"\d{4,}", product_name)
    return max(digit_sequences, key=len) if digit_sequences else None
