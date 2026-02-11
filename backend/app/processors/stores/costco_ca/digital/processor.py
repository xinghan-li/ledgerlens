"""
Costco Canada Digital Receipt Processor: Rule-based parser for Costco digital receipts.

Structure (top to bottom):
- Header: Member XXXXX and above
- Items: From Member line down to SUBTOTAL
- Totals: SUBTOTAL → TAX → TOTAL (above payment divider)
- Payment: Below divider under TOTAL

Costco-specific rules:
1. SKU-to-amount pairing: Leftmost SKU (6-7 digits) pairs with right-side amount.
2. TPD/ discount: "TPD/SKU" + negative amount → merge into previous item with that SKU.
3. Multi-line product names: Use x/y to group text blocks on same row.
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
TPD_PATTERN = re.compile(r"\d{4,7}\s+TPD/(\d{4,7})", re.IGNORECASE)
MEMBER_PATTERN = re.compile(r"Member\s*(\d{10,12})", re.IGNORECASE)


def _blocks_to_rows(blocks: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Group blocks into rows by y (global), then sort by x within row."""
    if not blocks:
        return []
    sorted_blocks = sorted(blocks, key=lambda b: (b.get("center_y", b.get("y", 0)), b.get("center_x", b.get("x", 0))))
    rows: List[List[Dict]] = []
    current_row: List[Dict] = []
    last_y: Optional[float] = None
    for b in sorted_blocks:
        y = b.get("center_y", b.get("y", 0))
        if last_y is None or abs(y - last_y) <= ROW_Y_EPS:
            current_row.append(b)
        else:
            if current_row:
                current_row.sort(key=lambda x: x.get("center_x", x.get("x", 0)))
                rows.append(current_row)
            current_row = [b]
        last_y = y
    if current_row:
        current_row.sort(key=lambda x: x.get("center_x", x.get("x", 0)))
        rows.append(current_row)
    return rows


def _parse_amount_value(block: Dict) -> Optional[float]:
    amt = block.get("amount")
    text = (block.get("text") or "").strip()
    if amt is not None:
        if text.endswith("-") or (isinstance(amt, (int, float)) and text.endswith("-")):
            return -abs(float(amt))
        return float(amt)
    return None


def _is_amount_block(b: Dict) -> bool:
    return b.get("is_amount", False) and _parse_amount_value(b) is not None


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
            header_end = ri + 1
        if "SUBTOTAL" in norm and "SUB" in row_text:
            items_end = ri
            if totals_end < 0:
                totals_end = ri
        if norm == "TAX" or "TOTALTAX" in norm:
            if totals_end >= 0 and totals_end < ri:
                totals_end = ri
        if "TOTAL" in norm and "SUB" not in norm:
            if ri > (items_end if items_end >= 0 else -1):
                totals_end = ri
    if items_end < 0:
        items_end = len(rows)
    if totals_end < 0:
        totals_end = items_end
    return header_end, items_end, totals_end, membership_id


def _detect_x_boundaries(rows: List[List[Dict]], items_start: int, items_end: int) -> Tuple[float, float]:
    xs: List[float] = []
    for ri in range(items_start, items_end + 1):
        if ri >= len(rows):
            break
        for b in rows[ri]:
            if _is_tpd_row(rows[ri]):
                continue
            xs.append(b.get("center_x", b.get("x", 0)))
    if len(xs) < 3:
        return X_SKU_NAME_FALLBACK, X_NAME_AMOUNT_FALLBACK
    xs = sorted(set(xs))
    gaps: List[Tuple[float, float, float]] = []
    for i in range(len(xs) - 1):
        g = xs[i + 1] - xs[i]
        gaps.append((g, xs[i], xs[i + 1]))
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
    for b in row:
        cx = b.get("center_x", b.get("x", 0))
        t = (b.get("text") or "").strip()
        if not t or "TPD/" in t.upper():
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


def _is_tpd_row(row: List[Dict]) -> bool:
    return "TPD/" in " ".join(b.get("text", "") for b in row).upper()


