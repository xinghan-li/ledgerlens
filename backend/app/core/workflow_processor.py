"""
Workflow Processor: Complete receipt processing workflow.

Workflow:
1. Google Document AI OCR
2. Decide whether to use Gemini or GPT-4o-mini based on Gemini rate limiting
3. LLM processing to get structured JSON
4. Sum check
5. If failed, introduce AWS OCR + GPT-4o-mini secondary processing
6. File storage and timeline recording
7. Statistics update
"""
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime, timezone
import json
from pathlib import Path
import asyncio
import hashlib

from ..services.ocr.documentai_client import parse_receipt_documentai
from ..services.ocr.textract_client import parse_receipt_textract
from ..services.llm.gemini_rate_limiter import check_gemini_available, record_gemini_request
from ..services.llm.receipt_llm_processor import process_receipt_with_llm_from_ocr
from ..processors.core.sum_checker import check_receipt_sums, apply_field_conflicts_resolution, _effective_tolerance
from ..services.llm.llm_client import parse_receipt_with_llm
from ..prompts.prompt_manager import format_prompt, get_default_prompt
from ..prompts.prompt_loader import get_debug_prompt_system
from ..services.llm.gemini_client import (
    parse_receipt_with_gemini_vision,
    parse_receipt_with_gemini,
    parse_receipt_with_gemini_vision_escalation,
    is_image_receipt_like,
)
from ..services.llm.llm_client import parse_receipt_with_llm, parse_receipt_with_openai_vision
from ..config import settings
from ..services.database.statistics_manager import record_api_call
from ..services.database.supabase_client import (
    create_receipt,
    save_processing_run,
    update_receipt_status,
    get_test_user_id,
    update_receipt_file_url,
    check_duplicate_by_hash,
    USER_CLASS_ADMIN,
    get_user_class,
    get_store_chain,
    create_store_candidate,
    save_non_receipt_reject,
    append_workflow_step,
    check_user_locked,
    record_strike,
    count_strikes_in_last_hour,
    apply_user_lock,
)
from ..processors.enrichment.address_matcher import match_store, fix_ocr_address
from ..services.ocr.ocr_normalizer import normalize_ocr_result, extract_unified_info
import shutil
from ..exporters.csv_exporter import convert_receipt_to_csv_rows, append_to_daily_csv, get_csv_headers
from ..processors.stores.chain_cleaners import apply_chain_cleaner
from ..processors.enrichment.address_matcher import correct_address
from ..processors.text.data_cleaner import clean_llm_result
from ..processors.validation.coordinate_extractor import extract_text_blocks_with_coordinates
from ..processors.validation.pipeline import process_receipt_pipeline
from ..processors.validation.store_config_loader import get_store_config_for_receipt
from ..services.categorization.receipt_categorizer import categorize_receipt

logger = logging.getLogger(__name__)


def _initial_parse_summary_for_run(initial_parse_result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Build a small summary of rule-based initial parse for receipt_processing_runs input_payload (avoid storing full result)."""
    if not initial_parse_result or not isinstance(initial_parse_result, dict):
        return None
    return {
        "success": bool(initial_parse_result.get("success")),
        "method": initial_parse_result.get("method"),
        "items_count": len(initial_parse_result.get("items") or []),
        "chain_id": initial_parse_result.get("chain_id"),
    }


def _fail_output_payload(error_message: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Standard JSON output_payload when a stage fails; only error and reason, no uncertain structural answer."""
    return {"error": error_message, "reason": reason or error_message}


# Output directories (moved to project root)
# Path(__file__).parent.parent.parent.parent is project root
# backend/app/core/workflow_processor.py -> backend/app/core -> backend/app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = PROJECT_ROOT / "output"
INPUT_ROOT = PROJECT_ROOT / "input"

# Ensure root directories exist
OUTPUT_ROOT.mkdir(exist_ok=True)
INPUT_ROOT.mkdir(exist_ok=True)

# Escalation prompt: when cascade fails, send image to strongest models (GPT-5.1 / Gemini 3)
ESCALATION_VISION_PROMPT = """You are a bookkeeper for personal shopping categorization. This is a grocery receipt image. Traditional OCR and the initial Gemini 2.5 model could not correctly handle it and there are needs_review bugs.

As the escalated stronger model, please read the image and output a single structured JSON object with this exact structure. All monetary amounts in cents (integers).

{
  "receipt": {
    "merchant_name": "store name",
    "merchant_phone": "phone or null",
    "merchant_address": "string or null",
    "address_line1": "street only",
    "address_line2": "unit number only, e.g. 101 (no Suite/Unit/#)",
    "city": "string or null",
    "state": "string or null",
    "zip_code": "string or null",
    "country": "string or null",
    "subtotal": 2201,
    "tax": 0,
    "total": 2269,
    "currency": "USD",
    "payment_method": "Visa etc",
    "card_last4": "3719",
    "purchase_date": "YYYY-MM-DD",
    "purchase_time": "HH:MM or HH:MM:SS"
  },
  "items": [
    {
      "product_name": "item name",
      "quantity": 1,
      "unit": "lb or null",
      "unit_price": 199,
      "line_total": 199,
      "raw_text": "line as on receipt",
      "is_on_sale": false
    }
  ]
}

Rules:
1. Extract every line item with product_name, quantity, unit, unit_price, line_total.
2. Perform a sum check: sum(line_total) must equal receipt.subtotal (within 3 cents or 1%), and subtotal + tax must equal receipt.total.
3. Only output the JSON if your sum check passes. If it does not pass, fix the numbers so it passes, then output.
4. Output only valid JSON, no markdown or extra text."""


class TimelineRecorder:
    """Record timeline of processing workflow."""
    
    def __init__(self, receipt_id: str):
        self.receipt_id = receipt_id
        self.timeline: List[Dict[str, Any]] = []
        self._start_times: Dict[str, datetime] = {}
    
    def start(self, step: str):
        """Record step start time."""
        now = datetime.now(timezone.utc)
        self._start_times[step] = now
        self.timeline.append({
            "step": f"{step}_start",
            "timestamp": now.isoformat(),
            "duration_ms": None
        })

    def end(self, step: str):
        """Record step end time."""
        now = datetime.now(timezone.utc)
        start_time = self._start_times.get(step)
        duration_ms = None
        
        if start_time:
            duration = (now - start_time).total_seconds() * 1000
            duration_ms = round(duration, 2)
        
        self.timeline.append({
            "step": f"{step}_end",
            "timestamp": now.isoformat(),
            "duration_ms": duration_ms
        })

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "receipt_id": self.receipt_id,
            "timeline": self.timeline
        }


def generate_receipt_id(filename: Optional[str] = None) -> str:
    """
    Generate receipt ID (format: seq_mmyydd_hhmm_filename).
    
    Uses timestamp with microseconds to ensure uniqueness even in high-concurrency scenarios.
    For production, consider using database auto-increment or UUID for guaranteed uniqueness.
    
    Args:
        filename: Optional original filename to include in receipt ID
    
    Returns:
        Receipt ID string
    """
    now = datetime.now(timezone.utc)
    # Use microseconds to ensure uniqueness (6 digits from seconds + 2 digits from microseconds)
    # Format: HHMMSS + last 2 digits of microseconds = 8 digits total
    seq = now.strftime("%H%M%S") + str(now.microsecond)[-2:]  # 8 digits total
    date_time = now.strftime("%m%d%y_%H%M")
    
    # Include filename in receipt ID if provided
    if filename:
        # Clean filename: remove extension, replace spaces/special chars with underscores, limit length
        from pathlib import Path
        clean_name = Path(filename).stem  # Remove extension
        # Replace spaces and special characters with underscores
        import re
        clean_name = re.sub(r'[^\w\-_]', '_', clean_name)
        # Limit length to 20 characters to keep receipt_id reasonable
        clean_name = clean_name[:20]
        if clean_name:
            return f"{seq}_{date_time}_{clean_name}"
    
    return f"{seq}_{date_time}"


def get_date_folder_name(receipt_id: str = None) -> str:
    """
    Get date folder name in format YYYYMMDD.
    
    Args:
        receipt_id: Optional receipt ID to extract date from 
                    Format: seq_mmyydd_hhmm or seq_mmyydd_hhmm_filename
                    Example: 062332_012126_0623 or 062332_012126_0623_receipt1
    
    Returns:
        Date string in format YYYYMMDD
    """
    if receipt_id:
        # Try to extract date from receipt_id (format: seq_mmyydd_hhmm or seq_mmyydd_hhmm_filename)
        # Example: 062332_012126_0623 -> 012126 -> 01/21/26 -> 20260121
        # Example: 062332_012126_0623_receipt1 -> 012126 -> 01/21/26 -> 20260121
        import re
        match = re.search(r'_(\d{2})(\d{2})(\d{2})_', receipt_id)
        if match:
            month = match.group(1)
            day = match.group(2)
            year_2digit = match.group(3)
            # Assume 20XX
            year = f"20{year_2digit}"
            return f"{year}{month}{day}"
    
    # Fallback to current date
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d")


def _get_duration_from_timeline(timeline: TimelineRecorder, step_name: str) -> Optional[int]:
    """
    Get duration in milliseconds for a step from timeline.
    
    Args:
        timeline: TimelineRecorder instance
        step_name: Step name (e.g., "google_ocr", "gemini_llm")
        
    Returns:
        Duration in milliseconds or None
    """
    for entry in timeline.timeline:
        if entry.get("step") == f"{step_name}_end":
            return entry.get("duration_ms")
    return None


def _save_image_for_manual_review(
    receipt_id: str,
    image_bytes: bytes,
    filename: str
) -> Optional[str]:
    """
    Save image file for manual review (when processing fails).
    
    Args:
        receipt_id: Receipt ID
        image_bytes: Image bytes
        filename: Original filename
        
    Returns:
        Relative file path or None if failed
    """
    try:
        paths = get_output_paths_for_receipt(receipt_id)
        error_dir = paths["error_dir"]
        error_dir.mkdir(parents=True, exist_ok=True)
        
        # Determine file extension from filename or default to .jpg
        file_ext = Path(filename).suffix.lower() if filename else ".jpg"
        if file_ext not in [".jpg", ".jpeg", ".png"]:
            file_ext = ".jpg"
        
        image_file = error_dir / f"{receipt_id}_original{file_ext}"
        
        with open(image_file, "wb") as f:
            f.write(image_bytes)
        
        # Return relative path from project root
        relative_path = image_file.relative_to(PROJECT_ROOT)
        logger.info(f"Saved image for manual review: {relative_path}")
        return str(relative_path)
    except Exception as e:
        logger.error(f"Failed to save image for manual review: {e}")
        return None


def get_output_paths_for_receipt(receipt_id: str, date_folder: str = None) -> Dict[str, Path]:
    """
    Get all output paths for a receipt based on new directory structure.
    
    Returns:
        Dictionary with keys: date_dir, json_file, timeline_dir, timeline_file, csv_file, debug_dir, error_dir
    """
    if date_folder is None:
        date_folder = get_date_folder_name(receipt_id)
    
    date_dir = OUTPUT_ROOT / date_folder
    
    return {
        "date_dir": date_dir,
        "json_file": date_dir / f"{receipt_id}_output.json",
        "timeline_dir": date_dir / "timeline",
        "timeline_file": date_dir / "timeline" / f"{receipt_id}_timeline.json",
        "csv_file": date_dir / f"{date_folder}.csv",
        "debug_dir": date_dir / "debug-001",  # Fixed name for now, can be made dynamic later
        "error_dir": date_dir / "error-001"   # Fixed name for now, can be made dynamic later
    }


def _validate_receipt_like(ocr_result: Dict[str, Any]) -> tuple:
    """
    Check if OCR result looks like a receipt: (1) has total, (2) top 1/3 has store/address-like text.
    Returns (True, "") if valid, (False, reason) if not (for logging and non_receipt_rejects.reason).
    """
    # 1. Must have a total amount
    total = ocr_result.get("total")
    if total is None:
        return False, "no_total"
    try:
        if float(total) <= 0:
            return False, "total_zero_or_negative"
    except (TypeError, ValueError):
        return False, "total_not_numeric"
    # 2. Top 1/3 of receipt should have store name / address (multiple lines of text)
    coord = ocr_result.get("coordinate_data") or {}
    blocks = coord.get("text_blocks") or []
    top_text_parts = []
    for b in blocks:
        bbox = b.get("bounding_box") or {}
        y = bbox.get("y", 1.0)
        if bbox.get("is_normalized", True) and y < 0.35:
            top_text_parts.append((b.get("text") or "").strip())
        elif not bbox.get("is_normalized") and y < 200:
            top_text_parts.append((b.get("text") or "").strip())
    top_text = " ".join(p for p in top_text_parts if p)
    if len(top_text.strip()) < 10:
        return False, "no_store_or_address_in_top_third"
    return True, ""


