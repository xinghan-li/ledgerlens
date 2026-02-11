"""
Receipt Processing Pipeline: Complete pipeline using row-based approach.

Supports optional store_config (from config-driven pipeline) for wash_data,
region markers, and section headers.
"""
from typing import List, Dict, Any, Tuple, Optional
import logging
import re
from dataclasses import replace
from .receipt_structures import (
    TextBlock, PhysicalRow, ReceiptRegions, AmountColumns,
    AmountUsageTracker, ExtractedItem, TotalsSequence
)
from .row_reconstructor import build_physical_rows
from .column_detector import detect_amount_columns
from .skew_corrector import correct_skew
from .region_splitter import split_regions
from .item_extractor import extract_items, extract_fees_from_items_region
from .totals_extractor import find_subtotal_and_total, collect_middle_amounts
from .tax_fee_classifier import extract_tax_and_fees
from .math_validator import validate_item_math, validate_totals
from ...utils.float_precision import truncate_floats_in_result

logger = logging.getLogger(__name__)


def _rows_to_block_list(rows: List[PhysicalRow]) -> List[Dict[str, Any]]:
    """Serialize region rows for console log: list of {row_id, blocks: [{x, y, is_amount, text}, ...]}."""
    out = []
    for r in rows:
        out.append({
            "row_id": r.row_id,
            "blocks": [
                {
                    "x": int(b.center_x * 10000),
                    "y": int(b.center_y * 10000),
                    "is_amount": b.is_amount and b.amount is not None,
                    "text": (b.text or "")[:120],
                }
                for b in r.blocks
            ],
        })
    return out


def _wash_blocks(text_blocks: List[TextBlock], store_config: Dict[str, Any]) -> List[TextBlock]:
    """
    Apply store config wash_data: clear is_amount for blocks matching amount_exclude_patterns.
    """
    wash = store_config.get("wash_data", {}) or {}
    patterns = wash.get("amount_exclude_patterns", [])
    if not patterns:
        return text_blocks
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, re.IGNORECASE))
        except re.error:
            logger.debug(f"Invalid wash pattern skipped: {p}")
    if not compiled:
        return text_blocks
    out = []
    for b in text_blocks:
        if not b.is_amount:
            out.append(b)
            continue
        text = (b.text or "").strip()
        if any(rx.search(text) for rx in compiled):
            out.append(replace(b, is_amount=False, amount=None))
            logger.debug(f"Washed block (no longer amount): {text[:50]}")
        else:
            out.append(b)
    return out


def _detect_duplicate_bbox_blocks(text_blocks: List[TextBlock]) -> List[str]:
    """
    Detect blocks with identical bounding boxes (OCR error: e.g. /lb same bbox as JAPANESE SWEET POTATO).
    Escalate to error_log for LLM to handle.
    """
    errors = []
    eps = 1e-6
    seen: Dict[Tuple[float, float, float, float], List[str]] = {}
    for b in text_blocks:
        key = (round(b.x, 6), round(b.y, 6), round(b.width or 0, 6), round(b.height or 0, 6))
        if key not in seen:
            seen[key] = []
        seen[key].append((b.text or "").strip())
    for key, texts in seen.items():
        if len(texts) > 1:
            unique = list(dict.fromkeys(texts))  # preserve order, dedupe
            errors.append(f"Duplicate bbox with same coordinates: {unique}")
            logger.warning(f"[Pipeline] Duplicate bbox detected: {unique}")
    return errors


def _compute_average_half_line_height(blocks: List[Dict[str, Any]]) -> float:
    """
    Compute average half-line height from all blocks with height info.
    Returns average(block.height) * 0.5, or fallback 0.006 if no height data.
    """
    heights = [b.get("height") for b in blocks if b.get("height") and b.get("height") > 0]
    if not heights:
        return 0.006  # Fallback
    avg_height = sum(heights) / len(heights)
    half_line = avg_height * 0.5
    logger.info(f"Computed dynamic half-line tolerance: {half_line:.5f} (avg height={avg_height:.5f})")
    return half_line


