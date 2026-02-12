"""
Receipt Categorizer

主要功能：
1. 读取 receipt_processing_runs.output_payload
2. 标准化商品名、品牌、分类
3. 更新 catalog (products, brands, categories)
4. 保存到 receipt_items, receipt_summaries
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from ..database.supabase_client import (
    _get_client,
    save_receipt_summary,
    save_receipt_items
)

logger = logging.getLogger(__name__)


def can_categorize_receipt(receipt_id: str) -> Tuple[bool, str]:
    """
    检查小票是否可以被 categorize
    
    条件：
    1. Receipt 必须存在
    2. Current_status 必须是 'success' (通过了 sum check)
    3. 必须有 receipt_processing_runs 记录
    4. output_payload 必须有效
    
    Returns:
        (可以 categorize, 原因)
    """
    supabase = _get_client()
    
    try:
        # 检查 receipt 状态
        receipt = supabase.table("receipts")\
            .select("id, user_id, current_status, current_stage")\
            .eq("id", receipt_id)\
            .single()\
            .execute()
        
        if not receipt.data:
            return False, f"Receipt {receipt_id} not found"
        
        receipt_data = receipt.data
        
        # 必须是 success 状态
        if receipt_data.get("current_status") != "success":
            return False, f"Receipt status is '{receipt_data.get('current_status')}', must be 'success'"
        
        # 检查是否有 processing run
        runs = supabase.table("receipt_processing_runs")\
            .select("id, stage, status, output_payload")\
            .eq("receipt_id", receipt_id)\
            .eq("stage", "llm")\
            .eq("status", "pass")\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()
        
        if not runs.data:
            return False, "No successful LLM processing run found"
        
        run_data = runs.data[0]
        output_payload = run_data.get("output_payload")
        
        if not output_payload:
            return False, "output_payload is empty"
        
        # 检查必需字段
        if "receipt" not in output_payload or "items" not in output_payload:
            return False, "output_payload missing 'receipt' or 'items' fields"
        
        return True, "OK"
        
    except Exception as e:
        logger.error(f"Error checking receipt {receipt_id}: {e}")
        return False, f"Error: {str(e)}"


def categorize_receipt(receipt_id: str, force: bool = False) -> Dict[str, Any]:
    """
    对小票进行分类和标准化
    
    Args:
        receipt_id: Receipt ID (UUID string)
        force: 如果为 True，即使已经 categorize 过也重新处理
        
    Returns:
        {
            "success": bool,
            "receipt_id": str,
            "summary_id": str or None,
            "items_count": int,
            "message": str
        }
    """
    logger.info(f"Starting categorization for receipt {receipt_id} (force={force})")
    
    supabase = _get_client()
    
    # 1. 检查是否可以 categorize
    can_categorize, reason = can_categorize_receipt(receipt_id)
    if not can_categorize:
        logger.warning(f"Cannot categorize receipt {receipt_id}: {reason}")
        return {
            "success": False,
            "receipt_id": receipt_id,
            "message": f"Cannot categorize: {reason}"
        }
    
    # 2. 检查是否已经 categorize 过
    if not force:
        existing_summary = supabase.table("receipt_summaries")\
            .select("id")\
            .eq("receipt_id", receipt_id)\
            .execute()
        
        if existing_summary.data:
            logger.info(f"Receipt {receipt_id} already categorized")
            return {
                "success": True,
                "receipt_id": receipt_id,
                "message": "Already categorized (use force=true to re-categorize)"
            }
    
    # 3. 读取 receipt 和 processing run
    receipt = supabase.table("receipts")\
        .select("id, user_id")\
        .eq("id", receipt_id)\
        .single()\
        .execute()
    
    user_id = receipt.data.get("user_id")
    
    run = supabase.table("receipt_processing_runs")\
        .select("output_payload")\
        .eq("receipt_id", receipt_id)\
        .eq("stage", "llm")\
        .eq("status", "pass")\
        .order("created_at", desc=True)\
        .limit(1)\
        .single()\
        .execute()
    
    output_payload = run.data.get("output_payload", {})
    receipt_data = output_payload.get("receipt", {})
    items_data = output_payload.get("items", [])
    
    logger.info(f"Retrieved output_payload: {len(items_data)} items")
    
    # 4. 如果 force=True，删除旧数据
    if force:
        try:
            supabase.table("receipt_items").delete().eq("receipt_id", receipt_id).execute()
            supabase.table("receipt_summaries").delete().eq("receipt_id", receipt_id).execute()
            logger.info(f"Deleted existing categorization data for {receipt_id}")
        except Exception as e:
            logger.warning(f"Failed to delete old data: {e}")
    
    # 5. 保存 receipt_summary
    summary_id = None
    try:
        summary_id = save_receipt_summary(
            receipt_id=receipt_id,
            user_id=user_id,
            receipt_data=receipt_data
        )
        logger.info(f"✅ Saved receipt_summary: {summary_id}")
    except Exception as e:
        logger.error(f"❌ Failed to save receipt_summary: {e}")
        return {
            "success": False,
            "receipt_id": receipt_id,
            "message": f"Failed to save summary: {str(e)}"
        }
    
    # 6. 保存 receipt_items
    item_ids = []
    try:
        item_ids = save_receipt_items(
            receipt_id=receipt_id,
            user_id=user_id,
            items_data=items_data
        )
        logger.info(f"✅ Saved {len(item_ids)} receipt_items")
    except Exception as e:
        logger.error(f"❌ Failed to save receipt_items: {e}")
        # 如果 items 保存失败，回滚 summary
        try:
            supabase.table("receipt_summaries").delete().eq("id", summary_id).execute()
        except Exception as rollback_error:
            logger.warning(f"Failed to rollback summary {summary_id}: {rollback_error}")
        return {
            "success": False,
            "receipt_id": receipt_id,
            "message": f"Failed to save items: {str(e)}"
        }
    
    # 7. 返回成功结果
    result = {
        "success": True,
        "receipt_id": receipt_id,
        "summary_id": summary_id,
        "items_count": len(item_ids),
        "message": "Categorization completed successfully"
    }
    
    logger.info(f"✅ Categorization completed: {result}")
    return result


def categorize_receipts_batch(
    receipt_ids: List[str],
    force: bool = False
) -> Dict[str, Any]:
    """
    批量 categorize 多张小票
    
    Args:
        receipt_ids: List of receipt IDs
        force: 如果为 True，重新处理已经 categorize 过的
        
    Returns:
        {
            "success": int,
            "failed": int,
            "results": List[Dict]
        }
    """
    logger.info(f"Starting batch categorization for {len(receipt_ids)} receipts")
    
    results = []
    success_count = 0
    failed_count = 0
    
    for receipt_id in receipt_ids:
        try:
            result = categorize_receipt(receipt_id, force=force)
            results.append(result)
            
            if result.get("success"):
                success_count += 1
            else:
                failed_count += 1
        except Exception as e:
            logger.error(f"Error categorizing {receipt_id}: {e}")
            results.append({
                "success": False,
                "receipt_id": receipt_id,
                "message": f"Error: {str(e)}"
            })
            failed_count += 1
    
    summary = {
        "total": len(receipt_ids),
        "success": success_count,
        "failed": failed_count,
        "results": results
    }
    
    logger.info(f"Batch categorization completed: {success_count} success, {failed_count} failed")
    return summary