async def process_receipt_workflow(
    image_bytes: bytes,
    filename: str,
    mime_type: str = "image/jpeg",
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Complete receipt processing workflow.
    
    Args:
        image_bytes: Image bytes
        filename: Filename
        mime_type: MIME type
        user_id: Optional user ID (if None, uses get_test_user_id())
        
    Returns:
        Processing result dictionary
    """
    receipt_id = generate_receipt_id(filename)
    timeline = TimelineRecorder(receipt_id)
    
    # Calculate file hash for duplicate detection
    original_file_hash = hashlib.sha256(image_bytes).hexdigest()
    file_hash = original_file_hash

    # Get user_id
    if user_id is None:
        user_id = get_test_user_id()
        if not user_id:
            logger.warning("get_test_user_id() returned None")
    
    # 12h lock check (non-admin): 3 strikes in 1h -> locked
    if user_id:
        user_class = get_user_class(user_id)
        if user_class < USER_CLASS_ADMIN:
            locked, locked_until = check_user_locked(user_id)
            if locked:
                return {
                    "success": False,
                    "receipt_id": None,
                    "status": "locked",
                    "error": "user_locked",
                    "message": "Upload is temporarily locked due to repeated non-receipt uploads. Please try again later.",
                    "locked_until": locked_until.isoformat() if locked_until else None,
                }
    
    # Check for duplicate before processing (if user_id is available)
    # Only admin and super_admin may upload duplicates; others get a clear error for frontend.
    if user_id:
        existing_receipt_id = check_duplicate_by_hash(file_hash, user_id)
        if existing_receipt_id:
            user_class = get_user_class(user_id)
            allow_duplicate = user_class >= USER_CLASS_ADMIN or settings.allow_duplicate_for_debug
            if allow_duplicate:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                file_hash = f"{original_file_hash}_debug_{timestamp}"
            else:
                logger.warning(
                    f"Duplicate receipt rejected for user {user_id} (class={user_class}): existing_receipt_id={existing_receipt_id}"
                )
                return {
                    "success": False,
                    "receipt_id": receipt_id,
                    "status": "duplicate",
                    "error": "duplicate_receipt",
                    "message": "This receipt has already been uploaded. If there was an error, please delete the existing receipt and upload a new photo.",
                    "existing_receipt_id": existing_receipt_id,
                }
    
    # Validate user_id before creating receipt
    if not user_id:
        logger.error(
            "user_id is required but not provided. "
            "Please set TEST_USER_ID environment variable or provide user_id parameter. "
            "The user_id must be a valid UUID that exists in the users table."
        )
        # Continue without database storage, but log the issue
        db_receipt_id = None
    else:
        # Create receipt record in database
        db_receipt_id: Optional[str] = None
        try:
            db_receipt_id = create_receipt(user_id=user_id, raw_file_url=None, file_hash=file_hash)
            logger.info(f"Created receipt record: {db_receipt_id}")
            if db_receipt_id:
                append_workflow_step(db_receipt_id, "create_db", "ok")
        except Exception as e:
            error_msg = str(e)
            # Check if it's a duplicate error (unique constraint on file_hash)
            if "duplicate" in error_msg.lower() or "Duplicate receipt" in error_msg:
                user_class = get_user_class(user_id)
                allow_duplicate = user_class >= USER_CLASS_ADMIN or settings.allow_duplicate_for_debug
                if allow_duplicate:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    file_hash = f"{original_file_hash}_debug_{timestamp}"
                    try:
                        db_receipt_id = create_receipt(user_id=user_id, raw_file_url=None, file_hash=file_hash)
                        logger.info(f"Created receipt record (retry): {db_receipt_id}")
                    except Exception as retry_error:
                        logger.error(f"Failed to create receipt even with modified hash: {retry_error}")
                        raise
                else:
                    logger.warning(f"Duplicate receipt during creation for user {user_id}: {error_msg}")
                    existing_receipt_id = check_duplicate_by_hash(original_file_hash, user_id)
                    return {
                        "success": False,
                        "receipt_id": receipt_id,
                        "status": "duplicate",
                        "error": "duplicate_receipt",
                        "message": "This receipt has already been uploaded. If there was an error, please delete the existing receipt and upload a new photo.",
                        "existing_receipt_id": existing_receipt_id,
                    }
            
            logger.error(
                f"✗ Failed to create receipt record in database: {type(e).__name__}: {e}. "
                f"user_id={user_id}. "
                "This may be due to: "
                "1. Invalid user_id (must be a valid UUID that exists in users table), "
                "2. Database connection issue, "
                "3. Missing user record in users table. "
                "Continuing with file-only workflow."
            )
            db_receipt_id = None
    
    try:
        # Step 1: Google Document AI OCR
        # Update stage to ocr
        if db_receipt_id:
            try:
                update_receipt_status(db_receipt_id, current_status="failed", current_stage="ocr")
            except Exception as e:
                logger.warning(f"Failed to update receipt stage to ocr: {e}")
        
        timeline.start("google_ocr")
        try:
            google_ocr_result = parse_receipt_documentai(image_bytes, mime_type=mime_type)
            timeline.end("google_ocr")
            
            # Save OCR processing run to database
            if db_receipt_id:
                try:
                    # Calculate duration from timeline
                    ocr_duration = None
                    for entry in timeline.timeline:
                        if entry.get("step") == "google_ocr_end":
                            ocr_duration = entry.get("duration_ms")
                            break
                    
                    ocr_run_id = save_processing_run(
                        receipt_id=db_receipt_id,
                        stage="ocr",
                        model_provider="google_documentai",
                        model_name=None,  # OCR doesn't have model_name
                        model_version=None,
                        input_payload={"image_bytes_length": len(image_bytes), "mime_type": mime_type},
                        output_payload=google_ocr_result,
                        output_schema_version=None,  # OCR doesn't have schema version
                        status="pass",
                        error_message=None
                    )
                    logger.info(f"Saved OCR processing run for receipt {db_receipt_id}")
                    append_workflow_step(db_receipt_id, "ocr", "pass", run_id=ocr_run_id)
                    
                    # Record API call for statistics
                    ocr_duration = _get_duration_from_timeline(timeline, "google_ocr")
                    record_api_call(
                        call_type="ocr",
                        provider="google_documentai",
                        receipt_id=db_receipt_id,
                        duration_ms=int(ocr_duration) if ocr_duration else None,
                        status="success"
                    )
                except Exception as e:
                    logger.warning(f"Failed to save OCR processing run: {e}")
            
            # Receipt-like validation: must have total and store/address-like content in top 1/3
            valid, reject_reason = _validate_receipt_like(google_ocr_result)
            if not valid:
                timeline.end("google_ocr")
                if db_receipt_id:
                    append_workflow_step(db_receipt_id, "valid", "fail", details={"reason": reject_reason})
                    image_path_reject = _save_image_for_manual_review(receipt_id, image_bytes, filename)
                    if image_path_reject:
                        try:
                            update_receipt_file_url(db_receipt_id, str(image_path_reject))
                        except Exception as url_err:
                            logger.warning(f"Failed to update receipt file URL: {url_err}")
                    try:
                        update_receipt_status(db_receipt_id, current_status="failed", current_stage="pending_receipt_confirm")
                    except Exception as e:
                        logger.warning(f"Failed to update receipt status: {e}")
                logger.warning(f"Receipt-like validation failed: {reject_reason}")
                return {
                    "success": False,
                    "receipt_id": db_receipt_id or receipt_id,
                    "status": "pending_receipt_confirm",
                    "error": "not_a_receipt",
                    "needs_user_confirm": True,
                    "message": "This does not look like a receipt. Please confirm this is a clear photo of a receipt (with total and store name visible).",
                }
            if db_receipt_id:
                append_workflow_step(db_receipt_id, "valid", "ok")
            # Pre-rule address correction: match and correct merchant name/address before initial_parse
            normalized_early = normalize_ocr_result(google_ocr_result, provider="google_documentai")
            unified_info = extract_unified_info(normalized_early)
            merchant_name_early = (unified_info.get("merchant_name") or "").strip()
            store_address_early = (fix_ocr_address(unified_info.get("merchant_address")) or "").strip()
            store_match = match_store(merchant_name_early, store_address_early or None)
            if store_match.get("matched") and store_match.get("location_data"):
                corrected_merchant_name = (store_match["location_data"].get("store_name") or merchant_name_early) or merchant_name_early
                corrected_address = (store_match["location_data"].get("address_string") or store_address_early) or store_address_early
                if db_receipt_id:
                    append_workflow_step(db_receipt_id, "addr_match", "ok", details={"corrected_merchant": corrected_merchant_name[:80]})
            else:
                corrected_merchant_name = merchant_name_early
                corrected_address = store_address_early
                if db_receipt_id:
                    append_workflow_step(db_receipt_id, "addr_match", "skip")
            store_in_chain = bool(store_match.get("matched"))
            
        except Exception as e:
            timeline.end("google_ocr")
            logger.error(f"Google OCR failed: {e}")
            
            # Save failed OCR run to database
            if db_receipt_id:
                try:
                    save_processing_run(
                        receipt_id=db_receipt_id,
                        stage="ocr",
                        model_provider="google_documentai",
                        model_name=None,  # OCR doesn't have model_name
                        model_version=None,
                        input_payload={"image_bytes_length": len(image_bytes), "mime_type": mime_type},
                        output_payload=_fail_output_payload(str(e)),
                        output_schema_version=None,  # OCR doesn't have schema version
                        status="fail",
                        error_message=str(e)
                    )
                    update_receipt_status(db_receipt_id, current_status="failed", current_stage="ocr")
                    
                    # Save image for manual review
                    image_path = _save_image_for_manual_review(receipt_id, image_bytes, filename)
                    if image_path:
                        try:
                            update_receipt_file_url(db_receipt_id, image_path)
                        except Exception as url_error:
                            logger.warning(f"Failed to update receipt file URL: {url_error}")
                except Exception as db_error:
                    logger.warning(f"Failed to save failed OCR run: {db_error}")
                append_workflow_step(db_receipt_id, "ocr", "fail")
            
            # OCR failed: ask Gemini "is this image receipt-like?" then branch
            like_receipt = await is_image_receipt_like(image_bytes, mime_type=mime_type)
            if not like_receipt:
                if db_receipt_id:
                    append_workflow_step(db_receipt_id, "like_receipt", "no")
                    try:
                        update_receipt_status(db_receipt_id, current_status="failed", current_stage="pending_receipt_confirm")
                    except Exception as ex:
                        logger.warning(f"Failed to update receipt status: {ex}")
                return {
                    "success": False,
                    "receipt_id": db_receipt_id or receipt_id,
                    "status": "pending_receipt_confirm",
                    "error": "ocr_failed_not_receipt_like",
                    "needs_user_confirm": True,
                    "message": "OCR failed and this does not look like a receipt. Please confirm this is a clear photo of a receipt.",
                }
            if db_receipt_id:
                append_workflow_step(db_receipt_id, "like_receipt", "yes")
            return await _run_ocr_fail_vision_then_textract(
                image_bytes=image_bytes,
                filename=filename,
                receipt_id=receipt_id,
                timeline=timeline,
                mime_type=mime_type,
                db_receipt_id=db_receipt_id,
                user_id=user_id,
                error=f"Google OCR failed: {e}",
            )
        
        # Save Google OCR result (temporarily not saved, will save when needed)
        google_ocr_data = google_ocr_result
        
        # Step 1.5: Run Initial Parse (rule-based extraction before LLM) using corrected merchant
        timeline.start("initial_parse")
        initial_parse_result = None
        try:
            # Extract coordinate data from Document AI response
            coordinate_data = google_ocr_result.get("coordinate_data", {})
            if coordinate_data:
                # Extract text blocks with coordinates
                blocks = extract_text_blocks_with_coordinates(coordinate_data, apply_receipt_body_filter=True)
                # Use corrected merchant name from pre-rule address match
                merchant_name = corrected_merchant_name
                # Load store config
                store_config = get_store_config_for_receipt(merchant_name, blocks=blocks)
                # Run rule-based pipeline (pass corrected address so output shows Hwy not Huy)
                initial_parse_result = process_receipt_pipeline(
                    blocks=blocks,
                    llm_result={},  # No LLM result yet
                    store_config=store_config,
                    merchant_name=merchant_name,
                    merchant_address=corrected_address or None,
                )
                
                logger.info(f"Initial parse completed: success={initial_parse_result.get('success')}, "
                           f"method={initial_parse_result.get('method')}, "
                           f"items={len(initial_parse_result.get('items', []))}")
            else:
                logger.warning("No coordinate data in OCR result, skipping initial parse")
                
        except Exception as e:
            logger.warning(f"Initial parse failed: {e}")
            # Don't fail the entire workflow if initial parse fails
        finally:
            timeline.end("initial_parse")
        
        # Save rule-based cleaning stage (input_payload = OCR as JSON, output_payload = RBSJ)
        if db_receipt_id:
            try:
                raw_text = (google_ocr_result.get("raw_text") or "") if isinstance(google_ocr_result.get("raw_text"), str) else ""
                coord = google_ocr_result.get("coordinate_data") or {}
                rule_input: Dict[str, Any] = {
                    "ocr_provider": "google_documentai",
                    "raw_text_length": len(raw_text),
                    "raw_text_preview": raw_text[:2000] if raw_text else "",
                    "has_coordinate_data": bool(coord),
                    "merchant_name": google_ocr_result.get("merchant_name"),
                }
                rule_output: Dict[str, Any] = initial_parse_result if isinstance(initial_parse_result, dict) else {"success": False, "reason": "no result"}
                rule_run_id = save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="rule_based_cleaning",
                    model_provider=None,
                    model_name=None,
                    model_version=None,
                    input_payload=rule_input,
                    output_payload=rule_output,
                    output_schema_version=None,
                    status="pass" if (initial_parse_result and initial_parse_result.get("success")) else "fail",
                    error_message=None if (initial_parse_result and initial_parse_result.get("success")) else "initial_parse failed or no coordinate data",
                )
                append_workflow_step(
                    db_receipt_id, "rule_clean", "pass" if (initial_parse_result and initial_parse_result.get("success")) else "fail", run_id=rule_run_id
                )
            except Exception as e:
                logger.warning(f"Failed to save rule_based_cleaning run: {e}")
        
        # store_in_chain already set from pre-rule addr_match (match_store)
        if db_receipt_id:
            append_workflow_step(db_receipt_id, "in_chain", "yes" if store_in_chain else "no", details={"store_in_chain": store_in_chain})
        logger.info(f"Store in chain: {store_in_chain} (merchant_name=%r)", corrected_merchant_name or None)
        
        # Step 2: Decide which LLM to use
        gemini_available, gemini_reason = await check_gemini_available()
        
        if gemini_available:
            # Use Gemini
            llm_provider = "gemini"
            request_info = await record_gemini_request()
            logger.info(f"Using Gemini LLM (request {request_info['count_this_minute']} this minute)")
        else:
            # Use GPT-4o-mini
            llm_provider = "openai"
            logger.info(f"Using GPT-4o-mini LLM (Gemini unavailable: {gemini_reason})")
        
        # Update stage to llm_primary
        if db_receipt_id:
            try:
                update_receipt_status(db_receipt_id, current_status="failed", current_stage="llm_primary")
            except Exception as e:
                logger.warning(f"Failed to update receipt stage to llm_primary: {e}")
        
        # Step 3: LLM processing (with initial parse result)
        timeline.start(f"{llm_provider}_llm")
        try:
            if store_in_chain:
                first_llm_result = await process_receipt_with_llm_from_ocr(
                    ocr_result=google_ocr_data,
                    merchant_name=None,
                    ocr_provider="google_documentai",
                    llm_provider=llm_provider,
                    receipt_id=db_receipt_id,
                    initial_parse_result=initial_parse_result,
                    store_in_chain=True,
                )
            else:
                # Not in chain: we have image (OCR came from it). Do LLM 全量 OCR first; only on failure fall back to OCR+image to Gemini for debug.
                first_llm_result = await process_receipt_with_llm_from_ocr(
                    ocr_result=google_ocr_data,
                    merchant_name=None,
                    ocr_provider="google_documentai",
                    llm_provider=llm_provider,
                    receipt_id=db_receipt_id,
                    initial_parse_result=initial_parse_result,
                    store_in_chain=False,
                )
            timeline.end(f"{llm_provider}_llm")
            
            # Merge store-specific fields from initial_parse (e.g. Trader Joe's transaction_info, merchant_phone, purchase_time) into payload before save
            if first_llm_result and initial_parse_result and isinstance(initial_parse_result, dict):
                ti = initial_parse_result.get("transaction_info") or {}
                if ti and not first_llm_result.get("transaction_info"):
                    first_llm_result["transaction_info"] = ti
                rec = first_llm_result.setdefault("receipt", {})
                if initial_parse_result.get("merchant_phone") and not rec.get("merchant_phone"):
                    rec["merchant_phone"] = initial_parse_result["merchant_phone"]
                if ti.get("datetime") and not rec.get("purchase_time"):
                    dt = ti["datetime"]
                    if isinstance(dt, str) and " " in dt:
                        rec["purchase_time"] = dt.split(" ", 1)[1].strip()
                    else:
                        rec["purchase_time"] = dt
            
        except Exception as e:
            timeline.end(f"{llm_provider}_llm")
            logger.error(f"{llm_provider.upper()} LLM failed: {e}")
            
            # Save failed LLM run to database
            if db_receipt_id:
                try:
                    # Get model name from settings
                    if llm_provider.lower() == "gemini":
                        model_name = settings.gemini_model
                    else:
                        model_name = settings.openai_model
                    
                    _input = {"ocr_result": google_ocr_data}
                    _summary = _initial_parse_summary_for_run(initial_parse_result)
                    if _summary is not None:
                        _input["initial_parse_summary"] = _summary
                    save_processing_run(
                        receipt_id=db_receipt_id,
                        stage="llm",
                        model_provider=llm_provider,
                        model_name=model_name,
                        model_version=None,
                        input_payload=_input,
                        output_payload=_fail_output_payload(str(e)),
                        output_schema_version="0.1",
                        status="fail",
                        error_message=str(e)
                    )
                    update_receipt_status(db_receipt_id, current_status="failed", current_stage="ocr")
                    # Save image for manual review (strategy B: failed/needs_review only)
                    image_path = _save_image_for_manual_review(receipt_id, image_bytes, filename)
                    if image_path:
                        try:
                            update_receipt_file_url(db_receipt_id, image_path)
                        except Exception as url_err:
                            logger.warning(f"Failed to update receipt file URL: {url_err}")
                except Exception as db_error:
                    logger.warning(f"Failed to save failed LLM run: {db_error}")
            
            # When first LLM failed and we have image: try once with full OCR + image to Gemini for debug (whether first was Gemini or OpenAI)
            if image_bytes:
                logger.info(
                    "First LLM (%s) failed; trying Gemini vision retry with full OCR + receipt image for debug",
                    llm_provider,
                )
                vision_retry_result = await _try_gemini_vision_retry(
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    error=str(e),
                    receipt_id=receipt_id,
                    timeline=timeline,
                    db_receipt_id=db_receipt_id,
                    user_id=user_id,
                    google_ocr_data=google_ocr_data,
                    filename=filename,
                    initial_parse_result=initial_parse_result,
                )
                if vision_retry_result is not None:
                    return vision_retry_result
                logger.info("Gemini vision retry did not succeed, falling back to other LLM (AWS OCR + OpenAI)")
            
            # Fallback to another LLM (pass image_bytes for manual review if fallback also fails)
            return await _fallback_to_other_llm(
                google_ocr_data, filename, receipt_id, timeline,
                failed_provider=llm_provider, error=str(e), db_receipt_id=db_receipt_id, user_id=user_id,
                image_bytes=image_bytes
            )
        
        if first_llm_result is None:
            logger.error("first_llm_result is None after LLM processing")
            raise ValueError("first_llm_result cannot be None")
        
        # Step 4: Clean data fields (dates, times, etc.)
        timeline.start("data_cleaning")
        first_llm_result = clean_llm_result(first_llm_result)
        timeline.end("data_cleaning")
        
        # Step 4.5: Apply T&T-specific cleaning rules (remove membership lines, extract card number)
        timeline.start("tt_cleaning")
        first_llm_result = apply_chain_cleaner(first_llm_result)
        timeline.end("tt_cleaning")
        
        # Step 4.6: Correct address using fuzzy matching against canonical database
        timeline.start("address_correction")
        first_llm_result = correct_address(first_llm_result, auto_correct=True)
        timeline.end("address_correction")
        
        # Save LLM processing run after address correction so categorize_receipt sees final chain_id/location_id and receipt address
        if db_receipt_id and first_llm_result:
            try:
                if llm_provider.lower() == "gemini":
                    model_name = settings.gemini_model
                else:
                    model_name = settings.openai_model
                rag_metadata = first_llm_result.get("_metadata", {}).get("rag_metadata", {})
                _input = {"ocr_result": google_ocr_data, "rag_metadata": rag_metadata}
                _summary = _initial_parse_summary_for_run(initial_parse_result)
                if _summary is not None:
                    _input["initial_parse_summary"] = _summary
                llm_run_id = save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="llm",
                    model_provider=llm_provider,
                    model_name=model_name,
                    model_version=None,
                    input_payload=_input,
                    output_payload=first_llm_result,
                    output_schema_version="0.1",
                    status="pass",
                    error_message=None
                )
                append_workflow_step(db_receipt_id, "llm_primary", "pass", run_id=llm_run_id)
                logger.info(f"Saved LLM processing run for receipt {db_receipt_id} (after address correction)")
            except Exception as e:
                logger.warning(f"Failed to save LLM processing run: {e}")
        
        # Step 5: Sum check (use OCR raw_text so receipt footer "Item count: N" is available for item-count check)
        if google_ocr_data and isinstance(google_ocr_data.get("raw_text"), str) and (google_ocr_data.get("raw_text") or "").strip():
            first_llm_result = {**first_llm_result, "raw_text": google_ocr_data.get("raw_text", "") or first_llm_result.get("raw_text", "")}
        timeline.start("sum_check")
        sum_check_passed, sum_check_details = check_receipt_sums(first_llm_result)
        timeline.end("sum_check")
        
        # Step 6: Process results
        if sum_check_passed:
            # If LLM explicitly marked needs_review (e.g. missing items, conflicts), do not mark success
            llm_validation = (first_llm_result.get("_metadata") or {}).get("validation_status")
            force_needs_review = (llm_validation == "needs_review")
            if force_needs_review:
                logger.info(f"Sum check passed but LLM validation_status=needs_review, treating as needs_review for receipt {db_receipt_id}")
            # Sum check passed
            field_conflicts = first_llm_result.get("tbd", {}).get("field_conflicts", {})
            
            if not field_conflicts and not force_needs_review:
                # Fully passed, return directly
                timeline.start("save_output")
                await _save_output(receipt_id, first_llm_result, timeline, google_ocr_data, user_id=user_id)
                timeline.end("save_output")
                
                # Update receipt status
                if db_receipt_id:
                    try:
                        update_receipt_status(db_receipt_id, current_status="success", current_stage="llm_primary")
                    except Exception as e:
                        logger.warning(f"Failed to update receipt status: {e}")
                    # Categorize: save to record_summaries/record_items, enqueue unmatched to classification_review
                    try:
                        cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
                        if cat_result.get("success"):
                            logger.info(f"✅ Categorization completed for receipt {db_receipt_id}")
                        else:
                            logger.warning(f"Categorization skipped for {db_receipt_id}: {cat_result.get('message')}")
                    except Exception as cat_err:
                        logger.warning(f"Categorization failed for {db_receipt_id}: {cat_err}")
                
                # Record API call for statistics
                llm_duration = _get_duration_from_timeline(timeline, f"{llm_provider}_llm")
                record_api_call(
                    call_type="llm",
                    provider=llm_provider,
                    receipt_id=db_receipt_id,
                    duration_ms=int(llm_duration) if llm_duration else None,
                    status="success"
                )
                
                return {
                    "success": True,
                    "receipt_id": receipt_id,
                    "status": "passed",
                    "data": first_llm_result,
                    "sum_check": sum_check_details,
                    "llm_provider": llm_provider
                }
            elif force_needs_review:
                # Sum check passed but LLM marked needs_review: save and categorize for manual edit, do not mark success
                data_to_save = apply_field_conflicts_resolution(first_llm_result) if field_conflicts else first_llm_result
                timeline.start("save_output")
                await _save_output(receipt_id, data_to_save, timeline, google_ocr_data, user_id=user_id)
                timeline.end("save_output")
                if db_receipt_id:
                    try:
                        update_receipt_status(db_receipt_id, current_status="needs_review", current_stage="manual")
                    except Exception as e:
                        logger.warning(f"Failed to update receipt status: {e}")
                    try:
                        cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
                        if cat_result.get("success"):
                            logger.info(f"Saved parsed data for needs_review receipt {db_receipt_id}")
                        else:
                            logger.warning(f"Categorization skipped for {db_receipt_id}: {cat_result.get('message')}")
                    except Exception as cat_err:
                        logger.warning(f"Categorization failed for {db_receipt_id}: {cat_err}")
                llm_duration = _get_duration_from_timeline(timeline, f"{llm_provider}_llm")
                record_api_call(
                    call_type="llm",
                    provider=llm_provider,
                    receipt_id=db_receipt_id,
                    duration_ms=int(llm_duration) if llm_duration else None,
                    status="success"
                )
                return {
                    "success": False,
                    "receipt_id": receipt_id,
                    "status": "needs_review",
                    "data": data_to_save,
                    "sum_check": sum_check_details,
                    "llm_provider": llm_provider,
                    "reason": "LLM validation_status=needs_review",
                }
            else:
                # Sum check passed but has field_conflicts (no force_needs_review), apply resolution and success
                resolved_result = apply_field_conflicts_resolution(first_llm_result)
                timeline.start("save_output")
                await _save_output(receipt_id, resolved_result, timeline, google_ocr_data, user_id=user_id)
                timeline.end("save_output")
                
                # Update receipt status
                if db_receipt_id:
                    try:
                        update_receipt_status(db_receipt_id, current_status="success", current_stage="llm_primary")
                    except Exception as e:
                        logger.warning(f"Failed to update receipt status: {e}")
                    # Categorize: save to record_summaries/record_items, enqueue unmatched to classification_review
                    try:
                        cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
                        if cat_result.get("success"):
                            logger.info(f"✅ Categorization completed for receipt {db_receipt_id}")
                        else:
                            logger.warning(f"Categorization skipped for {db_receipt_id}: {cat_result.get('message')}")
                    except Exception as cat_err:
                        logger.warning(f"Categorization failed for {db_receipt_id}: {cat_err}")
                
                # Record API call for statistics
                llm_duration = _get_duration_from_timeline(timeline, f"{llm_provider}_llm")
                record_api_call(
                    call_type="llm",
                    provider=llm_provider,
                    receipt_id=db_receipt_id,
                    duration_ms=int(llm_duration) if llm_duration else None,
                    status="success"
                )
                
                return {
                    "success": True,
                    "receipt_id": receipt_id,
                    "status": "passed_with_resolution",
                    "data": resolved_result,
                    "sum_check": sum_check_details,
                    "llm_provider": llm_provider,
                    "resolved_conflicts": resolved_result.get("tbd", {}).get("resolved_conflicts", [])
                }
        else:
            # Sum check failed, introduce AWS OCR + GPT-4o-mini secondary processing
            logger.warning(f"Sum check failed for {receipt_id}, triggering backup check")
            
            # Update stage and save image for manual review (strategy B: needs_review)
            if db_receipt_id:
                try:
                    update_receipt_status(db_receipt_id, current_status="needs_review", current_stage="manual")
                    image_path = _save_image_for_manual_review(receipt_id, image_bytes, filename)
                    if image_path:
                        try:
                            update_receipt_file_url(db_receipt_id, image_path)
                        except Exception as url_err:
                            logger.warning(f"Failed to update receipt file URL: {url_err}")
                    # Persist LLM result to record_summaries/record_items so frontend can show editable fields
                    try:
                        cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
                        if cat_result.get("success"):
                            logger.info(f"Saved parsed data for manual review receipt {db_receipt_id}")
                        else:
                            logger.warning(f"Categorization for needs_review skipped: {cat_result.get('message')}")
                    except Exception as cat_err:
                        logger.warning(f"Categorization for needs_review failed for {db_receipt_id}: {cat_err}")
                except Exception as e:
                    logger.warning(f"Failed to update receipt stage to sum_check_failed: {e}")
            
            return await _llm_debug_cascade(
                image_bytes=image_bytes,
                mime_type=mime_type,
                filename=filename,
                receipt_id=receipt_id,
                timeline=timeline,
                google_ocr_data=google_ocr_data,
                first_llm_result=first_llm_result,
                sum_check_details=sum_check_details,
                first_llm_provider=llm_provider,
                user_id=user_id,
                db_receipt_id=db_receipt_id,
            )
    
    except Exception as e:
        logger.error(f"Workflow failed for {receipt_id}: {e}", exc_info=True)
        timeline.start("save_error")
        await _save_error(receipt_id, timeline, error=str(e), filename=filename)
        timeline.end("save_error")
        
        # Save image for failed-receipts / manual review so admin can see the receipt
        if db_receipt_id and image_bytes and filename:
            try:
                image_path = _save_image_for_manual_review(receipt_id, image_bytes, filename)
                if image_path:
                    update_receipt_file_url(db_receipt_id, image_path)
                    logger.info(f"Saved image for failed receipt {db_receipt_id}: {image_path}")
            except Exception as img_err:
                logger.warning(f"Failed to save image for failed receipt: {img_err}")
        
        # Record API call (error)
        record_api_call(
            call_type="llm",
            provider="openai",
            receipt_id=db_receipt_id,
            duration_ms=None,
            status="failed",
            error_message=str(e)
        )
        
        return {
            "success": False,
            "receipt_id": receipt_id,
            "status": "error",
            "error": str(e)
        }


async def _llm_debug_cascade(
    image_bytes: bytes,
    mime_type: str,
    filename: str,
    receipt_id: str,
    timeline: TimelineRecorder,
    google_ocr_data: Dict[str, Any],
    first_llm_result: Dict[str, Any],
    sum_check_details: Dict[str, Any],
    first_llm_provider: str,
    user_id: str,
    db_receipt_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Sum check failed: try (1) LLM debug with raw OCR, (2) LLM debug with image + reason, (3) Textract + OpenAI.
    Uses prompt_library receipt_parse_debug_ocr and receipt_parse_debug_vision when available.
    """
    prompt_config = get_default_prompt()
    output_schema = prompt_config.get("output_schema") or {}
    output_schema_json = json.dumps(output_schema, indent=2, ensure_ascii=False)
    raw_text = (google_ocr_data or {}).get("raw_text") or ""

    # Step 1: Debug with raw OCR only
    debug_ocr_system = get_debug_prompt_system("receipt_parse_debug_ocr") or (
        "The previous answer had sum/total issues. Compare the OCR and summarized JSON below. "
        "Correct and output full receipt JSON, or set top-level 'reason' and escalate."
    )
    debug_ocr_user = (
        "## Previous LLM output\n" + json.dumps(first_llm_result, indent=2, ensure_ascii=False)[:8000]
        + "\n\n## Sum check details\n" + json.dumps(sum_check_details, ensure_ascii=False)
        + "\n\n## OCR raw text\n" + (raw_text[:6000] + "..." if len(raw_text) > 6000 else raw_text)
    )
    timeline.start("llm_debug_ocr")
    debug_ocr_result = None
    try:
        if first_llm_provider.lower() == "gemini":
            debug_ocr_result = await parse_receipt_with_gemini(
                system_message=debug_ocr_system,
                user_message=debug_ocr_user,
                model=settings.gemini_model,
                temperature=0,
            )
        else:
            debug_ocr_result = parse_receipt_with_llm(
                system_message=debug_ocr_system,
                user_message=debug_ocr_user,
                model=settings.openai_model,
                temperature=0,
            )
    except Exception as e:
        logger.warning(f"LLM debug (OCR) failed: {e}")
        if db_receipt_id:
            try:
                save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="llm",
                    model_provider=first_llm_provider,
                    model_name=settings.gemini_model if first_llm_provider.lower() == "gemini" else settings.openai_model,
                    model_version=None,
                    input_payload={"debug_ocr": True, "sum_check_details": sum_check_details},
                    output_payload=_fail_output_payload(str(e)),
                    output_schema_version="0.1",
                    status="fail",
                    error_message=str(e),
                )
            except Exception as se:
                logger.warning(f"Failed to save debug OCR run: {se}")
    timeline.end("llm_debug_ocr")

    if debug_ocr_result and isinstance(debug_ocr_result, dict):
        debug_ocr_result = clean_llm_result(debug_ocr_result)
        debug_ocr_result = apply_chain_cleaner(debug_ocr_result)
        debug_ocr_result = correct_address(debug_ocr_result, auto_correct=True)
        sum_check_passed_debug, _ = check_receipt_sums(debug_ocr_result)
        if sum_check_passed_debug and db_receipt_id:
            try:
                save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="llm",
                    model_provider=first_llm_provider,
                    model_name=settings.gemini_model if first_llm_provider.lower() == "gemini" else settings.openai_model,
                    model_version=None,
                    input_payload={"debug_ocr": True, "sum_check_details": sum_check_details},
                    output_payload=debug_ocr_result,
                    output_schema_version="0.1",
                    status="pass",
                    error_message=None,
                )
                update_receipt_status(db_receipt_id, current_status="success", current_stage="llm_primary")
            except Exception as e:
                logger.warning(f"Failed to save debug OCR success run: {e}")
            await _save_output(receipt_id, debug_ocr_result, timeline, google_ocr_data, user_id=user_id)
            try:
                cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
                if cat_result.get("success"):
                    logger.info(f"✅ Categorization completed after debug OCR for {db_receipt_id}")
            except Exception as ce:
                logger.warning(f"Categorization failed after debug OCR: {ce}")
            return {"success": True, "receipt_id": receipt_id, "status": "passed_after_debug_ocr", "data": debug_ocr_result}

    # Step 2: Debug with image (same conversation), output reason if escalating
    debug_vision_system = get_debug_prompt_system("receipt_parse_debug_vision") or (
        "You are now given the receipt image. Use it with the previous OCR and JSON to produce correct receipt JSON. Set top-level 'reason' if not confident."
    )
    vision_context = (
        debug_vision_system
        + "\n\n## Previous debug (OCR) output\n"
        + json.dumps(debug_ocr_result or first_llm_result, indent=2, ensure_ascii=False)[:6000]
        + "\n\n## Sum check details\n"
        + json.dumps(sum_check_details, ensure_ascii=False)
        + "\n\nBelow is the receipt image."
    )
    timeline.start("llm_debug_vision")
    debug_vision_result = None
    try:
        debug_vision_result = await parse_receipt_with_gemini_vision(
            image_bytes=image_bytes,
            failure_context=vision_context,
            output_schema_json=output_schema_json,
            mime_type=mime_type,
        )
    except Exception as e:
        logger.warning(f"LLM debug (vision) failed: {e}")
        if db_receipt_id:
            try:
                save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="llm",
                    model_provider="gemini",
                    model_name=settings.gemini_model,
                    model_version=None,
                    input_payload={"debug_vision": True, "image_bytes_length": len(image_bytes)},
                    output_payload=_fail_output_payload(str(e)),
                    output_schema_version="0.1",
                    status="fail",
                    error_message=str(e),
                )
            except Exception as se:
                logger.warning(f"Failed to save debug vision run: {se}")
    timeline.end("llm_debug_vision")

    if debug_vision_result and isinstance(debug_vision_result, dict):
        debug_vision_result = clean_llm_result(debug_vision_result)
        debug_vision_result = apply_chain_cleaner(debug_vision_result)
        debug_vision_result = correct_address(debug_vision_result, auto_correct=True)
        sum_check_passed_v, _ = check_receipt_sums(debug_vision_result)
        if sum_check_passed_v and db_receipt_id:
            try:
                save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="llm",
                    model_provider="gemini",
                    model_name=settings.gemini_model,
                    model_version=None,
                    input_payload={"debug_vision": True, "image_bytes_length": len(image_bytes)},
                    output_payload=debug_vision_result,
                    output_schema_version="0.1",
                    status="pass",
                    error_message=None,
                )
                update_receipt_status(db_receipt_id, current_status="success", current_stage="llm_primary")
            except Exception as e:
                logger.warning(f"Failed to save debug vision success run: {e}")
            await _save_output(receipt_id, debug_vision_result, timeline, google_ocr_data, user_id=user_id)
            try:
                cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
                if cat_result.get("success"):
                    logger.info(f"✅ Categorization completed after debug vision for {db_receipt_id}")
            except Exception as ce:
                logger.warning(f"Categorization failed after debug vision: {ce}")
            return {"success": True, "receipt_id": receipt_id, "status": "passed_after_vision_retry", "data": debug_vision_result}

    # Step 3: Escalation to strongest models (image → GPT-5.1 & Gemini 3) or fallback to Textract + OpenAI
    if getattr(settings, "openai_escalation_model", None) and getattr(settings, "gemini_escalation_model", None):
        escalation_result = await _escalation_to_strongest_models(
            image_bytes=image_bytes,
            filename=filename,
            receipt_id=receipt_id,
            timeline=timeline,
            user_id=user_id,
            db_receipt_id=db_receipt_id,
            google_ocr_data=google_ocr_data,
        )
        if escalation_result is not None:
            return escalation_result
        # Escalation failed or disagreed → fall through to Textract
    return await _backup_check_with_aws_ocr(
        image_bytes, filename, receipt_id, timeline,
        google_ocr_data, first_llm_result, sum_check_details, first_llm_provider,
        user_id=user_id,
        db_receipt_id=db_receipt_id,
    )


