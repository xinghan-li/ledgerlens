"""
Workflow Processor: 完整的收据处理流程。

流程：
1. Google Document AI OCR
2. 根据 Gemini 限流决定使用 Gemini 还是 GPT-4o-mini
3. LLM 处理得到结构化 JSON
4. Sum check
5. 如果失败，引入 AWS OCR + GPT-4o-mini 二次处理
6. 文件存储和时间线记录
7. 统计更新
"""
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime, timezone
import json
from pathlib import Path
import asyncio

from .documentai_client import parse_receipt_documentai
from .textract_client import parse_receipt_textract
from .gemini_rate_limiter import check_gemini_available, record_gemini_request
from .receipt_llm_processor import process_receipt_with_llm_from_ocr
from .sum_checker import check_receipt_sums, apply_field_conflicts_resolution
from .llm_client import parse_receipt_with_llm
from .prompt_manager import format_prompt, get_default_prompt
from .config import settings
from .statistics_manager import update_statistics

logger = logging.getLogger(__name__)

# 输出目录
OUTPUT_DIR = Path(__file__).parent.parent / "output"
DEBUG_DIR = OUTPUT_DIR / "debug"
ERROR_DIR = OUTPUT_DIR / "error"

# 确保目录存在
OUTPUT_DIR.mkdir(exist_ok=True)
DEBUG_DIR.mkdir(exist_ok=True)
ERROR_DIR.mkdir(exist_ok=True)


class TimelineRecorder:
    """记录处理流程的时间线。"""
    
    def __init__(self, receipt_id: str):
        self.receipt_id = receipt_id
        self.timeline: List[Dict[str, Any]] = []
        self._start_times: Dict[str, datetime] = {}
    
    def start(self, step: str):
        """记录步骤开始时间。"""
        now = datetime.now(timezone.utc)
        self._start_times[step] = now
        self.timeline.append({
            "step": f"{step}_start",
            "timestamp": now.isoformat(),
            "duration_ms": None
        })
        logger.debug(f"Timeline: {step} started at {now.isoformat()}")
    
    def end(self, step: str):
        """记录步骤结束时间。"""
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
        """转换为字典格式。"""
        return {
            "receipt_id": self.receipt_id,
            "timeline": self.timeline
        }


def generate_receipt_id() -> str:
    """生成收据 ID（格式：001_mmyydd_hhmm）。"""
    now = datetime.now(timezone.utc)
    # 使用序号（暂时用时间戳，未来可以改为数据库自增）
    seq = now.strftime("%H%M%S")[-6:]  # 使用秒的后6位作为序号
    date_time = now.strftime("%m%d%y_%H%M")
    return f"{seq}_{date_time}"


