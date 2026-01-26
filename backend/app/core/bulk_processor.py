"""
Bulk Processor: Handles bulk receipt uploads with Gemini rate limiting.

Manages processing queue to ensure Gemini API free tier limit (15 requests/minute) is respected.
Uses a smart queue system that waits for the next minute when rate limit is reached.
"""
import asyncio
import logging
from typing import List, Dict, Any
from datetime import datetime, timezone
from fastapi import UploadFile

from .workflow_processor import process_receipt_workflow
from ..services.llm.gemini_rate_limiter import check_gemini_available

logger = logging.getLogger(__name__)


async def _process_single_receipt(
    file: UploadFile,
    result_list: List[Dict[str, Any]],
    index: int
) -> None:
    """
    Process a single receipt file.
    
    Args:
        file: UploadFile object
        result_list: Shared list to store results
        index: Index of this file in the batch
    """
    try:
        # Read file contents
        contents = await file.read()
        if len(contents) == 0:
            result_list[index] = {
                "filename": file.filename,
                "success": False,
                "error": "Empty file"
            }
            return
        
        # Check file size
        if len(contents) > 5 * 1024 * 1024:
            result_list[index] = {
                "filename": file.filename,
                "success": False,
                "error": "File size exceeds 5MB limit"
            }
            return
        
        # Determine MIME type
        mime_type = "image/jpeg" if file.content_type in ("image/jpeg", "image/jpg") else "image/png"
        
        # Process receipt (workflow will handle Gemini rate limiting internally)
        result = await process_receipt_workflow(
            image_bytes=contents,
            filename=file.filename,
            mime_type=mime_type
        )
        
        result_list[index] = {
            "filename": file.filename,
            "success": result.get("success", False),
            "receipt_id": result.get("receipt_id"),
            "status": result.get("status"),
            "data": result.get("data"),
            "sum_check": result.get("sum_check"),
            "llm_provider": result.get("llm_provider"),
            "error": result.get("error")
        }
        
        logger.info(f"Processed receipt {index + 1}: {file.filename} - Status: {result.get('status')}")
        
    except Exception as e:
        logger.error(f"Error processing receipt {file.filename}: {e}", exc_info=True)
        result_list[index] = {
            "filename": file.filename,
            "success": False,
            "error": str(e)
        }


async def _wait_for_next_minute() -> None:
    """Wait until the next minute starts."""
    now = datetime.now(timezone.utc)
    seconds_until_next_minute = 60 - now.second
    if seconds_until_next_minute > 0:
        logger.info(f"Waiting {seconds_until_next_minute} seconds until next minute for Gemini rate limit reset")
        await asyncio.sleep(seconds_until_next_minute + 1)  # Add 1 second buffer


async def process_bulk_receipts(
    files: List[UploadFile],
    max_concurrent: int = 3
) -> Dict[str, Any]:
    """
    Process multiple receipt files with Gemini rate limiting.
    
    Strategy:
    1. Process files with controlled concurrency (semaphore)
    2. Before each file, check if Gemini is available
    3. If Gemini rate limit reached (15/minute), wait for next minute
    4. Process files sequentially when rate limit is active to avoid exceeding limit
    
    Args:
        files: List of UploadFile objects
        max_concurrent: Maximum number of concurrent workers (default: 3)
    
    Returns:
        Dictionary with processing results
    """
    total_files = len(files)
    logger.info(f"Starting bulk processing of {total_files} receipts")
    
    # Validate files
    valid_files = []
    for file in files:
        if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
            logger.warning(f"Skipping invalid file type: {file.filename} ({file.content_type})")
            continue
        valid_files.append(file)
    
    if not valid_files:
        return {
            "success": False,
            "error": "No valid files to process",
            "total": total_files,
            "processed": 0,
            "results": []
        }
    
    # Initialize result list
    results = [None] * len(valid_files)
    
    # Use semaphore to limit concurrent processing
    semaphore = asyncio.Semaphore(max_concurrent)
    
    # Shared lock for Gemini rate limit checking
    gemini_lock = asyncio.Lock()
    gemini_count_this_minute = 0
    current_minute = None
    
    async def process_with_rate_limiting(file: UploadFile, index: int):
        """Process a file with rate limiting control."""
        nonlocal gemini_count_this_minute, current_minute
        
        async with semaphore:
            # Check Gemini availability with lock to ensure thread safety
            async with gemini_lock:
                # Check current minute
                now = datetime.now(timezone.utc)
                minute_str = now.strftime("%Y-%m-%d %H:%M")
                
                # If minute changed, reset counter
                if current_minute != minute_str:
                    current_minute = minute_str
                    gemini_count_this_minute = 0
                    logger.debug(f"New minute: {minute_str}, reset Gemini counter")
                
                # Check Gemini availability before processing
                gemini_available, gemini_reason = await check_gemini_available()
                
                if not gemini_available:
                    # Rate limit reached, wait for next minute
                    logger.info(f"Gemini rate limit reached, waiting for next minute")
                    await _wait_for_next_minute()
                    # Reset counter after waiting
                    current_minute = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                    gemini_count_this_minute = 0
                    # Re-check availability after waiting
                    gemini_available, _ = await check_gemini_available()
                    if not gemini_available:
                        logger.warning(f"Gemini still unavailable after waiting, will use GPT-4o-mini")
            
            # Process the file (outside lock to avoid blocking)
            await _process_single_receipt(file, results, index)
            
            # Track if Gemini was used (check result)
            async with gemini_lock:
                if results[index] and results[index].get("llm_provider") == "gemini":
                    gemini_count_this_minute += 1
                    logger.debug(f"Gemini used for {file.filename}, count this minute: {gemini_count_this_minute}/15")
    
    # Create tasks for all files
    tasks = [
        process_with_rate_limiting(file, i)
        for i, file in enumerate(valid_files)
    ]
    
    # Wait for all tasks to complete
    await asyncio.gather(*tasks)
    
    # Compile results
    successful = sum(1 for r in results if r and r.get("success", False))
    failed = len(results) - successful
    
    logger.info(f"Bulk processing completed: {successful} successful, {failed} failed out of {len(valid_files)} files")
    
    return {
        "success": True,
        "total": total_files,
        "processed": len(valid_files),
        "successful": successful,
        "failed": failed,
        "results": results
    }
