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
from ..processors.core.sum_checker import check_receipt_sums, apply_field_conflicts_resolution
from ..services.llm.llm_client import parse_receipt_with_llm
from ..prompts.prompt_manager import format_prompt, get_default_prompt
from ..config import settings
from ..services.database.statistics_manager import record_api_call
from ..services.database.supabase_client import (
    create_receipt,
    save_processing_run,
    update_receipt_status,
    get_test_user_id,
    update_receipt_file_url,
    check_duplicate_by_hash
)
import shutil
from ..exporters.csv_exporter import convert_receipt_to_csv_rows, append_to_daily_csv, get_csv_headers
from ..processors.stores.tnt_supermarket import clean_tnt_receipt_items
from ..processors.enrichment.address_matcher import correct_address
from ..processors.text.data_cleaner import clean_llm_result
from ..processors.validation.coordinate_extractor import extract_text_blocks_with_coordinates
from ..processors.validation.pipeline import process_receipt_pipeline
from ..processors.validation.store_config_loader import get_store_config_for_receipt

logger = logging.getLogger(__name__)

# Output directories (moved to project root)
# Path(__file__).parent.parent.parent.parent is project root
# backend/app/core/workflow_processor.py -> backend/app/core -> backend/app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = PROJECT_ROOT / "output"
INPUT_ROOT = PROJECT_ROOT / "input"

