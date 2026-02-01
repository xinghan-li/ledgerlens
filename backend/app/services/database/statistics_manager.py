"""
Statistics Manager: Record API calls for OCR and LLM.

Records each API call to api_calls table for future analytics.
"""
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import logging
from .supabase_client import _get_client

logger = logging.getLogger(__name__)


def record_api_call(
    call_type: str,  # 'ocr' | 'llm'
    provider: str,  # google_documentai, aws_textract, gemini, openai
    receipt_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    status: str = "success",  # success | failed
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    request_metadata: Optional[Dict[str, Any]] = None,
    response_metadata: Optional[Dict[str, Any]] = None
):
    """
    Record an API call to api_calls table.
    
    Args:
        call_type: 'ocr' or 'llm'
        provider: Provider name (google_documentai, aws_textract, gemini, openai)
        receipt_id: Optional receipt ID (UUID string)
        duration_ms: Duration in milliseconds
        status: 'success' or 'failed'
        error_code: Error code if failed
        error_message: Error message if failed
        request_metadata: Optional request metadata (jsonb)
        response_metadata: Optional response metadata (jsonb)
    """
    try:
        supabase = _get_client()
        
        insert_data = {
            "call_type": call_type,
            "provider": provider,
            "receipt_id": receipt_id,
            "duration_ms": duration_ms,
            "status": status,
            "error_code": error_code,
            "error_message": error_message,
            "request_metadata": request_metadata,
            "response_metadata": response_metadata,
        }
        
        supabase.table("api_calls").insert(insert_data).execute()
        logger.debug(f"Recorded {call_type} call: {provider}, status: {status}")
    
    except Exception as e:
        logger.error(f"Failed to record API call: {e}", exc_info=True)
        # Don't raise exception to avoid affecting main workflow


def update_statistics(
    llm_provider: str,
    sum_check_passed: bool,
    is_error: bool = False,
    is_manual_review: bool = False
):
    """
    DEPRECATED: This function is kept for backward compatibility.
    
    TODO: 需要确认是否还需要这个函数，或者完全用record_api_call替代？
    新的api_calls表记录每次调用，可以通过查询来生成统计。
    
    Args:
        llm_provider: "gemini" or "openai" (GPT-4o-mini)
        sum_check_passed: Whether sum check passed
        is_error: Whether it's an error return
        is_manual_review: Whether manual review is needed
    """
    # For now, just log a warning
    logger.warning("update_statistics is deprecated. Use record_api_call instead.")
    # TODO: 可以在这里调用record_api_call，但需要receipt_id和duration_ms参数
