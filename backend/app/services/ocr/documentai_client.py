"""
Google Cloud Document AI client for parsing receipts.

Uses Expense Parser processor to extract structured receipt information.
"""
from google.oauth2 import service_account
from ...config import settings
import logging
from typing import Dict, Any, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from google.cloud import documentai

logger = logging.getLogger(__name__)

# Document AI client instance
_client = None
_processor_name: Optional[str] = None


def _get_client():
    """Get or create Document AI client (lazy import)."""
    global _client
    if _client is None:
        # Lazy import to avoid import errors at startup
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
    """Get processor name."""
    global _processor_name
    if _processor_name is None:
        if settings.documentai_endpoint:
            # Extract processor name from endpoint URL
            # Example: https://us-documentai.googleapis.com/v1/projects/891554344619/locations/us/processors/8f8a3fc3da6da7cc:process
            # Extract: projects/891554344619/locations/us/processors/8f8a3fc3da6da7cc
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
    Parse receipt image using Google Document AI Expense Parser.
    
    Args:
        image_bytes: Image file bytes
        
    Returns:
        Parsed receipt data dictionary
    """
    # Lazy import documentai
    from google.cloud import documentai
    
    client = _get_client()
    processor_name = _get_processor_name()
    
    # Prepare request
    raw_document = documentai.RawDocument(
        content=image_bytes,
        mime_type=mime_type,
    )
    
    request = documentai.ProcessRequest(
        name=processor_name,
        raw_document=raw_document,
    )
    
    try:
        # Call API
        logger.info(f"Processing document with Document AI processor: {processor_name}")
        result = client.process_document(request=request)
        document = result.document
        
        # Extract structured data
        parsed_data = _extract_receipt_data(document)
        logger.info(f"Document AI parsing completed successfully")
        
        return parsed_data
        
    except Exception as e:
        logger.error(f"Document AI processing failed: {e}")
        raise


def _extract_receipt_data(document) -> Dict[str, Any]:
    """
    Extract receipt data from Document object returned by Document AI.
    
    Document AI Expense Parser returns fields including:
    - entities (supplier name, date, total amount, etc.)
    - properties (line items, tax, etc.)
    - text (complete text)
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
    
    # Extract entities
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
                
                # Map common fields
                if entity_type == "supplier_name" or entity_type == "merchant_name":
                    data["merchant_name"] = entity_value
                elif entity_type == "receipt_date" or entity_type == "transaction_date":
                    data["purchase_time"] = entity_value
                elif entity_type == "total_amount" or entity_type == "net_amount":
                    data["total"] = _parse_amount(entity_value)
                elif entity_type == "tax_amount" or entity_type == "total_tax_amount":
                    # If confidence is low, judge based on merchant type (grocery usually tax-free)
                    if confidence and confidence < 0.6:
                        # Don't set for now, let validation function handle
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
    
    # Extract properties (line items, etc.)
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
    
    # If line_items not found, try to extract from properties
    if not data["line_items"] and hasattr(document, 'entities'):
        # Try to find line_item related nested entities
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
    
    # If no subtotal, calculate from total and tax
    if not data["subtotal"] and data["total"]:
        tax_value = data["tax"] or 0
        data["subtotal"] = data["total"] - tax_value
    
    # If no tax, set to 0
    if data["tax"] is None:
        data["tax"] = 0.0
    
    # Validate and correct data
    data = _validate_and_correct_receipt_data(data, document.text if hasattr(document, 'text') else data.get("raw_text", ""))
    
    return data


def _get_entity_value(entity) -> Any:
    """Extract entity value."""
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
        # Try to extract from text_anchor
        return None  # Need original document text
    
    return None


def _parse_amount(value: Any) -> Optional[float]:
    """Parse amount string to float."""
    if value is None:
        return None
    
    if isinstance(value, (int, float)):
        return float(value)
    
    # Try to extract number from string
    import re
    if isinstance(value, str):
        # Remove currency symbols and commas
        cleaned = re.sub(r'[^\d.]', '', value)
        try:
            return float(cleaned)
        except ValueError:
            return None
    
    return None


