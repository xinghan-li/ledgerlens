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

from ..services.ocr.documentai_client import parse_receipt_documentai
from ..services.ocr.textract_client import parse_receipt_textract
from ..services.llm.gemini_rate_limiter import check_gemini_available, record_gemini_request
from ..services.llm.receipt_llm_processor import process_receipt_with_llm_from_ocr
from ..processors.validation.sum_checker import check_receipt_sums, apply_field_conflicts_resolution
from ..services.llm.llm_client import parse_receipt_with_llm
from ..prompts.prompt_manager import format_prompt, get_default_prompt
from ..config import settings
from ..services.database.statistics_manager import update_statistics
from ..exporters.csv_exporter import convert_receipt_to_csv_rows, append_to_daily_csv, get_csv_headers
from ..processors.merchants.implementations.tt_supermarket import clean_tt_receipt_items
from ..processors.enrichment.address_matcher import correct_address
from ..processors.text.data_cleaner import clean_llm_result

logger = logging.getLogger(__name__)

# Output directories (moved to project root)
# Path(__file__).parent.parent.parent is project root (backend/app -> backend -> project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent
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
    
    Args:
        filename: Optional original filename to include in receipt ID
    
    Returns:
        Receipt ID string
    """
    now = datetime.now(timezone.utc)
    # Use sequence number (temporarily use timestamp, can be changed to database auto-increment in the future)
    seq = now.strftime("%H%M%S")[-6:]  # Use last 6 digits of seconds as sequence number
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
    mime_type: str = "image/jpeg"
) -> Dict[str, Any]:
    """
    Complete receipt processing workflow.
    
    Args:
        image_bytes: Image bytes
        filename: Filename
        mime_type: MIME type
        
    Returns:
        Processing result dictionary
    """
    receipt_id = generate_receipt_id(filename)
    timeline = TimelineRecorder(receipt_id)
    
    try:
        # Step 1: Google Document AI OCR
        timeline.start("google_ocr")
        try:
            google_ocr_result = parse_receipt_documentai(image_bytes, mime_type=mime_type)
            timeline.end("google_ocr")
        except Exception as e:
            timeline.end("google_ocr")
            logger.error(f"Google OCR failed: {e}")
            # Fallback to AWS OCR
            return await _fallback_to_aws_ocr(image_bytes, filename, receipt_id, timeline, error=f"Google OCR failed: {e}")
        
        # Save Google OCR result (temporarily not saved, will save when needed)
        google_ocr_data = google_ocr_result
        
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
        
        # Step 3: LLM processing
        timeline.start(f"{llm_provider}_llm")
        try:
            first_llm_result = await process_receipt_with_llm_from_ocr(
                ocr_result=google_ocr_data,
                merchant_name=None,
                ocr_provider="google_documentai",
                llm_provider=llm_provider
            )
            timeline.end(f"{llm_provider}_llm")
        except Exception as e:
            timeline.end(f"{llm_provider}_llm")
            logger.error(f"{llm_provider.upper()} LLM failed: {e}")
            # Fallback to another LLM
            return await _fallback_to_other_llm(
                google_ocr_data, filename, receipt_id, timeline, 
                failed_provider=llm_provider, error=str(e)
            )
        
        # Step 4: Clean data fields (dates, times, etc.)
        timeline.start("data_cleaning")
        first_llm_result = clean_llm_result(first_llm_result)
        timeline.end("data_cleaning")
        
        # Step 4.5: Apply T&T-specific cleaning rules (remove membership lines, extract card number)
        timeline.start("tt_cleaning")
        first_llm_result = clean_tt_receipt_items(first_llm_result)
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
                await _save_output(receipt_id, first_llm_result, timeline, google_ocr_data)
                timeline.end("save_output")
                
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
                await _save_output(receipt_id, resolved_result, timeline, google_ocr_data)
                timeline.end("save_output")
                
                # Update statistics
                update_statistics(llm_provider, sum_check_passed=True)
                
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
            return await _backup_check_with_aws_ocr(
                image_bytes, filename, receipt_id, timeline,
                google_ocr_data, first_llm_result, sum_check_details, llm_provider
            )
    
    except Exception as e:
        logger.error(f"Workflow failed for {receipt_id}: {e}", exc_info=True)
        timeline.start("save_error")
        await _save_error(receipt_id, timeline, error=str(e), filename=filename)
        timeline.end("save_error")
        
        # Update statistics (error)
        update_statistics("openai", sum_check_passed=False, is_error=True)
        
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
    first_llm_provider: str
) -> Dict[str, Any]:
    """Use AWS OCR + GPT-4o-mini for secondary processing."""
    # Step 1: AWS OCR
    timeline.start("aws_ocr")
    try:
        aws_ocr_result = parse_receipt_textract(image_bytes)
        timeline.end("aws_ocr")
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
            error=f"AWS OCR failed: {e}"
        )
    
    # Step 2: GPT-4o-mini secondary processing
    timeline.start("gpt_backup_llm")
    try:
        backup_llm_result = await _gpt_backup_processing(
            google_ocr_data, aws_ocr_result, first_llm_result, sum_check_details
        )
        timeline.end("gpt_backup_llm")
    except Exception as e:
        timeline.end("gpt_backup_llm")
        logger.error(f"GPT backup processing failed: {e}")
        return await _mark_for_manual_review(
            receipt_id=receipt_id,
            timeline=timeline,
            google_ocr_data=google_ocr_data,
            aws_ocr_data=aws_ocr_result,
            first_llm_result=first_llm_result,
            sum_check_details=sum_check_details,
            error=f"GPT backup failed: {e}"
        )
    
    # Step 3: Clean data fields
    timeline.start("data_cleaning_backup")
    backup_llm_result = clean_llm_result(backup_llm_result)
    timeline.end("data_cleaning_backup")
    
    # Step 3.5: Apply T&T cleaning on backup result
    timeline.start("tt_cleaning_backup")
    backup_llm_result = clean_tt_receipt_items(backup_llm_result)
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
        await _save_output(receipt_id, backup_llm_result, timeline, google_ocr_data)
        timeline.end("save_output")
        
        # Save debug files
        await _save_debug_files(
            receipt_id, google_ocr_data, aws_ocr_result,
            first_llm_result, backup_llm_result, image_bytes, filename
        )
        
        # Update statistics (GPT-4o-mini passed)
        update_statistics("openai", sum_check_passed=True)
        
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
        # Update statistics (GPT-4o-mini failed, needs manual review)
        update_statistics("openai", sum_check_passed=False, is_manual_review=True)
        
        return await _mark_for_manual_review(
            receipt_id=receipt_id,
            timeline=timeline,
            google_ocr_data=google_ocr_data,
            aws_ocr_data=aws_ocr_result,
            first_llm_result=first_llm_result,
            backup_llm_result=backup_llm_result,
            sum_check_details=sum_check_details,
            backup_sum_check_details=backup_sum_check_details,
            error="Backup sum check also failed"
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
    error: str
) -> Dict[str, Any]:
    """Google OCR failed, fallback to AWS OCR."""
    timeline.start("aws_ocr_fallback")
    try:
        aws_ocr_result = parse_receipt_textract(image_bytes)
        timeline.end("aws_ocr_fallback")
        
        # Use GPT-4o-mini to process AWS OCR result
        timeline.start("gpt_llm_fallback")
        try:
            llm_result = await process_receipt_with_llm_from_ocr(
                ocr_result=aws_ocr_result,
                merchant_name=None,
                ocr_provider="aws_textract",
                llm_provider="openai"
            )
            timeline.end("gpt_llm_fallback")
            
            # Sum check
            timeline.start("sum_check")
            sum_check_passed, sum_check_details = check_receipt_sums(llm_result)
            timeline.end("sum_check")
            
            if sum_check_passed:
                timeline.start("save_output")
                await _save_output(receipt_id, llm_result, timeline, aws_ocr_result)
                timeline.end("save_output")
                
                # Update statistics
                update_statistics("openai", sum_check_passed=True)
                
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
                # Update statistics (failed)
                update_statistics("openai", sum_check_passed=False, is_manual_review=True)
                
                return await _mark_for_manual_review(
                    receipt_id=receipt_id,
                    timeline=timeline,
                    aws_ocr_data=aws_ocr_result,
                    first_llm_result=llm_result,
                    sum_check_details=sum_check_details,
                    error=f"Google OCR failed, AWS OCR sum check also failed. Original error: {error}"
                )
        except Exception as e:
            timeline.end("gpt_llm_fallback")
            # Update statistics (error)
            update_statistics("openai", sum_check_passed=False, is_error=True)
            
            return await _mark_for_manual_review(
                receipt_id=receipt_id,
                timeline=timeline,
                aws_ocr_data=aws_ocr_result,
                error=f"Google OCR failed, GPT LLM also failed: {e}"
            )
    except Exception as e:
        timeline.end("aws_ocr_fallback")
        # Update statistics (error)
        update_statistics("openai", sum_check_passed=False, is_error=True)
        
        return await _mark_for_manual_review(
            receipt_id=receipt_id,
            timeline=timeline,
            error=f"Both OCRs failed. Google: {error}, AWS: {e}"
        )


async def _fallback_to_other_llm(
    google_ocr_data: Dict[str, Any],
    filename: str,
    receipt_id: str,
    timeline: TimelineRecorder,
    failed_provider: str,
    error: str
) -> Dict[str, Any]:
    """First LLM failed, fallback to another LLM."""
    other_provider = "openai" if failed_provider == "gemini" else "gemini"
    
    timeline.start(f"{other_provider}_llm_fallback")
    try:
        llm_result = await process_receipt_with_llm_from_ocr(
            ocr_result=google_ocr_data,
            merchant_name=None,
            ocr_provider="google_documentai",
            llm_provider=other_provider
        )
        timeline.end(f"{other_provider}_llm_fallback")
        
        # Sum check
        timeline.start("sum_check")
        sum_check_passed, sum_check_details = check_receipt_sums(llm_result)
        timeline.end("sum_check")
        
        if sum_check_passed:
            timeline.start("save_output")
            await _save_output(receipt_id, llm_result, timeline, google_ocr_data)
            timeline.end("save_output")
            
            # Update statistics
            update_statistics(other_provider, sum_check_passed=True)
            
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
            # Update statistics (failed)
            update_statistics(other_provider, sum_check_passed=False, is_manual_review=True)
            
            return await _mark_for_manual_review(
                receipt_id=receipt_id,
                timeline=timeline,
                google_ocr_data=google_ocr_data,
                first_llm_result=llm_result,
                sum_check_details=sum_check_details,
                error=f"{failed_provider.upper()} failed, {other_provider.upper()} sum check also failed"
            )
    except Exception as e:
        timeline.end(f"{other_provider}_llm_fallback")
        # Update statistics (error)
        update_statistics(other_provider, sum_check_passed=False, is_error=True)
        
        return await _mark_for_manual_review(
            receipt_id=receipt_id,
            timeline=timeline,
            google_ocr_data=google_ocr_data,
            error=f"Both LLMs failed. {failed_provider.upper()}: {error}, {other_provider.upper()}: {e}"
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
    filename: Optional[str] = None
) -> Dict[str, Any]:
    """Mark for manual review, save all related files."""
    # Save debug files
    await _save_debug_files(
        receipt_id, google_ocr_data, aws_ocr_data,
        first_llm_result, backup_llm_result, image_bytes, filename
    )
    
    # Save timeline
    timeline.start("save_timeline")
    paths = get_output_paths_for_receipt(receipt_id)
    paths["timeline_dir"].mkdir(parents=True, exist_ok=True)
    with open(paths["timeline_file"], "w", encoding="utf-8") as f:
        json.dump(timeline.to_dict(), f, indent=2, ensure_ascii=False)
    timeline.end("save_timeline")
    
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
    with open(paths["json_file"], "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved output JSON: {paths['json_file']}")
    
    # Save timeline
    with open(paths["timeline_file"], "w", encoding="utf-8") as f:
        json.dump(timeline.to_dict(), f, indent=2, ensure_ascii=False)
    logger.info(f"Saved timeline: {paths['timeline_file']}")
    
    # Convert to CSV rows and append to daily CSV
    csv_rows = convert_receipt_to_csv_rows(llm_result, user_id=user_id)
    csv_headers = get_csv_headers()
    append_to_daily_csv(paths["csv_file"], csv_rows, csv_headers)
    logger.info(f"Appended {len(csv_rows)} rows to CSV: {paths['csv_file']}")


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
    paths["debug_dir"].mkdir(parents=True, exist_ok=True)
    
    if google_ocr_data:
        path = paths["debug_dir"] / f"{receipt_id}_google_ocr.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(google_ocr_data, f, indent=2, ensure_ascii=False)
    
    if aws_ocr_data:
        path = paths["debug_dir"] / f"{receipt_id}_aws_ocr.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(aws_ocr_data, f, indent=2, ensure_ascii=False)
    
    if first_llm_result:
        # Determine if it's Gemini or GPT
        llm_provider = first_llm_result.get("_metadata", {}).get("llm_provider", "unknown")
        if llm_provider == "gemini":
            path = paths["debug_dir"] / f"{receipt_id}_gemini_llm.json"
        else:
            path = paths["debug_dir"] / f"{receipt_id}_gpt_llm.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(first_llm_result, f, indent=2, ensure_ascii=False)
    
    if backup_llm_result:
        path = paths["debug_dir"] / f"{receipt_id}_gpt_llm.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(backup_llm_result, f, indent=2, ensure_ascii=False)
    
    if image_bytes and filename:
        # Save original image
        ext = Path(filename).suffix or ".jpg"
        path = paths["debug_dir"] / f"{receipt_id}_original{ext}"
        with open(path, "wb") as f:
            f.write(image_bytes)


async def _save_error(
    receipt_id: str,
    timeline: TimelineRecorder,
    error: str,
    filename: Optional[str] = None
):
    """Save error information to error folder in new directory structure."""
    paths = get_output_paths_for_receipt(receipt_id)
    
    # Ensure error directory exists
    paths["error_dir"].mkdir(parents=True, exist_ok=True)
    
    error_data = {
        "receipt_id": receipt_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": error,
        "filename": filename,
        "timeline": timeline.to_dict()
    }
    
    error_path = paths["error_dir"] / f"{receipt_id}_error.json"
    with open(error_path, "w", encoding="utf-8") as f:
        json.dump(error_data, f, indent=2, ensure_ascii=False)
    
    # Save timeline
    paths["timeline_dir"].mkdir(parents=True, exist_ok=True)
    timeline_path = paths["timeline_dir"] / f"{receipt_id}_timeline.json"
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(timeline.to_dict(), f, indent=2, ensure_ascii=False)
