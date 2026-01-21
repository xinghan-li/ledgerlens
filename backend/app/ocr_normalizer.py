"""
OCR Normalizer: 统一不同 OCR 服务的输出格式。

目标：
1. 将 Google Document AI、AWS Textract 等不同 OCR 的输出标准化为统一格式
2. 所有后续处理（提取、验证、LLM）都基于标准化后的格式
3. 避免为每个 OCR 重复写提取和验证逻辑

统一格式（Unified OCR Result Format）：
{
    "raw_text": str,  # 所有 OCR 都有
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
        "original_data": {...}  # 保留原始数据供调试
    }
}
"""
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


def normalize_ocr_result(ocr_result: Dict[str, Any], provider: str = "unknown") -> Dict[str, Any]:
    """
    将不同 OCR 服务的输出标准化为统一格式。
    
    Args:
        ocr_result: OCR 服务的原始输出
        provider: OCR 提供商（"google_documentai", "aws_textract", "google_vision"）
        
    Returns:
        标准化后的统一格式
    """
    if provider == "google_documentai":
        return _normalize_google_documentai(ocr_result)
    elif provider == "aws_textract":
        return _normalize_aws_textract(ocr_result)
    elif provider == "google_vision":
        return _normalize_google_vision(ocr_result)
    else:
        # 尝试自动检测
        if "entities" in ocr_result and "line_items" in ocr_result:
            # 可能是 Document AI 格式
            return _normalize_google_documentai(ocr_result)
        elif "ExpenseDocuments" in str(ocr_result) or "Blocks" in ocr_result:
            # 可能是 Textract 原始格式
            return _normalize_aws_textract(ocr_result)
        else:
            # 假设已经是部分标准化格式，补充缺失字段
            return _ensure_unified_format(ocr_result, provider)


def _normalize_google_documentai(docai_result: Dict[str, Any]) -> Dict[str, Any]:
    """标准化 Google Document AI 的输出。"""
    # Document AI 的输出已经接近统一格式，只需确保字段一致
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
    
    # 确保 line_items 格式一致
    normalized["line_items"] = [_normalize_line_item(item) for item in normalized["line_items"]]
    
    return normalized


def _normalize_aws_textract(textract_result: Dict[str, Any]) -> Dict[str, Any]:
    """标准化 AWS Textract 的输出。"""
    # textract_result 可能是 textract_client.py 返回的格式（已经部分处理过）
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
    
    # 确保 line_items 格式一致
    normalized["line_items"] = [_normalize_line_item(item) for item in normalized["line_items"]]
    
    return normalized


def _normalize_google_vision(vision_result: Dict[str, Any]) -> Dict[str, Any]:
    """标准化 Google Cloud Vision 的输出（只有 raw_text）。"""
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
    """确保部分标准化的结果符合统一格式。"""
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
    """标准化单个 line_item，确保字段类型和名称一致。"""
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
    """安全地将值转换为 float。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            # 移除货币符号和逗号
            cleaned = value.replace("$", "").replace(",", "").strip()
            return float(cleaned)
        except (ValueError, AttributeError):
            return None
    return None


def extract_unified_info(normalized_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    从标准化后的 OCR 结果中提取关键信息，用于后续处理。
    
    Returns:
        {
            "raw_text": str,
            "merchant_name": str | None,
            "trusted_hints": Dict,  # 高置信度字段
            "total": float | None,
            "line_items": List,  # 标准化的 line_items
        }
    """
    entities = normalized_result.get("entities", {})
    
    # 提取高置信度字段作为 trusted_hints（confidence >= 0.95）
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
    
    # 提取 total
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