def _validate_and_correct_receipt_data(data: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    """
    Validate and correct receipt data.
    
    1. Mark low-confidence fields (confidence < 0.6) as requiring manual confirmation
    2. Validate correctness of line_items (quantity × unit_price = line_total)
    3. Re-extract and pair line_items from raw_text
    4. Verify if sum of all line totals equals total
    """
    # 1. Mark low-confidence fields
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
    
    # Special handling for tax_amount: if confidence is low, set to 0 and mark for confirmation
    if "total_tax_amount" in data.get("entities", {}):
        tax_entity = data["entities"]["total_tax_amount"]
        tax_confidence = tax_entity.get("confidence", 1.0)
        tax_value = _parse_amount(tax_entity.get("value"))
        
        if tax_confidence < 0.6:
            # For grocery, usually no tax
            data["tax"] = 0.0
            needs_review.append({
                "field": "tax_amount",
                "original_value": tax_value,
                "corrected_value": 0.0,
                "confidence": tax_confidence,
                "reason": f"Low confidence tax amount ({tax_confidence:.2f} < 0.6), set to 0 for grocery"
            })
    
    # 2. Validate and re-pair line_items
    if raw_text and data.get("line_items"):
        corrected_items = _reconstruct_line_items_from_text(raw_text, data.get("line_items", []))
        if corrected_items:
            data["line_items"] = corrected_items
            data["item_count"] = len([item for item in corrected_items if item.get("product_name")])
    
    # 3. Validate amount consistency
    calculated_subtotal = sum(
        item.get("line_total", 0) 
        for item in data.get("line_items", []) 
        if item.get("line_total") is not None
    )
    
    total = data.get("total")
    if total and calculated_subtotal > 0:
        difference = abs(calculated_subtotal - total)
        if difference > 0.01:  # Allow 1 cent error
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
    Reconstruct line_items from raw_text by pairing through validation of quantity × unit_price = line_total.
    
    Strategy:
    1. Parse each line in raw_text, look for product name + price patterns
    2. For lines containing "quantity @ unit_price", calculation should equal "FP price"
    3. If calculation is correct (error ±0.01), mark as high confidence
    4. Pair product names and prices
    """
    import re
    from decimal import Decimal
    
    lines = raw_text.split('\n')
    reconstructed = []
    used_indices = set()
    
    # Pattern 1: Product name + "FP $price"
    pattern1 = re.compile(r'^([^$]+?)\s+FP\s+\$?(\d+\.\d{2})$', re.IGNORECASE)
    
    # Pattern 2: Product name + "quantity unit @ $unit_price/unit" + "FP $total_price"
    pattern2 = re.compile(
        r'^([^0-9$]+?)\s+(\d+\.?\d*)\s*(lb|kg|oz|g|ea|pcs?|ct)\s*@\s+\$?(\d+\.\d{2})/(?:lb|kg|oz|g|ea|pcs?|ct)\s+FP\s+\$?(\d+\.\d{2})$',
        re.IGNORECASE
    )
    
    # Pattern 3: "(SALE) product name" + price information
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
        
        # Check if promotional item
        sale_match = pattern3.match(line)
        if sale_match:
            item["is_on_sale"] = True
            line = sale_match.group(1).strip()
        
        # Try pattern 2: line containing quantity and unit price
        match2 = pattern2.match(line)
        if match2:
            product_name = match2.group(1).strip()
            quantity = Decimal(match2.group(2))
            unit = match2.group(3).lower()
            unit_price = Decimal(match2.group(4))
            line_total = Decimal(match2.group(5))
            
            # Validate: quantity × unit_price should equal line_total (allow ±0.01 error)
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
        
        # Try pattern 1: simple product name + FP price
        match1 = pattern1.match(line)
        if match1:
            product_name = match1.group(1).strip()
            line_total = Decimal(match1.group(2))
            
            # Check if next line has quantity and unit price information
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                qty_match = re.search(r'(\d+\.?\d*)\s*(lb|kg|oz|g|ea|pcs?|ct)\s*@\s+\$?(\d+\.\d{2})/', next_line, re.IGNORECASE)
                if qty_match:
                    quantity = Decimal(qty_match.group(1))
                    unit = qty_match.group(2).lower()
                    unit_price = Decimal(qty_match.group(3))
                    
                    # Validate calculation
                    expected_total = quantity * unit_price
                    if abs(expected_total - line_total) <= Decimal('0.01'):
                        item["product_name"] = product_name
                        item["quantity"] = float(quantity)
                        item["unit"] = unit
                        item["unit_price"] = float(unit_price)
                        item["line_total"] = float(line_total)
                        item["confidence"] = "high"
                        item["raw_text"] = f"{line}\n{next_line}"  # Include both lines
                        reconstructed.append(item)
                        i += 2
                        continue
            
            # No quantity and unit price, only product name and price
            item["product_name"] = product_name
            item["line_total"] = float(line_total)
            item["confidence"] = "medium"
            reconstructed.append(item)
        
        i += 1
    
    # If no items matched through patterns, try to extract prices from existing items and pair
    if not reconstructed and existing_items:
        # Extract all prices
        prices = []
        product_names = []
        
        for item in existing_items:
            if item.get("line_total"):
                prices.append(item["line_total"])
            if item.get("product_name"):
                product_names.append(item["product_name"])
        
        # Try to find product name and price pairs in raw_text
        for name in product_names:
            # Find price near this product name in raw_text
            name_lower = name.lower()
            for i, line in enumerate(lines):
                if name_lower in line.lower():
                    # Find price on same line or nearby lines
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
    """Extract line item information from entity."""
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
    
    # Extract basic information
    if hasattr(entity, 'mention_text'):
        line_item["raw_text"] = entity.mention_text
    
    # Extract detailed information from properties
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
    
    # If at least has some information, return
    if line_item["product_name"] or line_item["line_total"]:
        return line_item
    
    return None
