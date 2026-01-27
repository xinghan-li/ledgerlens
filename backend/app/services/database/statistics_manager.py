"""
Statistics Manager: Manage statistics for LLM calls.

Update statistics table once per day, record accuracy rates for Gemini and GPT-4o-mini.
"""
from datetime import datetime, timezone, date
from typing import Dict, Any, Optional
import logging
from .supabase_client import _get_client

logger = logging.getLogger(__name__)


def update_statistics(
    llm_provider: str,
    sum_check_passed: bool,
    is_error: bool = False,
    is_manual_review: bool = False
):
    """
    Update statistics.
    
    Args:
        llm_provider: "gemini" or "openai" (GPT-4o-mini)
        sum_check_passed: Whether sum check passed
        is_error: Whether it's an error return
        is_manual_review: Whether manual review is needed
    """
    try:
        supabase = _get_client()
        today = date.today()
        
        # Get or create today's statistics record
        res = supabase.table("llm_statistics").select("*").eq("date", today.isoformat()).execute()
        
        if res.data and len(res.data) > 0:
            # Update existing record
            stats = res.data[0]
            stats_id = stats["id"]
            
            # Update corresponding LLM statistics
            if llm_provider.lower() == "gemini":
                gemini_total = stats.get("gemini_total_calls", 0) + 1
                gemini_passed = stats.get("gemini_sum_check_passed", 0)
                if sum_check_passed:
                    gemini_passed += 1
                
                gemini_accuracy = gemini_passed / gemini_total if gemini_total > 0 else 0.0
                
                update_data = {
                    "gemini_total_calls": gemini_total,
                    "gemini_sum_check_passed": gemini_passed,
                    "gemini_accuracy": round(gemini_accuracy, 4)
                }
            else:
                # GPT-4o-mini
                gpt_total = stats.get("gpt_total_calls", 0) + 1
                gpt_passed = stats.get("gpt_sum_check_passed", 0)
                if sum_check_passed:
                    gpt_passed += 1
                
                gpt_accuracy = gpt_passed / gpt_total if gpt_total > 0 else 0.0
                
                update_data = {
                    "gpt_total_calls": gpt_total,
                    "gpt_sum_check_passed": gpt_passed,
                    "gpt_accuracy": round(gpt_accuracy, 4)
                }
            
            # Update error and manual review counts
            if is_error:
                update_data["error_count"] = stats.get("error_count", 0) + 1
            if is_manual_review:
                update_data["manual_review_count"] = stats.get("manual_review_count", 0) + 1
            
            # Execute update
            supabase.table("llm_statistics").update(update_data).eq("id", stats_id).execute()
            logger.debug(f"Updated statistics for {today}: {update_data}")
        else:
            # Create new record
            if llm_provider.lower() == "gemini":
                insert_data = {
                    "date": today.isoformat(),
                    "gemini_total_calls": 1,
                    "gemini_sum_check_passed": 1 if sum_check_passed else 0,
                    "gemini_accuracy": 1.0 if sum_check_passed else 0.0,
                    "gpt_total_calls": 0,
                    "gpt_sum_check_passed": 0,
                    "gpt_accuracy": 0.0,
                    "error_count": 1 if is_error else 0,
                    "manual_review_count": 1 if is_manual_review else 0
                }
            else:
                insert_data = {
                    "date": today.isoformat(),
                    "gemini_total_calls": 0,
                    "gemini_sum_check_passed": 0,
                    "gemini_accuracy": 0.0,
                    "gpt_total_calls": 1,
                    "gpt_sum_check_passed": 1 if sum_check_passed else 0,
                    "gpt_accuracy": 1.0 if sum_check_passed else 0.0,
                    "error_count": 1 if is_error else 0,
                    "manual_review_count": 1 if is_manual_review else 0
                }
            
            supabase.table("llm_statistics").insert(insert_data).execute()
            logger.info(f"Created new statistics record for {today}")
    
    except Exception as e:
        logger.error(f"Failed to update statistics: {e}", exc_info=True)
        # Don't raise exception to avoid affecting main workflow


def get_statistics(date_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get statistics.
    
    Args:
        date_str: Date string (YYYY-MM-DD), if None then get today's
        
    Returns:
        Statistics information dictionary
    """
    try:
        supabase = _get_client()
        target_date = date_str or date.today().isoformat()
        
        res = supabase.table("llm_statistics").select("*").eq("date", target_date).execute()
        
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
        return None
