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
        
        # Extract coordinate data for advanced sum checking
        parsed_data["coordinate_data"] = _extract_coordinate_data(document)
        
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


def _extract_coordinate_data(document) -> Dict[str, Any]:
    """
    Extract coordinate data from Document AI response.
    
    Returns:
        Dictionary containing:
        - text_blocks: List of text blocks with coordinates
        - pages: List of pages with layout information
    """
    coordinate_data = {
        "text_blocks": [],
        "pages": []
    }
    
    try:
        # Extract from pages
        if hasattr(document, 'pages') and document.pages:
            for page_idx, page in enumerate(document.pages):
                page_data = {
                    "page_number": page_idx + 1,
                    "width": page.dimension.width if hasattr(page, 'dimension') else None,
                    "height": page.dimension.height if hasattr(page, 'dimension') else None,
                    "blocks": [],
                    "paragraphs": [],
                    "lines": [],
                    "tokens": []
                }
                
                # Extract tokens (most granular)
                if hasattr(page, 'tokens') and page.tokens:
                    for token in page.tokens:
                        if hasattr(token, 'layout') and token.layout:
                            bbox = _extract_bounding_box(token.layout)
                            if bbox:
                                token_data = {
                                    "text": _get_text_from_layout(token.layout),
                                    "bounding_box": bbox,
                                    "confidence": token.layout.confidence if hasattr(token.layout, 'confidence') else None,
                                    "page_number": page_idx + 1,
                                    "type": "token"
                                }
                                page_data["tokens"].append(token_data)
                                coordinate_data["text_blocks"].append(token_data)
                
                # Extract lines
                if hasattr(page, 'lines') and page.lines:
                    for line in page.lines:
                        if hasattr(line, 'layout') and line.layout:
                            bbox = _extract_bounding_box(line.layout)
                            if bbox:
                                line_data = {
                                    "text": _get_text_from_layout(line.layout),
                                    "bounding_box": bbox,
                                    "confidence": line.layout.confidence if hasattr(line.layout, 'confidence') else None
                                }
                                page_data["lines"].append(line_data)
                
                # Extract paragraphs
                if hasattr(page, 'paragraphs') and page.paragraphs:
                    for para in page.paragraphs:
                        if hasattr(para, 'layout') and para.layout:
                            bbox = _extract_bounding_box(para.layout)
                            if bbox:
                                para_data = {
                                    "text": _get_text_from_layout(para.layout),
                                    "bounding_box": bbox,
                                    "confidence": para.layout.confidence if hasattr(para.layout, 'confidence') else None
                                }
                                page_data["paragraphs"].append(para_data)
                
                # Extract blocks
                if hasattr(page, 'blocks') and page.blocks:
                    for block in page.blocks:
                        if hasattr(block, 'layout') and block.layout:
                            bbox = _extract_bounding_box(block.layout)
                            if bbox:
                                block_data = {
                                    "text": _get_text_from_layout(block.layout),
                                    "bounding_box": bbox,
                                    "confidence": block.layout.confidence if hasattr(block.layout, 'confidence') else None
                                }
                                page_data["blocks"].append(block_data)
                
                coordinate_data["pages"].append(page_data)
        
        # Extract entity coordinates
        if hasattr(document, 'entities') and document.entities:
            coordinate_data["entities"] = []
            for entity in document.entities:
                entity_coords = _extract_entity_coordinates(entity)
                if entity_coords:
                    coordinate_data["entities"].append({
                        "type": entity.type_ if hasattr(entity, 'type_') else None,
                        "value": _get_entity_value(entity),
                        "bounding_box": entity_coords,
                        "confidence": entity.confidence if hasattr(entity, 'confidence') else None
                    })
        
        logger.debug(f"Extracted {len(coordinate_data['text_blocks'])} text blocks with coordinates")
        
    except Exception as e:
        logger.warning(f"Failed to extract coordinate data: {e}")
        # Return empty structure if extraction fails
        pass
    
    return coordinate_data


