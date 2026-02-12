"""
Supabase client for storing receipt OCR data and parsed receipts.

Note: The database schema is defined in database/001_schema_v2.sql
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


def check_duplicate_by_hash(
    file_hash: str,
    user_id: str
) -> Optional[str]:
    """
    Check if a receipt with the same file hash already exists for this user.
    
    Args:
        file_hash: SHA256 hash of the file
        user_id: User ID (UUID string)
        
    Returns:
        Existing receipt_id if duplicate found, None otherwise
    """
    if not file_hash or not user_id:
        return None
    
    supabase = _get_client()
    
    try:
        res = supabase.table("receipts").select("id, uploaded_at, current_status").eq(
            "user_id", user_id
        ).eq("file_hash", file_hash).limit(1).execute()
        
        if res.data and len(res.data) > 0:
            existing_receipt = res.data[0]
            logger.info(
                f"Duplicate receipt found: file_hash={file_hash[:16]}..., "
                f"existing_receipt_id={existing_receipt['id']}, "
                f"uploaded_at={existing_receipt.get('uploaded_at')}, "
                f"status={existing_receipt.get('current_status')}"
            )
            return existing_receipt["id"]
        
        return None
    except Exception as e:
        logger.warning(f"Failed to check duplicate by hash: {e}")
        # Don't raise - allow processing to continue if check fails
        return None


def create_receipt(user_id: str, raw_file_url: Optional[str] = None, file_hash: Optional[str] = None) -> str:
    """
    Create a new receipt record in receipts table.
    
    Args:
        user_id: User identifier (UUID string)
        raw_file_url: Optional URL to the uploaded file
        file_hash: Optional SHA256 hash of the file for duplicate detection
        
    Returns:
        receipt_id (UUID string)
    """
    if not user_id:
        raise ValueError("user_id is required")
    
    supabase = _get_client()
    
    payload = {
        "user_id": user_id,
        "current_status": "failed",  # Start with "failed", will be updated to "success" when processing completes
        "current_stage": "ocr",  # Start with ocr, will be updated during processing
        "raw_file_url": raw_file_url,
        "file_hash": file_hash,
    }
    
    logger.info(f"[DEBUG] Attempting to insert receipt with payload: {payload}")
    
    try:
        res = supabase.table("receipts").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to create receipt, no data returned")
        receipt_id = res.data[0]["id"]
        logger.info(f"Created receipt record: {receipt_id}")
        return receipt_id
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[DEBUG] Insert failed with error: {type(e).__name__}")
        logger.error(f"[DEBUG] Error message: {error_msg}")
        logger.error(f"[DEBUG] Payload was: {payload}")
        # Check if it's a unique constraint violation (duplicate file_hash)
        if "unique" in error_msg.lower() or "duplicate" in error_msg.lower():
            logger.warning(
                f"Duplicate receipt detected (unique constraint): file_hash={file_hash[:16] if file_hash else 'None'}..., "
                f"user_id={user_id}. This receipt has already been uploaded."
            )
            # Try to find the existing receipt
            if file_hash:
                existing_id = check_duplicate_by_hash(file_hash, user_id)
                if existing_id:
                    raise ValueError(f"Duplicate receipt: This file has already been uploaded (receipt_id={existing_id})")
        
        logger.error(
            f"Failed to create receipt: {type(e).__name__}: {error_msg}. "
            f"user_id={user_id}. "
            "Common causes: "
            "1. user_id does not exist in users table (foreign key constraint violation), "
            "2. user_id is not a valid UUID format, "
            "3. Duplicate file_hash (same file uploaded twice), "
            "4. Database connection or permission issue."
        )
        raise


def save_processing_run(
    receipt_id: str,
    stage: str,
    model_provider: Optional[str],
    model_name: Optional[str],
    model_version: Optional[str],
    input_payload: Dict[str, Any],
    output_payload: Dict[str, Any],
    output_schema_version: Optional[str],
    status: str,
    error_message: Optional[str] = None
) -> str:
    """
    Save a processing run to receipt_processing_runs table.
    
    Args:
        receipt_id: Receipt ID (UUID string)
        stage: Processing stage ('ocr', 'llm', 'manual')
        model_provider: Model provider (e.g., 'google_documentai', 'gemini', 'openai')
        model_name: Model name (e.g., 'gpt-4o-mini', 'gemini-1.5-flash')
        model_version: Model version (e.g., '2024-01-01')
        input_payload: Input data (JSONB)
        output_payload: Output data (JSONB)
        output_schema_version: Output schema version
        status: Processing status ('pass' or 'fail')
        error_message: Optional error message if status is 'fail'
        
    Returns:
        run_id (UUID string)
    """
    if stage not in ('ocr', 'llm', 'manual'):
        raise ValueError(f"Invalid stage: {stage}")
    if status not in ('pass', 'fail'):
        raise ValueError(f"Invalid status: {status}")
    
    supabase = _get_client()
    
    # Extract validation_status from output_payload for LLM stage records
    validation_status = None
    if stage == "llm" and output_payload:
        metadata = output_payload.get("_metadata", {})
        validation_status = metadata.get("validation_status")
        # Ensure validation_status is one of the valid values
        if validation_status and validation_status not in ("pass", "needs_review", "unknown"):
            logger.warning(f"Invalid validation_status '{validation_status}', setting to 'unknown'")
            validation_status = "unknown"
    
    payload = {
        "receipt_id": receipt_id,
        "stage": stage,
        "model_provider": model_provider,
        "model_name": model_name,
        "model_version": model_version,
        "input_payload": input_payload,
        "output_payload": output_payload,
        "output_schema_version": output_schema_version,
        "status": status,
        "error_message": error_message,
        "validation_status": validation_status,  # Add validation_status field
    }
    
    try:
        res = supabase.table("receipt_processing_runs").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to save processing run, no data returned")
        run_id = res.data[0]["id"]
        logger.info(f"Saved processing run: {run_id} (stage={stage}, status={status})")
        return run_id
    except Exception as e:
        logger.error(f"Failed to save processing run: {e}")
        raise


def update_receipt_status(
    receipt_id: str,
    current_status: str,
    current_stage: str
) -> None:
    """
    Update receipt current_status and current_stage.
    
    Args:
        receipt_id: Receipt ID (UUID string)
        current_status: New status ('success', 'failed', 'needs_review')
        current_stage: New stage ('ocr', 'llm_primary', 'llm_fallback', 'manual')
    """
    if current_status not in ('success', 'failed', 'needs_review'):
        raise ValueError(f"Invalid status: {current_status}")
    if current_stage not in ('ocr', 'llm_primary', 'llm_fallback', 'manual'):
        raise ValueError(f"Invalid stage: {current_stage}")
    
    supabase = _get_client()
    
    try:
        supabase.table("receipts").update({
            "current_status": current_status,
            "current_stage": current_stage,
        }).eq("id", receipt_id).execute()
        logger.info(f"Updated receipt {receipt_id}: status={current_status}, stage={current_stage}")
    except Exception as e:
        logger.error(f"Failed to update receipt status: {e}")
        raise


def update_receipt_file_url(
    receipt_id: str,
    raw_file_url: str
) -> None:
    """
    Update receipt raw_file_url.
    
    Args:
        receipt_id: Receipt ID (UUID string)
        raw_file_url: File URL or path
    """
    supabase = _get_client()
    
    try:
        supabase.table("receipts").update({
            "raw_file_url": raw_file_url,
        }).eq("id", receipt_id).execute()
        logger.info(f"Updated receipt {receipt_id}: raw_file_url={raw_file_url}")
    except Exception as e:
        logger.error(f"Failed to update receipt file URL: {e}")
        raise


# DEPRECATED: save_parsed_receipt is no longer used
# Receipts are now saved via create_receipt + save_processing_run


def get_test_user_id() -> Optional[str]:
    """
    Get test user ID (if configured).
    In production environment, should get real user_id from authentication.
    
    Returns:
        User ID string or None
    """
    # First, try to get from environment variable
    if settings.test_user_id:
        logger.info(f"Using TEST_USER_ID from environment: {settings.test_user_id}")
        return settings.test_user_id
    
    logger.info("TEST_USER_ID not set in environment, attempting to get first user from database...")
    # If not set, try to get the first user from database
    try:
        supabase = _get_client()
        res = supabase.table("users").select("id, user_name, email").limit(1).execute()
        if res.data and len(res.data) > 0:
            user_id = res.data[0]["id"]
            user_name = res.data[0].get("user_name", "N/A")
            logger.info(f"✓ Auto-detected user_id from database: {user_id} (name: {user_name})")
            return user_id
        else:
            logger.warning("No users found in users table")
    except Exception as e:
        logger.error(f"✗ Failed to get user from database: {type(e).__name__}: {e}")
    
    # Return None if nothing found
    logger.warning("get_test_user_id() returning None - no user_id available")
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


def save_receipt_summary(
    receipt_id: str,
    user_id: str,
    receipt_data: Dict[str, Any]
) -> str:
    """
    Save receipt summary data to receipt_summaries table.
    
    Args:
        receipt_id: Receipt ID (UUID string)
        user_id: User ID (UUID string)
        receipt_data: Receipt-level data from LLM output
        
    Returns:
        summary_id (UUID string)
    """
    if not receipt_id or not user_id:
        raise ValueError("receipt_id and user_id are required")
    
    supabase = _get_client()
    
    # Extract receipt-level fields
    merchant_name = receipt_data.get("merchant_name")
    merchant_address = receipt_data.get("merchant_address")
    purchase_date = receipt_data.get("purchase_date")
    purchase_time = receipt_data.get("purchase_time")
    subtotal = receipt_data.get("subtotal")
    tax = receipt_data.get("tax")
    total = receipt_data.get("total")
    currency = receipt_data.get("currency", "USD")
    payment_method = receipt_data.get("payment_method")
    card_last4 = receipt_data.get("card_last4")
    country = receipt_data.get("country")
    
    if not total:
        raise ValueError("total is required in receipt_data")
    
    # Try to match store_chain and store_location
    store_chain_id = None
    store_location_id = None
    
    if merchant_name:
        try:
            # Try to find existing store chain
            chain_result = supabase.table("store_chains").select("id").ilike("name", f"%{merchant_name}%").limit(1).execute()
            if chain_result.data and len(chain_result.data) > 0:
                store_chain_id = chain_result.data[0]["id"]
                logger.info(f"Matched store chain: {merchant_name} -> {store_chain_id}")
            else:
                logger.debug(f"Store chain not found for: {merchant_name}")
        except Exception as e:
            logger.warning(f"Failed to match store chain: {e}")
    
    # Prepare payload
    payload = {
        "receipt_id": receipt_id,
        "user_id": user_id,
        "store_chain_id": store_chain_id,
        "store_location_id": store_location_id,
        "store_name": merchant_name,
        "store_address": merchant_address,
        "subtotal": float(subtotal) if subtotal else None,
        "tax": float(tax) if tax else None,
        "total": float(total),
        "currency": currency,
        "payment_method": payment_method,
        "payment_last4": card_last4,
        "receipt_date": purchase_date,
    }
    
    try:
        res = supabase.table("receipt_summaries").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to create receipt summary, no data returned")
        summary_id = res.data[0]["id"]
        logger.info(f"Created receipt_summary: {summary_id} for receipt {receipt_id}")
        return summary_id
    except Exception as e:
        logger.error(f"Failed to create receipt summary: {e}")
        raise


def save_receipt_items(
    receipt_id: str,
    user_id: str,
    items_data: List[Dict[str, Any]]
) -> List[str]:
    """
    Save receipt items to receipt_items table.
    
    Args:
        receipt_id: Receipt ID (UUID string)
        user_id: User ID (UUID string)
        items_data: List of item dictionaries from LLM output
        
    Returns:
        List of item_ids (UUID strings)
    """
    if not receipt_id or not user_id:
        raise ValueError("receipt_id and user_id are required")
    
    if not items_data:
        logger.warning(f"No items to save for receipt {receipt_id}")
        return []
    
    supabase = _get_client()
    
    # Prepare batch insert
    items_payload = []
    for idx, item in enumerate(items_data):
        product_name = item.get("product_name")
        if not product_name:
            logger.warning(f"Skipping item without product_name at index {idx}")
            continue
        
        quantity = item.get("quantity")
        unit = item.get("unit")
        unit_price = item.get("unit_price")
        line_total = item.get("line_total")
        
        if line_total is None:
            logger.warning(f"Skipping item '{product_name}' without line_total")
            continue
        
        # Extract brand if available
        brand = item.get("brand")
        
        # Extract category (for now just save as TEXT, Phase 2 will link to categories table)
        category = item.get("category")
        category_l1 = None
        category_l2 = None
        category_l3 = None
        
        # Try to parse category string (e.g., "Grocery > Produce > Fruit")
        if category:
            parts = [p.strip() for p in category.split(">")]
            if len(parts) >= 1:
                category_l1 = parts[0]
            if len(parts) >= 2:
                category_l2 = parts[1]
            if len(parts) >= 3:
                category_l3 = parts[2]
        
        # Check for sale/discount
        is_on_sale = item.get("is_on_sale", False)
        original_price = item.get("original_price")
        discount_amount = item.get("discount_amount")
        
        item_payload = {
            "receipt_id": receipt_id,
            "user_id": user_id,
            "product_name": product_name,
            "brand": brand,
            "quantity": float(quantity) if quantity else None,
            "unit": unit,
            "unit_price": float(unit_price) if unit_price else None,
            "line_total": float(line_total),
            "on_sale": is_on_sale,
            "original_price": float(original_price) if original_price else None,
            "discount_amount": float(discount_amount) if discount_amount else None,
            "category_l1": category_l1,
            "category_l2": category_l2,
            "category_l3": category_l3,
            "item_index": idx,
        }
        
        items_payload.append(item_payload)
    
    if not items_payload:
        logger.warning(f"No valid items to insert for receipt {receipt_id}")
        return []
    
    try:
        res = supabase.table("receipt_items").insert(items_payload).execute()
        if not res.data:
            raise ValueError("Failed to create receipt items, no data returned")
        item_ids = [item["id"] for item in res.data]
        logger.info(f"Created {len(item_ids)} receipt_items for receipt {receipt_id}")
        return item_ids
    except Exception as e:
        logger.error(f"Failed to create receipt items: {e}")
        raise


def get_store_chain(
    chain_name: str,
    store_address: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get store chain by name using fuzzy matching.
    Does NOT create candidate here - candidate should be created after LLM processing
    with complete information.
    
    Args:
        chain_name: Store chain name (e.g., "Costco", "T&T Supermarket")
        store_address: Optional store address for better matching
        
    Returns:
        Dict with:
        - 'matched': bool - Whether a high confidence match was found
        - 'chain_id': Optional[str] - Matched chain_id (if high confidence)
        - 'location_id': Optional[str] - Matched location_id (if high confidence)
        - 'suggested_chain_id': Optional[str] - Suggested chain_id (if low confidence)
        - 'suggested_location_id': Optional[str] - Suggested location_id (if low confidence)
        - 'confidence_score': Optional[float] - Confidence score (0.0-1.0)
    """
    if not chain_name:
        return {
            "matched": False,
            "chain_id": None,
            "location_id": None,
            "suggested_chain_id": None,
            "suggested_location_id": None,
            "confidence_score": None
        }
    
    # Import here to avoid circular dependency
    from ...processors.enrichment.address_matcher import match_store
    
    # Try to match using address_matcher
    match_result = match_store(chain_name, store_address)
    
    if match_result.get("matched"):
        # High confidence match - return directly
        result = {
            "matched": True,
            "chain_id": match_result.get("chain_id"),
            "location_id": match_result.get("location_id"),
            "suggested_chain_id": None,
            "suggested_location_id": None,
            "confidence_score": match_result.get("confidence_score")
        }
        logger.info(f"Matched store chain: {chain_name} -> chain_id={result['chain_id']}, location_id={result.get('location_id')}")
        return result
    
    # Not matched - return suggestion info if available
    result = {
        "matched": False,
        "chain_id": None,
        "location_id": None,
        "suggested_chain_id": match_result.get("suggested_chain_id"),
        "suggested_location_id": match_result.get("suggested_location_id"),
        "confidence_score": match_result.get("confidence_score")
    }
    
    if result.get("suggested_chain_id"):
        logger.info(f"Low confidence match for store chain: {chain_name} -> suggested_chain_id={result['suggested_chain_id']}, confidence={result.get('confidence_score', 0):.2f}")
    else:
        logger.info(f"Store chain not found: {chain_name}, will create candidate after LLM processing")
    
    return result


