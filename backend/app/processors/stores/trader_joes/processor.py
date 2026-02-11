"""
Trader Joe's Receipt Processor: Rule-based parser for Trader Joe's receipts.

Structure (top to bottom):
- Header: TRADER JOE'S, address, phone, SALE TRANSACTION
- Items: Product name + price (no SKU, simple format)
- Totals: Tax → Balance to pay (total)
- Payment: Card info, authorization, transaction details

Trader Joe's specifics:
1. No SKU codes (unlike Costco)
2. Simple item format: "PRODUCT NAME" + "$X.XX" right-aligned
3. Tax line shows base and rate: "Tax: $X.XX @ 10.2%"
4. "Balance to pay" = total (not "SUBTOTAL")
5. "T" prefix on taxable items (e.g. "T SPARKL FRENCH PINK LEMAD")
6. Detailed transaction info: Store, Till, Trans#, Date/Time, Cashier
"""
import re
import logging
from typing import Dict, Any, List, Optional, Tuple

from ...core.structures import ExtractedItem
from ....utils.float_precision import truncate_floats_in_result

logger = logging.getLogger(__name__)

ROW_Y_EPS = 0.015  # Smaller epsilon for Trader Joe's compact layout
PRICE_X_MIN = 0.55  # Prices are right-aligned, typically x > 0.55 (lowered from 0.60 to handle various receipt formats)