async def _escalation_to_strongest_models(
    image_bytes: bytes,
    filename: str,
    receipt_id: str,
    timeline: TimelineRecorder,
    user_id: str,
    db_receipt_id: Optional[str] = None,
    google_ocr_data: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    When cascade fails: send image to OpenAI escalation model + Gemini escalation model,
    get two structured JSONs, run sum check on both. If both pass and agree (same item count,
    same sum check result), return success with one payload; else escalate (needs_review) and return.
    Returns None to fall back to Textract when escalation is not configured or both calls fail.
    """
    openai_model = getattr(settings, "openai_escalation_model", None) or ""
    gemini_model = getattr(settings, "gemini_escalation_model", None) or ""
    if not openai_model or not gemini_model:
        return None
    timeline.start("escalation_vision")
    try:
        gemini_task = asyncio.create_task(
            parse_receipt_with_gemini_vision_escalation(
                image_bytes, ESCALATION_VISION_PROMPT, gemini_model, "image/jpeg"
            )
        )
        openai_task = asyncio.create_task(
            asyncio.to_thread(
                parse_receipt_with_openai_vision,
                image_bytes,
                ESCALATION_VISION_PROMPT,
                openai_model,
                "image/jpeg",
            )
        )
        gemini_raw, openai_result = await asyncio.gather(gemini_task, openai_task)
        gemini_result = gemini_raw[0] if isinstance(gemini_raw, tuple) else gemini_raw
    except Exception as e:
        timeline.end("escalation_vision")
        logger.warning(f"Escalation vision (one or both models) failed: {e}, falling back to Textract")
        return None
    timeline.end("escalation_vision")
    for name, raw in [("gemini", gemini_result), ("openai", openai_result)]:
        if not raw or not isinstance(raw, dict):
            logger.warning(f"Escalation {name} returned invalid result, escalating")
            return await _escalation_mark_needs_review(
                receipt_id, timeline, db_receipt_id, user_id,
                image_bytes, filename, gemini_result, openai_result,
                reason="one or both escalation models returned invalid JSON",
            )
    gemini_clean = clean_llm_result(gemini_result)
    openai_clean = clean_llm_result(openai_result)
    gemini_clean = apply_chain_cleaner(gemini_clean)
    openai_clean = apply_chain_cleaner(openai_clean)
    gemini_clean = correct_address(gemini_clean, auto_correct=True)
    openai_clean = correct_address(openai_clean, auto_correct=True)
    gemini_pass, gemini_sum = check_receipt_sums(gemini_clean)
    openai_pass, openai_sum = check_receipt_sums(openai_clean)
    items_g = (gemini_clean.get("items") or [])
    items_o = (openai_clean.get("items") or [])
    count_g = len([i for i in items_g if (i.get("product_name") or i.get("line_total"))])
    count_o = len([i for i in items_o if (i.get("product_name") or i.get("line_total"))])
    if not gemini_pass or not openai_pass:
        logger.info("Escalation: sum check failed for one or both models, escalating")
        return await _escalation_mark_needs_review(
            receipt_id, timeline, db_receipt_id, user_id,
            image_bytes, filename, gemini_clean, openai_clean,
            reason="sum check failed for one or both escalation models",
        )
    if count_g != count_o:
        logger.info(f"Escalation: item count mismatch gemini={count_g} openai={count_o}, escalating")
        return await _escalation_mark_needs_review(
            receipt_id, timeline, db_receipt_id, user_id,
            image_bytes, filename, gemini_clean, openai_clean,
            reason=f"item count mismatch: gemini={count_g}, openai={count_o}",
        )
    rec_g = gemini_clean.get("receipt", {})
    rec_o = openai_clean.get("receipt", {})
    total_g = rec_g.get("total")
    total_o = rec_o.get("total")
    if total_g is not None and total_o is not None:
        try:
            tolerance = _effective_tolerance(None, total_g, 0.0)
            if abs(float(total_g) - float(total_o)) > tolerance:
                logger.info("Escalation: total mismatch between models, escalating")
                return await _escalation_mark_needs_review(
                    receipt_id, timeline, db_receipt_id, user_id,
                    image_bytes, filename, gemini_clean, openai_clean,
                    reason="total amount mismatch between escalation models",
                )
        except (TypeError, ValueError):
            pass
    # Consensus: both pass sum check, same item count, totals agree → success with one payload (use Gemini)
    # Input payload includes full prompt so DB has exact input for future debug
    _escalation_input = {
        "escalation_vision": True,
        "image_bytes_length": len(image_bytes),
        "mime_type": "image/jpeg",
        "escalation_prompt": ESCALATION_VISION_PROMPT,
    }
    if db_receipt_id:
        try:
            save_processing_run(
                receipt_id=db_receipt_id,
                stage="llm",
                model_provider="openai",
                model_name=openai_model,
                model_version=None,
                input_payload=_escalation_input,
                output_payload=openai_clean,
                output_schema_version="0.1",
                status="pass",
                error_message=None,
            )
            save_processing_run(
                receipt_id=db_receipt_id,
                stage="llm",
                model_provider="gemini",
                model_name=gemini_model,
                model_version=None,
                input_payload=_escalation_input,
                output_payload=gemini_clean,
                output_schema_version="0.1",
                status="pass",
                error_message=None,
            )
            update_receipt_status(db_receipt_id, current_status="success", current_stage="llm_fallback")
        except Exception as e:
            logger.warning(f"Failed to save escalation runs or update status: {e}")
    await _save_output(receipt_id, gemini_clean, timeline, google_ocr_data or {}, user_id=user_id)
    if db_receipt_id:
        try:
            cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
            if cat_result.get("success"):
                logger.info(f"✅ Categorization completed after escalation for {db_receipt_id}")
        except Exception as ce:
            logger.warning(f"Categorization after escalation failed: {ce}")
    return {
        "success": True,
        "receipt_id": receipt_id,
        "status": "passed_escalation_consensus",
        "data": gemini_clean,
        "escalation_used": True,
    }


async def _escalation_mark_needs_review(
    receipt_id: str,
    timeline: TimelineRecorder,
    db_receipt_id: Optional[str],
    user_id: str,
    image_bytes: bytes,
    filename: str,
    gemini_payload: Dict[str, Any],
    openai_payload: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    """Save both escalation payloads and mark receipt needs_review."""
    if db_receipt_id:
        try:
            update_receipt_status(db_receipt_id, current_status="needs_review", current_stage="manual")
            image_path = _save_image_for_manual_review(receipt_id, image_bytes, filename)
            if image_path:
                update_receipt_file_url(db_receipt_id, image_path)
        except Exception as e:
            logger.warning(f"Failed to update receipt for escalation needs_review: {e}")
        _escalation_input_review = {
            "escalation_vision": True,
            "image_bytes_length": len(image_bytes),
            "mime_type": "image/jpeg",
            "escalation_prompt": ESCALATION_VISION_PROMPT,
            "escalate_reason": reason,
        }
        try:
            save_processing_run(
                receipt_id=db_receipt_id,
                stage="llm",
                model_provider="openai",
                model_name=getattr(settings, "openai_escalation_model", "openai_escalation"),
                model_version=None,
                input_payload=_escalation_input_review,
                output_payload=openai_payload,
                output_schema_version="0.1",
                status="pass",
                error_message=None,
            )
            save_processing_run(
                receipt_id=db_receipt_id,
                stage="llm",
                model_provider="gemini",
                model_name=getattr(settings, "gemini_escalation_model", "gemini_escalation"),
                model_version=None,
                input_payload=_escalation_input_review,
                output_payload=gemini_payload,
                output_schema_version="0.1",
                status="pass",
                error_message=None,
            )
        except Exception as e:
            logger.warning(f"Failed to save escalation runs: {e}")
        try:
            cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
            if cat_result.get("success"):
                logger.info(f"Saved escalation payloads for needs_review receipt {db_receipt_id}")
        except Exception as ce:
            logger.warning(f"Categorization for escalation needs_review failed: {ce}")
    return {
        "success": False,
        "receipt_id": receipt_id,
        "status": "needs_review",
        "data": gemini_payload,
        "reason": reason,
        "escalation_openai_payload": openai_payload,
        "escalation_gemini_payload": gemini_payload,
    }


async def _backup_check_with_aws_ocr(
    image_bytes: bytes,
    filename: str,
    receipt_id: str,
    timeline: TimelineRecorder,
    google_ocr_data: Dict[str, Any],
    first_llm_result: Dict[str, Any],
    sum_check_details: Dict[str, Any],
    first_llm_provider: str,
    user_id: str,
    db_receipt_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Use AWS OCR + GPT-4o-mini for secondary processing."""
    # Update stage to llm_fallback
    if db_receipt_id:
        try:
            update_receipt_status(db_receipt_id, current_status="needs_review", current_stage="llm_fallback")
        except Exception as e:
            logger.warning(f"Failed to update receipt stage to llm_fallback: {e}")
    
    # Step 1: AWS OCR
    timeline.start("aws_ocr")
    try:
        aws_ocr_result = parse_receipt_textract(image_bytes)
        timeline.end("aws_ocr")
        
        # Save AWS OCR processing run to database
        if db_receipt_id:
            try:
                save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="ocr",
                    model_provider="aws_textract",
                    model_name=None,  # OCR doesn't have model_name
                    model_version=None,
                    input_payload={"image_bytes_length": len(image_bytes)},
                    output_payload=aws_ocr_result,
                    output_schema_version=None,  # OCR doesn't have schema version
                    status="pass",
                    error_message=None
                )
                
                # Record API call for statistics
                aws_ocr_duration = _get_duration_from_timeline(timeline, "aws_ocr")
                record_api_call(
                    call_type="ocr",
                    provider="aws_textract",
                    receipt_id=db_receipt_id,
                    duration_ms=int(aws_ocr_duration) if aws_ocr_duration else None,
                    status="success"
                )
            except Exception as e:
                logger.warning(f"Failed to save AWS OCR processing run: {e}")
    except Exception as e:
        timeline.end("aws_ocr")
        logger.error(f"AWS OCR failed: {e}")
        # AWS OCR also failed, mark for manual review
        return await _mark_for_manual_review(
            receipt_id=receipt_id,
            timeline=timeline,
            google_ocr_data=google_ocr_data,
            first_llm_result=first_llm_result,
            sum_check_details=sum_check_details,
            error=f"AWS OCR failed: {e}",
            image_bytes=image_bytes,
            filename=filename,
            db_receipt_id=db_receipt_id
        )
    
    # Step 2: GPT-4o-mini secondary processing
    timeline.start("gpt_backup_llm")
    try:
        backup_llm_result = await _gpt_backup_processing(
            google_ocr_data, aws_ocr_result, first_llm_result, sum_check_details
        )
        timeline.end("gpt_backup_llm")
        
        # Save GPT backup LLM processing run to database (regardless of sum check result)
        if db_receipt_id:
            try:
                save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="llm",
                    model_provider="openai",
                    model_name=settings.openai_model,
                    model_version=None,  # Model version not available from API
                    input_payload={
                        "google_ocr": google_ocr_data,
                        "aws_ocr": aws_ocr_result,
                        "first_llm_result": first_llm_result,
                        "sum_check_details": sum_check_details
                    },
                    output_payload=backup_llm_result,
                    output_schema_version="0.1",  # Current schema version
                    status="pass",  # LLM processing succeeded, sum check will be done separately
                    error_message=None
                )
                logger.info(f"Saved GPT backup LLM processing run for receipt {db_receipt_id}")
            except Exception as db_error:
                logger.warning(f"Failed to save GPT backup LLM processing run: {db_error}")
    except Exception as e:
        timeline.end("gpt_backup_llm")
        logger.error(f"GPT backup processing failed: {e}")
        
        # Save failed GPT backup LLM processing run to database
        if db_receipt_id:
            try:
                save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="llm",
                    model_provider="openai",
                    model_name=settings.openai_model,
                    model_version=None,
                    input_payload={
                        "google_ocr": google_ocr_data,
                        "aws_ocr": aws_ocr_result,
                        "first_llm_result": first_llm_result,
                        "sum_check_details": sum_check_details
                    },
                    output_payload=_fail_output_payload(str(e)),
                    output_schema_version=None,
                    status="fail",
                    error_message=str(e)
                )
            except Exception as db_error:
                logger.warning(f"Failed to save failed GPT backup LLM run: {db_error}")
        
        return await _mark_for_manual_review(
            receipt_id=receipt_id,
            timeline=timeline,
            google_ocr_data=google_ocr_data,
            aws_ocr_data=aws_ocr_result,
            first_llm_result=first_llm_result,
            sum_check_details=sum_check_details,
            error=f"GPT backup failed: {e}",
            image_bytes=image_bytes,
            filename=filename,
            db_receipt_id=db_receipt_id
        )
    
    # Step 3: Clean data fields
    if backup_llm_result is None:
        logger.error("backup_llm_result is None, cannot proceed with cleaning")
        raise ValueError("backup_llm_result cannot be None")
    
    timeline.start("data_cleaning_backup")
    backup_llm_result = clean_llm_result(backup_llm_result)
    timeline.end("data_cleaning_backup")
    
    # Step 3.5: Apply T&T cleaning on backup result
    timeline.start("tt_cleaning_backup")
    backup_llm_result = apply_chain_cleaner(backup_llm_result)
    timeline.end("tt_cleaning_backup")
    
    # Step 3.6: Correct address
    timeline.start("address_correction_backup")
    backup_llm_result = correct_address(backup_llm_result, auto_correct=True)
    timeline.end("address_correction_backup")
    
    # Step 4: Sum check again
    timeline.start("backup_sum_check")
    backup_sum_check_passed, backup_sum_check_details = check_receipt_sums(backup_llm_result)
    timeline.end("backup_sum_check")
    
    if backup_sum_check_passed:
        # Backup check passed
        timeline.start("save_output")
        await _save_output(receipt_id, backup_llm_result, timeline, google_ocr_data, user_id=user_id)
        timeline.end("save_output")
        
        # Update receipt status
        if db_receipt_id:
            try:
                update_receipt_status(db_receipt_id, current_status="success", current_stage="llm_fallback")
            except Exception as e:
                logger.warning(f"Failed to update receipt status: {e}")
            # Categorize: save to record_summaries/record_items, enqueue unmatched to classification_review
            try:
                cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
                if cat_result.get("success"):
                    logger.info(f"✅ Categorization completed for receipt {db_receipt_id}")
                else:
                    logger.warning(f"Categorization skipped for {db_receipt_id}: {cat_result.get('message')}")
            except Exception as cat_err:
                logger.warning(f"Categorization failed for {db_receipt_id}: {cat_err}")
        
        # Save debug files
        await _save_debug_files(
            receipt_id, google_ocr_data, aws_ocr_result,
            first_llm_result, backup_llm_result, image_bytes, filename
        )
        
        # Record API calls for statistics
        # AWS OCR
        aws_ocr_duration = _get_duration_from_timeline(timeline, "aws_ocr")
        record_api_call(
            call_type="ocr",
            provider="aws_textract",
            receipt_id=db_receipt_id,
            duration_ms=int(aws_ocr_duration) if aws_ocr_duration else None,
            status="success"
        )
        
        # GPT-4o-mini LLM
        llm_duration = _get_duration_from_timeline(timeline, "gpt_backup_llm")
        record_api_call(
            call_type="llm",
            provider="openai",
            receipt_id=db_receipt_id,
            duration_ms=int(llm_duration) if llm_duration else None,
            status="success"
        )
        
        return {
            "success": True,
            "receipt_id": receipt_id,
            "status": "passed_after_backup",
            "data": backup_llm_result,
            "sum_check": backup_sum_check_details,
            "llm_provider": "gpt-4o-mini",
            "backup_used": True
        }
    else:
        # Backup check also failed, mark for manual review
        # Note: The GPT backup LLM processing run was already saved with status="pass" above
        # We don't update it here because the LLM processing itself succeeded, only the sum check failed
        # The sum check failure is recorded in the error_message and manual review status
        
        # Record API call (GPT-4o-mini sum check failed, needs manual review)
        llm_duration = _get_duration_from_timeline(timeline, "gpt_backup_llm")
        record_api_call(
            call_type="llm",
            provider="openai",
            receipt_id=db_receipt_id,
            duration_ms=int(llm_duration) if llm_duration else None,
            status="failed",
            error_message="Sum check failed, needs manual review"
        )
        
        return await _mark_for_manual_review(
            receipt_id=receipt_id,
            timeline=timeline,
            google_ocr_data=google_ocr_data,
            aws_ocr_data=aws_ocr_result,
            first_llm_result=first_llm_result,
            backup_llm_result=backup_llm_result,
            sum_check_details=sum_check_details,
            backup_sum_check_details=backup_sum_check_details,
            error="Backup sum check also failed",
            image_bytes=image_bytes,
            filename=filename,
            db_receipt_id=db_receipt_id
        )


