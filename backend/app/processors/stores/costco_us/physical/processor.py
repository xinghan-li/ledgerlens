"""
Costco US Physical Receipt Processor: Rule-based parser for Costco physical store receipts.

Structure (top to bottom):
- Header: COSTCO, WHOLESALE, store name #num, street, city state zip, Member XXXXX and above
- Items: From first product row to SUBTOTAL. 4 columns: E (exempt), SKU, name, price
- Totals: SUBTOTAL → TAX → TOTAL
- Other: Below TOTAL (payment, etc.)

Physical receipt: E | SKU | Name | Price. Discount lines: / SKU on left, amount- on right.
OCR blocks → rule-based extraction (no LLM).
"""
import re
import logging
from typing import Dict, Any, List, Optional, Tuple

from ....core.structures import ExtractedItem
from .....utils.float_precision import truncate_floats_in_result

logger = logging.getLogger(__name__)

ROW_Y_EPS = 0.008
def _is_ocr_noise_word(t: str) -> bool:
    """True if text is OCR noise (e.g. шш, யயய) - non-Latin, short."""
    if not t or len(t) > 4:
        return False
    # Cyrillic, Tamil, other non-Latin scripts that often appear as OCR garbage
    return bool(re.search(r"[\u0400-\u04FF\u0B80-\u0BFF]", t))


def _clean_product_name(name: str) -> str:
    """Remove OCR noise and leading/trailing non-ASCII."""
    words = [w for w in name.split() if not _is_ocr_noise_word(w)]
    return " ".join(words).strip()
X_SKU_NAME_FALLBACK = 0.42
X_NAME_AMOUNT_FALLBACK = 0.58
SKU_PATTERN = re.compile(r"^(\d{3,7})\s+(.+)$")
MEMBER_PATTERN = re.compile(r"Membe[r]?\s*(\d{10,12})", re.IGNORECASE)  # Membe = OCR typo for Member
DISCOUNT_ROW_PATTERN = re.compile(r"/\s*(\d{4,7})\s*$")  # "0000369385 / 990929" or "E 0000371308 / 189 143"