async def process_receipt_workflow(
    image_bytes: bytes,
    filename: str,
    mime_type: str = "image/jpeg"
) -> Dict[str, Any]:
    """
    完整的收据处理流程。
    
    Args:
        image_bytes: 图片字节
        filename: 文件名
        mime_type: MIME 类型
        
    Returns:
        处理结果字典
    """
    receipt_id = generate_receipt_id()
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
            # Fallback 到 AWS OCR
            return await _fallback_to_aws_ocr(image_bytes, filename, receipt_id, timeline, error=f"Google OCR failed: {e}")
        
        # 保存 Google OCR 结果（暂时不保存，等需要时再保存）
        google_ocr_data = google_ocr_result
        
        # Step 2: 决定使用哪个 LLM
        gemini_available, gemini_reason = await check_gemini_available()
        
        if gemini_available:
            # 使用 Gemini
            llm_provider = "gemini"
            request_info = await record_gemini_request()
            logger.info(f"Using Gemini LLM (request {request_info['count_this_minute']} this minute)")
        else:
            # 使用 GPT-4o-mini
            llm_provider = "openai"
            logger.info(f"Using GPT-4o-mini LLM (Gemini unavailable: {gemini_reason})")
        
        # Step 3: LLM 处理
        timeline.start(f"{llm_provider}_llm")
        try:
            first_llm_result = process_receipt_with_llm_from_ocr(
                ocr_result=google_ocr_data,
                merchant_name=None,
                ocr_provider="google_documentai",
                llm_provider=llm_provider
            )
            timeline.end(f"{llm_provider}_llm")
        except Exception as e:
            timeline.end(f"{llm_provider}_llm")
            logger.error(f"{llm_provider.upper()} LLM failed: {e}")
            # Fallback 到另一个 LLM
            return await _fallback_to_other_llm(
                google_ocr_data, filename, receipt_id, timeline, 
                failed_provider=llm_provider, error=str(e)
            )
        
        # Step 4: Sum check
        timeline.start("sum_check")
        sum_check_passed, sum_check_details = check_receipt_sums(first_llm_result)
        timeline.end("sum_check")
        
        # Step 5: 处理结果
        if sum_check_passed:
            # Sum check 通过
            field_conflicts = first_llm_result.get("tbd", {}).get("field_conflicts", {})
            
            if not field_conflicts:
                # 完全通过，直接返回
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
                # Sum check 通过但有 field_conflicts，应用解决方案
                resolved_result = apply_field_conflicts_resolution(first_llm_result)
                timeline.start("save_output")
                await _save_output(receipt_id, resolved_result, timeline, google_ocr_data)
                timeline.end("save_output")
                
                # 更新统计
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
            # Sum check 失败，引入 AWS OCR + GPT-4o-mini 二次处理
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
        
        # 更新统计（错误）
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
    """使用 AWS OCR + GPT-4o-mini 进行二次处理。"""
    # Step 1: AWS OCR
    timeline.start("aws_ocr")
    try:
        aws_ocr_result = parse_receipt_textract(image_bytes)
        timeline.end("aws_ocr")
    except Exception as e:
        timeline.end("aws_ocr")
        logger.error(f"AWS OCR failed: {e}")
        # AWS OCR 也失败，标记为需要人工检查
        return await _mark_for_manual_review(
            receipt_id=receipt_id,
            timeline=timeline,
            google_ocr_data=google_ocr_data,
            first_llm_result=first_llm_result,
            sum_check_details=sum_check_details,
            error=f"AWS OCR failed: {e}"
        )
    
    # Step 2: GPT-4o-mini 二次处理
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
    
    # Step 3: 再次 sum check
    timeline.start("backup_sum_check")
    backup_sum_check_passed, backup_sum_check_details = check_receipt_sums(backup_llm_result)
    timeline.end("backup_sum_check")
    
    if backup_sum_check_passed:
        # 备份检查通过
        timeline.start("save_output")
        await _save_output(receipt_id, backup_llm_result, timeline, google_ocr_data)
        timeline.end("save_output")
        
        # 保存 debug 文件
        await _save_debug_files(
            receipt_id, google_ocr_data, aws_ocr_result,
            first_llm_result, backup_llm_result, image_bytes, filename
        )
        
        # 更新统计（GPT-4o-mini 通过）
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
        # 备份检查也失败，标记为需要人工检查
        # 更新统计（GPT-4o-mini 失败，需要人工检查）
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
    """使用 GPT-4o-mini 进行二次处理，修正 sum check 错误。"""
    # 构建 prompt
    prompt = _build_backup_prompt(google_ocr_data, aws_ocr_data, first_llm_result, sum_check_details)
    
    # 获取默认 prompt 配置
    prompt_config = get_default_prompt()
    system_message = prompt_config.get("system_message", "")
    
    # 调用 GPT-4o-mini（同步调用，因为已经在 async 函数中）
    # 注意：这里使用 run_in_executor 来避免阻塞事件循环
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
    """构建 GPT-4o-mini 二次处理的 prompt。"""
    google_raw_text = google_ocr_data.get("raw_text", "")
    aws_raw_text = aws_ocr_data.get("raw_text", "")
    first_llm_json = json.dumps(first_llm_result, indent=2, ensure_ascii=False)
    sum_check_json = json.dumps(sum_check_details, indent=2, ensure_ascii=False)
    
    prompt = f"""You are a receipt parsing expert. A previous attempt to parse a receipt failed the sum check.

## Google OCR Raw Text:
{google_raw_text[:2000]}  # 限制长度

## AWS OCR Raw Text (Second Opinion):
{aws_raw_text[:2000]}  # 限制长度

## Previous LLM Result (Failed Sum Check):
{first_llm_json}

## Sum Check Failure Details:
{sum_check_json}

## Your Task:
1. Analyze both OCR raw texts and the previous LLM result
2. Identify where the errors might be (missing items, incorrect prices, wrong calculations)
3. Correct the errors to make the sum check pass:
   - sum(line_total) ≈ subtotal (tolerance: ±0.03)
   - subtotal + tax ≈ total (tolerance: ±0.03)
4. Output the corrected JSON following the same schema
5. In the "tbd" field, provide detailed explanation:
   - What errors you found
   - What you corrected
   - Why you made those corrections
   - Any remaining uncertainties

## Important:
- If you cannot fix the errors, set a flag in tbd indicating manual review is needed
- Be precise with numbers - ensure all calculations match
- Preserve all correct information from the previous result

Output the corrected JSON now:"""
    
    return prompt