async def _gpt_backup_processing(
    google_ocr_data: Dict[str, Any],
    aws_ocr_data: Dict[str, Any],
    first_llm_result: Dict[str, Any],
    sum_check_details: Dict[str, Any]
) -> Dict[str, Any]:
    """Use GPT-4o-mini for secondary processing to fix sum check errors."""
    # Build prompt
    prompt = _build_backup_prompt(google_ocr_data, aws_ocr_data, first_llm_result, sum_check_details)
    
    # Get default prompt configuration
    prompt_config = get_default_prompt()
    system_message = prompt_config.get("system_message", "")
    
    # Call GPT-4o-mini (synchronous call, since already in async function)
    # Note: Use run_in_executor here to avoid blocking the event loop
    import asyncio
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: parse_receipt_with_llm(
            system_message=system_message,
            user_message=prompt,
            model=settings.openai_model,
            temperature=0.0
        )
    )
    
    return result


def _build_backup_prompt(
    google_ocr_data: Dict[str, Any],
    aws_ocr_data: Dict[str, Any],
    first_llm_result: Dict[str, Any],
    sum_check_details: Dict[str, Any]
) -> str:
    """Build prompt for GPT-4o-mini secondary processing."""
    google_raw_text = google_ocr_data.get("raw_text", "")
    aws_raw_text = aws_ocr_data.get("raw_text", "")
    first_llm_json = json.dumps(first_llm_result, indent=2, ensure_ascii=False)
    sum_check_json = json.dumps(sum_check_details, indent=2, ensure_ascii=False)
    
    prompt = f"""You are a receipt parsing expert. A previous attempt to parse a receipt failed the sum check.

## Google OCR Raw Text:
{google_raw_text[:2000]}  # Limit length

## AWS OCR Raw Text (Second Opinion):
{aws_raw_text[:2000]}  # Limit length

## Previous LLM Result (Failed Sum Check):
{first_llm_json}

## Sum Check Failure Details:
{sum_check_json}

## Your Task:
1. Analyze both OCR raw texts and the previous LLM result
2. Identify where the errors might be (missing items, incorrect prices, wrong calculations)
3. Important rules for subtotal and tax:
   - Only extract subtotal if explicitly shown on receipt
   - Only extract tax if explicitly shown on receipt (look for "TAX", "GST", "PST", "HST", etc.)
   - DO NOT calculate tax by subtracting subtotal from total
   - Deposits, fees, and other charges are NOT tax
   - If subtotal is not shown, set to null
   - If tax is not shown, set to null
4. Correct the errors to make the sum check pass:
   - sum(all line_totals including deposits/fees) ≈ total (tolerance: ±0.03)
   - If subtotal exists: sum(product line_totals) ≈ subtotal (may exclude deposits/fees)
   - If both subtotal and tax exist: subtotal + tax + deposits/fees ≈ total (tolerance: ±0.03)
5. Output the corrected JSON following the same schema
6. In the "tbd" field, provide detailed explanation:
   - What errors you found
   - What you corrected
   - Why you made those corrections
   - Any remaining uncertainties

## Important:
- If you cannot fix the errors, set a flag in tbd indicating manual review is needed
- Be precise with numbers - ensure all calculations match
- Preserve all correct information from the previous result
- Never guess or calculate tax - only extract if explicitly stated

Output the corrected JSON now:"""
    
    return prompt