def _blocks_to_rows(blocks: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
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
    """Parse amount from block. Handles trailing '-' (e.g. 2.40-, 2.40-A) as negative."""
    amt = block.get("amount")
    text = (block.get("text") or "").strip()
    is_negative = text.endswith("-") or re.search(r"\d+\.\d{2}\s*-\s*[A-Z]?\s*$", text)  # 2.40-, 2.40-A
    if amt is not None:
        val = float(amt)
        return -abs(val) if is_negative else val
    m = re.search(r"\$?\s*(\d+\.\d{2})(?:\s*-\s*[A-Z]?|\s*[A-Z]?\s*-\s*)?\s*$", text)
    if m:
        val = float(m.group(1))
        return -abs(val) if is_negative else val
    return None


def _is_amount_block(b: Dict) -> bool:
    return b.get("is_amount", False) and _parse_amount_value(b) is not None


def _is_item_row_physical(row: List[Dict]) -> bool:
    row_text = " ".join(b.get("text", "") for b in row)
    if "SUBTOTAL" in row_text.upper() or "TOTAL" in row_text.upper() or "TAX" == row_text.strip().upper():
        return False
    if "Member" in row_text or "Bottom of Basket" in row_text or "BOB Count" in row_text:
        return False
    has_sku_name = bool(re.search(r"\d{3,7}\s+[A-Za-z]", row_text))
    has_amount = any(_is_amount_block(b) for b in row)
    return has_sku_name and has_amount


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
        if ("SUBTOTAL" in norm or "SUBTOTA" in norm) and "SUB" in row_text.upper():
            items_end = ri
            if totals_end < 0:
                totals_end = ri
        if norm == "TAX" or "TOTALTAX" in norm:
            if totals_end >= 0 and totals_end < ri:
                totals_end = ri
        # TOTAL row: exclude "TOTAL NUMBER OF ITEMS SOLD" (that's item count, not amount)
        if ("TOTAL" in norm or "TOTA" in norm) and "SUB" not in norm:
            if "ITEMSSOLD" in norm or "NUMBEROFITEMS" in norm:
                continue
            if ri > (items_end if items_end >= 0 else -1):
                totals_end = ri
    if items_end < 0:
        items_end = len(rows)
    if totals_end < 0:
        totals_end = items_end
    # When Member not found (OCR typo), header = all rows before items_start
    if header_end == 0 and items_end >= 0:
        items_start = -1
        for ri in range(len(rows)):
            if ri < items_end and _is_item_row_physical(rows[ri]):
                items_start = ri
                break
        if items_start >= 0:
            header_end = items_start
    return header_end, items_end, totals_end, membership_id


def _detect_x_boundaries(rows: List[List[Dict]], items_start: int, items_end: int) -> Tuple[float, float]:
    xs: List[float] = []
    for ri in range(items_start, items_end + 1):
        if ri >= len(rows) or not _is_item_row_physical(rows[ri]):
            continue
        for b in rows[ri]:
            xs.append(b.get("center_x", b.get("x", 0)))
    if len(xs) < 2:
        return X_SKU_NAME_FALLBACK, X_NAME_AMOUNT_FALLBACK
    xs = sorted(set(xs))
    gaps: List[Tuple[float, float, float]] = []
    for i in range(len(xs) - 1):
        g = xs[i + 1] - xs[i]
        gaps.append((g, xs[i], xs[i + 1]))
    gaps.sort(key=lambda t: -t[0])
    if not gaps:
        return X_SKU_NAME_FALLBACK, X_NAME_AMOUNT_FALLBACK
    b1 = (gaps[0][1] + gaps[0][2]) / 2
    x_sku_name = gaps[0][1]
    x_name_amount = b1
    if x_sku_name >= x_name_amount - 0.02:
        return X_SKU_NAME_FALLBACK, X_NAME_AMOUNT_FALLBACK
    return x_sku_name, x_name_amount


def _is_discount_row(row: List[Dict]) -> bool:
    """Discount line: / SKU on left, negative amount (e.g. 2.40-) on right."""
    row_text = " ".join(b.get("text", "") for b in row)
    if "/" not in row_text:
        return False
    for b in row:
        if b.get("is_amount"):
            val = _parse_amount_value(b)
            if val is not None and val < 0:
                return True
        elif re.search(r"\d+\.\d{2}\s*-", (b.get("text") or "")):
            return True
    return False


def _get_discount_target_sku(row: List[Dict]) -> Optional[str]:
    """Extract SKU after / from discount row. '0000369385 / 990929' -> 990929. '189 143' -> 189143."""
    for b in row:
        t = (b.get("text") or "").strip()
        m = re.search(r"/\s*(\d{4,7})\s*$", t)
        if m:
            return m.group(1)
        m = re.search(r"/\s*(\d+)\s+(\d+)", t)  # "189 143" or "1891 143"
        if m:
            return m.group(1) + m.group(2)
    return None


def _find_matching_sku_for_discount(extracted: str, sku_to_idx: Dict[str, int]) -> Optional[int]:
    """Match discount SKU to item. Handles OCR split: 189143 vs 1891143 (match by suffix)."""
    if extracted in sku_to_idx:
        return sku_to_idx[extracted]
    if len(extracted) >= 3:
        suffix = extracted[-3:]
        for sku, idx in sku_to_idx.items():
            if sku.endswith(suffix) or sku == extracted:
                return idx
    return None


def _get_discount_amount(row: List[Dict], x_name_amount: float) -> Optional[float]:
    for b in row:
        if b.get("center_x", b.get("x", 0)) >= x_name_amount - 0.02:
            val = _parse_amount_value(b)
            if val is not None and val < 0:
                return val
    return None


def _extract_product_from_row(row: List[Dict], x_name_amount: float) -> Tuple[Optional[str], Optional[float]]:
    name_parts: List[str] = []
    amount_val: Optional[float] = None
    for b in row:
        cx = b.get("center_x", b.get("x", 0))
        t = (b.get("text") or "").strip()
        if not t or re.match(r"^E+$", t, re.I):
            continue
        if cx >= x_name_amount - 0.02:
            val = _parse_amount_value(b)
            if val is not None and 0.01 <= val <= 9999.99:
                amount_val = val
                break
    for b in row:
        cx = b.get("center_x", b.get("x", 0))
        t = (b.get("text") or "").strip()
        if not t or re.match(r"^E+$", t, re.I):
            continue
        if cx < x_name_amount - 0.02 and not _is_amount_block(b):
            if _is_ocr_noise_word(t):
                continue
            m = SKU_PATTERN.match(t)
            if m:
                name_part = (m.group(2) or "").strip()
                if name_part and not re.match(r"^\d+\.\d{2}$", name_part):
                    name_parts.append(name_part)
            elif not re.match(r"^\d+\.\d{2}$", t):
                name_parts.append(t)
    product_name = _clean_product_name(" ".join(name_parts).strip())
    return product_name if product_name else None, amount_val


def _extract_products_from_row_multi(
    row: List[Dict], x_name_amount: float, row_id: int
) -> List[Tuple[str, float, str, Optional[str]]]:
    """When row has multiple amount blocks (e.g. BANANAS 1.99 + LONG PEPPERS 4.99), split by Y."""
    amount_blocks = [
        b for b in row
        if b.get("center_x", b.get("x", 0)) >= x_name_amount - 0.02
        and _parse_amount_value(b) is not None
        and 0.01 <= (_parse_amount_value(b) or 0) <= 9999.99
    ]
    if len(amount_blocks) <= 1:
        return []
    name_blocks = [
        b for b in row
        if b.get("center_x", b.get("x", 0)) < x_name_amount - 0.02
        and not _is_amount_block(b)
        and (b.get("text") or "").strip()
        and not re.match(r"^E+$", (b.get("text") or ""), re.I)
    ]
    results: List[Tuple[str, float, str, Optional[str]]] = []
    LINE_Y_EPS = 0.012
    for amt_b in sorted(amount_blocks, key=lambda x: x.get("center_y", x.get("y", 0))):
        amt_y = amt_b.get("center_y", amt_b.get("y", 0))
        amt_val = _parse_amount_value(amt_b)
        if amt_val is None or amt_val < 0:
            continue
        closest = [
            nb for nb in name_blocks
            if abs(nb.get("center_y", nb.get("y", 0)) - amt_y) <= LINE_Y_EPS
        ]
        name_parts = []
        sku: Optional[str] = None
        for nb in sorted(closest, key=lambda x: x.get("center_x", x.get("x", 0))):
            t = (nb.get("text") or "").strip()
            if re.match(r"^\d+\.\d{2}$", t):
                continue
            if _is_ocr_noise_word(t):
                continue
            m = SKU_PATTERN.match(t)
            if m:
                if not sku and len(m.group(1)) >= 4:
                    sku = m.group(1)
                part = (m.group(2) or "").strip()
                if part:
                    name_parts.append(part)
            else:
                name_parts.append(t)
        name = _clean_product_name(" ".join(name_parts).strip())
        if name:
            raw = " ".join(b.get("text", "") for b in row).strip()
            results.append((name, amt_val, raw, sku))
    return results


def _extract_sku_from_row(row: List[Dict]) -> Optional[str]:
    """Get first SKU (4-7 digits) from row for discount matching."""
    for b in row:
        t = (b.get("text") or "").strip()
        m = re.match(r"^(\d{4,7})\s", t)
        if m:
            return m.group(1)
        m = re.search(r"\b(\d{4,7})\b", t)
        if m:
            return m.group(1)
    return None


def _extract_items_from_rows(rows: List[List[Dict]], header_end: int, items_end: int) -> List[ExtractedItem]:
    items: List[ExtractedItem] = []
    sku_to_idx: Dict[str, int] = {}
    if header_end > items_end:
        return items
    x_sku_name, x_name_amount = _detect_x_boundaries(rows, header_end, items_end)
    for ri in range(header_end, items_end + 1):
        if ri >= len(rows):
            break
        row = rows[ri]
        if _is_discount_row(row):
            target_sku = _get_discount_target_sku(row)
            discount = _get_discount_amount(row, x_name_amount)
            if target_sku and discount is not None and items:
                idx = _find_matching_sku_for_discount(target_sku, sku_to_idx)
                if idx is not None:
                    prev = items[idx]
                    unit_price = prev.line_total
                    new_total = round(unit_price + discount, 2)
                    items[idx] = ExtractedItem(
                        product_name=_clean_product_name(prev.product_name), line_total=new_total,
                        amount_block_id=prev.amount_block_id, row_id=prev.row_id, quantity=1, unit=None,
                        unit_price=unit_price, on_sale=True, confidence=prev.confidence, raw_text=prev.raw_text,
                    )
            continue
        if not _is_item_row_physical(row):
            continue
        multi = _extract_products_from_row_multi(row, x_name_amount, ri)
        if multi:
            for name, amt, raw, sku in multi:
                if sku:
                    sku_to_idx[sku] = len(items)
                items.append(ExtractedItem(
                    product_name=name, line_total=amt, amount_block_id=ri, row_id=ri,
                    quantity=1, unit=None, unit_price=None, on_sale=False, confidence=1.0, raw_text=raw,
                ))
        else:
            product_name, amount_val = _extract_product_from_row(row, x_name_amount)
            if not product_name or amount_val is None:
                continue
            raw_text = " ".join(b.get("text", "") for b in row).strip()
            sku = _extract_sku_from_row(row)
            if sku:
                sku_to_idx[sku] = len(items)
            items.append(ExtractedItem(
                product_name=product_name, line_total=amount_val, amount_block_id=ri, row_id=ri,
                quantity=1, unit=None, unit_price=None, on_sale=False, confidence=1.0, raw_text=raw_text,
            ))
    return items


def _extract_totals_from_rows(rows: List[List[Dict]], items_end: int, totals_end: int) -> Tuple[Optional[float], List[Dict], List[Dict], Optional[float]]:
    subtotal = tax_amount = total = None
    tax_list: List[Dict] = []
    fees: List[Dict] = []
    for ri in range(items_end, min(totals_end + 1, len(rows))):
        row = rows[ri]
        row_text = " ".join(b.get("text", "") for b in row).strip().upper()
        norm = re.sub(r"[.\s\-_]", "", row_text)
        has_items_sold = "ITEMSSOLD" in norm or "NUMBEROFITEMS" in norm
        for b in row:
            amt = _parse_amount_value(b)
            if amt is None or amt < 0:
                continue
            # ITEMS SOLD row: amount is integer (e.g. 13) = item count, not dollars; skip
            if has_items_sold and abs(amt - round(amt)) < 0.001:
                continue
            if "SUBTOTAL" in norm:
                subtotal = amt
            elif norm == "TAX" or "TOTALTAX" in norm:
                tax_amount = amt
            elif ("TOTAL" in norm or "TOTA" in norm) and "SUB" not in norm and "TAX" not in row_text:
                total = amt
    if tax_amount is not None and tax_amount != 0:
        tax_list = [{"label": "TAX", "amount": round(tax_amount, 2)}]
    return subtotal, tax_list, fees, total


def _extract_store_from_header(rows: List[List[Dict]], header_end: int) -> Optional[str]:
    for ri in range(min(header_end, len(rows))):
        for b in rows[ri]:
            t = (b.get("text") or "").strip()
            if not t or "Member" in t:
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
            if re.search(r"\d+\s+[A-Z0-9].*(\bAVE\b|\bST\b|\bRD\b|\bBLVD\b|\bDR\b|\bDRIVE\b)", t, re.I):
                addr_blocks.append((b.get("center_y", b.get("y", 0)), t))
            elif re.search(r",\s*[A-Z]{2}\s+[0-9]{5}", t) or re.search(r"^[A-Za-z]+,?\s+[A-Z]{2}\s+[0-9]{5}", t):
                addr_blocks.append((b.get("center_y", b.get("y", 0)), t))
    if not addr_blocks:
        return None
    addr_blocks.sort(key=lambda x: x[0])
    return ", ".join(t for _, t in addr_blocks)


def _infer_currency_from_address(address: Optional[str], store: Optional[str]) -> str:
    text = f"{address or ''} {store or ''}".upper()
    if re.search(r"\bON\b|\bBC\b|\bAB\b|\bQC\b|CANADA", text):
        return "CAD"
    return "USD"


def process_costco_us_physical(
    blocks: List[Dict[str, Any]],
    store_config: Optional[Dict[str, Any]] = None,
    merchant_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Process Costco US physical receipt (OCR blocks → rule-based extraction)."""
    if not blocks:
        return _empty_result(store_config, merchant_name, ["No blocks provided"], blocks=blocks)
    rows = _blocks_to_rows(blocks)
    header_end, items_end, totals_end, membership_id = _find_region_boundaries(rows)
    items = _extract_items_from_rows(rows, header_end, items_end - 1 if items_end >= 0 else len(rows) - 1)
    subtotal_val, tax_list, fees, total_val = _extract_totals_from_rows(rows, items_end, totals_end)
    total_tax = sum(t["amount"] for t in tax_list)
    items_sum = sum(i.line_total for i in items)
    validation_details: Dict[str, Any] = {
        "items_sum_check": {"passed": False, "calculated": items_sum, "expected": subtotal_val, "difference": 0},
        "totals_sum_check": {"passed": False},
        "passed": False,
    }
    error_log: List[str] = []
    if subtotal_val is not None:
        diff = round(abs(items_sum - subtotal_val), 2)
        validation_details["items_sum_check"] = {"passed": diff <= 0.03, "calculated": round(items_sum, 2), "expected": subtotal_val, "difference": diff}
        if diff > 0.03:
            error_log.append(f"Items sum mismatch: calculated {items_sum:.2f} vs subtotal {subtotal_val}")
    if subtotal_val is not None and total_val is not None:
        calculated = round(subtotal_val + total_tax + sum(f.get("amount", 0) for f in fees), 2)
        diff = round(abs(calculated - total_val), 2)
        validation_details["totals_sum_check"] = {"passed": diff <= 0.03, "calculated": calculated, "expected": total_val, "difference": diff, "breakdown": {"subtotal": subtotal_val, "fees": 0, "tax": total_tax, "sum": calculated}}
        validation_details["passed"] = validation_details["items_sum_check"]["passed"] and validation_details["totals_sum_check"]["passed"]
        if diff > 0.03:
            error_log.append(f"Totals mismatch: calculated {calculated} vs total {total_val}")
    elif total_val is not None:
        validation_details["totals_sum_check"] = {"passed": None, "reason": "no_subtotal"}
        error_log.append("Subtotal not found")
    else:
        validation_details["totals_sum_check"] = {"passed": None, "reason": "no_total"}
        if items_end < 0:
            error_log.append("SUBTOTAL not found")
        if total_val is None:
            error_log.append("TOTAL not found")
    if not validation_details["passed"] and not error_log:
        error_log.append("Validation failed")
    store_name = _extract_store_from_header(rows, header_end) or merchant_name or "COSTCO WHOLESALE"
    address = _extract_address_from_header(rows, header_end)
    currency = _infer_currency_from_address(address, store_name)
    chain_id = (store_config or {}).get("chain_id", "Costco_USA")
    result = {
        "success": validation_details["passed"],
        "method": "costco_us",
        "chain_id": chain_id,
        "store": store_name,
        "address": address,
        "currency": currency,
        "membership": membership_id,
        "error_log": error_log,
        "items": [{"product_name": i.product_name, "line_total": int(round(i.line_total * 100)), "quantity": 1, "unit": None, "unit_price": int(round(i.unit_price * 100)) if i.unit_price is not None else None, "on_sale": i.on_sale, "confidence": i.confidence, "raw_text": i.raw_text} for i in items],
        "totals": {"subtotal": subtotal_val, "tax": tax_list, "fees": fees, "total": total_val},
        "validation": validation_details,
        "regions_y_bounds": {},
        "amount_column": {},
        "ocr_and_regions": {},
        "ocr_blocks": blocks,
    }
    return truncate_floats_in_result(result, precision=5)


def _empty_result(
    store_config: Optional[Dict],
    merchant_name: Optional[str],
    errors: Optional[List[str]] = None,
    blocks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    result = {
        "success": False, "method": "costco_us",
        "chain_id": (store_config or {}).get("chain_id", "Costco_USA"),
        "store": merchant_name or "COSTCO WHOLESALE", "address": None, "currency": "USD",
        "membership": None, "error_log": errors or ["No blocks provided"], "items": [],
        "totals": {"subtotal": None, "tax": [], "fees": [], "total": None},
        "validation": {"items_sum_check": None, "totals_sum_check": None, "passed": False},
        "regions_y_bounds": {}, "amount_column": {}, "ocr_and_regions": {},
        "ocr_blocks": blocks if blocks is not None else [],
    }
    return truncate_floats_in_result(result, precision=5)