async def _fallback_to_aws_ocr(
    image_bytes: bytes,
    filename: str,
    receipt_id: str,
    timeline: TimelineRecorder,
    error: str
) -> Dict[str, Any]:
    """Google OCR 失败，fallback 到 AWS OCR。"""
    timeline.start("aws_ocr_fallback")
    try:
        aws_ocr_result = parse_receipt_textract(image_bytes)
        timeline.end("aws_ocr_fallback")
        
        # 使用 GPT-4o-mini 处理 AWS OCR 结果
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
                
                # 更新统计
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
                # 更新统计（失败）
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
            # 更新统计（错误）
            update_statistics("openai", sum_check_passed=False, is_error=True)
            
            return await _mark_for_manual_review(
                receipt_id=receipt_id,
                timeline=timeline,
                aws_ocr_data=aws_ocr_result,
                error=f"Google OCR failed, GPT LLM also failed: {e}"
            )
    except Exception as e:
        timeline.end("aws_ocr_fallback")
        # 更新统计（错误）
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
    """第一个 LLM 失败，fallback 到另一个 LLM。"""
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
            
            # 更新统计
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
            # 更新统计（失败）
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
        # 更新统计（错误）
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
    """标记为需要人工检查，保存所有相关文件。"""
    # 保存 debug 文件
    await _save_debug_files(
        receipt_id, google_ocr_data, aws_ocr_data,
        first_llm_result, backup_llm_result, image_bytes, filename
    )
    
    # 保存时间线
    timeline.start("save_timeline")
    timeline_path = DEBUG_DIR / f"{receipt_id}_timeline.json"
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(timeline.to_dict(), f, indent=2, ensure_ascii=False)
    timeline.end("save_timeline")
    
    # 构建需要人工检查的结果
    manual_review_result = {
        "status": "needs_manual_review",
        "receipt_id": receipt_id,
        "error": error,
        "sum_check": sum_check_details,
        "backup_sum_check": backup_sum_check_details,
        "first_llm_result": first_llm_result,
        "backup_llm_result": backup_llm_result
    }
    
    # 如果 backup_llm_result 存在，使用它作为最终结果（即使 sum check 失败）
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
    ocr_data: Optional[Dict[str, Any]] = None
):
    """保存最终输出文件。"""
    # 保存 output JSON
    output_path = OUTPUT_DIR / f"{receipt_id}_output.json"
    output_data = {
        "receipt_id": receipt_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": llm_result
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    # 保存时间线
    timeline_path = OUTPUT_DIR / f"{receipt_id}_timeline.json"
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(timeline.to_dict(), f, indent=2, ensure_ascii=False)


async def _save_debug_files(
    receipt_id: str,
    google_ocr_data: Optional[Dict[str, Any]],
    aws_ocr_data: Optional[Dict[str, Any]],
    first_llm_result: Optional[Dict[str, Any]],
    backup_llm_result: Optional[Dict[str, Any]],
    image_bytes: Optional[bytes],
    filename: Optional[str]
):
    """保存 debug 文件（当需要人工检查时）。"""
    if google_ocr_data:
        path = DEBUG_DIR / f"{receipt_id}_google_ocr.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(google_ocr_data, f, indent=2, ensure_ascii=False)
    
    if aws_ocr_data:
        path = DEBUG_DIR / f"{receipt_id}_aws_ocr.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(aws_ocr_data, f, indent=2, ensure_ascii=False)
    
    if first_llm_result:
        # 判断是 Gemini 还是 GPT
        llm_provider = first_llm_result.get("_metadata", {}).get("llm_provider", "unknown")
        if llm_provider == "gemini":
            path = DEBUG_DIR / f"{receipt_id}_gemini_llm.json"
        else:
            path = DEBUG_DIR / f"{receipt_id}_gpt_llm.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(first_llm_result, f, indent=2, ensure_ascii=False)
    
    if backup_llm_result:
        path = DEBUG_DIR / f"{receipt_id}_gpt_llm.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(backup_llm_result, f, indent=2, ensure_ascii=False)
    
    if image_bytes and filename:
        # 保存原始图片
        ext = Path(filename).suffix or ".jpg"
        path = DEBUG_DIR / f"{receipt_id}_original{ext}"
        with open(path, "wb") as f:
            f.write(image_bytes)


async def _save_error(
    receipt_id: str,
    timeline: TimelineRecorder,
    error: str,
    filename: Optional[str] = None
):
    """保存错误信息到 error 文件夹。"""
    error_data = {
        "receipt_id": receipt_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": error,
        "filename": filename,
        "timeline": timeline.to_dict()
    }
    
    error_path = ERROR_DIR / f"{receipt_id}_error.json"
    with open(error_path, "w", encoding="utf-8") as f:
        json.dump(error_data, f, indent=2, ensure_ascii=False)
    
    # 保存时间线
    timeline_path = ERROR_DIR / f"{receipt_id}_timeline.json"
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(timeline.to_dict(), f, indent=2, ensure_ascii=False)
