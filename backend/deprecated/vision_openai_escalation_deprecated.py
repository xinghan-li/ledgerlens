"""
DEPRECATED — Vision pipeline OpenAI debate step (no longer used).

Previously: on sum check failure we ran Gemini + OpenAI in parallel and merged with
_check_vision_consensus. As of the deprecation, escalation is Gemini-only; OpenAI
is no longer called in the vision pipeline.

This file is kept for reference only. Not imported anywhere.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 1. Old _run_vision_escalation (parallel Gemini + OpenAI)
# ---------------------------------------------------------------------------
# Called with: image_bytes, mime_type, failure_reason, primary_notes, db_receipt_id,
#              gemini_model=..., openai_model=...
# Returned: (gemini_result, openai_result)
#
# Logic: asyncio.gather(_call_gemini(), _call_openai()); _call_openai used
# parse_receipt_with_openai_vision from app.services.llm.llm_client.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 2. Old _check_vision_consensus(result_a: Gemini, result_b: OpenAI)
# ---------------------------------------------------------------------------
# Compared receipt.total, subtotal, tax (3-cent / 1% tolerance), item count,
# and text fields (merchant_name, purchase_date, payment_method).
# Returned: (agree: bool, conflicts: list, merged: dict with result_a + _vision_conflicts).
# ---------------------------------------------------------------------------


def _check_vision_consensus_deprecated(
    result_a: Dict[str, Any],
    result_b: Dict[str, Any],
) -> Tuple[bool, List[Dict[str, Any]], Dict[str, Any]]:
    """
    [DEPRECATED] Compare two vision-model outputs (Gemini vs OpenAI).
    Returns (agree, conflicts, merged_result). merged_result = result_a + conflict annotations.
    """
    receipt_a = result_a.get("receipt") or {}
    receipt_b = result_b.get("receipt") or {}
    items_a = result_a.get("items") or []
    items_b = result_b.get("items") or []

    conflicts: List[Dict[str, Any]] = []

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

    if abs(len(items_a) - len(items_b)) > 0:
        conflicts.append({
            "field": "items.count",
            "model_a": len(items_a),
            "model_b": len(items_b),
        })

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
    merged = dict(result_a)
    merged["_vision_conflicts"] = conflicts
    merged["_vision_model_b_total"] = receipt_b.get("total")
    merged["_vision_model_b_item_count"] = len(items_b)

    return agree, conflicts, merged
