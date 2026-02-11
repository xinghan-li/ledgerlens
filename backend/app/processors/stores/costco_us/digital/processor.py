"""
Costco US Digital Receipt Processor: Rule-based parser for Costco US digital receipts
(e.g. Orders & Purchases PDF, multi-page).

Structure (top to bottom):
- Header: COSTCO, WHOLESALE, store #, address, transaction id, Member + number
- Items: From Member line down to SUBTOTAL (SKU + name, amount with N/Y suffix)
- Totals: SUBTOTAL → TAX → **** TOTAL
- Payment: CHIP, card, APPROVED, etc. (page 1); page 2 may have TOTAL TAX, INSTANT SAVINGS

US Digital specifics:
1. Discount format: "369985/990929" + negative amount (no TPD prefix).
2. Amounts: X.XX N or X.XX Y suffix.
3. Tax: Simple "TAX" line (no HST/GST).
4. Exclude ITEMS SOLD, TOTAL NUMBER OF ITEMS SOLD from totals.
5. Only accept amounts matching X.XX (reject OCR-mislabeled SKUs like 371, 189).
"""
import re
import logging
from typing import Dict, Any, List, Optional, Tuple

from ....core.structures import ExtractedItem
from .....utils.float_precision import truncate_floats_in_result

logger = logging.getLogger(__name__)

ROW_Y_EPS = 0.02
X_SKU_NAME_FALLBACK = 0.48
X_NAME_AMOUNT_FALLBACK = 0.65
SKU_PATTERN = re.compile(r"^(\d{4,7})(?:\s+(.+))?$")
# US digital: "369985/990929" (no TPD), target SKU after /
DISCOUNT_SKU_PATTERN = re.compile(r"/\s*(\d{4,7})\s*$")
DISCOUNT_SKU_SPLIT = re.compile(r"/\s*(\d+)\s+(\d+)")
MEMBER_PATTERN = re.compile(r"Member\s*(\d{10,12})", re.IGNORECASE)


