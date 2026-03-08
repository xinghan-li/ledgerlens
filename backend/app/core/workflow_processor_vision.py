"""
Vision-First Receipt Processing Pipeline — Route B

Flow:
1. Duplicate / rate-limit / user checks  (mirrors legacy)
2. Create receipt_status row with pipeline_version='vision_b'
3. PRIMARY: Gemini vision call → structured JSON
4. If familiar store (e.g. Costco, Trader Joe's): optional Vision 2 (store-specific second round)
5. Backend sum check + item count check (independent of model self-report)
6. If PASS → save, categorize; if model set needs_review (e.g. item count only) → needs_review, no escalation.
7. If FAIL → ESCALATION: Gemini only (e.g. Gemini 2.5 Pro). If still wrong → needs_review (ask user).
8. Shadow legacy runs in background for A/B comparison (optional).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import settings
from ..processors.core.sum_checker import check_receipt_sums
from ..processors.enrichment.address_matcher import correct_address
from ..services.categorization.receipt_categorizer import categorize_receipt
from ..services.database.supabase_client import (
    USER_CLASS_ADMIN,
    append_workflow_step,
    check_duplicate_by_hash,
    check_user_locked,
    create_receipt,
    get_store_chain,
    get_test_user_id,
    get_user_class,
    save_processing_run,
    update_receipt_file_url,
    update_receipt_status,
)
from ..services.database.statistics_manager import record_api_call
from ..services.llm.gemini_client import (
    is_image_receipt_like,
    parse_receipt_with_gemini_vision_escalation,
)
from ..services.ocr.documentai_client import parse_receipt_documentai
from ..services.llm.receipt_llm_processor import (
    process_receipt_with_llm_from_docai,
    _is_costco_usa_receipt,
    _items_has_negative_line_total,
    _is_trader_joes_receipt,
    _has_item_count_mismatch,
    _detect_cc_rewards_and_fix_totals,
    run_costco_second_round,
    run_trader_joes_second_round,
)
# ---------------------------------------------------------------------------
# File system helpers (inlined from former workflow_common.py)
# ---------------------------------------------------------------------------
# workflow_processor_vision.py -> core -> app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = PROJECT_ROOT / "output"
INPUT_ROOT = PROJECT_ROOT / "input"

OUTPUT_ROOT.mkdir(exist_ok=True)
INPUT_ROOT.mkdir(exist_ok=True)


def _fail_output_payload(error_message: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Standard JSON output_payload when a stage fails."""
    return {"error": error_message, "reason": reason or error_message}


class TimelineRecorder:
    """Record timeline of processing workflow."""

    def __init__(self, receipt_id: str):
        self.receipt_id = receipt_id
        self.timeline: List[Dict[str, Any]] = []
        self._start_times: Dict[str, datetime] = {}

    def start(self, step: str):
        now = datetime.now(timezone.utc)
        self._start_times[step] = now
        self.timeline.append({
            "step": f"{step}_start",
            "timestamp": now.isoformat(),
            "duration_ms": None
        })

    def end(self, step: str):
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
        return {
            "receipt_id": self.receipt_id,
            "timeline": self.timeline
        }


def generate_receipt_id(filename: Optional[str] = None) -> str:
    """Generate receipt ID (format: seq_mmddyy_hhmm_filename)."""
    now = datetime.now(timezone.utc)
    seq = now.strftime("%H%M%S") + str(now.microsecond)[-2:]
    date_time = now.strftime("%m%d%y_%H%M")
    if filename:
        clean_name = Path(filename).stem
        clean_name = re.sub(r'[^\w\-_]', '_', clean_name)
        clean_name = clean_name[:20]
        if clean_name:
            return f"{seq}_{date_time}_{clean_name}"
    return f"{seq}_{date_time}"


def get_date_folder_name(receipt_id: Optional[str] = None) -> str:
    """Get date folder name in format YYYYMMDD from receipt_id or current date."""
    if receipt_id:
        match = re.search(r'_(\d{2})(\d{2})(\d{2})_', receipt_id)
        if match:
            month, day, year_2digit = match.group(1), match.group(2), match.group(3)
            return f"20{year_2digit}{month}{day}"
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _get_duration_from_timeline(timeline: "TimelineRecorder", step_name: str) -> Optional[int]:
    """Get duration in milliseconds for a step from timeline."""
    for entry in timeline.timeline:
        if entry.get("step") == f"{step_name}_end":
            return entry.get("duration_ms")
    return None


def get_output_paths_for_receipt(receipt_id: str, date_folder: Optional[str] = None) -> Dict[str, Path]:
    """Get all output paths for a receipt (date_dir, json_file, timeline_dir, etc.)."""
    if date_folder is None:
        date_folder = get_date_folder_name(receipt_id)
    date_dir = OUTPUT_ROOT / date_folder
    return {
        "date_dir": date_dir,
        "json_file": date_dir / f"{receipt_id}_output.json",
        "timeline_dir": date_dir / "timeline",
        "timeline_file": date_dir / "timeline" / f"{receipt_id}_timeline.json",
        "csv_file": date_dir / f"{date_folder}.csv",
        "debug_dir": date_dir / "debug-001",
        "error_dir": date_dir / "error-001"
    }


