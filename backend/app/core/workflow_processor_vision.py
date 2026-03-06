"""
Vision-First Receipt Processing Pipeline — Route B

Flow:
1. Duplicate / rate-limit / user checks  (mirrors legacy)
2. Create receipt_status row with pipeline_version='vision_b'
3. PRIMARY: Gemini vision call → structured JSON
4. Backend sum check + item count check (independent of model self-report)
5. If PASS → save, categorize; if model set needs_review (e.g. item count only) → needs_review, no escalation.
6. If FAIL (backend sum check failed or unclear) → ESCALATION: parallel Gemini + OpenAI → consensus
   6a. If they agree  → success
   6b. If they differ → needs_review (pre-fill agreed fields, highlight conflicts)
7. Shadow legacy always runs in background for A/B comparison
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..config import settings
from ..processors.core.sum_checker import check_receipt_sums
from ..services.categorization.receipt_categorizer import categorize_receipt
from ..services.database.supabase_client import (
    append_workflow_step,
    check_duplicate_by_hash,
    check_user_locked,
    create_receipt,
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
from ..services.llm.llm_client import parse_receipt_with_openai_vision
from ..services.ocr.documentai_client import parse_receipt_documentai
from ..services.llm.receipt_llm_processor import process_receipt_with_llm_from_docai
from .workflow_processor import (
    TimelineRecorder,
    _fail_output_payload,
    _get_duration_from_timeline,
    _save_image_for_manual_review,
    _save_output,
    generate_receipt_id,
    get_output_paths_for_receipt,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

VISION_PRIMARY_PROMPT = """You are a bookkeeper for personal shopping categorization.
Read the attached receipt image and extract the data into the JSON structure below.

RULES:
1. Read every line on the receipt. Do not skip any line.

2. All monetary amounts must be output in CENTS (integer).
   Example: $14.99 → 1499, $22.69 → 2269. Never output decimals for money.

3. Extract EVERY product line as a separate item in the items array.
   Each item must have ALL of these fields explicitly set (use null if not available):
   product_name, quantity, unit, unit_price, line_total, raw_text, is_on_sale.

4. For weighted items (e.g. "1.73 lb @ $1.88/lb"):
   set quantity=1.73, unit="lb", unit_price=188, line_total=<actual printed total>.

5. For package discounts (e.g. "2 for $5.00", "3/$9.99"):
   use the actual line_total printed on the receipt. Do NOT recalculate.
   Set is_on_sale=true.

6. Item-level price check:
   For each item where quantity AND unit_price are both present:
   - Calculate expected_line_total = round(quantity × unit_price)
   - If abs(expected_line_total - line_total) / line_total > 0.03 (more than 3% off):
     → Add an entry to tbd.items_with_inconsistent_price explaining the discrepancy.
     → Lower _metadata.confidence by one tier (high→medium, medium→low).
   - If the difference is ≤ 3%: use the receipt's printed line_total as-is, no penalty.
   Exception: skip this check for package discount items (is_on_sale=true with package format).

7. Receipt-level sum check and subtotal rule:
   - All monetary values must be read from the receipt or calculated from it. If you cannot read or compute a value reliably, use null. Do NOT fabricate numbers.
   - receipt.subtotal MUST equal the sum of all items' line_total when that sum is consistent with the receipt (i.e. when sum(items) + tax + fees = total). If the receipt does not print a subtotal line, set receipt.subtotal = sum(items[*].line_total). If the receipt does print a subtotal but it disagrees with sum(items), prefer sum(items) as receipt.subtotal so the math balances; never output a different subtotal that makes sum check fail.
   a) sum(items[*].line_total) must equal receipt.subtotal (within 3 cents or 1%).
   b) receipt.subtotal + receipt.tax + receipt.fees must equal receipt.total (within 3 cents or 1%).
   If either check fails after honest extraction, set _metadata.sum_check_passed=false and document in _metadata.sum_check_notes.

8. If your sum check (Rule 7) fails after best effort:
   Set _metadata.validation_status="needs_review".
   Do NOT fabricate numbers to force the sum to balance.