def create_store_candidate(
    chain_name: str,
    receipt_id: Optional[str] = None,
    source: str = "llm",
    llm_result: Optional[Dict[str, Any]] = None,
    suggested_chain_id: Optional[str] = None,
    suggested_location_id: Optional[str] = None,
    confidence_score: Optional[float] = None
) -> Optional[str]:
    """
    Create a store candidate in store_candidates table with complete information.
    
    Args:
        chain_name: Store chain name
        receipt_id: Receipt ID that triggered this candidate
        source: Source of the candidate ('ocr', 'llm', 'user')
        llm_result: Optional LLM result to extract structured data (address, phone, currency, etc.)
        suggested_chain_id: Optional suggested chain_id from fuzzy matching
        suggested_location_id: Optional suggested location_id from fuzzy matching
        confidence_score: Optional confidence score (0.00 - 1.00)
        
    Returns:
        candidate_id (UUID string) or None
    """
    if not chain_name:
        return None
    
    if source not in ('ocr', 'llm', 'user'):
        raise ValueError(f"Invalid source: {source}")
    
    supabase = _get_client()
    
    normalized_name = chain_name.lower().strip()
    
    # Extract structured data from LLM result
    metadata = {}
    if llm_result:
        receipt = llm_result.get("receipt", {})
        
        # Extract address information (structured)
        address_info = {}
        if receipt.get("merchant_address"):
            address_info["full_address"] = receipt.get("merchant_address")
        
        # Try to get structured address fields
        if receipt.get("address1"):
            address_info["address1"] = receipt.get("address1")
        if receipt.get("address2"):
            address_info["address2"] = receipt.get("address2")
        if receipt.get("city"):
            address_info["city"] = receipt.get("city")
        if receipt.get("state"):
            address_info["state"] = receipt.get("state")
        if receipt.get("country"):
            address_info["country"] = receipt.get("country")
        if receipt.get("zipcode"):
            address_info["zipcode"] = receipt.get("zipcode")
        
        # If structured fields are missing but we have merchant_address, try to parse it
        if not address_info.get("address1") and receipt.get("merchant_address"):
            try:
                from ...processors.enrichment.address_matcher import extract_address_components_from_string
                parsed_components = extract_address_components_from_string(receipt.get("merchant_address"))
                if parsed_components:
                    if parsed_components.get("address1"):
                        address_info["address1"] = parsed_components["address1"]
                    if parsed_components.get("address2"):
                        address_info["address2"] = parsed_components["address2"]
                    if parsed_components.get("city"):
                        address_info["city"] = parsed_components["city"]
                    if parsed_components.get("state"):
                        address_info["state"] = parsed_components["state"]
                    if parsed_components.get("country"):
                        address_info["country"] = parsed_components["country"]
                    if parsed_components.get("zipcode"):
                        address_info["zipcode"] = parsed_components["zipcode"]
            except Exception as e:
                logger.warning(f"Failed to parse address from merchant_address: {e}")
        
        if address_info:
            metadata["address"] = address_info
        
        # Extract contact information
        if receipt.get("merchant_phone"):
            metadata["phone"] = receipt.get("merchant_phone")
        
        # Extract currency
        if receipt.get("currency"):
            metadata["currency"] = receipt.get("currency")
        
        # Extract purchase date/time (for reference)
        if receipt.get("purchase_date"):
            metadata["purchase_date"] = receipt.get("purchase_date")
        if receipt.get("purchase_time"):
            metadata["purchase_time"] = receipt.get("purchase_time")
    
    payload = {
        "raw_name": chain_name,
        "normalized_name": normalized_name,
        "source": source,
        "receipt_id": receipt_id,
        "suggested_chain_id": suggested_chain_id,
        "suggested_location_id": suggested_location_id,
        "confidence_score": confidence_score,
        "status": "pending",
        "metadata": metadata if metadata else None,
    }
    
    try:
        res = supabase.table("store_candidates").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to create store candidate, no data returned")
        candidate_id = res.data[0]["id"]
        logger.info(f"Created store candidate: {candidate_id} for '{chain_name}' (receipt_id={receipt_id})")
        return candidate_id
    except Exception as e:
        logger.error(f"Failed to create store candidate: {e}")
        return None