def _extract_bounding_box(layout) -> Optional[Dict[str, Any]]:
    """Extract bounding box from layout object."""
    if not hasattr(layout, 'bounding_poly') or not layout.bounding_poly:
        return None
    
    bbox = layout.bounding_poly
    
    # Try normalized_vertices first (preferred)
    if hasattr(bbox, 'normalized_vertices') and bbox.normalized_vertices:
        vertices = bbox.normalized_vertices
        x_coords = [v.x for v in vertices]
        y_coords = [v.y for v in vertices]
        
        return {
            "normalized_vertices": [{"x": v.x, "y": v.y} for v in vertices],
            "x": min(x_coords),
            "y": min(y_coords),
            "width": max(x_coords) - min(x_coords),
            "height": max(y_coords) - min(y_coords),
            "center_x": sum(x_coords) / len(x_coords),
            "center_y": sum(y_coords) / len(y_coords),
            "is_normalized": True
        }
    
    # Fallback to vertices (pixel coordinates)
    elif hasattr(bbox, 'vertices') and bbox.vertices:
        vertices = bbox.vertices
        x_coords = [v.x for v in vertices]
        y_coords = [v.y for v in vertices]
        
        return {
            "vertices": [{"x": v.x, "y": v.y} for v in vertices],
            "x": min(x_coords),
            "y": min(y_coords),
            "width": max(x_coords) - min(x_coords),
            "height": max(y_coords) - min(y_coords),
            "center_x": sum(x_coords) / len(x_coords),
            "center_y": sum(y_coords) / len(y_coords),
            "is_normalized": False
        }
    
    return None


def _get_text_from_layout(layout) -> str:
    """Extract text from layout object."""
    if hasattr(layout, 'text_anchor') and layout.text_anchor:
        if hasattr(layout.text_anchor, 'content'):
            return layout.text_anchor.content
        elif hasattr(layout.text_anchor, 'text_segments'):
            # Text segments contain start_index and end_index
            # We'd need the full document text to extract, but for now return empty
            return ""
    return ""


def _extract_entity_coordinates(entity) -> Optional[Dict[str, Any]]:
    """Extract coordinates from entity (page_anchor or text_anchor)."""
    # Try page_anchor first
    if hasattr(entity, 'page_anchor') and entity.page_anchor:
        if hasattr(entity.page_anchor, 'page_refs') and entity.page_anchor.page_refs:
            page_ref = entity.page_anchor.page_refs[0]  # Take first reference
            if hasattr(page_ref, 'bounding_poly') and page_ref.bounding_poly:
                return _extract_bounding_box_from_poly(page_ref.bounding_poly)
    
    # Fallback to text_anchor (less precise)
    if hasattr(entity, 'text_anchor') and entity.text_anchor:
        # Text anchor doesn't have direct coordinates, but we can use it to find text position
        # For now, return None and we'll use text matching instead
        return None
    
    return None


def _extract_bounding_box_from_poly(bounding_poly) -> Optional[Dict[str, Any]]:
    """Extract bounding box from bounding_poly object."""
    # Try normalized_vertices first
    if hasattr(bounding_poly, 'normalized_vertices') and bounding_poly.normalized_vertices:
        vertices = bounding_poly.normalized_vertices
        x_coords = [v.x for v in vertices]
        y_coords = [v.y for v in vertices]
        
        return {
            "normalized_vertices": [{"x": v.x, "y": v.y} for v in vertices],
            "x": min(x_coords),
            "y": min(y_coords),
            "width": max(x_coords) - min(x_coords),
            "height": max(y_coords) - min(y_coords),
            "center_x": sum(x_coords) / len(x_coords),
            "center_y": sum(y_coords) / len(y_coords),
            "is_normalized": True
        }
    
    # Fallback to vertices
    elif hasattr(bounding_poly, 'vertices') and bounding_poly.vertices:
        vertices = bounding_poly.vertices
        x_coords = [v.x for v in vertices]
        y_coords = [v.y for v in vertices]
        
        return {
            "vertices": [{"x": v.x, "y": v.y} for v in vertices],
            "x": min(x_coords),
            "y": min(y_coords),
            "width": max(x_coords) - min(x_coords),
            "height": max(y_coords) - min(y_coords),
            "center_x": sum(x_coords) / len(x_coords),
            "center_y": sum(y_coords) / len(y_coords),
            "is_normalized": False
        }
    
    return None