def _save_image_for_manual_review(
    receipt_id: str,
    image_bytes: bytes,
    filename: str
) -> Optional[str]:
    """Save image for manual review; return relative path from project root or None."""
    try:
        paths = get_output_paths_for_receipt(receipt_id)
        paths["error_dir"].mkdir(parents=True, exist_ok=True)
        file_ext = Path(filename).suffix.lower() if filename else ".jpg"
        if file_ext not in [".jpg", ".jpeg", ".png"]:
            file_ext = ".jpg"
        image_file = paths["error_dir"] / f"{receipt_id}_original{file_ext}"
        image_file.write_bytes(image_bytes)
        rel = image_file.relative_to(PROJECT_ROOT)
        logger.info("Saved image for manual review: %s", rel)
        return str(rel)
    except Exception as e:
        logger.error("Failed to save image for manual review: %s", e)
        return None


async def _save_output(
    receipt_id: str,
    llm_result: Dict[str, Any],
    timeline: TimelineRecorder,
    ocr_data: Optional[Dict[str, Any]] = None,
    user_id: str = "dummy"
):
    """Save final output JSON in output/YYYYMMDD/{receipt_id}_output.json."""
    paths = get_output_paths_for_receipt(receipt_id)
    paths["date_dir"].mkdir(parents=True, exist_ok=True)
    paths["timeline_dir"].mkdir(parents=True, exist_ok=True)
    output_data = {
        "receipt_id": receipt_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": llm_result
    }
    paths["json_file"].parent.mkdir(parents=True, exist_ok=True)
    with open(paths["json_file"], "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    logger.info("Saved output JSON: %s", paths["json_file"])
from ..prompts.prompt_loader import load_vision_primary_prompt, load_vision_escalation_template

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

# Runtime-injected date prefix — prepended before vision_primary at call time.
# This CANNOT be stored in DB because it requires today's date.
REFERENCE_DATE_INSTRUCTION = """REFERENCE DATE (today): {reference_date}. Any receipt date on or before this date is valid.

**Past-year override (important):** If the receipt shows a 2-digit year (e.g. "21" in 26/02/21 or 02/26/21) and the resulting full date would be **more than one year before** the reference date above, treat the year as the reference year. Example: receipt shows "26/02/21" (DD/MM/YY) and reference is 2026-03-07 → output purchase_date 2026-02-26, not 2021-02-26. This handles receipt printer rollover, misprints, or old paper. Otherwise use the date exactly as printed.

"""

# Primary and escalation prompts live in prompt_library (keys: 'vision_primary',
# 'vision_escalation'). Run migration 058_vision_prompts_to_library.sql to populate.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_reference_date() -> str:
    """Current date (UTC) for prompt context: any receipt date on or before this is valid."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _get_vision_primary_prompt() -> str:
    """
    Load the vision primary system prompt from prompt_library (key='vision_primary').
    Raises RuntimeError if the key is missing — run migration 058 to populate.
    """
    content = load_vision_primary_prompt()
    if content:
        return content
    raise RuntimeError(
        "prompt_library key='vision_primary' not found or inactive. "
        "Run backend/database/058_vision_prompts_to_library.sql to populate."
    )


def _get_vision_escalation_template() -> str:
    """
    Load the vision escalation prompt template from prompt_library (key='vision_escalation').
    The returned string is a Python .format() template — caller must call
    .format(reference_date=..., failure_reason=..., primary_notes=...) before use.
    Raises RuntimeError if the key is missing.
    """
    content = load_vision_escalation_template()
    if content:
        return content
    raise RuntimeError(
        "prompt_library key='vision_escalation' not found or inactive. "
        "Run backend/database/058_vision_prompts_to_library.sql to populate."
    )


def _normalize_payment_method(pm: Any) -> str:
    """Normalize payment_method: array → joined string, single string → as-is."""
    if not pm:
        return "Other"
    if isinstance(pm, list):
        return " + ".join(str(x) for x in pm if x)
    return str(pm)


def _build_failure_reason(
    sum_check_passed: bool,
    sum_check_details: Dict[str, Any],
    llm_result: Dict[str, Any],
) -> Tuple[str, str]:
    """
    Build a human-readable failure_reason string and extract primary_notes.
    Returns (failure_reason, primary_notes).
    """
    lines: List[str] = []

    if not sum_check_passed:
        errors = sum_check_details.get("errors") or []
        for err in errors:
            lines.append(f"- {err}")
        if not errors:
            lines.append("- Sum check failed (details unavailable)")

    metadata = llm_result.get("_metadata") or {}
    model_status = metadata.get("validation_status", "unknown")
    model_reasoning = metadata.get("reasoning") or ""
    model_sum_notes = metadata.get("sum_check_notes") or ""

    lines.append(f"\nPrimary model validation_status: {model_status}")
    if model_reasoning:
        lines.append(f"Primary model reasoning: {model_reasoning}")
    if model_sum_notes:
        lines.append(f"Primary model sum_check_notes: {model_sum_notes}")

    ic_check = sum_check_details.get("item_count_check")
    if ic_check and not ic_check.get("passed"):
        lines.append(
            f"\nItem count mismatch: receipt states {ic_check.get('expected')} items, "
            f"extracted {ic_check.get('actual')} items."
        )

    failure_reason = "\n".join(lines)
    primary_notes = (llm_result.get("tbd") or {}).get("notes") or "None"
    return failure_reason, primary_notes


# ---------------------------------------------------------------------------
# Shadow — run legacy OCR→LLM pipeline in background for A/B comparison
# ---------------------------------------------------------------------------

async def _run_shadow_legacy(
    image_bytes: bytes,
    mime_type: str,
    db_receipt_id: str,
) -> None:
    """
    Run the legacy OCR→LLM pipeline in background and save results under the same
    receipt_id for A/B comparison. Does NOT touch receipt_status.
    """
    try:
        # Step A1: Google OCR
        google_ocr_result = await asyncio.to_thread(
            parse_receipt_documentai, image_bytes, mime_type
        )
        save_processing_run(
            receipt_id=db_receipt_id,
            stage="shadow_legacy",
            model_provider="google_documentai",
            model_name=None,
            model_version=None,
            input_payload={"image_bytes_length": len(image_bytes), "mime_type": mime_type},
            output_payload=google_ocr_result,
            output_schema_version=None,
            status="pass",
        )
        logger.info(f"[shadow] OCR saved for {db_receipt_id}")

        # Step A2: LLM on OCR result
        llm_result = await process_receipt_with_llm_from_docai(google_ocr_result)

        # Inject raw_text for item count check consistency
        raw_text = (google_ocr_result.get("raw_text") or "")
        if raw_text:
            llm_result = {**llm_result, "raw_text": raw_text}

        sum_passed, sum_details = check_receipt_sums(llm_result)
        # Shadow legacy uses OCR + OpenAI LLM (process_receipt_with_llm_from_docai hardcodes openai)
        save_processing_run(
            receipt_id=db_receipt_id,
            stage="shadow_legacy",
            model_provider="openai",
            model_name=settings.openai_model,
            model_version=None,
            input_payload={"raw_text_length": len(raw_text)},
            output_payload={
                **llm_result,
                "_shadow_sum_check": {"passed": sum_passed, "details": sum_details},
            },
            output_schema_version=None,
            status="pass",
        )
        logger.info(
            f"[shadow] LLM saved for {db_receipt_id}, sum_check_passed={sum_passed}, "
            f"items={len(llm_result.get('items') or [])}"
        )

    except Exception as exc:
        logger.warning(f"[shadow] legacy run failed for {db_receipt_id}: {exc}")


# ---------------------------------------------------------------------------
# Escalation — Gemini only (OpenAI debate deprecated)
# ---------------------------------------------------------------------------

async def _run_vision_escalation_gemini_only(
    image_bytes: bytes,
    mime_type: str,
    failure_reason: str,
    primary_notes: str,
    db_receipt_id: str,
    *,
    gemini_model: Optional[str] = None,
) -> Optional[Dict]:
    """
    Call Gemini escalation model only. Returns result or None on error.
    OpenAI was removed from vision escalation to avoid introducing errors.
    """
    escalation_prompt = _get_vision_escalation_template().format(
        reference_date=_get_reference_date(),
        failure_reason=failure_reason,
        primary_notes=primary_notes,
    )

    gemini_model = (gemini_model or "").strip() or (getattr(settings, "gemini_escalation_model", None) or "").strip() or (os.getenv("GEMINI_ESCALATION_MODEL") or "").strip()
    if not gemini_model:
        logger.info("[escalation] GEMINI_ESCALATION_MODEL not configured, skipping")
        return None
    try:
        result, usage = await parse_receipt_with_gemini_vision_escalation(
            image_bytes=image_bytes,
            instruction=escalation_prompt,
            model=gemini_model,
            mime_type=mime_type,
        )
        in_pl = {"failure_reason": failure_reason, "image_bytes_length": len(image_bytes)}
        out_pl = dict(result) if result else {}
        if usage:
            in_pl["token_usage"] = usage
            out_pl["token_usage"] = usage
        save_processing_run(
            receipt_id=db_receipt_id,
            stage="vision_escalation",
            model_provider="gemini",
            model_name=gemini_model,
            model_version=None,
            input_payload=in_pl,
            output_payload=out_pl,
            output_schema_version="vision_v1",
            status="pass",
        )
        return result
    except Exception as exc:
        logger.error(f"[escalation] Gemini failed: {exc}")
        save_processing_run(
            receipt_id=db_receipt_id,
            stage="vision_escalation",
            model_provider="gemini",
            model_name=gemini_model,
            model_version=None,
            input_payload={"failure_reason": failure_reason},
            output_payload=_fail_output_payload(str(exc)),
            output_schema_version=None,
            status="fail",
            error_message=str(exc),
        )
        return None


# ---------------------------------------------------------------------------
# Costco second-round helpers
# ---------------------------------------------------------------------------


def _resolve_costco_store_ids(
    primary_result: Dict,
) -> Tuple[Optional[str], Optional[str]]:
    """Return (chain_id, location_id) for a Costco receipt.

    Prefers the ids already stored in address-correction metadata (avoids a
    redundant store-match call and is immune to address-format edge-cases).
    Falls back to a direct ``get_store_chain`` lookup when metadata is absent.
    """
    _addr_corr = (primary_result.get("_metadata") or {}).get("address_correction") or {}
    chain_id = _addr_corr.get("chain_id")
    location_id = _addr_corr.get("location_id")
    if not chain_id:
        rec = primary_result.get("receipt") or {}
        store_match = get_store_chain(
            rec.get("merchant_name") or "",
            rec.get("merchant_address") or "",
        )
        if store_match.get("matched"):
            chain_id = store_match.get("chain_id")
            location_id = store_match.get("location_id")
    return chain_id, location_id


async def _run_and_save_costco_second_round(
    primary_result: Dict,
    chain_id: str,
    location_id: Optional[str],
    db_receipt_id: str,
    primary_run_id: Optional[str],
    trigger: str,
    image_bytes: Optional[bytes] = None,
    mime_type: str = "image/jpeg",
) -> Tuple[Optional[Dict], Optional[str]]:
    """Execute the Costco second-round LLM call and persist the processing run.

    image_bytes and mime_type are forwarded so the second-round call re-reads
    the original receipt image alongside the first-pass JSON.
    Returns ``(second_result, run_id)`` on success, or ``(None, None)`` when
    the call produced no result or the database write failed.
    """
    second_result = await run_costco_second_round(
        primary_result, chain_id, location_id, "gemini",
        image_bytes=image_bytes, mime_type=mime_type,
    )
    if not second_result:
        return None, None
    try:
        run_id = save_processing_run(
            receipt_id=db_receipt_id,
            stage="vision_store_specific",
            model_provider="gemini",
            model_name=settings.gemini_model,
            model_version="round_2",
            input_payload={
                "second_round": True,
                "trigger": trigger,
                "first_round_run_id": primary_run_id,
            },
            output_payload=second_result,
            output_schema_version="0.1",
            status="pass",
            error_message=None,
        )
        append_workflow_step(db_receipt_id, "vision_store_specific", "pass", run_id=run_id)
        logger.info(
            "[vision] Saved Costco second-round (%s) run for receipt %s: run_id=%s",
            trigger,
            db_receipt_id,
            run_id,
        )
        return second_result, run_id
    except Exception as e:
        logger.warning(
            "[vision] Failed to save Costco second-round (%s) processing run: %s",
            trigger,
            e,
        )
        return None, None


async def _run_and_save_trader_joes_second_round(
    primary_result: Dict,
    chain_id: str,
    location_id: Optional[str],
    db_receipt_id: str,
    primary_run_id: Optional[str],
    trigger: str,
    image_bytes: Optional[bytes] = None,
    mime_type: str = "image/jpeg",
) -> Tuple[Optional[Dict], Optional[str]]:
    """Execute the Trader Joe's second-round LLM call and persist the processing run.

    image_bytes and mime_type are forwarded so the second-round call re-reads
    the original receipt image alongside the first-pass JSON.
    """
    second_result = await run_trader_joes_second_round(
        primary_result, chain_id, location_id, "gemini",
        image_bytes=image_bytes, mime_type=mime_type,
    )
    if not second_result:
        return None, None
    try:
        run_id = save_processing_run(
            receipt_id=db_receipt_id,
            stage="vision_store_specific",
            model_provider="gemini",
            model_name=settings.gemini_model,
            model_version="round_2",
            input_payload={
                "second_round": True,
                "trigger": trigger,
                "first_round_run_id": primary_run_id,
            },
            output_payload=second_result,
            output_schema_version="0.1",
            status="pass",
            error_message=None,
        )
        append_workflow_step(db_receipt_id, "vision_store_specific", "pass", run_id=run_id)
        logger.info(
            "[vision] Saved Trader Joe's second-round (%s) run for receipt %s: run_id=%s",
            trigger,
            db_receipt_id,
            run_id,
        )
        return second_result, run_id
    except Exception as e:
        logger.warning(
            "[vision] Failed to save Trader Joe's second-round (%s) processing run: %s",
            trigger,
            e,
        )
        return None, None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def process_receipt_workflow_vision(
    image_bytes: bytes,
    filename: str,
    mime_type: str = "image/jpeg",
    user_id: Optional[str] = None,
    existing_receipt_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Vision-First receipt processing pipeline (Route B).

    Args:
        image_bytes: Raw image bytes
        filename: Original filename
        mime_type: MIME type (image/jpeg or image/png)
        user_id: Authenticated user ID; falls back to TEST_USER_ID if None
        existing_receipt_id: If set (e.g. user confirmed receipt), use this as receipt_id
            and db_receipt_id; skip create_receipt and duplicate check.

    Returns:
        Processing result dictionary (compatible shape with legacy workflow)
    """
    if existing_receipt_id:
        receipt_id = existing_receipt_id
    else:
        receipt_id = generate_receipt_id(filename)
    timeline = TimelineRecorder(receipt_id)

    original_file_hash = hashlib.sha256(image_bytes).hexdigest()
    file_hash = original_file_hash

    # Resolve user_id
    if user_id is None:
        user_id = get_test_user_id()

    # When re-running for an existing receipt (e.g. after user confirm), skip duplicate check and create_receipt
    db_receipt_id: Optional[str] = existing_receipt_id

    # Rate-limit / lock check
    if user_id and not existing_receipt_id:
        user_class = get_user_class(user_id)
        if user_class < USER_CLASS_ADMIN:
            locked, locked_until = check_user_locked(user_id)
            if locked:
                return {
                    "success": False,
                    "receipt_id": None,
                    "status": "locked",
                    "error": "user_locked",
                    "message": "Upload is temporarily locked. Please try again later.",
                    "locked_until": locked_until.isoformat() if locked_until else None,
                    "pipeline": "vision_b",
                }

    # Duplicate check (skip when re-running for existing receipt, e.g. after user confirm)
    if user_id and not existing_receipt_id:
        duplicate_id = check_duplicate_by_hash(file_hash, user_id)
        if duplicate_id:
            user_class = get_user_class(user_id)
            allow_dup = user_class >= USER_CLASS_ADMIN or settings.allow_duplicate_for_debug
            if allow_dup:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                file_hash = f"{original_file_hash}_debug_{timestamp}"
                logger.info(f"[vision] Duplicate allowed for {user_class}, reprocessing")
            else:
                return {
                    "success": False,
                    "receipt_id": receipt_id,
                    "status": "duplicate",
                    "error": "duplicate_receipt",
                    "message": "This receipt has already been uploaded.",
                    "existing_receipt_id": duplicate_id,
                    "pipeline": "vision_b",
                }

    # Create DB record (skip when existing_receipt_id is set)
    if user_id and not existing_receipt_id:
        try:
            db_receipt_id = create_receipt(
                user_id=user_id,
                raw_file_url=None,
                file_hash=file_hash,
                pipeline_version="vision_b",
            )
            logger.info(f"[vision] Created receipt {db_receipt_id}")
            append_workflow_step(db_receipt_id, "create_db", "ok")
        except Exception as exc:
            logger.error(f"[vision] Failed to create receipt: {exc}")
            db_receipt_id = None

    # -----------------------------------------------------------------------
    # STEP 1 — Primary vision call (Gemini)
    # -----------------------------------------------------------------------
    timeline.start("vision_primary")
    primary_result: Optional[Dict[str, Any]] = None
    primary_error: Optional[str] = None
    primary_usage: Optional[Dict[str, int]] = None
    primary_run_id: Optional[str] = None
    ran_costco_second_round = False
    ran_trader_joes_second_round = False
    try:
        primary_instruction = REFERENCE_DATE_INSTRUCTION.format(reference_date=_get_reference_date()) + _get_vision_primary_prompt()
        primary_result, primary_usage = await parse_receipt_with_gemini_vision_escalation(
            image_bytes=image_bytes,
            instruction=primary_instruction,
            model=settings.gemini_model,
            mime_type=mime_type,
        )
        timeline.end("vision_primary")

        if primary_usage:
            logger.info(
                "[vision] Primary token in=%s out=%s",
                primary_usage.get("input_tokens"),
                primary_usage.get("output_tokens"),
            )
        # Correct address with canonical DB data before saving or further processing
        if primary_result:
            primary_result = correct_address(primary_result, auto_correct=True)

        if db_receipt_id:
            primary_duration = _get_duration_from_timeline(timeline, "vision_primary")
            input_pl = {"image_bytes_length": len(image_bytes), "mime_type": mime_type}
            if primary_usage:
                input_pl["token_usage"] = primary_usage
            out_pl = dict(primary_result) if primary_result else {}
            if primary_usage:
                out_pl["token_usage"] = primary_usage
            primary_run_id = save_processing_run(
                receipt_id=db_receipt_id,
                stage="vision_primary",
                model_provider="gemini",
                model_name=settings.gemini_model,
                model_version=None,
                input_payload=input_pl,
                output_payload=out_pl,
                output_schema_version="vision_v1",
                status="pass",
            )
            record_api_call(
                call_type="llm",
                provider="gemini",
                receipt_id=db_receipt_id,
                duration_ms=int(primary_duration) if primary_duration else None,
                status="success",
            )
            append_workflow_step(db_receipt_id, "vision_primary", "pass", run_id=primary_run_id)

            # Costco second round: if any item has negative line_total, merge discounts and save round-2 run
            is_costco = _is_costco_usa_receipt(primary_result)
            has_negative = _items_has_negative_line_total(primary_result)
            logger.info(
                "[vision] Costco second-round check: is_costco=%s has_negative_item=%s items_count=%s",
                is_costco,
                has_negative,
                len(primary_result.get("items") or []),
            )
            if is_costco and has_negative:
                chain_id, location_id = _resolve_costco_store_ids(primary_result)
                logger.info(
                    "[vision] Costco store match: chain_id=%s",
                    chain_id,
                )
                if chain_id:
                    second_result, _ = await _run_and_save_costco_second_round(
                        primary_result, chain_id, location_id, db_receipt_id,
                        primary_run_id, "costco_discount_merge",
                        image_bytes=image_bytes, mime_type=mime_type,
                    )
                    if second_result:
                        primary_result = second_result
                        ran_costco_second_round = True
            # Trader Joe's second round: when item count mismatch, re-extract with item count by unit
            if not ran_costco_second_round and _is_trader_joes_receipt(primary_result) and _has_item_count_mismatch(primary_result):
                chain_id, location_id = _resolve_costco_store_ids(primary_result)
                if chain_id:
                    second_result, _ = await _run_and_save_trader_joes_second_round(
                        primary_result, chain_id, location_id, db_receipt_id,
                        primary_run_id, "trader_joes_item_count",
                        image_bytes=image_bytes, mime_type=mime_type,
                    )
                    if second_result:
                        primary_result = second_result
                        ran_trader_joes_second_round = True
            # Costco USA: use first (pre-reward) total only; if model wrote amount-after-CC-Rewards, overwrite to first total
            if primary_result:
                _detect_cc_rewards_and_fix_totals(primary_result)

    except Exception as exc:
        timeline.end("vision_primary")
        primary_error = str(exc)
        logger.error(f"[vision] Primary call failed for {receipt_id}: {exc}")

        if db_receipt_id:
            save_processing_run(
                receipt_id=db_receipt_id,
                stage="vision_primary",
                model_provider="gemini",
                model_name=settings.gemini_model,
                model_version=None,
                input_payload={"image_bytes_length": len(image_bytes), "mime_type": mime_type},
                output_payload=_fail_output_payload(str(exc)),
                output_schema_version=None,
                status="fail",
                error_message=str(exc),
            )
            append_workflow_step(db_receipt_id, "vision_primary", "fail")

    # If primary failed entirely, check if image looks like a receipt at all
    if primary_result is None:
        like_receipt = True
        try:
            like_receipt = await is_image_receipt_like(image_bytes, mime_type=mime_type)
        except Exception:
            pass

        if not like_receipt:
            if db_receipt_id:
                try:
                    update_receipt_status(
                        db_receipt_id,
                        current_status="failed",
                        current_stage="vision_primary",
                    )
                except Exception:
                    pass
            return {
                "success": False,
                "receipt_id": db_receipt_id or receipt_id,
                "status": "pending_receipt_confirm",
                "error": "not_a_receipt",
                "needs_user_confirm": True,
                "message": "This does not look like a receipt. Please confirm this is a clear photo of a receipt.",
                "pipeline": "vision_b",
            }

        # Vision model failed on what might be a valid receipt → return error
        if db_receipt_id:
            try:
                update_receipt_status(
                    db_receipt_id,
                    current_status="failed",
                    current_stage="vision_primary",
                )
                image_path = _save_image_for_manual_review(receipt_id, image_bytes, filename)
                if image_path:
                    update_receipt_file_url(db_receipt_id, image_path)
            except Exception:
                pass
        return {
            "success": False,
            "receipt_id": db_receipt_id or receipt_id,
            "status": "error",
            "error": f"Vision primary call failed: {primary_error}",
            "pipeline": "vision_b",
        }

    # -----------------------------------------------------------------------
    # STEP 2 — Backend sum check + item count check
    # -----------------------------------------------------------------------
    timeline.start("sum_check")
    sum_check_passed, sum_check_details = check_receipt_sums(primary_result)
    timeline.end("sum_check")

    # If sum check failed but we have Costco USA + store matched and did NOT run the second round yet,
    # try Costco-specific second round now. The primary may have missed negative discount lines or merged
    # them wrongly; the second round re-parses with Costco rules and can fix the totals so we avoid escalation.
    if (
        not sum_check_passed
        and db_receipt_id
        and _is_costco_usa_receipt(primary_result)
        and not ran_costco_second_round
    ):
        chain_id, location_id = _resolve_costco_store_ids(primary_result)
        if chain_id:
            logger.info(
                f"[vision] Sum check failed but Costco store matched; running Costco second round for {receipt_id}"
            )
            second_result, _ = await _run_and_save_costco_second_round(
                primary_result, chain_id, location_id, db_receipt_id,
                primary_run_id, "sum_check_fail_costco",
                image_bytes=image_bytes, mime_type=mime_type,
            )
            if second_result:
                primary_result = second_result
                ran_costco_second_round = True
                _detect_cc_rewards_and_fix_totals(primary_result)
                timeline.start("sum_check")
                sum_check_passed, sum_check_details = check_receipt_sums(primary_result)
                timeline.end("sum_check")
                logger.info(
                    f"[vision] After Costco second round: sum_check_passed={sum_check_passed}"
                )

    # Escalation only when backend sum check actually failed (numbers don't add up). Item-count mismatch
    # or model needs_review alone (e.g. receipt says 10 items, we got 9 — often deposit/fee or count difference)
    # does NOT trigger escalation; we save as needs_review for frontend and do not call stronger models.
    model_validation_status = (primary_result.get("_metadata") or {}).get("validation_status", "pass")

    logger.info(
        f"[vision] sum_check_passed={sum_check_passed}, "
        f"model_status={model_validation_status}, "
        f"items={len(primary_result.get('items') or [])}"
    )

    # -----------------------------------------------------------------------
    # STEP 3A — Backend sum check PASSED → save & categorize; escalate only when sum check fails
    # -----------------------------------------------------------------------
    if sum_check_passed:
        # Normalize payment_method
        receipt_data = primary_result.get("receipt") or {}
        receipt_data["payment_method"] = _normalize_payment_method(receipt_data.get("payment_method"))
        primary_result = {**primary_result, "receipt": receipt_data}

        # If model asked for needs_review (e.g. item count 9 vs 10) but numbers are correct: needs_review only, no escalation
        status_for_receipt = "success" if model_validation_status != "needs_review" else "needs_review"
        stage_for_receipt = "vision_store_specific" if (ran_costco_second_round or ran_trader_joes_second_round) else "vision_primary"
        if db_receipt_id:
            try:
                update_receipt_status(
                    db_receipt_id,
                    current_status=status_for_receipt,
                    current_stage=stage_for_receipt,
                )
                if status_for_receipt == "needs_review":
                    logger.info(
                        f"[vision] Backend sum check passed; model requested needs_review (e.g. item count) for {receipt_id} — not escalating"
                    )
                else:
                    logger.info(f"[vision] Updated receipt {db_receipt_id} to status=success, stage={stage_for_receipt}")
                append_workflow_step(db_receipt_id, "sum_check", "pass")
            except Exception as exc:
                logger.warning(f"[vision] Failed to update receipt status: {exc}")

            # Categorize
            try:
                logger.info(f"[vision] Calling categorize_receipt for receipt_id={db_receipt_id} (after vision_primary pass)")
                cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id)
                logger.info(f"[vision] categorize_receipt result: success={cat_result.get('success')}, message={cat_result.get('message')!r}, full={cat_result}")
                if cat_result.get("success"):
                    logger.info(f"[vision] Categorization completed for {db_receipt_id}")
                else:
                    logger.warning(f"[vision] Categorization skipped: {cat_result.get('message')}")
            except Exception as cat_err:
                logger.warning(f"[vision] Categorization failed: {cat_err}", exc_info=True)

            # Save JSON output file
            try:
                await _save_output(receipt_id, primary_result, timeline, user_id=user_id or "unknown")
            except Exception as out_err:
                logger.warning(f"[vision] Failed to save output JSON: {out_err}")

            # Fire-and-forget shadow legacy run
            asyncio.create_task(
                _run_shadow_legacy(image_bytes, mime_type, db_receipt_id)
            )

        return {
            "success": status_for_receipt == "success",
            "receipt_id": db_receipt_id or receipt_id,
            "status": "passed" if status_for_receipt == "success" else "needs_review",
            "current_stage": stage_for_receipt,
            "data": primary_result,
            "sum_check": sum_check_details,
            "pipeline": "vision_b",
        }

    # -----------------------------------------------------------------------
    # STEP 3B — Sum check FAILED → escalation
    # -----------------------------------------------------------------------
    logger.info(f"[vision] Sum check failed for {receipt_id}; escalating to strongest models")
    if db_receipt_id:
        append_workflow_step(db_receipt_id, "sum_check", "fail")
        try:
            image_path = _save_image_for_manual_review(receipt_id, image_bytes, filename)
            if image_path:
                update_receipt_file_url(db_receipt_id, image_path)
        except Exception:
            pass
        # 先写入 primary 结果到 record_summaries/record_items，避免前端在 escalation 期间显示 Unknown store / No items
        try:
            update_receipt_status(
                db_receipt_id,
                current_status="needs_review",
                current_stage="vision_primary",
            )
            logger.info(f"[vision] Set receipt {db_receipt_id} to needs_review before escalation; writing primary to record_summaries")
            await asyncio.to_thread(categorize_receipt, db_receipt_id)
        except Exception as cat_err:
            logger.warning(f"[vision] Failed to write primary result before escalation: {cat_err}")

    failure_reason, primary_notes = _build_failure_reason(
        sum_check_passed=False,
        sum_check_details=sum_check_details,
        llm_result=primary_result,
    )

    # Escalation: Gemini only (OpenAI debate deprecated)
    gemini_esc = (settings.gemini_escalation_model or "").strip() or (os.getenv("GEMINI_ESCALATION_MODEL") or "").strip()
    escalation_configured = bool(gemini_esc)

    if not escalation_configured:
        logger.warning(
            "[vision] No escalation model configured (GEMINI_ESCALATION_MODEL). "
            "Marking as needs_review without escalation."
        )
        if db_receipt_id:
            # needs_review + categorize 已在上面统一做过，此处只起 shadow
            asyncio.create_task(
                _run_shadow_legacy(image_bytes, mime_type, db_receipt_id)
            )
        receipt_data = primary_result.get("receipt") or {}
        receipt_data["payment_method"] = _normalize_payment_method(receipt_data.get("payment_method"))
        return {
            "success": False,
            "receipt_id": db_receipt_id or receipt_id,
            "status": "needs_review",
            "data": {**primary_result, "receipt": receipt_data},
            "sum_check": sum_check_details,
            "pipeline": "vision_b",
            "message": "Sum check failed and no escalation models configured.",
        }

    # -----------------------------------------------------------------------
    # STEP 4 — Escalation: Gemini only
    # -----------------------------------------------------------------------
    logger.info("[vision] Escalation: gemini=%s", gemini_esc or "(none)")
    timeline.start("vision_escalation")
    gemini_esc_result = await _run_vision_escalation_gemini_only(
        image_bytes=image_bytes,
        mime_type=mime_type,
        failure_reason=failure_reason,
        primary_notes=primary_notes,
        db_receipt_id=db_receipt_id or receipt_id,
        gemini_model=gemini_esc or None,
    )
    timeline.end("vision_escalation")

    if db_receipt_id:
        append_workflow_step(db_receipt_id, "vision_escalation", "done")

    # If escalation failed, mark needs_review with primary data
    if gemini_esc_result is None:
        logger.error(f"[vision] Escalation (Gemini) failed for {receipt_id}")
        if db_receipt_id:
            try:
                update_receipt_status(
                    db_receipt_id,
                    current_status="needs_review",
                    current_stage="vision_escalation",
                )
            except Exception:
                pass
            try:
                await asyncio.to_thread(categorize_receipt, db_receipt_id)
            except Exception:
                pass
            asyncio.create_task(
                _run_shadow_legacy(image_bytes, mime_type, db_receipt_id)
            )
        receipt_data = primary_result.get("receipt") or {}
        receipt_data["payment_method"] = _normalize_payment_method(receipt_data.get("payment_method"))
        return {
            "success": False,
            "receipt_id": db_receipt_id or receipt_id,
            "status": "needs_review",
            "data": {**primary_result, "receipt": receipt_data},
            "sum_check": sum_check_details,
            "pipeline": "vision_b",
            "message": "Escalation models both failed; manual review required.",
        }

    # -----------------------------------------------------------------------
    # STEP 4A — Escalation result sum check (Gemini only)
    # -----------------------------------------------------------------------
    best_result = gemini_esc_result
    gemini_sum_passed = False
    if gemini_esc_result is not None:
        gemini_sum_passed, _ = check_receipt_sums(gemini_esc_result)
    logger.info(f"[vision] Escalation sum check: gemini={gemini_sum_passed}")

    # Costco USA: use first (pre-reward) total only before persisting escalation result
    _detect_cc_rewards_and_fix_totals(best_result)

    # Normalize payment_method in best result
    rec = (best_result.get("receipt") or {})
    rec["payment_method"] = _normalize_payment_method(rec.get("payment_method"))
    best_result = {**best_result, "receipt": rec}

    # Correct address with canonical DB data (vision pipeline never called this before)
    best_result = correct_address(best_result, auto_correct=True)

    # -----------------------------------------------------------------------
    # STEP 5A — Escalation sum check passed → success
    # -----------------------------------------------------------------------
    if gemini_sum_passed:
        logger.info(f"[vision] Escalation (Gemini) sum check passed for {receipt_id}")
        if db_receipt_id:
            try:
                update_receipt_status(
                    db_receipt_id,
                    current_status="success",
                    current_stage="vision_escalation",
                )
                append_workflow_step(db_receipt_id, "escalation_consensus", "pass")
            except Exception as exc:
                logger.warning(f"[vision] Failed to update status: {exc}")
            # Save the winning escalation result BEFORE categorize_receipt.
            # Both Gemini and OpenAI individual runs are already saved with stage="vision_escalation".
            # Without this, categorize_receipt reads whichever model happened to finish last —
            # it could pick OpenAI even when Gemini won the sum check.
            # This write is always the most recent vision_escalation row, so categorize_receipt
            # consistently reads the correct winner.
            try:
                save_processing_run(
                    receipt_id=db_receipt_id,
                    stage="vision_escalation",
                    model_provider="winner",
                    model_name="best_result",
                    model_version=None,
                    input_payload={"winner": "gemini_escalation"},
                    output_payload=best_result,
                    output_schema_version="vision_v1",
                    status="pass",
                )
            except Exception as exc:
                logger.warning(f"[vision] Failed to save winning escalation result: {exc}")
            try:
                # force=True 覆盖之前写入的 primary，用 escalation 共识结果
                cat_result = await asyncio.to_thread(categorize_receipt, db_receipt_id, True)
                if cat_result.get("success"):
                    logger.info(f"[vision] Categorization (escalation result) completed for {db_receipt_id}")
            except Exception as cat_err:
                logger.warning(f"[vision] Categorization failed: {cat_err}")
            try:
                await _save_output(receipt_id, best_result, timeline, user_id=user_id or "unknown")
            except Exception:
                pass
            asyncio.create_task(
                _run_shadow_legacy(image_bytes, mime_type, db_receipt_id)
            )

        return {
            "success": True,
            "receipt_id": db_receipt_id or receipt_id,
            "status": "escalation_success",
            "current_stage": "vision_escalation",
            "data": best_result,
            "pipeline": "vision_b",
        }

    # -----------------------------------------------------------------------
    # STEP 5B — Escalation sum check failed → needs_review (ask user)
    # -----------------------------------------------------------------------
    logger.info(f"[vision] Escalation (Gemini) sum check failed for {receipt_id}; needs_review")
    if db_receipt_id:
        try:
            update_receipt_status(
                db_receipt_id,
                current_status="needs_review",
                current_stage="vision_escalation",
            )
            append_workflow_step(db_receipt_id, "escalation_consensus", "fail")
        except Exception as exc:
            logger.warning(f"[vision] Failed to update status: {exc}")
        try:
            save_processing_run(
                receipt_id=db_receipt_id,
                stage="vision_escalation",
                model_provider="winner",
                model_name="best_result",
                model_version=None,
                input_payload={"winner": "gemini_escalation", "sum_check_passed": False},
                output_payload=best_result,
                output_schema_version="vision_v1",
                status="pass",
            )
        except Exception as exc:
            logger.warning(f"[vision] Failed to save escalation result: {exc}")
        try:
            await asyncio.to_thread(categorize_receipt, db_receipt_id, True)
        except Exception:
            pass
        asyncio.create_task(
            _run_shadow_legacy(image_bytes, mime_type, db_receipt_id)
        )

    return {
        "success": False,
        "receipt_id": db_receipt_id or receipt_id,
        "status": "needs_review",
        "data": best_result,
        "pipeline": "vision_b",
        "message": "Escalation (Gemini) could not fix the sum check. Please correct manually.",
    }