async def _run_ocr_fail_vision_then_textract(
    image_bytes: bytes,
    filename: str,
    receipt_id: str,
    timeline: TimelineRecorder,
    mime_type: str,
    db_receipt_id: Optional[str],
    user_id: Optional[str],
    error: str,
) -> Dict[str, Any]:
    """OCR failed but image is receipt-like: try Gemini Vision (image only), then Textract+OpenAI if needed."""
    prompt_config = get_default_prompt()
    output_schema = prompt_config.get("output_schema") or {}
    output_schema_json = json.dumps(output_schema, indent=2, ensure_ascii=False)
    timeline.start("gemini_vision_first")
    try:
        vision_result = await parse_receipt_with_gemini_vision(
            image_bytes=image_bytes,
            failure_context="OCR failed. Please extract receipt data from the image only.",
            output_schema_json=output_schema_json,
            mime_type=mime_type,
        )
        timeline.end("gemini_vision_first")
        if not vision_result or not isinstance(vision_result, dict):
            raise ValueError("Gemini vision returned empty or invalid")
        rec = vision_result.get("receipt", {})
        merchant_name_v = (rec.get("merchant_name") or "").strip()
        address_v = (rec.get("merchant_address") or "").strip()
        store_match = get_store_chain(merchant_name_v, address_v or None)
        vision_result.setdefault("_metadata", {})
        vision_result["_metadata"].update({
            "merchant_name": merchant_name_v or None,
            "chain_id": store_match.get("chain_id"),
            "location_id": store_match.get("location_id"),
            "ocr_provider": None,
            "llm_provider": "gemini",
            "validation_status": vision_result.get("_metadata", {}).get("validation_status", "unknown"),
            "rag_metadata": {"vision_image_only": True},
        })
        vision_result = clean_llm_result(vision_result)
        vision_result = apply_chain_cleaner(vision_result)
        vision_result = correct_address(vision_result, auto_correct=True)
        sum_ok, sum_details = check_receipt_sums(vision_result)
        if sum_ok and db_receipt_id:
            run_id = save_processing_run(
                receipt_id=db_receipt_id,
                stage="llm",
                model_provider="gemini",
                model_name=settings.gemini_model,
                model_version=None,
                input_payload={"vision_image_only": True, "ocr_fail": True},
                output_payload=vision_result,
                output_schema_version="0.1",
                status="pass",
                error_message=None,
            )
            append_workflow_step(db_receipt_id, "llm_vision_first", "pass", run_id=run_id)
            update_receipt_status(db_receipt_id, current_status="success", current_stage="llm_fallback")
            await _save_output(receipt_id, vision_result, timeline, {}, user_id=user_id)
            try:
                await asyncio.to_thread(categorize_receipt, db_receipt_id)
            except Exception as ce:
                logger.warning(f"Categorization after vision-first failed: {ce}")
            return {
                "success": True,
                "receipt_id": receipt_id,
                "status": "passed_vision_first",
                "data": vision_result,
                "sum_check": sum_details,
                "llm_provider": "gemini",
            }
        if db_receipt_id:
            append_workflow_step(db_receipt_id, "llm_vision_first", "fail", details={"sum_check": sum_details})
    except Exception as vision_err:
        timeline.end("gemini_vision_first")
        logger.warning(f"Gemini vision (image only) failed: {vision_err}")
        if db_receipt_id:
            append_workflow_step(db_receipt_id, "llm_vision_first", "fail", details={"error": str(vision_err)})
    return await _fallback_to_aws_ocr(
        image_bytes=image_bytes,
        filename=filename,
        receipt_id=receipt_id,
        timeline=timeline,
        error=error,
        db_receipt_id=db_receipt_id,
        user_id=user_id,
    )