def _run_generic_validation_pipeline(
    blocks: List[Dict[str, Any]],
    llm_result: Dict[str, Any],
    store_config: Optional[Dict[str, Any]],
    merchant_name: Optional[str],
) -> Dict[str, Any]:
    """
    Run the generic (non-Costco) validation pipeline: wash → skew → rows → columns
    → regions → items → totals → tax/fees → validation. Used by both the default
    path and the T&T dedicated processor.
    """
    # Step 0a: Compute dynamic half-line tolerance from average block height
    half_line_tolerance = _compute_average_half_line_height(blocks)
    
    # Step 0: Convert blocks to TextBlock objects
    text_blocks = [
        TextBlock.from_dict(block, block_id=i)
        for i, block in enumerate(blocks)
    ]
    logger.info(f"Step 0: Converted {len(text_blocks)} blocks to TextBlock objects")

    # Step 0b: Apply store config wash_data (exclude SC-1, Points, etc. from amounts)
    if store_config:
        text_blocks = _wash_blocks(text_blocks, store_config)
        logger.info(f"Step 0b: Applied store config wash_data (chain_id={store_config.get('chain_id', '')})")

    # Step 0c: Skew correction using reference rows (date+cashier top, transaction+terminal bottom)
    skew_error_log: List[str] = []
    if store_config:
        text_blocks, skew_error_log = correct_skew(text_blocks, half_line_tolerance, store_config)
        if skew_error_log:
            logger.warning(f"Step 0c: Skew correction applied with warnings: {skew_error_log}")

    # Step 0d: Detect duplicate bbox (OCR error), escalate to error_log for LLM
    duplicate_bbox_errors = _detect_duplicate_bbox_blocks(text_blocks)

    # Step 1: Build physical rows
    rows = build_physical_rows(text_blocks)
    logger.info(f"Step 1: Built {len(rows)} physical rows")
    
    # Step 2: Detect amount columns
    amount_columns = detect_amount_columns(text_blocks)
    logger.info(f"Step 2: Detected main amount column at X={amount_columns.main_column.center_x:.4f}")
    
    # Step 3: Split regions (optionally using store config markers)
    regions = split_regions(rows, store_config=store_config)
    logger.info(f"Step 3: Split into regions: {len(regions.item_rows)} items, {len(regions.totals_rows)} totals")

    # Step 4: Extract items (optionally using store config section_headers)
    tracker = AmountUsageTracker()
    extract_error_log: List[str] = []
    items = extract_items(
        regions, amount_columns, tracker,
        store_config=store_config, half_line_tolerance=half_line_tolerance,
        error_log=extract_error_log
    )
    logger.info(f"Step 4: Extracted {len(items)} items")
    
    # Step 5: Find subtotal and total, then collect middle amounts
    totals_sequence = find_subtotal_and_total(regions, amount_columns, tracker)
    totals_sequence = collect_middle_amounts(regions, totals_sequence, amount_columns, tracker)
    logger.info(f"Step 5: Found {len(totals_sequence.middle_amounts)} middle amounts")
    
    # Step 6: Classify and extract tax and fees
    tax_list, fees = extract_tax_and_fees(totals_sequence, tracker)
    total_tax = sum(t["amount"] for t in tax_list)
    logger.info(f"Step 6: Extracted tax=${total_tax:.2f} ({len(tax_list)} tax lines), {len(fees)} fees")

    # Step 6b: Extract fees from items region (BC only: Bottle deposit, Env fee)
    fees_from_items = []
    if store_config:
        fees_from_items = extract_fees_from_items_region(
            regions, amount_columns, store_config
        )
        if fees_from_items:
            logger.info(f"Step 6b: Extracted {len(fees_from_items)} fees from items region (BC): {[f['label'] for f in fees_from_items]}")
            fees = fees + fees_from_items

    # Step 7: Validate math
    # Validate each item's math
    for item in items:
        # Find the row for this item
        item_row = next((r for r in regions.item_rows if r.row_id == item.row_id), None)
        if item_row:
            validate_item_math(item, item_row.text)
    
    # Validate totals (fees_from_items included for BC sumcheck)
    totals_valid, validation_details = validate_totals(
        items, totals_sequence, fees, total_tax,
        fees_from_items_region=fees_from_items,
    )
    logger.info(f"Step 7: Totals validation: {'PASSED' if totals_valid else 'FAILED'}")
    
    # Step 8: Amount usage is already tracked by AmountUsageTracker
    
    # Step 9: Extract membership (already extracted by split_regions for T&T)
    membership = getattr(regions, 'membership_id', None)

    # Build error log (per-block errors during processing)
    error_log = list(skew_error_log) + duplicate_bbox_errors + extract_error_log
    # TODO: Collect errors during processing (e.g. blocks that couldn't be parsed, regions that failed validation)
    # For now, return empty list; errors should be collected in real-time during processing
    
    # Build regions Y bounds (convert to integers: multiply by 10000)
    regions_y_bounds = {
        "header": [int(regions.header_rows[0].y_top * 10000), int(regions.header_rows[-1].y_bottom * 10000)] if regions.header_rows else [0, 0],
        "items": [int(regions.item_rows[0].y_top * 10000), int(regions.item_rows[-1].y_bottom * 10000)] if regions.item_rows else [0, 0],
        "totals": [int(regions.totals_rows[0].y_top * 10000), int(regions.totals_rows[-1].y_bottom * 10000)] if regions.totals_rows else [0, 0],
        "payment": [int(regions.payment_rows[0].y_top * 10000), int(regions.payment_rows[-1].y_bottom * 10000)] if regions.payment_rows else [0, 0],
    }
    
    # Simplify tax labels: remove amount from label (e.g. "State Sales Tax $0.91" -> "State Sales Tax")
    simplified_tax_list = [
        {
            "label": t["label"].rsplit(" $", 1)[0] if " $" in t["label"] else t["label"],
            "amount": t["amount"]
        }
        for t in tax_list
    ]
    
    # Build result
    result = {
        "success": totals_valid,
        "method": "pipeline",
        "chain_id": store_config.get("chain_id") if store_config else None,
        "store": merchant_name or (store_config.get("identification", {}).get("primary_name") if store_config else None),
        "membership": membership,
        "error_log": error_log,
        "items": [
            {
                "product_name": item.product_name,
                "line_total": int(item.line_total * 100),  # Convert to cents
                # Quantity: only multiply by 100 if has unit (weight-based), else keep as-is (count-based)
                "quantity": (
                    int(round(item.quantity * 100)) if item.unit is not None  # Weight-based: 1.16 lb -> 116 (round avoids 1.16*100=115.99 float error)
                    else int(item.quantity) if item.quantity is not None  # Count-based: 2 -> 2
                    else 1  # Default: 1 (no quantity info)
                ),
                "unit": item.unit,  # "1/100 lb" for weight-based, None otherwise
                "unit_price": int(item.unit_price * 100) if item.unit_price is not None else None,  # Convert to cents
                "on_sale": item.on_sale,
                "confidence": item.confidence
            }
            for item in items
        ],
        "totals": {
            "subtotal": totals_sequence.subtotal.amount if totals_sequence.subtotal else None,
            "tax": simplified_tax_list,
            "fees": fees,
            "total": totals_sequence.total.amount if totals_sequence.total else None
        },
        "validation": validation_details,
        "regions_y_bounds": regions_y_bounds,
        "amount_column": {
            "main_x": int(amount_columns.main_column.center_x * 10000),
            "tolerance": int(amount_columns.main_column.tolerance * 10000)
        },
        "ocr_and_regions": {
            "section_rows_detail": [
                {"section": "header", "label": "Store info", "rows": _rows_to_block_list(regions.header_rows)},
                {"section": "items", "label": "Items", "rows": _rows_to_block_list(regions.item_rows)},
                {"section": "totals", "label": "Totals", "rows": _rows_to_block_list(regions.totals_rows)},
                {"section": "payment", "label": "Payment & below", "rows": _rows_to_block_list(regions.payment_rows)},
            ],
        },
        "ocr_blocks": blocks,
    }
    return truncate_floats_in_result(result, precision=5)


