"""Shared helpers for LLM receipt payloads (_metadata vs metadata, reasoning keys)."""

from __future__ import annotations

from typing import Any, Dict, Optional


def llm_result_metadata(result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Read metadata dict from a run/output payload (supports _metadata or metadata)."""
    if not isinstance(result, dict):
        return {}
    inner = result.get("_metadata") or result.get("metadata") or {}
    return inner if isinstance(inner, dict) else {}


def llm_metadata_reasoning_text(meta: Optional[Dict[str, Any]]) -> str:
    """First non-empty of reasoning / validation_reasoning, stripped; empty string if absent."""
    if not isinstance(meta, dict):
        return ""
    v = meta.get("reasoning") or meta.get("validation_reasoning")
    if v is None:
        return ""
    return str(v).strip()


def llm_metadata_reasoning_optional(meta: Optional[Dict[str, Any]]) -> Optional[str]:
    """Like llm_metadata_reasoning_text but returns None when there is no reasoning (API clarity)."""
    text = llm_metadata_reasoning_text(meta)
    return text if text else None
