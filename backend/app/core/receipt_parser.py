"""
Receipt parser: Extract structured data from OCR text.

Currently supports T&T Supermarket format.

TODO: Future improvement directions (deferred)
- Can call QWEN model to improve parsing accuracy
- Use RAG (Retrieval-Augmented Generation) to calibrate via receipt merchant name and address
- Improve accuracy of product name splitting, quantity extraction, price parsing
"""
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from decimal import Decimal, InvalidOperation
import logging

logger = logging.getLogger(__name__)


class ReceiptItem:
    """Parsed receipt item."""
    def __init__(self):
        self.raw_text: str = ""
        self.product_name: str = ""
        self.quantity: Optional[Decimal] = None
        self.unit: Optional[str] = None
        self.unit_price: Optional[Decimal] = None
        self.line_total: Optional[Decimal] = None
        self.is_on_sale: bool = False
        self.category: Optional[str] = None
        self.line_index: int = 0


class ParsedReceipt:
    """Parsed receipt data."""
    def __init__(self):
        self.merchant_name: Optional[str] = None
        self.merchant_id: Optional[int] = None
        self.purchase_time: Optional[datetime] = None
        self.currency_code: str = "USD"
        self.subtotal: Optional[Decimal] = None
        self.tax: Optional[Decimal] = None
        self.total: Optional[Decimal] = None
        self.item_count: int = 0
        self.payment_method: Optional[str] = None
        self.items: List[ReceiptItem] = []
        self.raw_text: str = ""


def parse_tt_supermarket(text: str, merchant_id: Optional[int] = None) -> ParsedReceipt:
    """
    Parse T&T Supermarket receipt.
    
    Parsing patterns:
    - Merchant: "T&T Supermarket US"
    - Date: "01/10/26 1:45:58 PM" or "01/10/2026 TIME: 14:47:15"
    - Total: "TOTAL\nVisa\n$22.77"
    - Items: Various formats of item lines
    """
    receipt = ParsedReceipt()
    receipt.raw_text = text
    lines = text.split('\n')
    
    # 1. Extract merchant name
    merchant_match = re.search(r'T&T\s+Supermarket\s+US', text, re.IGNORECASE)
    if merchant_match:
        receipt.merchant_name = "T&T Supermarket US"
        receipt.merchant_id = merchant_id
    
    # 2. Extract date and time
    # Try format 1: "01/10/26 1:45:58 PM"
    date_match1 = re.search(r'(\d{2}/\d{2}/\d{2})\s+(\d{1,2}):(\d{2}):(\d{2})\s+(AM|PM)', text, re.IGNORECASE)
    if date_match1:
        try:
            date_str = date_match1.group(1)
            hour = int(date_match1.group(2))
            minute = int(date_match1.group(3))
            second = int(date_match1.group(4))
            ampm = date_match1.group(5).upper()
            
            if ampm == "PM" and hour != 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0
            
            # Assume 20XX year
            if len(date_str.split('/')[2]) == 2:
                year = 2000 + int(date_str.split('/')[2])
            else:
                year = int(date_str.split('/')[2])
            
            month = int(date_str.split('/')[0])
            day = int(date_str.split('/')[1])
            
            receipt.purchase_time = datetime(year, month, day, hour, minute, second)
        except Exception as e:
            logger.warning(f"Failed to parse date format 1: {e}")
    
    # Try format 2: "DATE: 01/10/2026 TIME: 14:47:15"
    if not receipt.purchase_time:
        date_match2 = re.search(r'DATE:\s*(\d{2}/\d{2}/\d{4})\s+TIME:\s*(\d{2}):(\d{2}):(\d{2})', text, re.IGNORECASE)
        if date_match2:
            try:
                date_str = date_match2.group(1)
                hour = int(date_match2.group(2))
                minute = int(date_match2.group(3))
                second = int(date_match2.group(4))
                
                parts = date_str.split('/')
                month = int(parts[0])
                day = int(parts[1])
                year = int(parts[2])
                
                receipt.purchase_time = datetime(year, month, day, hour, minute, second)
            except Exception as e:
                logger.warning(f"Failed to parse date format 2: {e}")
    
    # 3. Extract total amount
    # Find amount after "TOTAL"
    total_patterns = [
        r'TOTAL\s+Visa\s+\$?(\d+\.\d{2})',
        r'TOTAL\s+\$?(\d+\.\d{2})',
        r'AMOUNT\s+TOTAL\s+USD\$\s*(\d+\.\d{2})',
        r'Total\s+Sales\s+amount\s+with\s+tax:\s+\$?(\d+\.\d{2})',
    ]
    
    for pattern in total_patterns:
        total_match = re.search(pattern, text, re.IGNORECASE)
        if total_match:
            try:
                receipt.total = Decimal(total_match.group(1))
                break
            except (InvalidOperation, ValueError):
                continue
    
    # 4. Extract payment method
    payment_match = re.search(r'(Visa|Mastercard|Cash|Credit\s+Card|Debit)', text, re.IGNORECASE)
    if payment_match:
        receipt.payment_method = payment_match.group(1).strip()
    
    # 5. Extract items
    # Item lines usually after category identifiers like "FOOD", "PRODUCE", "DELI"
    item_start_keywords = ['FOOD', 'PRODUCE', 'DELI', 'GROCERY', 'DAIRY']
    item_lines = []
    in_items_section = False
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # Check if entered item area
        if any(keyword in line for keyword in item_start_keywords):
            in_items_section = True
            continue
        
        # If encounter TOTAL, stop parsing items
        if 'TOTAL' in line.upper() and in_items_section:
            break
        
        # If in item area, try to parse item line
        if in_items_section:
            item = _parse_item_line(line, i)
            if item:
                item_lines.append(item)
        
        # Also try to find item patterns globally
        if not in_items_section:
            item = _parse_item_line(line, i)
            if item:
                item_lines.append(item)
    
    receipt.items = item_lines
    receipt.item_count = len(item_lines)
    
    # 6. Calculate subtotal (sum of all item line totals)
    calculated_total = Decimal('0')
    for item in item_lines:
        if item.line_total:
            calculated_total += item.line_total
    
    if calculated_total > 0:
        receipt.subtotal = calculated_total
        # If total exists and is greater than subtotal, calculate tax
        if receipt.total and receipt.total > calculated_total:
            receipt.tax = receipt.total - calculated_total
    
    # If total not found yet, use calculated total
    if not receipt.total and calculated_total > 0:
        receipt.total = calculated_total
    
    return receipt