async def process_receipt_workflow_after_confirm(
    receipt_id: str,
    image_bytes: bytes,
    filename: str,
    mime_type: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    User confirmed "this is a clear receipt" after Valid fail or OCR fail + not receipt-like.
    Run Gemini Vision (image only) then Textract+OpenAI if needed. On final failure can record strike.
    """
    timeline = TimelineRecorder(receipt_id)
    append_workflow_step(receipt_id, "user_confirm", "yes")
    result = await _run_ocr_fail_vision_then_textract(
        image_bytes=image_bytes,
        filename=filename,
        receipt_id=receipt_id,
        timeline=timeline,
        mime_type=mime_type,
        db_receipt_id=receipt_id,
        user_id=user_id,
        error="User confirmed receipt after initial reject",
    )
    # If still failed (needs_review or error), optionally record strike for repeated non-receipt
    if not result.get("success") and user_id:
        n = count_strikes_in_last_hour(user_id)
        record_strike(user_id, receipt_id=receipt_id)
        if n + 1 >= 3:
            apply_user_lock(user_id, hours=12.0)
    return result


async def _fallback_to_aws_ocr(
    image_bytes: bytes,
    filename: str,
    receipt_id: str,
    timeline: TimelineRecorder,
    error: str,
    db_receipt_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Google OCR failed, fallback to AWS OCR."""
    timeline.start("aws_ocr_fallback")
    try:
        aws_ocr_result = parse_receipt_textract(image_bytes)
        timeline.end("aws_ocr_fallback")
        
        # Save AWS OCR processing run to database
        if db_receipt_id:
            try:
                save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="ocr",
                    model_provider="aws_textract",
                    model_name=None,  # OCR doesn't have model_name
                    model_version=None,
                    input_payload={"image_bytes_length": len(image_bytes)},
                    output_payload=aws_ocr_result,
                    output_schema_version=None,  # OCR doesn't have schema version
                    status="pass",
                    error_message=None
                )
                
                # Record API call for statistics
                aws_ocr_duration = _get_duration_from_timeline(timeline, "aws_ocr_fallback")
                record_api_call(
                    call_type="ocr",
                    provider="aws_textract",
                    receipt_id=db_receipt_id,
                    duration_ms=int(aws_ocr_duration) if aws_ocr_duration else None,
                    status="success"
                )
            except Exception as e:
                logger.warning(f"Failed to save AWS OCR processing run: {e}")
        
        # Use GPT-4o-mini to process AWS OCR result
        timeline.start("gpt_llm_fallback")
        try:
            llm_result = await process_receipt_with_llm_from_ocr(
                ocr_result=aws_ocr_result,
                merchant_name=None,
                ocr_provider="aws_textract",
                llm_provider="openai",
                receipt_id=db_receipt_id
            )
            timeline.end("gpt_llm_fallback")
            
            if llm_result is None:
                logger.error("llm_result is None after processing with GPT-4o-mini fallback")
                raise ValueError("llm_result cannot be None")
            
            # Save LLM processing run to database
            if db_receipt_id:
                try:
                    model_name = settings.openai_model
                    # Extract RAG metadata from LLM result
                    rag_metadata = llm_result.get("_metadata", {}).get("rag_metadata", {})
                    
                    save_processing_run(
                        receipt_id=db_receipt_id,
                        stage="llm",
                        model_provider="openai",
                        model_name=model_name,
                        model_version=None,
                        input_payload={
                            "ocr_result": aws_ocr_result,
                            "rag_metadata": rag_metadata  # Add RAG usage statistics
                        },
                        output_payload=llm_result,
                        output_schema_version="0.1",
                        status="pass",
                        error_message=None
                    )
                except Exception as e:
                    logger.warning(f"Failed to save LLM processing run: {e}")
            
            # Sum check
            timeline.start("sum_check")
            sum_check_passed, sum_check_details = check_receipt_sums(llm_result)
            timeline.end("sum_check")
            
            if sum_check_passed:
                timeline.start("save_output")
                await _save_output(receipt_id, llm_result, timeline, aws_ocr_result, user_id=user_id)
                timeline.end("save_output")
                
                # Update receipt status
                if db_receipt_id:
                    try:
                        update_receipt_status(db_receipt_id, current_status="success", current_stage="llm_fallback")
                    except Exception as e:
                        logger.warning(f"Failed to update receipt status: {e}")
                
                # Record API call
                llm_duration = _get_duration_from_timeline(timeline, "gpt_llm_fallback")
                record_api_call(
                    call_type="llm",
                    provider="openai",
                    receipt_id=db_receipt_id,
                    duration_ms=int(llm_duration) if llm_duration else None,
                    status="success"
                )
                
                return {
                    "success": True,
                    "receipt_id": receipt_id,
                    "status": "passed_after_fallback",
                    "data": llm_result,
                    "sum_check": sum_check_details,
                    "llm_provider": "openai",
                    "fallback_used": True
                }
            else:
                # Record API call (failed)
                llm_duration = _get_duration_from_timeline(timeline, "gpt_llm_fallback")
                record_api_call(
                    call_type="llm",
                    provider="openai",
                    receipt_id=db_receipt_id,
                    duration_ms=int(llm_duration) if llm_duration else None,
                    status="failed",
                    error_message="Sum check failed, needs manual review"
                )
                
                return await _mark_for_manual_review(
                    receipt_id=receipt_id,
                    timeline=timeline,
                    aws_ocr_data=aws_ocr_result,
                    first_llm_result=llm_result,
                    sum_check_details=sum_check_details,
                    error=f"Google OCR failed, AWS OCR sum check also failed. Original error: {error}",
                    image_bytes=image_bytes,
                    filename=filename,
                    db_receipt_id=db_receipt_id
                )
        except Exception as e:
            timeline.end("gpt_llm_fallback")
            
            # Save failed LLM run to database
            if db_receipt_id:
                try:
                    model_name = settings.openai_model
                    save_processing_run(
                        receipt_id=db_receipt_id,
                        stage="llm",
                        model_provider="openai",
                        model_name=model_name,
                        model_version=None,
                        input_payload={"ocr_result": aws_ocr_result},
                        output_payload=_fail_output_payload(str(e)),
                        output_schema_version="0.1",
                        status="fail",
                        error_message=str(e)
                    )
                except Exception as db_error:
                    logger.warning(f"Failed to save failed LLM run: {db_error}")
            
            # Record API call (error)
            record_api_call(
                call_type="llm",
                provider="openai",
                receipt_id=db_receipt_id,
                duration_ms=None,
                status="failed",
                error_message=str(e)
            )
            
            return await _mark_for_manual_review(
                receipt_id=receipt_id,
                timeline=timeline,
                aws_ocr_data=aws_ocr_result,
                error=f"Google OCR failed, GPT LLM also failed: {e}",
                image_bytes=image_bytes,
                filename=filename,
                db_receipt_id=db_receipt_id
            )
    except Exception as e:
        timeline.end("aws_ocr_fallback")
        # Record API call (error)
        record_api_call(
            call_type="ocr",
            provider="aws_textract",
            receipt_id=db_receipt_id,
            duration_ms=None,
            status="failed",
            error_message=error
        )
        
        return await _mark_for_manual_review(
            receipt_id=receipt_id,
            timeline=timeline,
            error=f"Both OCRs failed. Google: {error}, AWS: {e}",
            image_bytes=image_bytes,
            filename=filename,
            db_receipt_id=db_receipt_id
        )


