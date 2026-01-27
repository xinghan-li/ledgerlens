"""
OCR Normalizer: Unify output formats from different OCR services.

Goals:
1. Normalize outputs from different OCRs (Google Document AI, AWS Textract, etc.) to unified format
2. All subsequent processing (extraction, validation, LLM) based on normalized format
3. Avoid duplicating extraction and validation logic for each OCR

Unified format (Unified OCR Result Format):
{
    "raw_text": str,  # All OCRs have this
    "merchant_name": str | None,
    "entities": {
        "merchant_name": {"value": str, "confidence": float},
        "total_amount": {"value": str, "confidence": float},
        ...
    },
    "line_items": [
        {
            "raw_text": str,
            "product_name": str | None,
            "quantity": float | None,
            "unit": str | None,
            "unit_price": float | None,
            "line_total": float | None,
            "is_on_sale": bool,
            "category": str | None
        }
    ],
    "metadata": {
        "ocr_provider": "google_documentai" | "aws_textract" | "google_vision",
        "original_data": {...}  # Preserve original data for debugging
    }
}
"""
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


def normalize_ocr_result(ocr_result: Dict[str, Any], provider: str = "unknown") -> Dict[str, Any]:
    """
    Normalize outputs from different OCR services to unified format.
    
    Args:
        ocr_result: Original output from OCR service
        provider: OCR provider ("google_documentai", "aws_textract", "google_vision")
        
    Returns:
        Normalized unified format
    """
    if provider == "google_documentai":
        return _normalize_google_documentai(ocr_result)
    elif provider == "aws_textract":
        return _normalize_aws_textract(ocr_result)
    elif provider == "google_vision":
        return _normalize_google_vision(ocr_result)
    else:
        # Try auto-detection
        if "entities" in ocr_result and "line_items" in ocr_result:
            # Might be Document AI format
            return _normalize_google_documentai(ocr_result)
        elif "ExpenseDocuments" in str(ocr_result) or "Blocks" in ocr_result:
            # Might be Textract raw format
            return _normalize_aws_textract(ocr_result)
        else:
            # Assume already partially normalized format, supplement missing fields
            return _ensure_unified_format(ocr_result, provider)


def _normalize_google_documentai(docai_result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Google Document AI output."""
    # Document AI output is already close to unified format, just ensure field consistency
    normalized = {
        "raw_text": docai_result.get("raw_text", ""),
        "merchant_name": docai_result.get("merchant_name"),
        "entities": docai_result.get("entities", {}),
        "line_items": docai_result.get("line_items", []),
        "metadata": {
            "ocr_provider": "google_documentai",
            "original_data": docai_result
        }
    }
    
    # Ensure line_items format consistency
    normalized["line_items"] = [_normalize_line_item(item) for item in normalized["line_items"]]
    
    return normalized


def _normalize_aws_textract(textract_result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize AWS Textract output."""
    # textract_result might be format returned by textract_client.py (already partially processed)
    normalized = {
        "raw_text": textract_result.get("raw_text", ""),
        "merchant_name": textract_result.get("merchant_name"),
        "entities": textract_result.get("entities", {}),
        "line_items": textract_result.get("line_items", []),
        "metadata": {
            "ocr_provider": "aws_textract",
            "original_data": textract_result
        }
    }
    
    # Ensure line_items format consistency
    normalized["line_items"] = [_normalize_line_item(item) for item in normalized["line_items"]]
    
    return normalized


def _normalize_google_vision(vision_result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Google Cloud Vision output (only raw_text)."""
    raw_text = vision_result.get("text", vision_result.get("raw_text", ""))
    
    return {
        "raw_text": raw_text,
        "merchant_name": None,
        "entities": {},
        "line_items": [],
        "metadata": {
            "ocr_provider": "google_vision",
            "original_data": vision_result
        }
    }


def _ensure_unified_format(partial_result: Dict[str, Any], provider: str) -> Dict[str, Any]:
    """Ensure partially normalized result conforms to unified format."""
    return {
        "raw_text": partial_result.get("raw_text", ""),
        "merchant_name": partial_result.get("merchant_name"),
        "entities": partial_result.get("entities", {}),
        "line_items": [_normalize_line_item(item) for item in partial_result.get("line_items", [])],
        "metadata": {
            "ocr_provider": provider,
            "original_data": partial_result
        }
    }


def _normalize_line_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a single line_item, ensure field types and names are consistent."""
    normalized = {
        "raw_text": item.get("raw_text", ""),
        "product_name": item.get("product_name"),
        "quantity": _to_float(item.get("quantity")),
        "unit": item.get("unit"),
        "unit_price": _to_float(item.get("unit_price")),
        "line_total": _to_float(item.get("line_total")),
        "is_on_sale": bool(item.get("is_on_sale", False)),
        "category": item.get("category"),
    }
    
    return normalized


def _to_float(value: Any) -> Optional[float]:
    """Safely convert value to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            # Remove currency symbols and commas
            cleaned = value.replace("$", "").replace(",", "").strip()
            return float(cleaned)
        except (ValueError, AttributeError):
            return None
    return None


def extract_unified_info(normalized_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract key information from normalized OCR result for subsequent processing.
    
    Returns:
        {
            "raw_text": str,
            "merchant_name": str | None,
            "trusted_hints": Dict,  # High-confidence fields
            "total": float | None,
            "line_items": List,  # Normalized line_items
        }
    """
    entities = normalized_result.get("entities", {})
    
    # Extract high-confidence fields as trusted_hints (confidence >= 0.95)
    trusted_hints = {}
    for entity_type, entity_data in entities.items():
        if isinstance(entity_data, dict):
            confidence = entity_data.get("confidence", 0)
            value = entity_data.get("value")
            if confidence >= 0.95 and value is not None:
                trusted_hints[entity_type] = {
                    "value": value,
                    "confidence": confidence,
                    "source": normalized_result["metadata"]["ocr_provider"]
                }
    
    # Extract total
    total = None
    if "total_amount" in entities:
        total_value = entities["total_amount"].get("value")
        if total_value:
            total = _to_float(total_value)
    elif "total" in normalized_result:
        total = _to_float(normalized_result["total"])
    
    return {
        "raw_text": normalized_result["raw_text"],
        "merchant_name": normalized_result.get("merchant_name"),
        "trusted_hints": trusted_hints,
        "total": total,
        "line_items": normalized_result.get("line_items", []),
        "metadata": normalized_result.get("metadata", {})
    }