def _parse_item_line(line: str, line_index: int) -> Optional[ReceiptItem]:
    """
    Parse a single item line.
    
    Supported formats:
    - "PRODUCT_NAME FP $X.XX"
    - "PRODUCT_NAME $X.XX"
    - "X.XX lb @ $X.XX/lb FP $X.XX"
    - "(SALE) PRODUCT_NAME FP $X.XX"
    """
    line = line.strip()
    if not line:
        return None
    
    # Skip obvious non-item lines
    skip_patterns = [
        r'^TOTAL',
        r'^Subtotal',
        r'^Tax',
        r'^Points',
        r'^Reference',
        r'^Trans:',
        r'^Terminal:',
        r'^CLERK',
        r'^INVOICE:',
        r'^REFERENCE:',
        r'^AMOUNT',
        r'^APPROVED',
        r'^AUTH CODE',
        r'^APPLICATION',
    ]
    
    for pattern in skip_patterns:
        if re.match(pattern, line, re.IGNORECASE):
            return None
    
    item = ReceiptItem()
    item.raw_text = line
    item.line_index = line_index
    
    # Check if promotional item
    is_on_sale = '(SALE)' in line.upper()
    item.is_on_sale = is_on_sale
    if is_on_sale:
        line = re.sub(r'\(SALE\)\s*', '', line, flags=re.IGNORECASE)
    
    # Extract amount: find $X.XX format
    price_matches = list(re.finditer(r'\$(\d+\.\d{2})', line))
    if not price_matches:
        # Try format without $ symbol
        price_matches = list(re.finditer(r'\b(\d+\.\d{2})\b', line))
    
    if price_matches:
        # Last one is usually line total (FP price)
        last_price = Decimal(price_matches[-1].group(1))
        item.line_total = last_price
        
        # If multiple prices, might be unit price and total price
        if len(price_matches) >= 2:
            # Second to last might be unit price
            second_last_price = Decimal(price_matches[-2].group(1))
            item.unit_price = second_last_price
        elif len(price_matches) == 1:
            item.unit_price = last_price
    
    # Extract quantity and unit (e.g., "1.20 lb @ $1.38/lb")
    qty_unit_match = re.search(r'(\d+\.?\d*)\s*(lb|kg|oz|g|ea|pcs?|ct)\s*@\s*\$?(\d+\.\d{2})/(?:lb|kg|oz|g|ea|pcs?|ct)', line, re.IGNORECASE)
    if qty_unit_match:
        try:
            item.quantity = Decimal(qty_unit_match.group(1))
            item.unit = qty_unit_match.group(2).lower()
            if not item.unit_price:
                item.unit_price = Decimal(qty_unit_match.group(3))
        except (InvalidOperation, ValueError):
            pass
    
    # Extract product name (after removing price, quantity, etc.)
    product_name = line
    
    # Remove price information
    product_name = re.sub(r'\$?\d+\.\d{2}', '', product_name)
    # Remove quantity and unit information
    product_name = re.sub(r'\d+\.?\d*\s*(?:lb|kg|oz|g|ea|pcs?|ct)\s*@\s*\$?\d+\.\d{2}/(?:lb|kg|oz|g|ea|pcs?|ct)', '', product_name, flags=re.IGNORECASE)
    # Remove "FP" marker
    product_name = re.sub(r'\bFP\b', '', product_name, flags=re.IGNORECASE)
    # Clean up extra spaces
    product_name = re.sub(r'\s+', ' ', product_name).strip()
    
    item.product_name = product_name
    
    # Simple category inference
    product_lower = product_name.lower()
    if any(word in product_lower for word in ['milk', 'cheese', 'dairy']):
        item.category = 'DAIRY'
    elif any(word in product_lower for word in ['onion', 'bok choy', 'yu choy', 'sprout', 'vegetable']):
        item.category = 'PRODUCE'
    elif any(word in product_lower for word in ['egg', 'bun', 'bread']):
        item.category = 'FOOD'
    else:
        item.category = 'GENERAL'
    
    # Only return if has product name or price
    if item.product_name or item.line_total:
        return item
    
    return None


def parse_receipt(text: str, merchant_hint: Optional[str] = None, merchant_id: Optional[int] = None) -> ParsedReceipt:
    """
    Parse receipt text, automatically identify merchant type.
    
    Args:
        text: Text extracted by OCR
        merchant_hint: Optional merchant hint
        merchant_id: Optional merchant ID
        
    Returns:
        ParsedReceipt object
    """
    text_upper = text.upper()
    
    # Select parser based on merchant characteristics
    if 'T&T' in text_upper or 'T AND T' in text_upper:
        return parse_tt_supermarket(text, merchant_id)
    
    # Default to T&T parser (can be extended)
    logger.warning("Unknown merchant format, using T&T parser as fallback")
    return parse_tt_supermarket(text, merchant_id)