9. Set _metadata.validation_status and _metadata.confidence with detailed reasoning:
   - Start with validation_status="pass" and confidence="high".
   - Downgrade to confidence="medium" if:
     * Any item has a price discrepancy ≤ 3% (Rule 6 soft warning)
     * Any field is unclear but best-effort readable
   - Downgrade to confidence="low" if:
     * Any item has a price discrepancy > 3% (Rule 6 hard warning)
     * Image is blurry or partially obscured for any section
   - Set validation_status="needs_review" if:
     * Sum check cannot pass after honest re-examination (Rule 8)
     * Item count on receipt does not match items extracted (see Rule 10)
     * confidence="low" AND sum_check_passed=false
   - Set _metadata.reasoning to a plain-English explanation of your validation_status
     and confidence decisions. Be specific: name which items or fields caused issues.

10. Item count check:
    If the receipt shows "Item count: N", "Iten count: N", or similar:
    - Set _metadata.item_count_on_receipt = N
    - Set _metadata.item_count_extracted = len(items)
    - If item_count_extracted < item_count_on_receipt:
      → Set validation_status="needs_review"
      → Add note in _metadata.reasoning: "Extracted X items but receipt states N"
    This does not trigger escalation: the backend only escalates when sum check fails (numbers don't add up) or the image is unclear. Item count mismatch (e.g. 9 vs 10) is often a counting difference or a deposit/fee line; we save as needs_review for the user to confirm, without calling stronger models.
    If no item count is printed: set _metadata.item_count_on_receipt=null.

11. payment_method must be one of these exact values (case-sensitive):
    "Visa", "Mastercard", "AmEx", "Discover", "Cash", "Gift Card", "Other"
    If two payment methods are used (e.g. Gift Card + Visa):
    output as an array: ["Gift Card", "Visa"]
    If only one method: output as a string: "Visa"
    If unknown: "Other"

12. purchase_time: output as HH:MM in 24-hour format. Drop seconds. Null if not visible.

13. fees: extract any environmental fee, bottle deposit, bag fee, CRF, etc. as a
    receipt-level total (sum of all such charges in cents). Null or 0 if none present.
    These are also included as individual line items in the items array.

14. Output only valid JSON — no markdown fences, no extra text.

OUTPUT SCHEMA (all amounts in cents):
{
  "receipt": {
    "merchant_name": "T&T Supermarket US",
    "merchant_phone": "425-640-2648 or null",
    "merchant_address": "19630 Hwy 99, Lynnwood, WA 98036 or null",
    "country": "US or null",
    "currency": "USD",
    "purchase_date": "2026-03-02 or null",
    "purchase_time": "20:30 or null",
    "subtotal": 2269,
    "tax": 0,
    "fees": 0,
    "total": 2269,
    "payment_method": "Visa",
    "card_last4": "3719 or null"
  },
  "items": [
    {
      "product_name": "GREEN ONION",
      "quantity": 2,
      "unit": null,
      "unit_price": 129,
      "line_total": 258,
      "raw_text": "GREEN ONION   2   1.29   2.58",
      "is_on_sale": false
    },
    {
      "product_name": "LETTUCE STEM",
      "quantity": 1.73,
      "unit": "lb",
      "unit_price": 188,
      "line_total": 325,
      "raw_text": "(SALE) LETTUCE STEM  1.73 lb @ $1.88/lb  FP $3.25",
      "is_on_sale": true
    }
  ],
  "tbd": {
    "items_with_inconsistent_price": [
      {
        "product_name": "EXAMPLE ITEM",
        "raw_text": "EXAMPLE ITEM  2  1.29  2.75",
        "expected_line_total": 258,
        "actual_line_total": 275,
        "discrepancy_pct": 6.6,
        "note": "quantity x unit_price = 258 but receipt shows 275 (6.6% off, exceeds 3% threshold)"
      }
    ],
    "missing_info": [],
    "notes": "free-form observations about receipt quality or extraction issues"
  },
  "_metadata": {
    "validation_status": "pass",
    "confidence": "high",
    "reasoning": "All 9 items extracted. Sum check passed: items sum 2269 = total 2269. Item count matches receipt footer (Item count: 9). No price discrepancies.",
    "sum_check_passed": true,
    "sum_check_notes": null,
    "item_count_on_receipt": 9,
    "item_count_extracted": 9
  }
}"""


VISION_ESCALATION_PROMPT_TEMPLATE = """You are a senior bookkeeper for personal shopping categorization.
A faster model (gemini-2.5-flash) attempted to read the attached receipt image but could not produce a reliable result.

FAILURE REASON FROM PREVIOUS ATTEMPT:
{failure_reason}

NOTES FROM PREVIOUS ATTEMPT:
{primary_notes}

Please read the original receipt image again carefully and produce a corrected, fully structured JSON.

RULES:
1. Read EVERY line on the receipt — do not skip any product line.

2. All monetary amounts must be output in CENTS (integer). Example: $14.99 → 1499.
   Never output decimals for money.

3. Each item must have ALL fields explicitly set (null if not available):
   product_name, quantity, unit, unit_price, line_total, raw_text, is_on_sale.

4. If the receipt shows "Item count: N" or "Iten count: N" at the bottom:
   You MUST extract exactly N product items (excluding points/rewards/fee-only lines).
   Set _metadata.item_count_on_receipt=N and _metadata.item_count_extracted=len(items).

5. For weighted items (e.g. "1.73 lb @ $1.88/lb"):
   set quantity=1.73, unit="lb", unit_price=188, line_total=<actual printed total>.

6. Item-level price check:
   For each item where quantity AND unit_price are both present:
   - If abs(quantity x unit_price - line_total) / line_total > 0.03:
     → Add to tbd.items_with_inconsistent_price with discrepancy details.
     → Lower confidence by one tier.

7. Receipt-level numbers and sum check (CRITICAL — previous attempt had wrong numbers):
   - Every amount must be read from the image or calculated; if you cannot compute it, use null. Do NOT invent or copy wrong numbers.
   - receipt.subtotal MUST be the sum of all items' line_total whenever that sum + tax + fees equals the printed total. If the receipt has no subtotal line, set receipt.subtotal = sum(items[*].line_total). If a printed subtotal disagrees with sum(items), use sum(items) as receipt.subtotal so the backend sum check passes. Never output a subtotal that is not equal to sum(items) when the items sum is correct.
   a) sum(items[*].line_total) must equal receipt.subtotal (within 3 cents or 1%).
   b) receipt.subtotal + receipt.tax + receipt.fees must equal receipt.total (within 3 cents or 1%).
   If checks fail after honest extraction, report in _metadata.sum_check_notes. Do NOT fabricate numbers.

