"""
Google Cloud Document AI 客户端，用于解析收据。

使用 Expense Parser processor 来提取收据结构化信息。
"""
from google.oauth2 import service_account
from .config import settings
import logging
from typing import Dict, Any, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from google.cloud import documentai

logger = logging.getLogger(__name__)

# Document AI client instance
_client = None
_processor_name: Optional[str] = None


def _get_client():
    """获取或创建 Document AI 客户端（延迟导入）。"""
    global _client
    if _client is None:
        # 延迟导入，避免启动时的导入错误
        try:
            from google.cloud import documentai
        except ImportError as e:
            raise ImportError(
                "google-cloud-documentai package is not installed. "
                "Please install it with: pip install google-cloud-documentai"
            ) from e
        
        if not settings.gcp_credentials_path:
            raise ValueError(
                "GOOGLE_APPLICATION_CREDENTIALS environment variable must be set"
            )
        
        credentials = service_account.Credentials.from_service_account_file(
            settings.gcp_credentials_path
        )
        _client = documentai.DocumentProcessorServiceClient(credentials=credentials)
        logger.info("Google Cloud Document AI client initialized")
    
    return _client


def _get_processor_name() -> str:
    """获取 processor name。"""
    global _processor_name
    if _processor_name is None:
        if settings.documentai_endpoint:
            # 从 endpoint URL 提取 processor name
            # 例如: https://us-documentai.googleapis.com/v1/projects/891554344619/locations/us/processors/8f8a3fc3da6da7cc:process
            # 提取: projects/891554344619/locations/us/processors/8f8a3fc3da6da7cc
            import re
            match = re.search(r'projects/(\d+)/locations/([^/]+)/processors/([^/:]+)', settings.documentai_endpoint)
            if match:
                _processor_name = f"projects/{match.group(1)}/locations/{match.group(2)}/processors/{match.group(3)}"
            else:
                raise ValueError(f"Could not extract processor name from endpoint: {settings.documentai_endpoint}")
        elif settings.documentai_processor_name:
            _processor_name = settings.documentai_processor_name
        else:
            raise ValueError(
                "Either DOCUMENTAI_ENDPOINT or DOCUMENTAI_PROCESSOR_NAME must be set"
            )
    
    return _processor_name


def parse_receipt_documentai(image_bytes: bytes, mime_type: str = "image/jpeg") -> Dict[str, Any]:
    """
    使用 Google Document AI Expense Parser 解析收据图片。
    
    Args:
        image_bytes: 图片文件字节
        
    Returns:
        解析后的收据数据字典
    """
    # 延迟导入 documentai
    from google.cloud import documentai
    
    client = _get_client()
    processor_name = _get_processor_name()
    
    # 准备请求
    raw_document = documentai.RawDocument(
        content=image_bytes,
        mime_type=mime_type,
    )
    
    request = documentai.ProcessRequest(
        name=processor_name,
        raw_document=raw_document,
    )
    
    try:
        # 调用 API
        logger.info(f"Processing document with Document AI processor: {processor_name}")
        result = client.process_document(request=request)
        document = result.document
        
        # 提取结构化数据
        parsed_data = _extract_receipt_data(document)
        logger.info(f"Document AI parsing completed successfully")
        
        return parsed_data
        
    except Exception as e:
        logger.error(f"Document AI processing failed: {e}")
        raise