def _build_vision_ocr_rbsj_prompt(
    google_ocr_data: Dict[str, Any],
    initial_parse_result: Optional[Dict[str, Any]],
    max_ocr_chars: int = 6000,
) -> str:
    """Build single prompt for not-in-chain vision path: OCR + RBSJ (no previous error)."""
    parts = [
        "Store is not in our chain. Use the following OCR text and rule-based summarized JSON (RBSJ) together with the receipt image to extract the full receipt schema. Output only valid JSON."
    ]
    raw_text = (google_ocr_data or {}).get("raw_text") or ""
    if raw_text:
        truncated = raw_text[:max_ocr_chars] + ("..." if len(raw_text) > max_ocr_chars else "")
        parts.append("\n\n--- OCR text ---\n")
        parts.append(truncated)
    if initial_parse_result and isinstance(initial_parse_result, dict):
        parts.append("\n\n--- Rule-based summarized JSON (RBSJ) ---\n")
        parts.append(json.dumps(initial_parse_result, indent=2, ensure_ascii=False))
    parts.append("\n\nLook at the receipt image and output the full schema (receipt + items + tbd). If not confident, set top-level 'reason'.")
    return "".join(parts)


async def _process_receipt_vision_ocr_rbsj(
    image_bytes: bytes,
    mime_type: str,
    google_ocr_data: Dict[str, Any],
    initial_parse_result: Optional[Dict[str, Any]],
    db_receipt_id: Optional[str],
) -> Dict[str, Any]:
    """
    Not-in-chain path: one prompt with OCR + RBSJ + image, via Gemini vision.
    Returns parsed JSON (receipt + items + tbd); caller adds _metadata and runs clean/address.
    """
    prompt_config = get_default_prompt()
    output_schema = prompt_config.get("output_schema") or {}
    output_schema_json = json.dumps(output_schema, indent=2, ensure_ascii=False)
    prompt_text = _build_vision_ocr_rbsj_prompt(google_ocr_data, initial_parse_result)
    vision_result = await parse_receipt_with_gemini_vision(
        image_bytes=image_bytes,
        failure_context=prompt_text,
        output_schema_json=output_schema_json,
        mime_type=mime_type,
    )
    if not vision_result:
        raise ValueError("Gemini vision OCR+RBSJ returned empty")
    rec = vision_result.get("receipt", {})
    merchant_name_v = (rec.get("merchant_name") or "").strip()
    address_v = (rec.get("merchant_address") or "").strip()
    store_match = get_store_chain(merchant_name_v, address_v or None)
    vision_result["_metadata"] = {
        "merchant_name": merchant_name_v or None,
        "chain_id": store_match.get("chain_id"),
        "location_id": store_match.get("location_id"),
        "ocr_provider": "google_documentai",
        "llm_provider": "gemini",
        "entities": (google_ocr_data or {}).get("entities", {}),
        "validation_status": vision_result.get("_metadata", {}).get("validation_status", "unknown"),
        "rag_metadata": {"vision_ocr_rbsj": True},
    }
    if merchant_name_v and not store_match.get("matched") and db_receipt_id:
        try:
            create_store_candidate(
                chain_name=merchant_name_v,
                receipt_id=db_receipt_id,
                source="llm",
                llm_result=vision_result,
                suggested_chain_id=store_match.get("suggested_chain_id"),
                suggested_location_id=store_match.get("suggested_location_id"),
                confidence_score=store_match.get("confidence_score"),
            )
        except Exception as e:
            logger.warning(f"Failed to create store candidate after vision OCR+RBSJ: {e}")
    return vision_result


def _build_vision_retry_failure_context(
    error: str,
    google_ocr_data: Dict[str, Any],
    initial_parse_result: Optional[Dict[str, Any]],
    max_ocr_chars: int = 3500,
    max_parse_items: int = 50,
) -> str:
    """Build failure context for Gemini vision retry: include both OCR and rule-based (initial parse) results."""
    parts = [f"Previous attempt failed with error: {error}\n"]
    raw_text = (google_ocr_data or {}).get("raw_text") or ""
    if raw_text:
        truncated = raw_text[:max_ocr_chars] + ("..." if len(raw_text) > max_ocr_chars else "")
        parts.append("--- OCR text (from Google Document AI) ---\n")
        parts.append(truncated)
        parts.append("\n")
    if initial_parse_result and isinstance(initial_parse_result, dict):
        summary = {
            "method": initial_parse_result.get("method"),
            "success": initial_parse_result.get("success"),
            "store": initial_parse_result.get("store"),
            "chain_id": initial_parse_result.get("chain_id"),
            "items_count": len(initial_parse_result.get("items") or []),
            "items": (initial_parse_result.get("items") or [])[:max_parse_items],
            "totals": initial_parse_result.get("totals"),
            "validation": initial_parse_result.get("validation"),
        }
        parts.append("--- Rule-based (initial parse) extraction result ---\n")
        parts.append(json.dumps(summary, indent=2, ensure_ascii=False))
        parts.append("\n")
    parts.append(
        "Please look at the receipt image and extract the data correctly. "
        "Use the OCR and rule-based results above as reference; correct any errors. "
        "Pay attention to folded/wrinkled areas and layout issues."
    )
    return "".join(parts)


