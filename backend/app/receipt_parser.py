"""
收据解析器：从 OCR 文本中提取结构化数据。

当前支持 T&T Supermarket 格式。

TODO: 未来改进方向（暂缓）
- 可以调用 QWEN 模型来改进解析准确率
- 使用 RAG（检索增强生成）通过小票的商店名称和地址进行校准
- 提升商品名称拆分、数量提取、价格解析的准确率
"""
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from decimal import Decimal, InvalidOperation
import logging

logger = logging.getLogger(__name__)


class ReceiptItem:
    """解析后的收据商品项。"""
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
    """解析后的收据数据。"""
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
    解析 T&T Supermarket 收据。
    
    解析模式：
    - Merchant: "T&T Supermarket US"
    - Date: "01/10/26 1:45:58 PM" 或 "01/10/2026 TIME: 14:47:15"
    - Total: "TOTAL\nVisa\n$22.77"
    - Items: 各种格式的商品行
    """
    receipt = ParsedReceipt()
    receipt.raw_text = text
    lines = text.split('\n')
    
    # 1. 提取商户名称
    merchant_match = re.search(r'T&T\s+Supermarket\s+US', text, re.IGNORECASE)
    if merchant_match:
        receipt.merchant_name = "T&T Supermarket US"
        receipt.merchant_id = merchant_id
    
    # 2. 提取日期时间
    # 尝试格式 1: "01/10/26 1:45:58 PM"
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
            
            # 假设是 20XX 年
            if len(date_str.split('/')[2]) == 2:
                year = 2000 + int(date_str.split('/')[2])
            else:
                year = int(date_str.split('/')[2])
            
            month = int(date_str.split('/')[0])
            day = int(date_str.split('/')[1])
            
            receipt.purchase_time = datetime(year, month, day, hour, minute, second)
        except Exception as e:
            logger.warning(f"Failed to parse date format 1: {e}")
    
    # 尝试格式 2: "DATE: 01/10/2026 TIME: 14:47:15"
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
    
    # 3. 提取总金额
    # 查找 "TOTAL" 后面的金额
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
    
    # 4. 提取支付方式
    payment_match = re.search(r'(Visa|Mastercard|Cash|Credit\s+Card|Debit)', text, re.IGNORECASE)
    if payment_match:
        receipt.payment_method = payment_match.group(1).strip()
    
    # 5. 提取商品项
    # 商品行通常在 "FOOD", "PRODUCE", "DELI" 等类别标识后
    item_start_keywords = ['FOOD', 'PRODUCE', 'DELI', 'GROCERY', 'DAIRY']
    item_lines = []
    in_items_section = False
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # 检查是否进入商品区域
        if any(keyword in line for keyword in item_start_keywords):
            in_items_section = True
            continue
        
        # 如果遇到 TOTAL, 停止解析商品
        if 'TOTAL' in line.upper() and in_items_section:
            break
        
        # 如果在商品区域，尝试解析商品行
        if in_items_section:
            item = _parse_item_line(line, i)
            if item:
                item_lines.append(item)
        
        # 也尝试在全局范围内查找商品模式
        if not in_items_section:
            item = _parse_item_line(line, i)
            if item:
                item_lines.append(item)
    
    receipt.items = item_lines
    receipt.item_count = len(item_lines)
    
    # 6. 计算 subtotal（所有商品行总计）
    calculated_total = Decimal('0')
    for item in item_lines:
        if item.line_total:
            calculated_total += item.line_total
    
    if calculated_total > 0:
        receipt.subtotal = calculated_total
        # 如果 total 存在且大于 subtotal，计算 tax
        if receipt.total and receipt.total > calculated_total:
            receipt.tax = receipt.total - calculated_total
    
    # 如果 total 还没找到，使用计算的总计
    if not receipt.total and calculated_total > 0:
        receipt.total = calculated_total
    
    return receipt


def _parse_item_line(line: str, line_index: int) -> Optional[ReceiptItem]:
    """
    解析单个商品行。
    
    支持的格式：
    - "PRODUCT_NAME FP $X.XX"
    - "PRODUCT_NAME $X.XX"
    - "X.XX lb @ $X.XX/lb FP $X.XX"
    - "(SALE) PRODUCT_NAME FP $X.XX"
    """
    line = line.strip()
    if not line:
        return None
    
    # 跳过明显的非商品行
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
    
    # 检查是否为促销商品
    is_on_sale = '(SALE)' in line.upper()
    item.is_on_sale = is_on_sale
    if is_on_sale:
        line = re.sub(r'\(SALE\)\s*', '', line, flags=re.IGNORECASE)
    
    # 提取金额：查找 $X.XX 格式
    price_matches = list(re.finditer(r'\$(\d+\.\d{2})', line))
    if not price_matches:
        # 尝试没有 $ 符号的格式
        price_matches = list(re.finditer(r'\b(\d+\.\d{2})\b', line))
    
    if price_matches:
        # 最后一个通常是行总计（FP price）
        last_price = Decimal(price_matches[-1].group(1))
        item.line_total = last_price
        
        # 如果有多个价格，可能是单价和总价
        if len(price_matches) >= 2:
            # 倒数第二个可能是单价
            second_last_price = Decimal(price_matches[-2].group(1))
            item.unit_price = second_last_price
        elif len(price_matches) == 1:
            item.unit_price = last_price
    
    # 提取数量和单位（例如 "1.20 lb @ $1.38/lb"）
    qty_unit_match = re.search(r'(\d+\.?\d*)\s*(lb|kg|oz|g|ea|pcs?|ct)\s*@\s*\$?(\d+\.\d{2})/(?:lb|kg|oz|g|ea|pcs?|ct)', line, re.IGNORECASE)
    if qty_unit_match:
        try:
            item.quantity = Decimal(qty_unit_match.group(1))
            item.unit = qty_unit_match.group(2).lower()
            if not item.unit_price:
                item.unit_price = Decimal(qty_unit_match.group(3))
        except (InvalidOperation, ValueError):
            pass
    
    # 提取商品名称（移除价格、数量等信息后）
    product_name = line
    
    # 移除价格信息
    product_name = re.sub(r'\$?\d+\.\d{2}', '', product_name)
    # 移除数量和单位信息
    product_name = re.sub(r'\d+\.?\d*\s*(?:lb|kg|oz|g|ea|pcs?|ct)\s*@\s*\$?\d+\.\d{2}/(?:lb|kg|oz|g|ea|pcs?|ct)', '', product_name, flags=re.IGNORECASE)
    # 移除 "FP" 标记
    product_name = re.sub(r'\bFP\b', '', product_name, flags=re.IGNORECASE)
    # 清理多余空格
    product_name = re.sub(r'\s+', ' ', product_name).strip()
    
    item.product_name = product_name
    
    # 简单分类推断
    product_lower = product_name.lower()
    if any(word in product_lower for word in ['milk', 'cheese', 'dairy']):
        item.category = 'DAIRY'
    elif any(word in product_lower for word in ['onion', 'bok choy', 'yu choy', 'sprout', 'vegetable']):
        item.category = 'PRODUCE'
    elif any(word in product_lower for word in ['egg', 'bun', 'bread']):
        item.category = 'FOOD'
    else:
        item.category = 'GENERAL'
    
    # 只有当有商品名称或价格时才返回
    if item.product_name or item.line_total:
        return item
    
    return None


def parse_receipt(text: str, merchant_hint: Optional[str] = None, merchant_id: Optional[int] = None) -> ParsedReceipt:
    """
    解析收据文本，自动识别商户类型。
    
    Args:
        text: OCR 提取的文本
        merchant_hint: 可选的商户提示
        merchant_id: 可选的商户 ID
        
    Returns:
        ParsedReceipt 对象
    """
    text_upper = text.upper()
    
    # 根据商户特征选择解析器
    if 'T&T' in text_upper or 'T AND T' in text_upper:
        return parse_tt_supermarket(text, merchant_id)
    
    # 默认使用 T&T 解析器（可以扩展）
    logger.warning("Unknown merchant format, using T&T parser as fallback")
    return parse_tt_supermarket(text, merchant_id)