# Ensure root directories exist
OUTPUT_ROOT.mkdir(exist_ok=True)
INPUT_ROOT.mkdir(exist_ok=True)


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
        logger.debug(f"Timeline: {step} started at {now.isoformat()}")
    
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
        logger.debug(f"Timeline: {step} ended at {now.isoformat()}, duration: {duration_ms}ms")
    
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
    logger.info(f"File hash calculated: {file_hash[:16]}... (for duplicate detection)")
    
    # Get user_id
    if user_id is None:
        logger.info("user_id not provided, attempting to get from get_test_user_id()...")
        user_id = get_test_user_id()
        if user_id:
            logger.info(f"Got user_id from get_test_user_id(): {user_id}")
        else:
            logger.warning("get_test_user_id() returned None")
    
    # Check for duplicate before processing (if user_id is available)
    if user_id:
        existing_receipt_id = check_duplicate_by_hash(file_hash, user_id)
        if existing_receipt_id:
            # Log debug mode status for troubleshooting
            logger.info(f"Duplicate detected. allow_duplicate_for_debug = {settings.allow_duplicate_for_debug}")
            if settings.allow_duplicate_for_debug:
                # Debug mode: Allow duplicate by modifying file_hash with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                file_hash = f"{original_file_hash}_debug_{timestamp}"
                logger.warning(
                    f"DEBUG MODE: Duplicate receipt detected (original: {existing_receipt_id}), "
                    f"but allowing reprocess with modified hash: {file_hash[:32]}... "
                    f"This allows comparison of results between runs."
                )
            else:
                # Normal mode: Reject duplicate
                logger.warning(
                    f"Duplicate receipt detected: file_hash={file_hash[:16]}..., "
                    f"existing_receipt_id={existing_receipt_id}. "
                    "Skipping processing to avoid duplicate work. "
                    "Set ALLOW_DUPLICATE_FOR_DEBUG=true to allow reprocessing for debugging."
                )
                return {
                    "success": False,
                    "receipt_id": receipt_id,
                    "status": "duplicate",
                    "error": "duplicate_receipt",
                    "message": "This receipt has already been processed",
                    "existing_receipt_id": existing_receipt_id,
                    "file_hash": file_hash[:16] + "..."  # Only return first 16 chars for security
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
        logger.info(f"Attempting to create receipt record with user_id: {user_id}")
        # Create receipt record in database
        db_receipt_id: Optional[str] = None
        try:
            db_receipt_id = create_receipt(user_id=user_id, raw_file_url=None, file_hash=file_hash)
            logger.info(f"✓ Created receipt record in database: {db_receipt_id}")
        except Exception as e:
            error_msg = str(e)
            # Check if it's a duplicate error
            if "duplicate" in error_msg.lower() or "Duplicate receipt" in error_msg:
                if settings.allow_duplicate_for_debug:
                    # Debug mode: Try again with modified hash
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    file_hash = f"{original_file_hash}_debug_{timestamp}"
                    logger.warning(
                        f"DEBUG MODE: Duplicate detected during creation, retrying with modified hash: {file_hash[:32]}..."
                    )
                    try:
                        db_receipt_id = create_receipt(user_id=user_id, raw_file_url=None, file_hash=file_hash)
                        logger.info(f"✓ Created receipt record in database (debug mode): {db_receipt_id}")
                    except Exception as retry_error:
                        logger.error(f"Failed to create receipt even with modified hash: {retry_error}")
                        raise
                else:
                    # Normal mode: Return duplicate error
                    logger.warning(f"Duplicate receipt detected during creation: {error_msg}")
                    # Try to get existing receipt ID
                    existing_receipt_id = check_duplicate_by_hash(original_file_hash, user_id)
                    return {
                        "success": False,
                        "receipt_id": receipt_id,
                        "status": "duplicate",
                        "error": "duplicate_receipt",
                        "message": "This receipt has already been processed",
                        "existing_receipt_id": existing_receipt_id,
                        "file_hash": original_file_hash[:16] + "..."
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
                    
                    save_processing_run(
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
                        output_payload={},
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
            
            # Fallback to AWS OCR
            return await _fallback_to_aws_ocr(image_bytes, filename, receipt_id, timeline, error=f"Google OCR failed: {e}", db_receipt_id=db_receipt_id, user_id=user_id)
        
        # Save Google OCR result (temporarily not saved, will save when needed)
        google_ocr_data = google_ocr_result
        
        # Step 1.5: Run Initial Parse (rule-based extraction before LLM)
        timeline.start("initial_parse")
        initial_parse_result = None
        try:
            # Extract coordinate data from Document AI response
            coordinate_data = google_ocr_result.get("coordinate_data", {})
            if coordinate_data:
                # Extract text blocks with coordinates
                blocks = extract_text_blocks_with_coordinates(coordinate_data, apply_receipt_body_filter=True)
                
                # Get merchant name from OCR
                merchant_name = google_ocr_result.get("merchant_name", "")
                
                # Load store config
                store_config = get_store_config_for_receipt(merchant_name, blocks=blocks)
                
                # Run rule-based pipeline
                initial_parse_result = process_receipt_pipeline(
                    blocks=blocks,
                    llm_result={},  # No LLM result yet
                    store_config=store_config,
                    merchant_name=merchant_name
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
            logger.debug(f"Gemini unavailable reason: {gemini_reason}")
        
        # Update stage to llm_primary
        if db_receipt_id:
            try:
                update_receipt_status(db_receipt_id, current_status="failed", current_stage="llm_primary")
            except Exception as e:
                logger.warning(f"Failed to update receipt stage to llm_primary: {e}")
        
        # Step 3: LLM processing (with initial parse result)
        timeline.start(f"{llm_provider}_llm")
        try:
            first_llm_result = await process_receipt_with_llm_from_ocr(
                ocr_result=google_ocr_data,
                merchant_name=None,
                ocr_provider="google_documentai",
                llm_provider=llm_provider,
                receipt_id=db_receipt_id,
                initial_parse_result=initial_parse_result  # Pass initial parse result to LLM
            )
            timeline.end(f"{llm_provider}_llm")
            
            # Save LLM processing run to database
            if db_receipt_id and first_llm_result:
                try:
                    # Get model name from settings (the actual model used for the call)
                    if llm_provider.lower() == "gemini":
                        model_name = settings.gemini_model
                    else:
                        model_name = settings.openai_model
                    
                    # Extract RAG metadata from LLM result
                    rag_metadata = first_llm_result.get("_metadata", {}).get("rag_metadata", {})
                    
                    save_processing_run(
                        receipt_id=db_receipt_id,
                        stage="llm",
                        model_provider=llm_provider,
                        model_name=model_name,
                        model_version=None,  # Model version not available from API
                        input_payload={
                            "ocr_result": google_ocr_data,
                            "rag_metadata": rag_metadata  # Add RAG usage statistics
                        },
                        output_payload=first_llm_result,
                        output_schema_version="0.1",  # Current schema version
                        status="pass",
                        error_message=None
                    )
                    logger.info(f"Saved LLM processing run for receipt {db_receipt_id}")
                except Exception as e:
                    logger.warning(f"Failed to save LLM processing run: {e}")
            
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
                    
                    save_processing_run(
                        receipt_id=db_receipt_id,
                        stage="llm",
                        model_provider=llm_provider,
                        model_name=model_name,
                        model_version=None,
                        input_payload={"ocr_result": google_ocr_data},
                        output_payload={},
                        output_schema_version="0.1",
                        status="fail",
                        error_message=str(e)
                    )
                    update_receipt_status(db_receipt_id, current_status="failed", current_stage="ocr")
                except Exception as db_error:
                    logger.warning(f"Failed to save failed LLM run: {db_error}")
            
            # Fallback to another LLM
            return await _fallback_to_other_llm(
                google_ocr_data, filename, receipt_id, timeline, 
                failed_provider=llm_provider, error=str(e), db_receipt_id=db_receipt_id
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
        first_llm_result = clean_tnt_receipt_items(first_llm_result)
        timeline.end("tt_cleaning")
        
        # Step 4.6: Correct address using fuzzy matching against canonical database
        timeline.start("address_correction")
        first_llm_result = correct_address(first_llm_result, auto_correct=True)
        timeline.end("address_correction")
        
        # Step 5: Sum check
        timeline.start("sum_check")
        sum_check_passed, sum_check_details = check_receipt_sums(first_llm_result)
        timeline.end("sum_check")
        
        # Step 6: Process results
        if sum_check_passed:
            # Sum check passed
            field_conflicts = first_llm_result.get("tbd", {}).get("field_conflicts", {})
            
            if not field_conflicts:
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
            else:
                # Sum check passed but has field_conflicts, apply resolution
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
            
            # Update stage to sum_check_failed
            if db_receipt_id:
                try:
                    update_receipt_status(db_receipt_id, current_status="needs_review", current_stage="manual")
                except Exception as e:
                    logger.warning(f"Failed to update receipt stage to sum_check_failed: {e}")
            
            return await _backup_check_with_aws_ocr(
                image_bytes, filename, receipt_id, timeline,
                google_ocr_data, first_llm_result, sum_check_details, llm_provider,
                db_receipt_id=db_receipt_id,
                user_id=user_id
            )
    
    except Exception as e:
        logger.error(f"Workflow failed for {receipt_id}: {e}", exc_info=True)
        timeline.start("save_error")
        await _save_error(receipt_id, timeline, error=str(e), filename=filename)
        timeline.end("save_error")
        
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
                    output_payload={},
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
    backup_llm_result = clean_tnt_receipt_items(backup_llm_result)
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
                        output_payload={},
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


async def _fallback_to_other_llm(
    google_ocr_data: Dict[str, Any],
    filename: str,
    receipt_id: str,
    timeline: TimelineRecorder,
    failed_provider: str,
    error: str,
    db_receipt_id: Optional[str] = None
) -> Dict[str, Any]:
    """First LLM failed, fallback to another LLM."""
    other_provider = "openai" if failed_provider == "gemini" else "gemini"
    
    timeline.start(f"{other_provider}_llm_fallback")
    try:
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
            await _save_output(receipt_id, llm_result, timeline, google_ocr_data, user_id=user_id)
            timeline.end("save_output")
            
            # Update receipt status
            if db_receipt_id:
                try:
                    update_receipt_status(db_receipt_id, current_status="success", current_stage="llm_fallback")
                except Exception as e:
                    logger.warning(f"Failed to update receipt status: {e}")
            
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
            
            # Update stage to sum_check_failed
            if db_receipt_id:
                try:
                    update_receipt_status(db_receipt_id, current_status="needs_review", current_stage="manual")
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
                image_bytes=None,  # No image_bytes in this function
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
                    output_payload={},
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
            image_bytes=None,  # No image_bytes in this function
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
    logger.debug("Skipping timeline file generation (data stored in database)")
    
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
    logger.debug("Skipping timeline and CSV file generation (data stored in database)")
    
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
    logger.debug("Skipping timeline file generation (data stored in database)")