async def _try_gemini_vision_retry(
    image_bytes: bytes,
    mime_type: str,
    error: str,
    receipt_id: str,
    timeline: TimelineRecorder,
    db_receipt_id: Optional[str],
    user_id: Optional[str],
    google_ocr_data: Dict[str, Any],
    filename: str,
    initial_parse_result: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    When Gemini (text) failed, retry once by sending the receipt image + failure context
    (OCR + rule-based extraction) to Gemini vision and ask it to output the correct structured JSON.
    Returns the workflow result dict if vision retry succeeded and sum check passed; else None.
    """
    timeline.start("gemini_vision_retry")
    try:
        prompt_config = get_default_prompt()
        output_schema = prompt_config.get("output_schema") or {}
        output_schema_json = json.dumps(output_schema, indent=2, ensure_ascii=False)
        failure_context = _build_vision_retry_failure_context(
            error=error,
            google_ocr_data=google_ocr_data,
            initial_parse_result=initial_parse_result,
        )
        vision_result = await parse_receipt_with_gemini_vision(
            image_bytes=image_bytes,
            failure_context=failure_context,
            output_schema_json=output_schema_json,
            mime_type=mime_type,
        )
        timeline.end("gemini_vision_retry")
    except Exception as e:
        timeline.end("gemini_vision_retry")
        logger.warning(f"Gemini vision retry failed: {e}, falling back to other LLM")
        return None

    if not vision_result:
        return None

    # Same post-processing as primary LLM path
    vision_result = clean_llm_result(vision_result)
    vision_result = apply_chain_cleaner(vision_result)
    vision_result = correct_address(vision_result, auto_correct=True)

    sum_check_passed, sum_check_details = check_receipt_sums(vision_result)
    if not sum_check_passed:
        logger.warning(f"Gemini vision retry sum check failed for {receipt_id}, falling back to other LLM")
        return None

    # Save LLM run (vision retry)
    if db_receipt_id:
        try:
            save_processing_run(
                receipt_id=db_receipt_id,
                stage="llm",
                model_provider="gemini",
                model_name=settings.gemini_model,
                model_version=None,
                input_payload={
                    "vision_retry": True,
                    "image_bytes_length": len(image_bytes),
                    "mime_type": mime_type,
                    "previous_error": error[:500],
                },
                output_payload=vision_result,
                output_schema_version="0.1",
                status="pass",
                error_message=None,
            )
            update_receipt_status(db_receipt_id, current_status="success", current_stage="llm_primary")
        except Exception as e:
            logger.warning(f"Failed to save Gemini vision retry run: {e}")
    await _save_output(receipt_id, vision_result, timeline, google_ocr_data, user_id=user_id or "dummy")
    if db_receipt_id:
        try:
            cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
            if cat_result.get("success"):
                logger.info(f"✅ Categorization completed for receipt {db_receipt_id} (after Gemini vision retry)")
        except Exception as cat_err:
            logger.warning(f"Categorization failed for {db_receipt_id}: {cat_err}")
        llm_duration = _get_duration_from_timeline(timeline, "gemini_vision_retry")
        record_api_call(
            call_type="llm",
            provider="gemini",
            receipt_id=db_receipt_id,
            duration_ms=int(llm_duration) if llm_duration else None,
            status="success",
        )

    return {
        "success": True,
        "receipt_id": receipt_id,
        "status": "passed_after_vision_retry",
        "data": vision_result,
        "sum_check": sum_check_details,
        "llm_provider": "gemini",
        "vision_retry_used": True,
    }


async def _fallback_to_other_llm(
    google_ocr_data: Dict[str, Any],
    filename: str,
    receipt_id: str,
    timeline: TimelineRecorder,
    failed_provider: str,
    error: str,
    db_receipt_id: Optional[str] = None,
    user_id: Optional[str] = None,
    image_bytes: Optional[bytes] = None
) -> Dict[str, Any]:
    """First LLM failed, fallback to another LLM. When image_bytes provided and other is Gemini, use OCR+image vision."""
    other_provider = "openai" if failed_provider == "gemini" else "gemini"
    mime_type = "image/jpeg"

    timeline.start(f"{other_provider}_llm_fallback")
    try:
        if image_bytes and other_provider == "gemini":
            prompt_config = get_default_prompt()
            output_schema_json = json.dumps(prompt_config.get("output_schema") or {}, indent=2, ensure_ascii=False)
            failure_context = _build_vision_retry_failure_context(
                error=error, google_ocr_data=google_ocr_data, initial_parse_result=None
            )
            llm_result = await parse_receipt_with_gemini_vision(
                image_bytes=image_bytes,
                failure_context=failure_context,
                output_schema_json=output_schema_json,
                mime_type=mime_type,
            )
            if llm_result:
                rec = llm_result.get("receipt", {})
                merchant_name_v = (rec.get("merchant_name") or "").strip()
                address_v = (rec.get("merchant_address") or "").strip()
                store_match = get_store_chain(merchant_name_v, address_v or None)
                llm_result.setdefault("_metadata", {})
                llm_result["_metadata"].update({
                    "chain_id": store_match.get("chain_id"),
                    "location_id": store_match.get("location_id"),
                    "llm_provider": "gemini",
                    "rag_metadata": {"fallback_vision": True},
                })
                llm_result = clean_llm_result(llm_result)
                llm_result = apply_chain_cleaner(llm_result)
                llm_result = correct_address(llm_result, auto_correct=True)
        else:
            llm_result = await process_receipt_with_llm_from_ocr(
                ocr_result=google_ocr_data,
                merchant_name=None,
                ocr_provider="google_documentai",
                llm_provider=other_provider,
                receipt_id=db_receipt_id
            )
        timeline.end(f"{other_provider}_llm_fallback")
        
        if llm_result is None:
            logger.error(f"llm_result is None after processing with {other_provider} fallback")
            raise ValueError("llm_result cannot be None")
        
        # Save LLM processing run to database
        if db_receipt_id:
            try:
                if other_provider == "gemini":
                    model_name = settings.gemini_model
                else:
                    model_name = settings.openai_model
                # Extract RAG metadata from LLM result
                rag_metadata = llm_result.get("_metadata", {}).get("rag_metadata", {})
                
                save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="llm",
                    model_provider=other_provider,
                    model_name=model_name,
                    model_version=None,
                    input_payload={
                        "ocr_result": google_ocr_data,
                        "rag_metadata": rag_metadata  # Add RAG usage statistics
                    },
                    output_payload=llm_result,
                    output_schema_version="0.1",
                    status="pass",
                    error_message=None
                )
            except Exception as e:
                logger.warning(f"Failed to save LLM processing run: {e}")
        
        # Sum check
        timeline.start("sum_check")
        sum_check_passed, sum_check_details = check_receipt_sums(llm_result)
        timeline.end("sum_check")
        
        if sum_check_passed:
            timeline.start("save_output")
            await _save_output(receipt_id, llm_result, timeline, google_ocr_data, user_id=user_id or "dummy")
            timeline.end("save_output")
            
            # Update receipt status
            if db_receipt_id:
                try:
                    update_receipt_status(db_receipt_id, current_status="success", current_stage="llm_fallback")
                except Exception as e:
                    logger.warning(f"Failed to update receipt status: {e}")
                # Categorize: save to record_summaries/record_items, enqueue unmatched to classification_review
                try:
                    cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
                    if cat_result.get("success"):
                        logger.info(f"✅ Categorization completed for receipt {db_receipt_id}")
                    else:
                        logger.warning(f"Categorization skipped for {db_receipt_id}: {cat_result.get('message')}")
                except Exception as cat_err:
                    logger.warning(f"Categorization failed for {db_receipt_id}: {cat_err}")
            
            # Record API call
            llm_duration = _get_duration_from_timeline(timeline, f"{other_provider}_llm_fallback")
            record_api_call(
                call_type="llm",
                provider=other_provider,
                receipt_id=db_receipt_id,
                duration_ms=int(llm_duration) if llm_duration else None,
                status="success"
            )
            
            return {
                "success": True,
                "receipt_id": receipt_id,
                "status": "passed_after_fallback",
                "data": llm_result,
                "sum_check": sum_check_details,
                "llm_provider": other_provider,
                "fallback_used": True
            }
        else:
            # Sum check failed after fallback LLM, trigger AWS OCR backup check
            logger.warning(f"Sum check failed for {receipt_id} after {other_provider} fallback, triggering AWS OCR backup check")
            
            # Update stage to sum_check_failed and persist parsed data for manual review
            if db_receipt_id:
                try:
                    update_receipt_status(db_receipt_id, current_status="needs_review", current_stage="manual")
                    try:
                        cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
                        if cat_result.get("success"):
                            logger.info(f"Saved parsed data for manual review receipt {db_receipt_id} (after fallback)")
                        else:
                            logger.warning(f"Categorization for needs_review skipped: {cat_result.get('message')}")
                    except Exception as cat_err:
                        logger.warning(f"Categorization for needs_review failed for {db_receipt_id}: {cat_err}")
                except Exception as e:
                    logger.warning(f"Failed to update receipt stage to sum_check_failed: {e}")
            
            # Need image_bytes for AWS OCR, but we don't have it in this function
            # So we'll mark for manual review instead
            # TODO: Pass image_bytes to this function to enable AWS OCR fallback
            logger.warning(f"Cannot trigger AWS OCR backup check from _fallback_to_other_llm (image_bytes not available), marking for manual review")
            
            # Record API call (failed)
            llm_duration = _get_duration_from_timeline(timeline, f"{other_provider}_llm_fallback")
            record_api_call(
                call_type="llm",
                provider=other_provider,
                receipt_id=db_receipt_id,
                duration_ms=int(llm_duration) if llm_duration else None,
                status="failed",
                error_message="Sum check failed, needs manual review"
            )
            
            return await _mark_for_manual_review(
                receipt_id=receipt_id,
                timeline=timeline,
                google_ocr_data=google_ocr_data,
                first_llm_result=llm_result,
                sum_check_details=sum_check_details,
                error=f"{failed_provider.upper()} failed, {other_provider.upper()} sum check also failed",
                image_bytes=image_bytes,
                filename=filename,
                db_receipt_id=db_receipt_id
            )
    except Exception as e:
        timeline.end(f"{other_provider}_llm_fallback")
        
        # Save failed LLM run to database
        if db_receipt_id:
            try:
                if other_provider == "gemini":
                    model_name = settings.gemini_model
                else:
                    model_name = settings.openai_model
                save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="llm",
                    model_provider=other_provider,
                    model_name=model_name,
                    model_version=None,
                    input_payload={"ocr_result": google_ocr_data},
                    output_payload=_fail_output_payload(str(e)),
                    output_schema_version="0.1",
                    status="fail",
                    error_message=str(e)
                )
            except Exception as db_error:
                logger.warning(f"Failed to save failed LLM run: {db_error}")
        
        # Record API call (error)
        record_api_call(
            call_type="llm",
            provider=other_provider,
            receipt_id=db_receipt_id,
            duration_ms=None,
            status="failed",
            error_message=error
        )
        
        return await _mark_for_manual_review(
            receipt_id=receipt_id,
            timeline=timeline,
            google_ocr_data=google_ocr_data,
            error=f"Both LLMs failed. {failed_provider.upper()}: {error}, {other_provider.upper()}: {e}",
            image_bytes=image_bytes,
            filename=filename,
            db_receipt_id=db_receipt_id
        )


async def _mark_for_manual_review(
    receipt_id: str,
    timeline: TimelineRecorder,
    google_ocr_data: Optional[Dict[str, Any]] = None,
    aws_ocr_data: Optional[Dict[str, Any]] = None,
    first_llm_result: Optional[Dict[str, Any]] = None,
    backup_llm_result: Optional[Dict[str, Any]] = None,
    sum_check_details: Optional[Dict[str, Any]] = None,
    backup_sum_check_details: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    filename: Optional[str] = None,
    db_receipt_id: Optional[str] = None
) -> Dict[str, Any]:
    """Mark for manual review, save all related files."""
    # Save image for manual review if available
    if image_bytes and filename:
        image_path = _save_image_for_manual_review(receipt_id, image_bytes, filename)
        if image_path and db_receipt_id:
            try:
                update_receipt_file_url(db_receipt_id, image_path)
                logger.info(f"Updated receipt {db_receipt_id} with image path: {image_path}")
            except Exception as e:
                logger.warning(f"Failed to update receipt file URL: {e}")
    
    # Update receipt status to needs_review
    if db_receipt_id:
        try:
            update_receipt_status(db_receipt_id, current_status="needs_review", current_stage="manual")
        except Exception as e:
            logger.warning(f"Failed to update receipt status: {e}")
    
    # Save debug files
    await _save_debug_files(
        receipt_id, google_ocr_data, aws_ocr_data,
        first_llm_result, backup_llm_result, image_bytes, filename
    )
    
    # Note: Timeline files are no longer saved to disk
    # Timeline data is still tracked in memory for duration calculations
    # All data is now stored in the database
    
    # Build manual review result
    manual_review_result = {
        "status": "needs_manual_review",
        "receipt_id": receipt_id,
        "error": error,
        "sum_check": sum_check_details,
        "backup_sum_check": backup_sum_check_details,
        "first_llm_result": first_llm_result,
        "backup_llm_result": backup_llm_result
    }
    
    # If backup_llm_result exists, use it as final result (even if sum check failed)
    final_result = backup_llm_result or first_llm_result
    if final_result:
        final_result["_manual_review_required"] = True
        final_result["_manual_review_reason"] = error or "Sum check failed after backup processing"
    
    return {
        "success": False,
        "receipt_id": receipt_id,
        "status": "needs_manual_review",
        "data": final_result,
        "manual_review_info": manual_review_result
    }


async def _save_output(
    receipt_id: str,
    llm_result: Dict[str, Any],
    timeline: TimelineRecorder,
    ocr_data: Optional[Dict[str, Any]] = None,
    user_id: str = "dummy"
):
    """
    Save final output files in new directory structure.
    
    Structure:
    output/
      YYYYMMDD/
        {receipt_id}_output.json
        timeline/
          {receipt_id}_timeline.json
        YYYYMMDD.csv (appended)
    """
    # Get output paths
    paths = get_output_paths_for_receipt(receipt_id)
    
    # Ensure directories exist
    paths["date_dir"].mkdir(parents=True, exist_ok=True)
    paths["timeline_dir"].mkdir(parents=True, exist_ok=True)
    
    # Save output JSON
    output_data = {
        "receipt_id": receipt_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": llm_result
    }
    try:
        with open(paths["json_file"], "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved output JSON: {paths['json_file']}")
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.error(f"Failed to save output JSON to {paths['json_file']}: {e}")
        raise
    
    # Note: Timeline and CSV files are no longer saved to disk
    # All data is now stored in the database (receipts, receipt_processing_runs, api_calls tables)
    # Timeline data is still tracked in memory for duration calculations
    
    # Note: Categorization (saving to record_items/record_summaries) is now done via
    # a separate API endpoint (/api/receipt/categorize) after workflow completes successfully


async def _save_debug_files(
    receipt_id: str,
    google_ocr_data: Optional[Dict[str, Any]],
    aws_ocr_data: Optional[Dict[str, Any]],
    first_llm_result: Optional[Dict[str, Any]],
    backup_llm_result: Optional[Dict[str, Any]],
    image_bytes: Optional[bytes],
    filename: Optional[str]
):
    """Save debug files (when manual review is needed) in new directory structure."""
    # Get output paths
    paths = get_output_paths_for_receipt(receipt_id)
    
    # Ensure debug directory exists
    try:
        paths["debug_dir"].mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as e:
        logger.error(f"Failed to create debug directory {paths['debug_dir']}: {e}")
        raise
    
    if google_ocr_data:
        path = paths["debug_dir"] / f"{receipt_id}_google_ocr.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(google_ocr_data, f, indent=2, ensure_ascii=False)
        except (FileNotFoundError, PermissionError, OSError) as e:
            logger.error(f"Failed to save Google OCR debug file to {path}: {e}")
            # Don't raise, continue with other files
    
    if aws_ocr_data:
        path = paths["debug_dir"] / f"{receipt_id}_aws_ocr.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(aws_ocr_data, f, indent=2, ensure_ascii=False)
        except (FileNotFoundError, PermissionError, OSError) as e:
            logger.error(f"Failed to save AWS OCR debug file to {path}: {e}")
            # Don't raise, continue with other files
    
    if first_llm_result:
        # Determine if it's Gemini or GPT
        llm_provider = first_llm_result.get("_metadata", {}).get("llm_provider", "unknown")
        if llm_provider == "gemini":
            path = paths["debug_dir"] / f"{receipt_id}_gemini_llm.json"
        else:
            path = paths["debug_dir"] / f"{receipt_id}_gpt_llm.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(first_llm_result, f, indent=2, ensure_ascii=False)
        except (FileNotFoundError, PermissionError, OSError) as e:
            logger.error(f"Failed to save first LLM result debug file to {path}: {e}")
            # Don't raise, continue with other files
    
    if backup_llm_result:
        path = paths["debug_dir"] / f"{receipt_id}_gpt_llm.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(backup_llm_result, f, indent=2, ensure_ascii=False)
        except (FileNotFoundError, PermissionError, OSError) as e:
            logger.error(f"Failed to save backup LLM result debug file to {path}: {e}")
            # Don't raise, continue with other files
    
    if image_bytes and filename:
        # Save original image
        ext = Path(filename).suffix or ".jpg"
        path = paths["debug_dir"] / f"{receipt_id}_original{ext}"
        try:
            with open(path, "wb") as f:
                f.write(image_bytes)
        except (FileNotFoundError, PermissionError, OSError) as e:
            logger.error(f"Failed to save original image to {path}: {e}")
            # Don't raise, continue with other files


async def _save_error(
    receipt_id: str,
    timeline: TimelineRecorder,
    error: str,
    filename: Optional[str] = None
):
    """Save error information to error folder in new directory structure."""
    paths = get_output_paths_for_receipt(receipt_id)
    
    # Ensure error directory exists
    try:
        paths["error_dir"].mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as e:
        logger.error(f"Failed to create error directory {paths['error_dir']}: {e}")
        raise
    
    error_data = {
        "receipt_id": receipt_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": error,
        "filename": filename,
        "timeline": timeline.to_dict()
    }
    
    error_path = paths["error_dir"] / f"{receipt_id}_error.json"
    try:
        with open(error_path, "w", encoding="utf-8") as f:
            json.dump(error_data, f, indent=2, ensure_ascii=False)
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.error(f"Failed to save error file to {error_path}: {e}")
        raise
    
    # Save timeline
    try:
        paths["timeline_dir"].mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as e:
        logger.error(f"Failed to create timeline directory {paths['timeline_dir']}: {e}")
        raise
    
    # Note: Timeline files are no longer saved to disk
    # Timeline data is still tracked in memory for duration calculations
    # All data is now stored in the database