8. payment_method must be one of: "Visa", "Mastercard", "AmEx", "Discover", "Cash",
   "Gift Card", "Other". If two methods: output as array ["Gift Card", "Visa"].

9. purchase_time: HH:MM in 24-hour format. Drop seconds.

10. fees: sum of all environmental/bottle/bag/CRF charges at receipt level (cents).

11. Set _metadata.validation_status and reasoning:
    - "pass" if sum check passes, item count matches, confidence is high or medium.
    - "needs_review" if sum check fails or item count mismatches or confidence is low.
    - When only item count mismatches (e.g. receipt says 10, extracted 9) and sum check passes: set validation_status="needs_review" so the user can review; the backend will NOT escalate (often just deposit/fee or count difference).
    - _metadata.reasoning must explain specifically what passed or failed.

12. Output only valid JSON — no markdown, no extra text.

OUTPUT SCHEMA (identical to primary, all amounts in cents):
{{
  "receipt": {{
    "merchant_name": "string or null",
    "merchant_phone": "string or null",
    "merchant_address": "string or null",
    "country": "string or null",
    "currency": "USD",
    "purchase_date": "YYYY-MM-DD or null",
    "purchase_time": "HH:MM or null",
    "subtotal": 2269,
    "tax": 0,
    "fees": 0,
    "total": 2269,
    "payment_method": "Visa",
    "card_last4": "3719 or null"
  }},
  "items": [
    {{
      "product_name": "GREEN ONION",
      "quantity": 2,
      "unit": null,
      "unit_price": 129,
      "line_total": 258,
      "raw_text": "GREEN ONION   2   1.29   2.58",
      "is_on_sale": false
    }}
  ],
  "tbd": {{
    "items_with_inconsistent_price": [],
    "missing_info": [],
    "notes": "free-form observations"
  }},
  "_metadata": {{
    "validation_status": "pass",
    "confidence": "high",
    "reasoning": "Specific explanation of what passed/failed and why.",
    "sum_check_passed": true,
    "sum_check_notes": null,
    "item_count_on_receipt": 9,
    "item_count_extracted": 9
  }}
}}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _check_vision_consensus(
    result_a: Dict[str, Any],
    result_b: Dict[str, Any],
) -> Tuple[bool, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Compare two vision-model outputs.

    Returns:
        (agree, conflicts, merged_result)
        agree  = True if key fields are consistent within tolerance
        conflicts = list of {field, model_a, model_b} dicts
        merged_result = result_a annotated with conflicts list
    """
    receipt_a = result_a.get("receipt") or {}
    receipt_b = result_b.get("receipt") or {}
    items_a = result_a.get("items") or []
    items_b = result_b.get("items") or []

    conflicts: List[Dict[str, Any]] = []

    # Numeric fields: 3-cent or 1% tolerance
    for field in ("total", "subtotal", "tax"):
        va = receipt_a.get(field)
        vb = receipt_b.get(field)
        if va is not None and vb is not None:
            try:
                fa, fb = float(va), float(vb)
                ref = max(abs(fa), abs(fb), 1)
                tol = max(3.0, ref * 0.01)
                if abs(fa - fb) > tol:
                    conflicts.append({"field": f"receipt.{field}", "model_a": va, "model_b": vb})
            except (TypeError, ValueError):
                pass

    # Item count
    if abs(len(items_a) - len(items_b)) > 0:
        conflicts.append({
            "field": "items.count",
            "model_a": len(items_a),
            "model_b": len(items_b),
        })

    # Text fields (fuzzy-ish: simple lower-strip compare)
    for field in ("merchant_name", "purchase_date", "payment_method"):
        va = str(receipt_a.get(field) or "").strip().lower()
        vb = str(receipt_b.get(field) or "").strip().lower()
        if va and vb and va != vb:
            conflicts.append({
                "field": f"receipt.{field}",
                "model_a": receipt_a.get(field),
                "model_b": receipt_b.get(field),
            })

    agree = len(conflicts) == 0

    # Merge: prefer model_a (Gemini escalation), annotate conflicts
    merged = dict(result_a)
    merged["_vision_conflicts"] = conflicts
    merged["_vision_model_b_total"] = receipt_b.get("total")
    merged["_vision_model_b_item_count"] = len(items_b)

    return agree, conflicts, merged


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
# Escalation — parallel Gemini3 + OpenAI vision
# ---------------------------------------------------------------------------

async def _run_vision_escalation(
    image_bytes: bytes,
    mime_type: str,
    failure_reason: str,
    primary_notes: str,
    db_receipt_id: str,
    *,
    gemini_model: Optional[str] = None,
    openai_model: Optional[str] = None,
) -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    Call escalation models in parallel. Model names from caller (resolved from settings + env fallback).
    Returns (gemini_result, openai_result); either may be None on error.
    """
    escalation_prompt = VISION_ESCALATION_PROMPT_TEMPLATE.format(
        failure_reason=failure_reason,
        primary_notes=primary_notes,
    )

    gemini_model = (gemini_model or "").strip() or (getattr(settings, "gemini_escalation_model", None) or "").strip() or (os.getenv("GEMINI_ESCALATION_MODEL") or "").strip()
    openai_model = (openai_model or "").strip() or (getattr(settings, "openai_escalation_model", None) or "").strip() or (os.getenv("OPENAI_ESCALATION_MODEL") or "").strip()

    async def _call_gemini() -> Optional[Dict]:
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

    async def _call_openai() -> Optional[Dict]:
        if not openai_model:
            logger.info("[escalation] OPENAI_ESCALATION_MODEL not configured, skipping")
            return None
        try:
            result = await asyncio.to_thread(
                parse_receipt_with_openai_vision,
                image_bytes=image_bytes,
                instruction=escalation_prompt,
                model=openai_model,
                mime_type=mime_type,
            )
            save_processing_run(
                receipt_id=db_receipt_id,
                stage="vision_escalation",
                model_provider="openai",
                model_name=openai_model,
                model_version=None,
                input_payload={
                    "failure_reason": failure_reason,
                    "image_bytes_length": len(image_bytes),
                },
                output_payload=result,
                output_schema_version="vision_v1",
                status="pass",
            )
            return result
        except Exception as exc:
            logger.error(f"[escalation] OpenAI failed: {exc}")
            save_processing_run(
                receipt_id=db_receipt_id,
                stage="vision_escalation",
                model_provider="openai",
                model_name=openai_model,
                model_version=None,
                input_payload={"failure_reason": failure_reason},
                output_payload=_fail_output_payload(str(exc)),
                output_schema_version=None,
                status="fail",
                error_message=str(exc),
            )
            return None

    gemini_result, openai_result = await asyncio.gather(
        _call_gemini(), _call_openai()
    )
    return gemini_result, openai_result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def process_receipt_workflow_vision(
    image_bytes: bytes,
    filename: str,
    mime_type: str = "image/jpeg",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Vision-First receipt processing pipeline (Route B).

    Args:
        image_bytes: Raw image bytes
        filename: Original filename
        mime_type: MIME type (image/jpeg or image/png)
        user_id: Authenticated user ID; falls back to TEST_USER_ID if None

    Returns:
        Processing result dictionary (compatible shape with legacy workflow)
    """
    receipt_id = generate_receipt_id(filename)
    timeline = TimelineRecorder(receipt_id)

    original_file_hash = hashlib.sha256(image_bytes).hexdigest()
    file_hash = original_file_hash

    # Resolve user_id
    if user_id is None:
        user_id = get_test_user_id()

    # Rate-limit / lock check
    if user_id:
        user_class = get_user_class(user_id)
        if user_class not in ("super_admin", "admin"):
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

    # Duplicate check
    if user_id:
        existing_receipt_id = check_duplicate_by_hash(file_hash, user_id)
        if existing_receipt_id:
            user_class = get_user_class(user_id)
            allow_dup = user_class in ("super_admin", "admin") or settings.allow_duplicate_for_debug
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
                    "existing_receipt_id": existing_receipt_id,
                    "pipeline": "vision_b",
                }

    # Create DB record
    db_receipt_id: Optional[str] = None
    if user_id:
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
    try:
        primary_result, primary_usage = await parse_receipt_with_gemini_vision_escalation(
            image_bytes=image_bytes,
            instruction=VISION_PRIMARY_PROMPT,
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
        if db_receipt_id:
            primary_duration = _get_duration_from_timeline(timeline, "vision_primary")
            input_pl = {"image_bytes_length": len(image_bytes), "mime_type": mime_type}
            if primary_usage:
                input_pl["token_usage"] = primary_usage
            out_pl = dict(primary_result) if primary_result else {}
            if primary_usage:
                out_pl["token_usage"] = primary_usage
            save_processing_run(
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
            append_workflow_step(db_receipt_id, "vision_primary", "pass")

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
        if db_receipt_id:
            try:
                update_receipt_status(
                    db_receipt_id,
                    current_status=status_for_receipt,
                    current_stage="vision_primary",
                )
                if status_for_receipt == "needs_review":
                    logger.info(
                        f"[vision] Backend sum check passed; model requested needs_review (e.g. item count) for {receipt_id} — not escalating"
                    )
                else:
                    logger.info(f"[vision] Updated receipt {db_receipt_id} to status=success, stage=vision_primary")
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

    # Resolve escalation model names: prefer settings, fallback to env (pydantic-settings may not bind alias to env on all versions)
    gemini_esc = (settings.gemini_escalation_model or "").strip() or (os.getenv("GEMINI_ESCALATION_MODEL") or "").strip()
    openai_esc = (settings.openai_escalation_model or "").strip() or (os.getenv("OPENAI_ESCALATION_MODEL") or "").strip()
    escalation_configured = bool(gemini_esc or openai_esc)

    if not escalation_configured:
        logger.warning(
            "[vision] No escalation models configured "
            "(GEMINI_ESCALATION_MODEL / OPENAI_ESCALATION_MODEL). "
            "Marking as needs_review without escalation. "
            "settings.gemini_esc=%s settings.openai_esc=%s",
            getattr(settings, "gemini_escalation_model", None),
            getattr(settings, "openai_escalation_model", None),
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
    # STEP 4 — Escalation: parallel Gemini + OpenAI
    # -----------------------------------------------------------------------
    logger.info(
        "[vision] Escalation configured: gemini=%s openai=%s",
        gemini_esc or "(none)",
        openai_esc or "(none)",
    )
    timeline.start("vision_escalation")
    gemini_esc_result, openai_esc_result = await _run_vision_escalation(
        image_bytes=image_bytes,
        mime_type=mime_type,
        failure_reason=failure_reason,
        primary_notes=primary_notes,
        db_receipt_id=db_receipt_id or receipt_id,
        gemini_model=gemini_esc or None,
        openai_model=openai_esc or None,
    )
    timeline.end("vision_escalation")

    if db_receipt_id:
        append_workflow_step(db_receipt_id, "vision_escalation", "done")

    # If both escalation calls failed, mark needs_review with primary data
    if gemini_esc_result is None and openai_esc_result is None:
        logger.error(f"[vision] Both escalation models failed for {receipt_id}")
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

    # Use whichever escalation result is available for single-model case
    if gemini_esc_result is not None and openai_esc_result is None:
        best_result = gemini_esc_result
        agree, conflicts, merged = True, [], gemini_esc_result
    elif openai_esc_result is not None and gemini_esc_result is None:
        best_result = openai_esc_result
        agree, conflicts, merged = True, [], openai_esc_result
    else:
        # Both available → consensus check
        agree, conflicts, merged = _check_vision_consensus(gemini_esc_result, openai_esc_result)
        best_result = merged

    # Normalize payment_method in best result
    rec = (best_result.get("receipt") or {})
    rec["payment_method"] = _normalize_payment_method(rec.get("payment_method"))
    best_result = {**best_result, "receipt": rec}

    # -----------------------------------------------------------------------
    # STEP 5A — Escalation AGREED → success
    # -----------------------------------------------------------------------
    if agree:
        logger.info(f"[vision] Escalation consensus reached for {receipt_id}")
        if db_receipt_id:
            try:
                update_receipt_status(
                    db_receipt_id,
                    current_status="success",
                    current_stage="vision_escalation",
                )
                append_workflow_step(db_receipt_id, "escalation_consensus", "agree")
            except Exception as exc:
                logger.warning(f"[vision] Failed to update status: {exc}")
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
            "data": best_result,
            "pipeline": "vision_b",
        }

    # -----------------------------------------------------------------------
    # STEP 5B — Escalation DISAGREED → needs_review with highlights
    # -----------------------------------------------------------------------
    logger.info(
        f"[vision] Escalation conflict for {receipt_id}: {len(conflicts)} conflict(s)"
    )
    if db_receipt_id:
        try:
            update_receipt_status(
                db_receipt_id,
                current_status="needs_review",
                current_stage="vision_escalation",
            )
            append_workflow_step(
                db_receipt_id, "escalation_consensus", "conflict",
                details={"conflicts": conflicts},
            )
        except Exception as exc:
            logger.warning(f"[vision] Failed to update status: {exc}")
        try:
            await asyncio.to_thread(categorize_receipt, db_receipt_id)
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
        "conflicts": conflicts,
        "pipeline": "vision_b",
        "message": (
            f"Escalation models disagreed on {len(conflicts)} field(s). "
            "Conflicting fields are highlighted for manual correction."
        ),
    }