def _blocks_to_rows(blocks: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Group blocks into rows by y (global, supports multi-page), sort by x within row."""
    if not blocks:
        return []
    # Use (page, y) for multi-page; page_number defaults to 1
    def sort_key(b):
        page = b.get("page_number", 1)
        y = b.get("center_y", b.get("y", 0))
        return (page, y, b.get("center_x", b.get("x", 0)))
    sorted_blocks = sorted(blocks, key=sort_key)
    rows: List[List[Dict]] = []
    current_row: List[Dict] = []
    last_page = None
    for b in sorted_blocks:
        page = b.get("page_number", 1)
        y = b.get("center_y", b.get("y", 0))
        # New row when page changes or y is beyond this row's band (compare to row ref y, not last block)
        row_ref_y = current_row[0].get("center_y", current_row[0].get("y", 0)) if current_row else None
        if last_page is not None and (
            page != last_page or (row_ref_y is not None and abs(y - row_ref_y) > ROW_Y_EPS)
        ):
            if current_row:
                current_row.sort(key=lambda x: x.get("center_x", x.get("x", 0)))
                rows.append(current_row)
            current_row = [b]
        else:
            current_row.append(b)
        last_page = page
    if current_row:
        current_row.sort(key=lambda x: x.get("center_x", x.get("x", 0)))
        rows.append(current_row)
    return rows


def _parse_amount_value(block: Dict) -> Optional[float]:
    amt = block.get("amount")
    text = (block.get("text") or "").strip()
    is_negative = text.endswith("-") or re.search(r"\d+\.\d{2}\s*-\s*[A-Z]?\s*$", text)
    if amt is not None:
        val = float(amt)
        return -abs(val) if is_negative else val
    m = re.search(r"\$?(\d+\.\d{2})(?:\s*[NY]?\s*)?-?\s*$", text)
    if m:
        val = float(m.group(1))
        return -abs(val) if is_negative else val
    return None


def _is_valid_price_value(val: float, text: str) -> bool:
    """Only accept X.XX format. Reject SKUs mislabeled as amount (e.g. 371 from '371808')."""
    if val < 0.01 or val > 999.99:
        return False
    return bool(re.search(r"\d+\.\d{2}", text))


def _is_amount_block(b: Dict) -> bool:
    val = _parse_amount_value(b)
    if val is None:
        return False
    text = (b.get("text") or "").strip()
    return _is_valid_price_value(abs(val), text)


def _find_region_boundaries(rows: List[List[Dict]]) -> Tuple[int, int, int, Optional[str]]:
    membership_id: Optional[str] = None
    header_end = 0
    items_end = -1
    totals_end = -1
    for ri, row in enumerate(rows):
        texts = [b.get("text", "").strip() for b in row]
        row_text = " ".join(texts).upper()
        norm = re.sub(r"[.\s\-_]", "", row_text)
        m = MEMBER_PATTERN.search(" ".join(texts))
        if m:
            membership_id = m.group(1)
            if items_end < 0 or ri < items_end:
                header_end = ri + 1
        # Member number on next row (e.g. "Member" row then "111937424352" row)
        if not m and ri > 0 and re.match(r"^\d{10,12}\s*$", " ".join(texts).strip()):
            prev_text = " ".join(b.get("text", "") for b in rows[ri - 1]).strip()
            if re.search(r"Member", prev_text, re.I):
                membership_id = " ".join(texts).strip().split()[0]
                if items_end < 0 or ri < items_end:
                    header_end = ri + 1
        if "SUBTOTAL" in norm and "SUB" in row_text:
            items_end = ri
            if totals_end < 0:
                totals_end = ri
        if norm == "TAX" or "TOTALTAX" in norm:
            if totals_end >= 0 and totals_end < ri:
                totals_end = ri
        if ("TOTAL" in norm or "TOTA" in norm) and "SUB" not in norm:
            if "ITEMSSOLD" in norm or "NUMBEROFITEMS" in norm:
                continue
            if ri > (items_end if items_end >= 0 else -1):
                totals_end = ri
    if items_end < 0:
        items_end = len(rows)
    if totals_end < 0:
        totals_end = items_end
    return header_end, items_end, totals_end, membership_id


def _is_discount_row(row: List[Dict]) -> bool:
    row_text = " ".join(b.get("text", "") for b in row)
    # Check for negative amount
    has_negative = False
    for b in row:
        val = _parse_amount_value(b)
        if val is not None and val < 0:
            has_negative = True
            break
    if not has_negative:
        return False
    # Discount row: has "/" (e.g. "369985/990929") OR multiple SKUs (e.g. "371808 1891143")
    if "/" in row_text:
        return True
    # Count SKU patterns (4-7 digit numbers, even if mislabeled as amount when value is invalid price)
    sku_count = 0
    for b in row:
        t = (b.get("text") or "").strip()
        # Check for concatenated SKUs (10-14 digits, e.g. "3691101702153" = "369110" + "1702153")
        if re.match(r"^\d{10,14}$", t):
            # Likely two 5-7 digit SKUs concatenated
            sku_count += 2
        elif re.match(r"^\d{4,7}$", t):
            # If is_amount but not a valid price (e.g. 371, 189 from SKU misread), count as SKU
            if not b.get("is_amount"):
                sku_count += 1
            else:
                amt = b.get("amount")
                if amt is not None and not _is_valid_price_value(abs(float(amt)), t):
                    sku_count += 1
    return sku_count >= 2


def _get_discount_target_sku(row: List[Dict]) -> Optional[str]:
    # Try "/" format first (e.g. "369985/990929" or "TPD/1891143")
    for b in row:
        t = (b.get("text") or "").strip()
        m = re.search(r"/\s*(\d{4,7})\s*$", t)
        if m:
            return m.group(1)
        m = re.search(r"/\s*(\d+)\s+(\d+)", t)
        if m:
            return m.group(1) + m.group(2)
    # No slash: collect all SKUs (4-7 digit, or concatenated 10-14 digit), return last one (target)
    skus = []
    for b in row:
        t = (b.get("text") or "").strip()
        # Check for concatenated SKUs (10-14 digits, e.g. "3691101702153")
        if re.match(r"^\d{10,14}$", t):
            # Split into two SKUs: last 6-7 digits is target
            if len(t) >= 12:  # e.g. 13 digits: first 6, last 7
                skus.append(t[:6])
                skus.append(t[6:])
            elif len(t) == 11:  # 11 digits: first 5, last 6
                skus.append(t[:5])
                skus.append(t[5:])
            else:  # 10 digits: first 5, last 5
                skus.append(t[:5])
                skus.append(t[5:])
        elif re.match(r"^\d{4,7}$", t):
            # Include if not amount, or if amount but not valid price (SKU misread)
            if not b.get("is_amount"):
                skus.append(t)
            else:
                amt = b.get("amount")
                if amt is not None and not _is_valid_price_value(abs(float(amt)), t):
                    skus.append(t)
    return skus[-1] if skus else None


def _detect_x_boundaries(rows: List[List[Dict]], items_start: int, items_end: int) -> Tuple[float, float]:
    xs: List[float] = []
    for ri in range(items_start, min(items_end + 1, len(rows))):
        row = rows[ri]
        if _is_discount_row(row):
            continue
        for b in row:
            xs.append(b.get("center_x", b.get("x", 0)))
    if len(xs) < 3:
        return X_SKU_NAME_FALLBACK, X_NAME_AMOUNT_FALLBACK
    xs = sorted(set(xs))
    gaps: List[Tuple[float, float, float]] = []
    for i in range(len(xs) - 1):
        gaps.append((xs[i + 1] - xs[i], xs[i], xs[i + 1]))
    gaps.sort(key=lambda t: -t[0])
    if len(gaps) < 2:
        return X_SKU_NAME_FALLBACK, X_NAME_AMOUNT_FALLBACK
    b1 = (gaps[0][1] + gaps[0][2]) / 2
    b2 = (gaps[1][1] + gaps[1][2]) / 2
    x_sku_name = min(b1, b2)
    x_name_amount = max(b1, b2)
    if x_sku_name >= x_name_amount - 0.02:
        return X_SKU_NAME_FALLBACK, X_NAME_AMOUNT_FALLBACK
    return x_sku_name, x_name_amount


def _extract_product_name_and_sku(row: List[Dict], x_sku_name: float, x_name_amount: float) -> Tuple[Optional[str], Optional[str], str]:
    sku = None
    name_parts: List[str] = []
    
    # Handle single-block rows (e.g. "1935000 PULLUP 2T-3T 79.98 Y" in one block)
    if len(row) == 1:
        t = (row[0].get("text") or "").strip()
        # Try to parse: SKU + Name + Amount format
        m = re.match(r"^(\d{4,7})\s+(.+?)\s+\d+\.\d{2}\s*[NY]?\s*$", t)
        if m:
            sku = m.group(1)
            product_name = m.group(2).strip()
            return sku, product_name, product_name
    
    for b in row:
        cx = b.get("center_x", b.get("x", 0))
        t = (b.get("text") or "").strip()
        if not t or "/" in t and re.search(r"\d+/\d+", t):
            continue
        if cx < x_sku_name:
            m = SKU_PATTERN.match(t)
            if m and len(m.group(1)) >= 4:
                sku = m.group(1)
        elif x_sku_name <= cx < x_name_amount:
            if _is_amount_block(b) and len(t) < 15:
                continue
            m = SKU_PATTERN.match(t)
            if m:
                if not sku and len(m.group(1)) >= 4:
                    sku = m.group(1)
                rest = re.sub(r"\s*\d+\.\d{2}\s*[NY]?\s*\d*\s*$", "", (m.group(2) or "").strip()).strip()
                if rest:
                    name_parts.append(rest)
            else:
                stripped = re.sub(r"\s*\d+\.\d{2}\s*[NY]?\s*\d*\s*$", "", t).strip()
                if stripped and not re.match(r"^\d{6,7}$", stripped):
                    name_parts.append(stripped)
    product_name = " ".join(name_parts).strip()
    return sku, (product_name or None), product_name


def _extract_amount_from_row(row: List[Dict], x_name_amount: float) -> Optional[float]:
    for b in row:
        cx = b.get("center_x", b.get("x", 0))
        if cx >= x_name_amount - 0.02:
            val = _parse_amount_value(b)
            text = (b.get("text") or "").strip()
            if val is not None and 0.01 <= abs(val) <= 999.99 and _is_valid_price_value(abs(val), text):
                return val
    for b in row:
        cx = b.get("center_x", b.get("x", 0))
        if cx >= x_name_amount - 0.15:
            t = (b.get("text") or "").strip()
            for m in re.finditer(r"\$?(\d+\.\d{2})(?:\s*[NY]?\s*(?:\d+)?)?\b", t):
                try:
                    v = float(m.group(1))
                    if 0.01 <= v <= 999.99:
                        return v
                except ValueError:
                    pass
    return None


def _find_matching_sku_for_discount(extracted: str, sku_to_idx: Dict[str, int]) -> Optional[int]:
    if extracted in sku_to_idx:
        return sku_to_idx[extracted]
    if len(extracted) >= 3:
        suffix = extracted[-3:]
        for sku, idx in sku_to_idx.items():
            if sku.endswith(suffix) or sku == extracted:
                return idx
    return None


def _extract_items_from_rows(rows: List[List[Dict]], items_start: int, items_end: int) -> List[ExtractedItem]:
    items: List[ExtractedItem] = []
    sku_to_idx: Dict[str, int] = {}
    x_sku_name, x_name_amount = _detect_x_boundaries(rows, items_start, items_end)
    for ri in range(items_start, items_end + 1):
        if ri >= len(rows):
            break
        row = rows[ri]
        if not row:
            continue
        if _is_discount_row(row):
            target_sku = _get_discount_target_sku(row)
            discount = _extract_amount_from_row(row, x_name_amount)
            if target_sku and discount is not None and discount < 0 and items:
                idx = _find_matching_sku_for_discount(target_sku, sku_to_idx)
                if idx is not None:
                    prev = items[idx]
                    unit_price = prev.line_total
                    new_total = round(unit_price + discount, 2)
                    items[idx] = ExtractedItem(
                        product_name=prev.product_name, line_total=new_total,
                        amount_block_id=prev.amount_block_id, row_id=prev.row_id, quantity=1, unit=None,
                        unit_price=unit_price, raw_text=prev.raw_text, confidence=prev.confidence, on_sale=True,
                    )
            continue
        sku, _, product_name = _extract_product_name_and_sku(row, x_sku_name, x_name_amount)
        amount = _extract_amount_from_row(row, x_name_amount)
        if amount is None or amount < 0:
            continue
        if not product_name and sku:
            product_name = f"Item {sku}"
        if not product_name:
            continue
        raw_row = " ".join(b.get("text", "") for b in row)
        item = ExtractedItem(
            product_name=product_name, line_total=amount, amount_block_id=ri, row_id=ri,
            quantity=1, unit_price=None, unit=None,
            raw_text=raw_row, confidence=1.0, on_sale=False,
        )
        items.append(item)
        if sku:
            sku_to_idx[sku] = len(items) - 1
    return items


def _extract_totals_from_rows(rows: List[List[Dict]], items_end: int, totals_end: int) -> Tuple[Optional[float], List[Dict], List[Dict], Optional[float]]:
    subtotal = tax_amount = total = None
    tax_list: List[Dict] = []
    fees: List[Dict] = []
    for ri in range(items_end, min(totals_end + 1, len(rows))):
        row = rows[ri]
        texts = [b.get("text", "").strip() for b in row]
        row_text = " ".join(texts).upper()
        norm = re.sub(r"[.\s\-_]", "", row_text)
        # Exclude "ITEMS SOLD", "TOTAL NUMBER OF ITEMS", etc.
        if "ITEMSSOLD" in norm or "NUMBEROFITEMS" in norm or "TOTALNUMBEROF" in norm:
            continue
        for b in row:
            val = _parse_amount_value(b)
            text = (b.get("text") or "").strip()
            if val is None or val < 0:
                continue
            if abs(val - round(val)) < 0.001 and "ITEMSSOLD" in norm:
                continue
            if "SUBTOTAL" in norm:
                subtotal = val
            elif norm == "TAX" or "TOTALTAX" in norm:
                tax_amount = val
            # Match TOTAL or TOTA (OCR may miss L), but exclude SUBTOTAL and TAX rows
            elif ("TOTAL" in norm or "TOTA" in norm) and "SUB" not in norm and "TAX" not in row_text:
                if _is_valid_price_value(val, text):
                    total = val
    if tax_amount is not None and tax_amount != 0:
        tax_list = [{"label": "TAX", "amount": round(tax_amount, 2)}]
    return subtotal, tax_list, fees, total


def _extract_store_from_header(rows: List[List[Dict]], header_end: int) -> Optional[str]:
    for ri in range(min(header_end, len(rows))):
        for b in rows[ri]:
            t = (b.get("text") or "").strip()
            if not t or "Member" in t or "COSTCO" in t.upper() or "WHOLESALE" in t.upper():
                continue
            if re.search(r"#\s*\d{3,4}", t) or re.search(r"\w+\s*#\d+", t):
                return t
    return None


def _extract_address_from_header(rows: List[List[Dict]], header_end: int) -> Optional[str]:
    addr_blocks: List[Tuple[float, str]] = []
    for ri in range(min(header_end, len(rows))):
        for b in rows[ri]:
            t = (b.get("text") or "").strip()
            if not t or "Member" in t or "COSTCO" in t.upper() or "WHOLESALE" in t.upper():
                continue
            if re.match(r"^\d{20,}$", t):
                continue
            if re.search(r"\d+\s+[A-Z0-9].*(\bAVE\b|\bST\b|\bRD\b|\bBLVD\b|\bDR\b)", t, re.I):
                addr_blocks.append((b.get("center_y", b.get("y", 0)), t))
            elif re.search(r",\s*[A-Z]{2}\s+[0-9]{5}", t) or re.search(r"^[A-Za-z]+,?\s+[A-Z]{2}\s+[0-9]{5}", t):
                addr_blocks.append((b.get("center_y", b.get("y", 0)), t))
    if not addr_blocks:
        return None
    addr_blocks.sort(key=lambda x: x[0])
    return ", ".join(t for _, t in addr_blocks)


def _build_ocr_section_rows(rows: List[List[Dict]], header_end: int, items_end: int, totals_end: int) -> Dict[str, Any]:
    def row_to_blocks(row: List[Dict]) -> List[Dict]:
        return [{"x": int(b.get("center_x", 0) * 10000), "y": int(b.get("center_y", 0) * 10000), "is_amount": b.get("is_amount", False), "text": (b.get("text") or "")[:120]} for b in row]
    header_rows = [{"row_id": i, "blocks": row_to_blocks(rows[i])} for i in range(header_end) if i < len(rows)]
    item_end_idx = items_end if items_end >= 0 else len(rows)
    item_rows = [{"row_id": i, "blocks": row_to_blocks(rows[i])} for i in range(header_end, item_end_idx) if i < len(rows)]
    totals_rows = [{"row_id": i, "blocks": row_to_blocks(rows[i])} for i in range(item_end_idx, min(totals_end + 1, len(rows))) if i < len(rows)]
    payment_rows = [{"row_id": i, "blocks": row_to_blocks(rows[i])} for i in range(totals_end + 1, len(rows))] if totals_end + 1 < len(rows) else []
    return {
        "section_rows_detail": [
            {"section": "header", "label": "Store info", "rows": header_rows},
            {"section": "items", "label": "Items", "rows": item_rows},
            {"section": "totals", "label": "Totals", "rows": totals_rows},
            {"section": "payment", "label": "Payment & below", "rows": payment_rows},
        ]
    }


def process_costco_us_digital(
    blocks: List[Dict[str, Any]],
    store_config: Optional[Dict[str, Any]] = None,
    merchant_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Process Costco US digital receipt (Orders & Purchases PDF) with rule-based logic."""
    if not blocks:
        return _empty_result(store_config, merchant_name, blocks=blocks or [])
    rows = _blocks_to_rows(blocks)
    header_end, items_end, totals_end, membership_id = _find_region_boundaries(rows)
    items = _extract_items_from_rows(rows, header_end, items_end - 1 if items_end >= 0 else len(rows) - 1)
    subtotal_val, tax_list, fees, total_val = _extract_totals_from_rows(rows, items_end, totals_end)
    total_tax = sum(t["amount"] for t in tax_list)
    items_sum = sum(i.line_total for i in items)
    totals_valid = False
    validation_details: Dict[str, Any] = {
        "items_sum_check": {"passed": False, "calculated": items_sum, "expected": subtotal_val, "difference": 0},
        "totals_sum_check": {"passed": False},
        "passed": False,
    }
    if subtotal_val is not None:
        diff = round(abs(items_sum - subtotal_val), 2)
        validation_details["items_sum_check"] = {"passed": diff <= 0.03, "calculated": round(items_sum, 2), "expected": subtotal_val, "difference": diff}
    if subtotal_val is not None and total_val is not None:
        calculated = round(subtotal_val + total_tax + sum(f.get("amount", 0) for f in fees), 2)
        diff = round(abs(calculated - total_val), 2)
        validation_details["totals_sum_check"] = {
            "passed": diff <= 0.03, "calculated": calculated, "expected": total_val, "difference": diff,
            "breakdown": {"subtotal": subtotal_val, "fees": 0, "tax": total_tax, "sum": calculated},
        }
        validation_details["passed"] = validation_details["items_sum_check"]["passed"] and validation_details["totals_sum_check"]["passed"]
        totals_valid = validation_details["passed"]
    elif total_val is not None:
        validation_details["totals_sum_check"] = {"passed": None, "reason": "no_subtotal"}
    else:
        validation_details["totals_sum_check"] = {"passed": None, "reason": "no_total"}
    error_log: List[str] = []
    if not totals_valid:
        ic = validation_details.get("items_sum_check", {})
        tc = validation_details.get("totals_sum_check", {})
        if isinstance(ic, dict) and ic.get("passed") is False and ic.get("difference", 0) > 0.03:
            error_log.append(f"Items sum mismatch: calculated {items_sum:.2f} vs subtotal {subtotal_val}")
        if isinstance(tc, dict) and tc.get("passed") is False and tc.get("difference", 0) > 0.03:
            error_log.append(f"Totals mismatch: calculated {tc.get('calculated')} vs total {total_val}")
        if tc.get("reason") == "no_subtotal":
            error_log.append("Subtotal not found")
        if tc.get("reason") == "no_total":
            error_log.append("TOTAL not found")
        if not error_log:
            error_log.append("Validation failed")
    simplified_tax = [{"label": t["label"].rsplit(" $", 1)[0] if " $" in t["label"] else t["label"], "amount": t["amount"]} for t in tax_list]
    chain_id = (store_config or {}).get("chain_id", "Costco_USA")
    store_name = _extract_store_from_header(rows, header_end) or merchant_name or "COSTCO WHOLESALE"
    address = _extract_address_from_header(rows, header_end)
    result = {
        "success": totals_valid,
        "method": "costco_us_digital",
        "chain_id": chain_id,
        "store": store_name,
        "address": address,
        "currency": "USD",
        "membership": membership_id,
        "error_log": error_log,
        "items": [
            {
                "product_name": item.product_name,
                "line_total": int(round(item.line_total * 100)),
                "quantity": int(item.quantity) if item.quantity is not None else 1,
                "unit": item.unit,
                "unit_price": int(round(item.unit_price * 100)) if item.unit_price else None,
                "on_sale": item.on_sale,
                "confidence": item.confidence,
                "raw_text": item.raw_text,
            }
            for item in items
        ],
        "totals": {"subtotal": subtotal_val, "tax": simplified_tax, "fees": fees, "total": total_val},
        "validation": validation_details,
        "regions_y_bounds": {}, "amount_column": {},
        "ocr_and_regions": _build_ocr_section_rows(rows, header_end, items_end, totals_end),
        "ocr_blocks": blocks,
    }
    # Truncate float values to 5 decimal places to save LLM tokens
    return truncate_floats_in_result(result, precision=5)


def _empty_result(
    store_config: Optional[Dict], merchant_name: Optional[str], blocks: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    result = {
        "success": False, "method": "costco_us_digital",
        "chain_id": (store_config or {}).get("chain_id", "Costco_USA"),
        "store": merchant_name or "COSTCO WHOLESALE",
        "address": None, "currency": "USD",
        "membership": None, "error_log": ["No blocks provided"], "items": [],
        "totals": {"subtotal": None, "tax": [], "fees": [], "total": None},
        "validation": {"items_sum_check": None, "totals_sum_check": None, "passed": False},
        "regions_y_bounds": {}, "amount_column": {}, "ocr_and_regions": {},
        "ocr_blocks": blocks if blocks is not None else [],
    }
    return truncate_floats_in_result(result, precision=5)