def _blocks_to_rows(blocks: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Group blocks into rows by y coordinate."""
    if not blocks:
        return []
    
    def sort_key(b):
        return (b.get("page_number", 1), b.get("center_y", b.get("y", 0)), b.get("center_x", b.get("x", 0)))
    
    sorted_blocks = sorted(blocks, key=sort_key)
    rows: List[List[Dict]] = []
    current_row: List[Dict] = []
    last_page = None
    
    for b in sorted_blocks:
        page = b.get("page_number", 1)
        y = b.get("center_y", b.get("y", 0))
        
        # Start new row when page changes or y differs from row's reference y
        row_ref_y = current_row[0].get("center_y", current_row[0].get("y", 0)) if current_row else None
        
        # Special rule for item rows: if current row already has a price, new price starts new row
        row_has_price = any(blk.get("center_x", 0) >= PRICE_X_MIN and blk.get("is_amount") for blk in current_row) if current_row else False
        new_block_is_price = b.get("center_x", b.get("x", 0)) >= PRICE_X_MIN and b.get("is_amount")
        
        if last_page is not None and (
            page != last_page 
            or (row_ref_y is not None and abs(y - row_ref_y) > ROW_Y_EPS)
            or (row_has_price and new_block_is_price)  # Don't merge two price blocks
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
    """Parse amount from block."""
    amt = block.get("amount")
    text = (block.get("text") or "").strip()
    
    # Check for negative (rare for TJ's)
    is_negative = text.endswith("-")
    
    if amt is not None:
        val = float(amt)
        return -abs(val) if is_negative else val
    
    # Parse from text: $X.XX format
    m = re.search(r"\$(\d+\.\d{2})", text)
    if m:
        val = float(m.group(1))
        return -abs(val) if is_negative else val
    
    return None


def _is_price_block(block: Dict) -> bool:
    """Check if block is a price (right-aligned, has amount)."""
    cx = block.get("center_x", block.get("x", 0))
    amt = _parse_amount_value(block)
    return cx >= PRICE_X_MIN and amt is not None and amt > 0


def _parse_quantity_unit_price(product_name: str) -> Tuple[Optional[int], Optional[float], str]:
    """
    Parse quantity and unit price from product name if present.
    
    Format: "2@ $3.99 PRODUCT NAME" or "5 @ $0.23 PRODUCT NAME"
    
    Returns: (quantity, unit_price, cleaned_name)
    - If pattern not found: (None, None, original_name)
    - If pattern found: (quantity, unit_price, name_without_quantity_info)
    """
    # Pattern: "数量 @ $单价" at the beginning
    # Examples: "2@ $3.99", "5 @ $0.23", "2 @$3.99"
    pattern = r"^(\d+)\s*@\s*\$(\d+\.\d{2})\s+"
    match = re.match(pattern, product_name)
    
    if match:
        quantity = int(match.group(1))
        unit_price = float(match.group(2))
        cleaned_name = product_name[match.end():].strip()
        return quantity, unit_price, cleaned_name
    
    return None, None, product_name


def _find_region_boundaries(rows: List[List[Dict]]) -> Tuple[int, int, int]:
    """
    Find region boundaries for Trader Joe's receipt.
    Returns: (header_end, items_end, totals_end)
    
    Note: totals_end should include the "TOTAL PURCHASE" line at the bottom,
    not just "Balance to pay" in the middle.
    """
    header_end = 0
    items_end = -1
    totals_end = -1
    
    for ri, row in enumerate(rows):
        texts = [b.get("text", "").strip() for b in row]
        row_text = " ".join(texts).upper()
        
        # Header ends at "SALE TRANSACTION" (fuzzy match for OCR errors like "SALF")
        if "SALE TRANSACTION" in row_text or ("SALE" in row_text and "TRANSACTION" in row_text):
            header_end = ri + 1
        # OCR error tolerance: "SALF TRANSACTION" (E->F), "SAIL TRANSACTION" (E->I)
        elif re.search(r"\bSA[LI][EF]\s+TRANSACTION", row_text):
            header_end = ri + 1
        
        # Items end when we see "Tax:" or "TAX"
        if re.search(r"\bTAX\s*[:@]", row_text, re.I):
            if items_end < 0:
                items_end = ri
        
        # Alternative: Items end at "Balance to pay" or "Items in Transaction"
        # (for receipts without explicit tax line)
        if items_end < 0 and ("BALANCE" in row_text and "PAY" in row_text):
            items_end = ri
        if items_end < 0 and ("ITEMS IN TRANSACTION" in row_text or "ITEMS" in row_text and "TRANSACTION" in row_text):
            items_end = ri
        
        # Totals section continues until we see "TOTAL PURCHASE" (the actual total at bottom)
        # or other end markers like cashier name, store footer
        if "TOTAL" in row_text and "PURCHASE" in row_text:
            totals_end = ri
            break
        
        # Alternative end: CUSTOMER COPY (but keep looking for TOTAL PURCHASE first)
        if "CUSTOMER COPY" in row_text and totals_end < 0:
            totals_end = ri
    
    if items_end < 0:
        items_end = len(rows)
    if totals_end < 0:
        totals_end = min(len(rows) - 1, items_end + 15)  # Extended range to catch TOTAL PURCHASE
    
    return header_end, items_end, totals_end


def _extract_items_from_rows(rows: List[List[Dict]], items_start: int, items_end: int) -> List[ExtractedItem]:
    """
    Extract items from Trader Joe's receipt.
    Format: "PRODUCT NAME" + "$X.XX" (right-aligned)
    "T" prefix indicates taxable item.
    
    Note: Some rows may contain multiple items (OCR merged adjacent items).
    Strategy: Find all price blocks, then match each price with its closest left name block.
    """
    items: List[ExtractedItem] = []
    
    for ri in range(items_start, min(items_end, len(rows))):
        if ri >= len(rows):
            break
        
        row = rows[ri]
        if not row:
            continue
        
        raw_row = " ".join(b.get("text", "") for b in row)
        
        # Separate blocks into name blocks (left) and price blocks (right)
        name_blocks: List[Dict] = []
        price_blocks: List[Dict] = []
        
        for b in row:
            text = (b.get("text") or "").strip()
            if not text:
                continue
            
            if _is_price_block(b):
                amt = _parse_amount_value(b)
                if amt and amt > 0:
                    price_blocks.append(b)
            else:
                name_blocks.append(b)
        
        # If no prices found, skip this row
        if not price_blocks:
            continue
        
        # Strategy: Match each price with name blocks to its left
        # If we have N prices, we try to extract N items
        if len(price_blocks) == 1:
            # Simple case: one price, all names go to it
            if not name_blocks:
                continue
            
            product_name = " ".join(b.get("text", "").strip() for b in name_blocks).strip()
            price = _parse_amount_value(price_blocks[0])
            
            # Skip if name looks like a total/tax line
            if any(kw in product_name.upper() for kw in ["TAX", "TOTAL", "BALANCE", "SUBTOTAL", "VISA", "ITEMS IN"]):
                continue
            
            # Check if taxable (T prefix)
            is_taxable = product_name.upper().startswith("T ")
            if is_taxable:
                product_name = product_name[2:].strip()
            
            # Parse quantity and unit price if present (format: "2@ $3.99 NAME")
            quantity, unit_price, cleaned_name = _parse_quantity_unit_price(product_name)
            if quantity and unit_price:
                product_name = cleaned_name
            else:
                quantity = 1
                unit_price = None
            
            items.append(ExtractedItem(
                product_name=product_name,
                line_total=price,
                amount_block_id=ri,
                row_id=ri,
                quantity=quantity,
                unit_price=unit_price,
                unit=None,
                raw_text=raw_row,
                confidence=1.0,
                on_sale=False
            ))
        else:
            # Multiple prices: try to split name blocks between them
            # Heuristic: If we have N prices and M name blocks, split names evenly
            # Better heuristic: Each price likely corresponds to 1 name block before it
            if len(name_blocks) >= len(price_blocks):
                # Try to pair each price with its closest left name
                for i, price_block in enumerate(price_blocks):
                    if i < len(name_blocks):
                        product_name = name_blocks[i].get("text", "").strip()
                        price = _parse_amount_value(price_block)
                        
                        if not product_name or price is None or price <= 0:
                            continue
                        
                        # Check if taxable
                        is_taxable = product_name.upper().startswith("T ")
                        if is_taxable:
                            product_name = product_name[2:].strip()
                        
                        # Parse quantity and unit price if present
                        quantity, unit_price, cleaned_name = _parse_quantity_unit_price(product_name)
                        if quantity and unit_price:
                            product_name = cleaned_name
                        else:
                            quantity = 1
                            unit_price = None
                        
                        items.append(ExtractedItem(
                            product_name=product_name,
                            line_total=price,
                            amount_block_id=ri,
                            row_id=ri,
                            quantity=quantity,
                            unit_price=unit_price,
                            unit=None,
                            raw_text=raw_row,
                            confidence=0.8,  # Lower confidence for multi-item rows
                            on_sale=False
                        ))
            else:
                # More prices than names? OCR issue, use what we have
                # Merge all names and use first price
                if name_blocks:
                    product_name = " ".join(b.get("text", "").strip() for b in name_blocks).strip()
                    price = _parse_amount_value(price_blocks[0])
                    
                    # Parse quantity and unit price if present
                    quantity, unit_price, cleaned_name = _parse_quantity_unit_price(product_name)
                    if quantity and unit_price:
                        product_name = cleaned_name
                    else:
                        quantity = 1
                        unit_price = None
                    
                    items.append(ExtractedItem(
                        product_name=product_name,
                        line_total=price,
                        amount_block_id=ri,
                        row_id=ri,
                        quantity=quantity,
                        unit_price=unit_price,
                        unit=None,
                        raw_text=raw_row,
                        confidence=0.6,
                        on_sale=False
                    ))
    
    return items


def _extract_totals_from_rows(rows: List[List[Dict]], items_end: int, totals_end: int) -> Tuple[Optional[float], List[Dict], Optional[float]]:
    """
    Extract totals from Trader Joe's receipt.
    - Tax line: "Tax: $X.XX @ 10.2%" → "$0.XX"
    - Total line: "TOTAL PURCHASE $X.XX" (at bottom, after payment info)
    
    Note: "Balance to pay" is NOT the final total, it's just an intermediate amount.
    The actual total is "TOTAL PURCHASE" at the bottom of the receipt.
    """
    tax_amount = None
    total = None
    
    for ri in range(items_end, min(totals_end + 1, len(rows))):
        if ri >= len(rows):
            break
        
        row = rows[ri]
        texts = [b.get("text", "").strip() for b in row]
        row_text = " ".join(texts).upper()
        
        # Tax line
        if "TAX" in row_text and ("@" in row_text or ":" in row_text):
            for b in row:
                amt = _parse_amount_value(b)
                if amt is not None and amt > 0 and amt < 100:  # Tax should be small
                    # Take the rightmost/smallest amount (the actual tax, not the base)
                    if tax_amount is None or amt < tax_amount:
                        tax_amount = amt
        
        # Total line: "TOTAL PURCHASE" (the actual total at bottom)
        if "TOTAL" in row_text and "PURCHASE" in row_text:
            for b in row:
                text = (b.get("text") or "").strip()
                amt = _parse_amount_value(b)
                # Only accept properly formatted amounts (must contain "$" or have decimal point)
                # Reject OCR errors like "****0729" being marked as amount
                if amt is not None and amt > 0 and ("$" in text or "." in text):
                    total = amt
                    break
        
        # Fallback: "Balance to pay" (only use if TOTAL PURCHASE not found)
        if total is None and ("BALANCE" in row_text or ("PAY" in row_text and any("$" in t for t in texts))):
            for b in row:
                text = (b.get("text") or "").strip()
                amt = _parse_amount_value(b)
                if amt is not None and amt > 0 and ("$" in text or "." in text):
                    total = amt
    
    tax_list = []
    if tax_amount is not None and tax_amount > 0:
        tax_list = [{"label": "TAX", "amount": round(tax_amount, 2)}]
    
    return None, tax_list, total  # No separate subtotal for TJ's


def _extract_store_from_header(rows: List[List[Dict]], header_end: int) -> Optional[str]:
    """Extract store number from header (e.g., 'Store #0131')."""
    for ri in range(min(header_end + 1, len(rows))):
        row = rows[ri]
        texts = [b.get("text", "") for b in row]
        row_text = " ".join(texts)
        
        # Look for "Store #XXXX" or "S ore #XXXX" (OCR error)
        m = re.search(r"[Ss]\s*ore\s*#(\d{4})", row_text, re.I)
        if m:
            return f"Store #{m.group(1)}"
        
        # Alternative: "#XXXX" pattern in header
        m = re.search(r"#(\d{4})", row_text)
        if m:
            return f"Store #{m.group(1)}"
    
    return None


def _extract_address_from_header(rows: List[List[Dict]], header_end: int) -> Optional[str]:
    """Extract address from header (street, city, state zip only - exclude store# and phone)."""
    address_parts = []
    
    for ri in range(min(header_end + 1, len(rows))):
        row = rows[ri]
        
        # Skip brand name line
        row_text = " ".join(b.get("text", "") for b in row).strip()
        if "TRADER" in row_text.upper() and "JOE" in row_text.upper():
            continue
        
        # Skip hours/schedule line
        if "OPEN" in row_text.upper() or ("AM" in row_text.upper() and "PM" in row_text.upper()):
            continue
        
        # For each block in the row, check if it contains address info (exclude store# and phone)
        for b in row:
            text = b.get("text", "").strip()
            if not text:
                continue
            
            # Skip store number block (e.g., "S ore #0131 - 425-641-5069")
            if re.search(r"[Ss]\s*ore\s*#\d{4}", text, re.I):
                continue
            
            # Skip phone number block
            if re.search(r"\d{3}[-\s]\d{3}[-\s]\d{4}", text):
                continue
            
            # Skip TRADER JOE'S
            if "TRADER" in text.upper() and "JOE" in text.upper():
                continue
            
            # Look for street address (numbers + street name)
            if re.search(r"\d{3,5}\s+[A-Z]", text):
                address_parts.append(text)
            # Look for city, state (e.g., "Bellevue, WA")
            elif re.search(r"[A-Z][a-z]+,\s*[A-Z]{2}", text):
                address_parts.append(text)
            # Look for zip code alone
            elif re.search(r"^\d{5}$", text):
                address_parts.append(text)
    
    return " ".join(address_parts) if address_parts else None


def _extract_transaction_info(rows: List[List[Dict]], totals_end: int) -> Dict[str, Any]:
    """Extract transaction details: Store#, Till, Trans#, Date/Time, Cashier."""
    info = {}
    
    for ri in range(totals_end, min(len(rows), totals_end + 15)):
        row = rows[ri]
        texts = [b.get("text", "") for b in row]
        row_text = " ".join(texts)
        
        # Store number
        m = re.search(r"STORE\s*(\d+)|#(\d{4})", row_text, re.I)
        if m and "store_number" not in info:
            info["store_number"] = m.group(1) or m.group(2)
        
        # Till number
        m = re.search(r"TILL.*?(\d+)", row_text, re.I)
        if m and "till" not in info:
            info["till"] = m.group(1)
        
        # Transaction number
        m = re.search(r"TRANS.*?(\d{4,6})|^\s*(\d{5,6})\s*$", row_text, re.I)
        if m and "transaction_number" not in info:
            info["transaction_number"] = m.group(1) or m.group(2)
        
        # Date/Time
        m = re.search(r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s+(\d{1,2})[:\s](\d{2})", row_text)
        if m and "datetime" not in info:
            info["datetime"] = f"{m.group(1)} {m.group(2)}:{m.group(3)}"
        
        # Cashier name
        if "." in row_text and len(row_text) < 30 and not any(kw in row_text.upper() for kw in ["STORE", "TILL", "TRANS", "DATE"]):
            if "cashier" not in info:
                info["cashier"] = row_text.strip()
    
    return info


def _build_ocr_section_rows(rows: List[List[Dict]], header_end: int, items_end: int, totals_end: int) -> Dict[str, Any]:
    """Build OCR section rows with coordinate data for debugging/visualization."""
    def row_to_blocks(row: List[Dict]) -> List[Dict]:
        return [
            {
                "x": int(b.get("center_x", 0) * 10000),
                "y": int(b.get("center_y", 0) * 10000),
                "is_amount": b.get("is_amount", False),
                "text": (b.get("text") or "")[:120]
            }
            for b in row
        ]
    
    header_rows = [{"row_id": i, "blocks": row_to_blocks(rows[i])} for i in range(header_end) if i < len(rows)]
    item_end_idx = items_end if items_end >= 0 else len(rows)
    item_rows = [{"row_id": i, "blocks": row_to_blocks(rows[i])} for i in range(header_end, item_end_idx) if i < len(rows)]
    totals_rows = [{"row_id": i, "blocks": row_to_blocks(rows[i])} for i in range(item_end_idx, min(totals_end + 1, len(rows))) if i < len(rows)]
    payment_rows = [{"row_id": i, "blocks": row_to_blocks(rows[i])} for i in range(totals_end + 1, len(rows))] if totals_end + 1 < len(rows) else []
    
    return {
        "section_rows_detail": [
            {"section": "header", "label": "Store info", "rows": header_rows},
            {"section": "items", "label": "Purchased items", "rows": item_rows},
            {"section": "totals", "label": "Tax and Total", "rows": totals_rows},
            {"section": "payment", "label": "Payment method", "rows": payment_rows},
        ]
    }


def process_trader_joes(
    blocks: List[Dict[str, Any]],
    store_config: Optional[Dict[str, Any]] = None,
    merchant_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Process Trader Joe's receipt with rule-based logic."""
    if not blocks:
        return _empty_result(store_config, merchant_name, blocks)
    
    rows = _blocks_to_rows(blocks)
    header_end, items_end, totals_end = _find_region_boundaries(rows)
    
    items = _extract_items_from_rows(rows, header_end, items_end)
    _, tax_list, total = _extract_totals_from_rows(rows, items_end, totals_end)
    
    total_tax = sum(t["amount"] for t in tax_list)
    items_sum = sum(i.line_total for i in items)
    
    # Calculate subtotal (items sum)
    subtotal = round(items_sum, 2)
    
    # Validation
    validation_details: Dict[str, Any] = {
        "items_sum_check": {"passed": True, "calculated": subtotal, "note": "Items sum used as subtotal"},
        "totals_sum_check": {"passed": False},
        "passed": False,
    }
    
    if total is not None:
        calculated = round(subtotal + total_tax, 2)
        diff = round(abs(calculated - total), 2)
        validation_details["totals_sum_check"] = {
            "passed": diff <= 0.02,
            "calculated": calculated,
            "expected": total,
            "difference": diff,
            "breakdown": {"subtotal": subtotal, "tax": total_tax, "sum": calculated},
        }
        validation_details["passed"] = validation_details["totals_sum_check"]["passed"]
    else:
        validation_details["totals_sum_check"] = {"passed": None, "reason": "no_total"}
    
    error_log: List[str] = []
    if not validation_details["passed"]:
        tc = validation_details.get("totals_sum_check", {})
        if isinstance(tc, dict) and tc.get("passed") is False and tc.get("difference", 0) > 0.02:
            error_log.append(f"Totals mismatch: calculated {tc.get('calculated')} vs total {total}")
        if tc.get("reason") == "no_total":
            error_log.append("Total not found")
        if not error_log:
            error_log.append("Validation failed")
    
    store_name = _extract_store_from_header(rows, header_end) or merchant_name or "TRADER JOE'S"
    address = _extract_address_from_header(rows, header_end)
    trans_info = _extract_transaction_info(rows, totals_end)
    
    result = {
        "success": validation_details["passed"],
        "method": "trader_joes",
        "chain_id": "Trader_Joes",
        "store": store_name,
        "address": address,
        "currency": "USD",
        "membership": None,
        "error_log": error_log,
        "items": [
            {
                "product_name": item.product_name,
                "line_total": int(round(item.line_total * 100)),
                "quantity": int(item.quantity),
                "unit": item.unit,
                "unit_price": int(round(item.unit_price * 100)) if item.unit_price else None,
                "on_sale": item.on_sale,
                "confidence": item.confidence,
                "raw_text": item.raw_text,
            }
            for item in items
        ],
        "totals": {"subtotal": subtotal, "tax": tax_list, "fees": [], "total": total},
        "validation": validation_details,
        "transaction_info": trans_info,
        "regions_y_bounds": {},
        "amount_column": {},
        "ocr_and_regions": _build_ocr_section_rows(rows, header_end, items_end, totals_end),
        "ocr_blocks": blocks,
    }
    
    # Truncate float values to 5 decimal places to save LLM tokens
    result = truncate_floats_in_result(result, precision=5)
    
    return result


def _empty_result(store_config: Optional[Dict], merchant_name: Optional[str], blocks: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "success": False,
        "method": "trader_joes",
        "chain_id": "Trader_Joes",
        "store": merchant_name or "TRADER JOE'S",
        "address": None,
        "currency": "USD",
        "membership": None,
        "error_log": ["No blocks provided"],
        "items": [],
        "totals": {"subtotal": None, "tax": [], "fees": [], "total": None},
        "validation": {"items_sum_check": None, "totals_sum_check": None, "passed": False},
        "transaction_info": {},
        "regions_y_bounds": {},
        "amount_column": {},
        "ocr_and_regions": {},
        "ocr_blocks": blocks if blocks is not None else [],
    }
    return truncate_floats_in_result(result, precision=5)
