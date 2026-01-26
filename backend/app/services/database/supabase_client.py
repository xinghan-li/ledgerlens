"""
Supabase client for storing receipt OCR data and parsed receipts.

Note: The database schema is defined in database/001_schema_v0.sql
"""
from supabase import create_client, Client
from ...config import settings
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
    Save parsed receipt to receipts table, and save items to receipt_items table.
    
    Args:
        user_id: User ID (UUID string)
        parsed_receipt: ParsedReceipt object
        ocr_text: Original OCR text
        image_url: Optional image URL
        
    Returns:
        Dictionary containing receipt_id and receipt_items information
    """
    supabase = _get_client()
    
    # Prepare receipts table data
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
        "ocr_raw_json": {"text": ocr_text},  # Store as JSONB
    }
    
    try:
        # Insert receipt
        receipt_res = supabase.table("receipts").insert(receipt_payload).execute()
        if not receipt_res.data:
            raise ValueError("Failed to insert receipt, no data returned")
        
        receipt_data = receipt_res.data[0]
        receipt_id = receipt_data["id"]
        logger.info(f"Receipt saved with ID: {receipt_id}")
        
        # Insert receipt_items
        items_data = []
        for item in parsed_receipt.items:
            # If item is on sale, mark in normalized_text
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
                "is_taxable": None,  # Not parsing for now
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
    Get test user ID (if configured).
    In production environment, should get real user_id from authentication.
    
    Returns:
        User ID string or None
    """
    if settings.test_user_id:
        return settings.test_user_id
    return None


def verify_user_exists(user_id: str) -> bool:
    """
    Verify if user exists in auth.users table.
    
    Args:
        user_id: User ID (UUID string)
        
    Returns:
        True if user exists, False otherwise
    """
    supabase = _get_client()
    try:
        # Note: Need service role key to query auth.users
        # If using anon key, may need to verify via Supabase Auth API or other methods
        # Here try to indirectly verify via receipts table query (if user has receipt records)
        res = supabase.table("receipts").select("user_id").eq("user_id", user_id).limit(1).execute()
        # If can query (or query doesn't error), user might exist
        return True
    except Exception as e:
        logger.warning(f"Could not verify user existence: {e}")
        # For development environment, assume user exists (let database throw specific error)
        return False


def get_or_create_merchant(merchant_name: str) -> Optional[int]:
    """
    Get or create merchant record based on merchant name.
    
    Args:
        merchant_name: Merchant name
        
    Returns:
        merchant_id or None
    """
    if not merchant_name:
        return None
    
    supabase = _get_client()
    
    # Normalize name (lowercase, remove special characters)
    normalized_name = merchant_name.lower().strip()
    
    try:
        # Try to find existing merchant
        res = supabase.table("merchants").select("id").eq("normalized_name", normalized_name).execute()
        
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
        
        # Create new merchant
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