def _extract_receipt_data(document) -> Dict[str, Any]:
    """
    从 Document AI 返回的 Document 对象中提取收据数据。
    
    Document AI Expense Parser 返回的字段包括：
    - entities (供应商名称、日期、总金额等)
    - properties (行项、税费等)
    - text (完整文本)
    """
    data: Dict[str, Any] = {
        "raw_text": document.text if hasattr(document, 'text') else "",
        "entities": {},
        "properties": {},
        "line_items": [],
        "merchant_name": None,
        "purchase_time": None,
        "subtotal": None,
        "tax": None,
        "total": None,
        "currency": "USD",
        "payment_method": None,
        "card_last4": None,
        "item_count": 0,
    }
    
    # 提取 entities (实体)
    if hasattr(document, 'entities') and document.entities:
        for entity in document.entities:
            entity_type = entity.type_ if hasattr(entity, 'type_') else None
            entity_value = _get_entity_value(entity)
            confidence = entity.confidence if hasattr(entity, 'confidence') else None
            
            if entity_type:
                data["entities"][entity_type] = {
                    "value": entity_value,
                    "confidence": confidence
                }
                
                # 映射常用字段
                if entity_type == "supplier_name" or entity_type == "merchant_name":
                    data["merchant_name"] = entity_value
                elif entity_type == "receipt_date" or entity_type == "transaction_date":
                    data["purchase_time"] = entity_value
                elif entity_type == "total_amount" or entity_type == "net_amount":
                    data["total"] = _parse_amount(entity_value)
                elif entity_type == "tax_amount" or entity_type == "total_tax_amount":
                    # 如果置信度低，根据商户类型判断（grocery 通常免税）
                    if confidence and confidence < 0.6:
                        # 暂不设置，让验证函数处理
                        pass
                    else:
                        data["tax"] = _parse_amount(entity_value)
                elif entity_type == "subtotal_amount":
                    data["subtotal"] = _parse_amount(entity_value)
                elif entity_type == "payment_type":
                    data["payment_method"] = entity_value
                elif entity_type == "card_number" or entity_type == "credit_card_last_four_digits":
                    if entity_value and len(str(entity_value)) >= 4:
                        data["card_last4"] = str(entity_value)[-4:]
    
    # 提取 properties (行项等)
    if hasattr(document, 'entities') and document.entities:
        line_items = []
        for entity in document.entities:
            if hasattr(entity, 'type_') and entity.type_ in ["line_item", "expense_line_item"]:
                line_item = _extract_line_item(entity)
                if line_item:
                    line_items.append(line_item)
        
        if line_items:
            data["line_items"] = line_items
            data["item_count"] = len(line_items)
    
    # 如果没有找到 line_items，尝试从 properties 中提取
    if not data["line_items"] and hasattr(document, 'entities'):
        # 尝试查找 line_item 相关的嵌套 entities
        for entity in document.entities:
            if hasattr(entity, 'properties') and entity.properties:
                for prop in entity.properties:
                    prop_type = prop.type_ if hasattr(prop, 'type_') else None
                    if prop_type and "line_item" in prop_type.lower():
                        line_item = _extract_line_item(prop)
                        if line_item:
                            data["line_items"].append(line_item)
        
        if data["line_items"]:
            data["item_count"] = len(data["line_items"])
    
    # 如果没有 subtotal，从 total 和 tax 计算
    if not data["subtotal"] and data["total"]:
        tax_value = data["tax"] or 0
        data["subtotal"] = data["total"] - tax_value
    
    # 如果没有 tax，设为 0
    if data["tax"] is None:
        data["tax"] = 0.0
    
    # 验证和修正数据
    data = _validate_and_correct_receipt_data(data, document.text if hasattr(document, 'text') else data.get("raw_text", ""))
    
    return data


def _get_entity_value(entity) -> Any:
    """提取 entity 的值。"""
    if hasattr(entity, 'mention_text') and entity.mention_text:
        return entity.mention_text
    elif hasattr(entity, 'normalized_value'):
        norm_value = entity.normalized_value
        if hasattr(norm_value, 'text'):
            return norm_value.text
        elif hasattr(norm_value, 'money_value'):
            money = norm_value.money_value
            if hasattr(money, 'currency_code') and hasattr(money, 'units'):
                return float(money.units) + (money.nanos / 1e9 if hasattr(money, 'nanos') else 0)
    elif hasattr(entity, 'text_anchor') and entity.text_anchor:
        # 尝试从 text_anchor 提取
        return None  # 需要原始文档文本
    
    return None


def _parse_amount(value: Any) -> Optional[float]:
    """解析金额字符串为浮点数。"""
    if value is None:
        return None
    
    if isinstance(value, (int, float)):
        return float(value)
    
    # 尝试从字符串中提取数字
    import re
    if isinstance(value, str):
        # 移除货币符号和逗号
        cleaned = re.sub(r'[^\d.]', '', value)
        try:
            return float(cleaned)
        except ValueError:
            return None
    
    return None