def _get_tpd_target_sku(row: List[Dict]) -> Optional[str]:
    m = TPD_PATTERN.search(" ".join(b.get("text", "") for b in row))
    return m.group(1) if m else None


def _extract_amount_from_row(row: List[Dict], x_name_amount: float) -> Optional[float]:
    for b in row:
        cx = b.get("center_x", b.get("x", 0))
        if cx >= x_name_amount - 0.02:
            val = _parse_amount_value(b)
            if val is not None and 0.01 <= abs(val) <= 9999.99:
                return val
    for b in row:
        cx = b.get("center_x", b.get("x", 0))
        if cx >= x_name_amount - 0.15:
            t = (b.get("text") or "").strip()
            for m in re.finditer(r"\$?(\d+\.\d{2})(?:\s*[NY]?\s*(?:\d+)?)?\b", t):
                try:
                    v = float(m.group(1))
                    if 0.01 <= v <= 9999.99:
                        return v
                except ValueError:
                    pass
    return None


def _extract_items_from_rows(rows: List[List[Dict]], items_start: int, items_end: int) -> List[ExtractedItem]:
    items: List[ExtractedItem] = []
    sku_to_item_idx: Dict[str, int] = {}
    x_sku_name, x_name_amount = _detect_x_boundaries(rows, items_start, items_end)
    for ri in range(items_start, items_end + 1):
        row = rows[ri]
        if not row:
            continue
        if _is_tpd_row(row):
            target_sku = _get_tpd_target_sku(row)
            discount = _extract_amount_from_row(row, x_name_amount)
            if target_sku and discount is not None and discount < 0 and items:
                idx = sku_to_item_idx.get(target_sku)
                if idx is not None:
                    prev = items[idx]
                    original_price = prev.line_total
                    new_total = round(prev.line_total + discount, 2)
                    items[idx] = ExtractedItem(
                        product_name=prev.product_name, line_total=new_total,
                        amount_block_id=prev.amount_block_id, row_id=prev.row_id, quantity=prev.quantity,
                        unit_price=original_price, unit=prev.unit, raw_text=prev.raw_text,
                        confidence=prev.confidence, on_sale=True,
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
            sku_to_item_idx[sku] = len(items) - 1
    return items


def _extract_totals_from_rows(rows: List[List[Dict]], items_end: int, totals_end: int) -> Tuple[Optional[float], List[Dict], List[Dict], Optional[float]]:
    subtotal = None
    hst_amount: Optional[float] = None
    gst_amount: Optional[float] = None
    total_tax_amount: Optional[float] = None
    fees: List[Dict] = []
    total = None
    for ri in range(items_end, len(rows)):
        row = rows[ri]
        texts = [b.get("text", "").strip() for b in row]
        row_text = " ".join(texts).upper()
        norm = re.sub(r"[.\s\-_]", "", row_text)
        amount = _extract_amount_from_row(row, X_NAME_AMOUNT_FALLBACK)
        if "SUBTOTAL" in norm:
            if amount is not None:
                subtotal = amount
        elif "(A)HST" in norm or "HST" in norm and "(A)" in row_text:
            if amount is not None and amount > 0:
                hst_amount = amount
        elif "5%GST" in norm or "(B)5%GST" in norm or ("GST" in norm and "(B)" in row_text):
            if amount is not None and amount > 0:
                gst_amount = amount
        elif "TOTALTAX" in norm or (norm == "TAX" and amount is not None and "TOTAL" in row_text):
            if amount is not None and amount > 0:
                total_tax_amount = amount
        elif "TOTAL" in norm and "SUB" not in norm and "TAX" not in row_text:
            if amount is not None and amount > 10:
                total = amount
    tax_list: List[Dict] = []
    if hst_amount is not None or gst_amount is not None:
        hst = round(hst_amount or 0, 2)
        gst = round(gst_amount or 0, 2)
        if total_tax_amount is not None and abs(hst + gst - total_tax_amount) > 0.03:
            if hst_amount is not None and gst_amount is not None:
                hst = round(total_tax_amount - gst, 2)
            elif hst_amount is not None:
                hst = round(total_tax_amount, 2)
                gst = 0
            else:
                gst = round(total_tax_amount, 2)
        if hst > 0:
            tax_list.append({"label": "HST", "amount": hst})
        if gst > 0:
            tax_list.append({"label": "GST", "amount": gst})
    elif total_tax_amount is not None:
        tax_list = [{"label": "TOTAL TAX", "amount": round(total_tax_amount, 2)}]
    return subtotal, tax_list, fees, total


def _extract_store_from_header(rows: List[List[Dict]], header_end: int) -> Optional[str]:
    for ri in range(min(header_end, len(rows))):
        for b in rows[ri]:
            t = (b.get("text") or "").strip()
            if not t or "TPD/" in t.upper():
                continue
            if re.search(r"[NS]\s+LONDON\s*#?\s*\d{3,4}", t, re.I):
                return t.title() if t.isupper() or "#" in t else t
            if re.search(r"#\s*\d{3,4}", t):
                return t.title() if t.isupper() else t
    return None


def _extract_address_from_header(rows: List[List[Dict]], header_end: int) -> Optional[str]:
    lines: List[str] = []
    for ri in range(min(header_end, len(rows))):
        for b in rows[ri]:
            t = (b.get("text") or "").strip()
            if not t or "TPD/" in t.upper() or re.match(r"^\d{20,}$", t):
                continue
            if re.search(r"\d+\s+[A-Z].*DRIVE|STREET|RD|AVE|BLVD", t, re.I) or re.search(r"^[A-Z]{2}\s+,", t) or re.search(r",\s*[A-Z]{2}\s+[A-Z0-9]", t):
                lines.append(t)
    return ", ".join(lines) if lines else None


def _infer_currency_from_address(address: Optional[str], store: Optional[str]) -> str:
    text = f"{address or ''} {store or ''}".upper()
    if re.search(r"\bON\b|\bBC\b|\bAB\b|\bQC\b|\bN[0-9A-Z]\s*[0-9A-Z][0-9A-Z]|LONDON,\s*ON|TORONTO|VANCOUVER", text):
        return "CAD"
    return "USD"


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


def process_costco_ca_digital(
    blocks: List[Dict[str, Any]],
    store_config: Optional[Dict[str, Any]] = None,
    merchant_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Process Costco Canada digital receipt with rule-based logic (OCR blocks → extraction)."""
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
    chain_id = (store_config or {}).get("chain_id", "Costco_Canada")
    store_name = _extract_store_from_header(rows, header_end) or merchant_name or (store_config or {}).get("identification", {}).get("primary_name", "COSTCO WHOLESALE")
    address = _extract_address_from_header(rows, header_end)
    currency = _infer_currency_from_address(address, store_name)
    result = {
        "success": totals_valid,
        "method": "costco_ca_digital",
        "chain_id": chain_id,
        "store": store_name,
        "address": address,
        "currency": currency,
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
    return truncate_floats_in_result(result, precision=5)


def _empty_result(
    store_config: Optional[Dict], merchant_name: Optional[str], blocks: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    result = {
        "success": False, "method": "costco_ca_digital",
        "chain_id": (store_config or {}).get("chain_id", "Costco_Canada"),
        "store": merchant_name or "COSTCO WHOLESALE",
        "address": None, "currency": "CAD",
        "membership": None,
        "error_log": ["No blocks provided"], "items": [],
        "totals": {"subtotal": None, "tax": [], "fees": [], "total": None},
        "validation": {"items_sum_check": None, "totals_sum_check": None, "passed": False},
        "regions_y_bounds": {}, "amount_column": {}, "ocr_and_regions": {},
        "ocr_blocks": blocks if blocks is not None else [],
    }
    return truncate_floats_in_result(result, precision=5)
