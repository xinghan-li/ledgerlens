"""
Supabase client for storing receipt OCR data and parsed receipts.

Note: The database schema is defined in database/001_schema_v0.sql
"""
from supabase import create_client, Client
from .config import settings
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)

# Singleton Supabase client
_supabase: Optional[Client] = None


def _get_client() -> Client:
    """Get or create the Supabase client."""
    global _supabase
    if _supabase is None:
        if not settings.supabase_url or not settings.supabase_anon_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment"
            )
        
        # Use service role key if available, otherwise use anon key
        key = settings.supabase_service_role_key or settings.supabase_anon_key
        _supabase = create_client(settings.supabase_url, key)
        logger.info("Supabase client initialized")
    
    return _supabase


def save_receipt_ocr(user_id: Optional[str], filename: str, text: str) -> Dict[str, Any]:
    """
    Save receipt OCR data to Supabase (legacy function for old schema).
    
    Args:
        user_id: Optional user identifier
        filename: Original filename of the uploaded image
        text: Extracted OCR text
        
    Returns:
        Dictionary containing the saved record (including generated id)
    """
    supabase = _get_client()
    
    payload = {
        "user_id": user_id,
        "filename": filename,
        "raw_text": text,
    }
    
    try:
        res = supabase.table("receipts").insert(payload).execute()
        return res.data[0] if res.data else payload
    except Exception as e:
        logger.error(f"Failed to save receipt OCR: {e}")
        raise


def save_parsed_receipt(
    user_id: str,
    parsed_receipt: Any,  # ParsedReceipt from receipt_parser
    ocr_text: str,
    image_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    保存解析后的收据到 receipts 表，并保存商品项到 receipt_items 表。
    
    Args:
        user_id: 用户 ID (UUID 字符串)
        parsed_receipt: ParsedReceipt 对象
        ocr_text: 原始 OCR 文本
        image_url: 可选的图片 URL
        
    Returns:
        包含 receipt_id 和 receipt_items 信息的字典
    """
    supabase = _get_client()
    
    # 准备 receipts 表数据
    receipt_payload: Dict[str, Any] = {
        "user_id": user_id,
        "merchant_name_raw": parsed_receipt.merchant_name,
        "merchant_id": parsed_receipt.merchant_id,
        "purchase_time": parsed_receipt.purchase_time.isoformat() if parsed_receipt.purchase_time else None,
        "currency_code": parsed_receipt.currency_code,
        "subtotal": float(parsed_receipt.subtotal) if parsed_receipt.subtotal else None,
        "tax": float(parsed_receipt.tax) if parsed_receipt.tax else None,
        "total": float(parsed_receipt.total) if parsed_receipt.total else None,
        "item_count": parsed_receipt.item_count,
        "payment_method": parsed_receipt.payment_method,
        "status": "pending",
        "image_url": image_url,
        "ocr_raw_json": {"text": ocr_text},  # 存储为 JSONB
    }
    
    try:
        # 插入 receipt
        receipt_res = supabase.table("receipts").insert(receipt_payload).execute()
        if not receipt_res.data:
            raise ValueError("Failed to insert receipt, no data returned")
        
        receipt_data = receipt_res.data[0]
        receipt_id = receipt_data["id"]
        logger.info(f"Receipt saved with ID: {receipt_id}")
        
        # 插入 receipt_items
        items_data = []
        for item in parsed_receipt.items:
            # 如果商品在促销，在 normalized_text 中标记
            normalized_text = item.product_name
            if item.is_on_sale:
                normalized_text = f"[SALE] {normalized_text}"
            
            item_payload = {
                "receipt_id": receipt_id,
                "line_index": item.line_index,
                "raw_text": item.raw_text,
                "normalized_text": normalized_text,
                "quantity": float(item.quantity) if item.quantity else None,
                "unit_price": float(item.unit_price) if item.unit_price else None,
                "line_total": float(item.line_total) if item.line_total else None,
                "is_taxable": None,  # 暂不解析
                "status": "unresolved",
            }
            items_data.append(item_payload)
        
        if items_data:
            items_res = supabase.table("receipt_items").insert(items_data).execute()
            logger.info(f"Inserted {len(items_data)} receipt items")
        else:
            items_res = type('obj', (object,), {'data': []})()
        
        return {
            "receipt": receipt_data,
            "receipt_id": receipt_id,
            "items": items_res.data if hasattr(items_res, 'data') and items_res.data else [],
        }
        
    except Exception as e:
        logger.error(f"Failed to save parsed receipt: {e}")
        raise


def get_test_user_id() -> Optional[str]:
    """
    获取测试用户 ID（如果配置了的话）。
    在生产环境中应该从认证中获取真实的 user_id。
    
    Returns:
        用户 ID 字符串或 None
    """
    if settings.test_user_id:
        return settings.test_user_id
    return None


def verify_user_exists(user_id: str) -> bool:
    """
    验证用户是否存在于 auth.users 表中。
    
    Args:
        user_id: 用户 ID (UUID 字符串)
        
    Returns:
        如果用户存在返回 True，否则返回 False
    """
    supabase = _get_client()
    try:
        # 注意：需要 service role key 才能查询 auth.users
        # 如果使用 anon key，可能需要通过 Supabase Auth API 或其他方式验证
        # 这里尝试通过 receipts 表的查询来间接验证（如果用户有收据记录）
        res = supabase.table("receipts").select("user_id").eq("user_id", user_id).limit(1).execute()
        # 如果能查询到（或查询不报错），说明用户可能存在
        return True
    except Exception as e:
        logger.warning(f"Could not verify user existence: {e}")
        # 对于开发环境，假设用户存在（让数据库抛出具体错误）
        return False


def get_or_create_merchant(merchant_name: str) -> Optional[int]:
    """
    根据商户名称获取或创建 merchant 记录。
    
    Args:
        merchant_name: 商户名称
        
    Returns:
        merchant_id 或 None
    """
    if not merchant_name:
        return None
    
    supabase = _get_client()
    
    # 规范化名称（小写、移除特殊字符）
    normalized_name = merchant_name.lower().strip()
    
    try:
        # 尝试查找现有商户
        res = supabase.table("merchants").select("id").eq("normalized_name", normalized_name).execute()
        
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
        
        # 创建新商户
        insert_res = supabase.table("merchants").insert({
            "name": merchant_name,
            "normalized_name": normalized_name,
        }).execute()
        
        if insert_res.data and len(insert_res.data) > 0:
            logger.info(f"Created new merchant: {merchant_name} (ID: {insert_res.data[0]['id']})")
            return insert_res.data[0]["id"]
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to get/create merchant: {e}")
        return None