def _validate_and_correct_receipt_data(data: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    """
    验证和修正收据数据。
    
    1. 标记低置信度字段（confidence < 0.6）为需要人工确认
    2. 验证 line_items 的正确性（数量×单价=行总计）
    3. 从 raw_text 中重新提取和配对 line_items
    4. 验证所有行总计加总是否等于 total
    """
    # 1. 标记低置信度字段
    needs_review = []
    for entity_type, entity_data in data.get("entities", {}).items():
        confidence = entity_data.get("confidence")
        if confidence is not None and confidence < 0.6:
            needs_review.append({
                "field": entity_type,
                "value": entity_data.get("value"),
                "confidence": confidence,
                "reason": f"Low confidence ({confidence:.2f} < 0.6)"
            })
    
    # 特别处理 tax_amount：如果置信度低，设置为 0 并标记需要确认
    if "total_tax_amount" in data.get("entities", {}):
        tax_entity = data["entities"]["total_tax_amount"]
        tax_confidence = tax_entity.get("confidence", 1.0)
        tax_value = _parse_amount(tax_entity.get("value"))
        
        if tax_confidence < 0.6:
            # 对于 grocery，通常没有 tax
            data["tax"] = 0.0
            needs_review.append({
                "field": "tax_amount",
                "original_value": tax_value,
                "corrected_value": 0.0,
                "confidence": tax_confidence,
                "reason": f"Low confidence tax amount ({tax_confidence:.2f} < 0.6), set to 0 for grocery"
            })
    
    # 2. 验证和重新配对 line_items
    if raw_text and data.get("line_items"):
        corrected_items = _reconstruct_line_items_from_text(raw_text, data.get("line_items", []))
        if corrected_items:
            data["line_items"] = corrected_items
            data["item_count"] = len([item for item in corrected_items if item.get("product_name")])
    
    # 3. 验证金额一致性
    calculated_subtotal = sum(
        item.get("line_total", 0) 
        for item in data.get("line_items", []) 
        if item.get("line_total") is not None
    )
    
    total = data.get("total")
    if total and calculated_subtotal > 0:
        difference = abs(calculated_subtotal - total)
        if difference > 0.01:  # 允许 1 分钱误差
            needs_review.append({
                "field": "subtotal_validation",
                "calculated_subtotal": calculated_subtotal,
                "total": total,
                "difference": difference,
                "reason": "Line items subtotal does not match total"
            })
    
    data["needs_review"] = needs_review
    data["validation_status"] = "pass" if not needs_review else "needs_review"
    
    return data


def _reconstruct_line_items_from_text(raw_text: str, existing_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    从 raw_text 中重新构建 line_items，通过验证数量×单价=行总计来配对。
    
    策略：
    1. 解析 raw_text 中的每一行，寻找商品名 + 价格模式
    2. 对于包含 "数量 @ 单价" 的行，计算应该等于 "FP 价格"
    3. 如果计算正确（误差 ±0.01），标记为 high confidence
    4. 配对商品名和价格
    """
    import re
    from decimal import Decimal
    
    lines = raw_text.split('\n')
    reconstructed = []
    used_indices = set()
    
    # 模式1: 商品名 + "FP $价格"
    pattern1 = re.compile(r'^([^$]+?)\s+FP\s+\$?(\d+\.\d{2})$', re.IGNORECASE)
    
    # 模式2: 商品名 + "数量 单位 @ $单价/单位" + "FP $总价"
    pattern2 = re.compile(
        r'^([^0-9$]+?)\s+(\d+\.?\d*)\s*(lb|kg|oz|g|ea|pcs?|ct)\s*@\s+\$?(\d+\.\d{2})/(?:lb|kg|oz|g|ea|pcs?|ct)\s+FP\s+\$?(\d+\.\d{2})$',
        re.IGNORECASE
    )
    
    # 模式3: "(SALE) 商品名" + 价格信息
    pattern3 = re.compile(r'^\(SALE\)\s*(.+)$', re.IGNORECASE)
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        
        item = {
            "raw_text": line,
            "product_name": None,
            "quantity": None,
            "unit": None,
            "unit_price": None,
            "line_total": None,
            "is_on_sale": False,
            "category": None,
            "confidence": "low",
        }
        
        # 检查是否是促销商品
        sale_match = pattern3.match(line)
        if sale_match:
            item["is_on_sale"] = True
            line = sale_match.group(1).strip()
        
        # 尝试模式2：包含数量和单价的行
        match2 = pattern2.match(line)
        if match2:
            product_name = match2.group(1).strip()
            quantity = Decimal(match2.group(2))
            unit = match2.group(3).lower()
            unit_price = Decimal(match2.group(4))
            line_total = Decimal(match2.group(5))
            
            # 验证：数量 × 单价 应该等于行总计（允许 ±0.01 误差）
            expected_total = quantity * unit_price
            if abs(expected_total - line_total) <= Decimal('0.01'):
                item["product_name"] = product_name
                item["quantity"] = float(quantity)
                item["unit"] = unit
                item["unit_price"] = float(unit_price)
                item["line_total"] = float(line_total)
                item["confidence"] = "high"
                reconstructed.append(item)
                i += 1
                continue
        
        # 尝试模式1：简单商品名 + FP 价格
        match1 = pattern1.match(line)
        if match1:
            product_name = match1.group(1).strip()
            line_total = Decimal(match1.group(2))
            
            # 检查下一行是否有数量和单价信息
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                qty_match = re.search(r'(\d+\.?\d*)\s*(lb|kg|oz|g|ea|pcs?|ct)\s*@\s+\$?(\d+\.\d{2})/', next_line, re.IGNORECASE)
                if qty_match:
                    quantity = Decimal(qty_match.group(1))
                    unit = qty_match.group(2).lower()
                    unit_price = Decimal(qty_match.group(3))
                    
                    # 验证计算
                    expected_total = quantity * unit_price
                    if abs(expected_total - line_total) <= Decimal('0.01'):
                        item["product_name"] = product_name
                        item["quantity"] = float(quantity)
                        item["unit"] = unit
                        item["unit_price"] = float(unit_price)
                        item["line_total"] = float(line_total)
                        item["confidence"] = "high"
                        item["raw_text"] = f"{line}\n{next_line}"  # 包含两行
                        reconstructed.append(item)
                        i += 2
                        continue
            
            # 没有数量和单价，只有商品名和价格
            item["product_name"] = product_name
            item["line_total"] = float(line_total)
            item["confidence"] = "medium"
            reconstructed.append(item)
        
        i += 1
    
    # 如果没有通过模式匹配到任何项，尝试从现有 items 中提取价格并配对
    if not reconstructed and existing_items:
        # 提取所有价格
        prices = []
        product_names = []
        
        for item in existing_items:
            if item.get("line_total"):
                prices.append(item["line_total"])
            if item.get("product_name"):
                product_names.append(item["product_name"])
        
        # 尝试在 raw_text 中查找商品名和价格的配对
        for name in product_names:
            # 在 raw_text 中查找该商品名附近的价格
            name_lower = name.lower()
            for i, line in enumerate(lines):
                if name_lower in line.lower():
                    # 查找同一行或附近行的价格
                    for j in range(max(0, i-1), min(len(lines), i+3)):
                        price_match = re.search(r'\$?(\d+\.\d{2})', lines[j])
                        if price_match:
                            price = float(price_match.group(1))
                            if price in prices:
                                reconstructed.append({
                                    "raw_text": f"{lines[i]}\n{lines[j]}",
                                    "product_name": name,
                                    "line_total": price,
                                    "confidence": "medium",
                                    "quantity": None,
                                    "unit": None,
                                    "unit_price": None,
                                    "is_on_sale": False,
                                    "category": None,
                                })
                                prices.remove(price)
                                break
    
    return reconstructed


def _extract_line_item(entity) -> Optional[Dict[str, Any]]:
    """从 entity 中提取行项信息。"""
    line_item = {
        "raw_text": "",
        "product_name": None,
        "quantity": None,
        "unit": None,
        "unit_price": None,
        "line_total": None,
        "is_on_sale": False,
        "category": None,
    }
    
    # 提取基础信息
    if hasattr(entity, 'mention_text'):
        line_item["raw_text"] = entity.mention_text
    
    # 从 properties 中提取详细信息
    if hasattr(entity, 'properties') and entity.properties:
        for prop in entity.properties:
            prop_type = prop.type_ if hasattr(prop, 'type_') else ""
            prop_value = _get_entity_value(prop)
            
            if "item_description" in prop_type.lower() or "description" in prop_type.lower():
                line_item["product_name"] = prop_value
            elif "quantity" in prop_type.lower():
                line_item["quantity"] = _parse_amount(prop_value)
            elif "unit_price" in prop_type.lower() or "price" in prop_type.lower():
                line_item["unit_price"] = _parse_amount(prop_value)
            elif "amount" in prop_type.lower() or "line_total" in prop_type.lower():
                line_item["line_total"] = _parse_amount(prop_value)
    
    # 如果至少有一些信息，返回
    if line_item["product_name"] or line_item["line_total"]:
        return line_item
    
    return None
