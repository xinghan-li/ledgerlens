"""
Statistics Manager: 管理 LLM 调用的统计信息。

每天更新一次统计表，记录 Gemini 和 GPT-4o-mini 的正确率。
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
    更新统计信息。
    
    Args:
        llm_provider: "gemini" 或 "openai" (GPT-4o-mini)
        sum_check_passed: sum check 是否通过
        is_error: 是否是错误返回
        is_manual_review: 是否需要人工检查
    """
    try:
        supabase = _get_client()
        today = date.today()
        
        # 获取或创建今天的统计记录
        res = supabase.table("llm_statistics").select("*").eq("date", today.isoformat()).execute()
        
        if res.data and len(res.data) > 0:
            # 更新现有记录
            stats = res.data[0]
            stats_id = stats["id"]
            
            # 更新对应 LLM 的统计
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
            
            # 更新错误和人工检查计数
            if is_error:
                update_data["error_count"] = stats.get("error_count", 0) + 1
            if is_manual_review:
                update_data["manual_review_count"] = stats.get("manual_review_count", 0) + 1
            
            # 执行更新
            supabase.table("llm_statistics").update(update_data).eq("id", stats_id).execute()
            logger.debug(f"Updated statistics for {today}: {update_data}")
        else:
            # 创建新记录
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
        # 不抛出异常，避免影响主流程


def get_statistics(date_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    获取统计信息。
    
    Args:
        date_str: 日期字符串（YYYY-MM-DD），如果为 None 则获取今天的
        
    Returns:
        统计信息字典
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