def process_receipt_pipeline(
    blocks: List[Dict[str, Any]],
    llm_result: Dict[str, Any],
    store_config: Optional[Dict[str, Any]] = None,
    merchant_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Complete receipt processing pipeline. Routes to dedicated processors for
    Costco (by layout) and T&T (by chain_id); otherwise runs generic validation.
    """
    if store_config and store_config.get("layout") == "costco_ca_digital":
        from ..stores.costco_ca.digital import process_costco_ca_digital
        logger.info("Using Costco CA digital rule-based processor")
        return process_costco_ca_digital(blocks, store_config=store_config, merchant_name=merchant_name)

    if store_config and store_config.get("layout") == "costco_us_physical":
        from ..stores.costco_us.physical import process_costco_us_physical
        logger.info("Using Costco US physical rule-based processor")
        return process_costco_us_physical(blocks, store_config=store_config, merchant_name=merchant_name)

    if store_config and store_config.get("layout") == "costco_us_digital":
        from ..stores.costco_us.digital import process_costco_us_digital
        logger.info("Using Costco US digital rule-based processor")
        return process_costco_us_digital(blocks, store_config=store_config, merchant_name=merchant_name)

    if store_config and store_config.get("layout") == "trader_joes":
        from ..stores.trader_joes import process_trader_joes
        logger.info("Using Trader Joe's rule-based processor")
        return process_trader_joes(blocks, store_config=store_config, merchant_name=merchant_name)

    if store_config and store_config.get("chain_id") in ("tnt_supermarket_us", "tnt_supermarket_ca"):
        from ..stores.tnt_supermarket.processor import process_tnt_supermarket
        logger.info("Using T&T dedicated rule-based processor (chain_id=%s)", store_config.get("chain_id"))
        return process_tnt_supermarket(blocks, store_config=store_config, merchant_name=merchant_name)

    return _run_generic_validation_pipeline(blocks, llm_result, store_config, merchant_name)


def _extract_membership_from_regions(
    regions: ReceiptRegions,
    store_config: Optional[Dict[str, Any]]
) -> Optional[str]:
    """
    If store_config has header.membership_pattern, find first row (in header then items)
    whose text matches that pattern and which has an amount block with value 0. Return that row text.
    """
    if not store_config:
        return None
    header_cfg = store_config.get("header", {}) or {}
    pat = header_cfg.get("membership_pattern")
    if not pat:
        return None
    try:
        rx = re.compile(pat)
    except re.error:
        return None
    for row in list(regions.header_rows) + list(regions.item_rows):
        text = (row.text or "").strip()
        if not rx.search(text):
            continue
        for b in row.get_amount_blocks():
            if b.amount is not None and float(b.amount) == 0:
                return text or None
    return None


def _generate_formatted_output(
    items: List[ExtractedItem],
    totals_sequence: TotalsSequence,
    tax_list: List[dict],
    fees: List[dict]
) -> str:
    """Generate formatted vertical addition output for debugging."""
    lines = []
    
    # Add items
    for item in items:
        product_name = item.product_name
        if len(product_name) > 40:
            product_name = product_name[:37] + "..."
        lines.append(f"{product_name:<40} ${item.line_total:>8.2f}")
    
    # Separator
    if items:
        lines.append("-" * 50)
    
    # Subtotal
    if totals_sequence.subtotal:
        lines.append(f"{'SUBTOTAL':<40} ${totals_sequence.subtotal.amount:>8.2f}")
    
    # Tax list
    for tax_item in tax_list:
        tax_label = tax_item.get("label", "TAX")
        tax_amt = tax_item.get("amount", 0)
        if len(tax_label) > 40:
            tax_label = tax_label[:37] + "..."
        lines.append(f"{tax_label:<40} ${tax_amt:>8.2f}")
    
    # Fees
    for fee in fees:
        fee_label = fee.get("label", "FEE")
        fee_amount = fee.get("amount", 0)
        if len(fee_label) > 40:
            fee_label = fee_label[:37] + "..."
        lines.append(f"{fee_label:<40} ${fee_amount:>8.2f}")
    
    # Separator
    lines.append("-" * 50)
    
    # Total
    if totals_sequence.total:
        lines.append(f"{'TOTAL':<40} ${totals_sequence.total.amount:>8.2f}")
    
    return "\n".join(lines)
