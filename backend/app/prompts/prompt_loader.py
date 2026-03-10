"""
Prompt Loader: Load and combine prompts from prompt_library + prompt_binding.

Replaces the old tag-based RAG system. Uses scope (default/chain/location) to
resolve which library entries to combine.
"""
import json
import logging
from typing import Dict, Any, Optional, List, Tuple

from ..services.database.supabase_client import _get_client

logger = logging.getLogger(__name__)

# Cache: prompt_key -> list of (priority, library_entry)
_binding_cache: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
_cache_populated = False


def _populate_binding_cache():
    """Load prompt_binding + prompt_library into cache."""
    global _cache_populated, _binding_cache

    if _cache_populated:
        return

    try:
        supabase = _get_client()
        bindings_res = (
            supabase.table("prompt_binding")
            .select("prompt_key, library_id, scope, chain_id, location_id, priority")
            .eq("is_active", True)
            .execute()
        )
        bindings = bindings_res.data or []

        library_ids = list({b["library_id"] for b in bindings})
        library_map: Dict[str, Dict[str, Any]] = {}
        if library_ids:
            lib_res = (
                supabase.table("prompt_library")
                .select("id, key, content, content_role, category")
                .eq("is_active", True)
                .in_("id", library_ids)
                .execute()
            )
            for lib in lib_res.data or []:
                library_map[str(lib["id"])] = lib

        for row in bindings:
            lib = library_map.get(str(row["library_id"]))
            if not lib:
                continue
            key = row["prompt_key"]
            if key not in _binding_cache:
                _binding_cache[key] = []
            _binding_cache[key].append((
                row.get("priority", 0),
                {
                    **lib,
                    "scope": row["scope"],
                    "chain_id": row.get("chain_id"),
                    "location_id": row.get("location_id"),
                },
            ))

        for key in _binding_cache:
            _binding_cache[key].sort(key=lambda x: x[0])

        _cache_populated = True
        logger.info(f"[PromptLoader] Loaded bindings for {len(_binding_cache)} prompt_key(s)")
    except Exception as e:
        logger.error(f"[PromptLoader] Failed to load bindings: {e}", exc_info=True)


def load_prompts_for_receipt_parse(
    prompt_key: str = "receipt_parse",
    store_chain_id: Optional[str] = None,
    location_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Load and combine prompts for receipt parsing.

    Args:
        prompt_key: Use case key (default 'receipt_parse')
        store_chain_id: Optional chain ID for chain-scoped bindings
        location_id: Optional location ID for location-scoped bindings

    Returns:
        {
            "system_parts": [str, ...],  # Ordered by priority
            "user_template": str or None,
            "schema": str or None,
        }
    """
    _populate_binding_cache()

    result: Dict[str, Any] = {
        "system_parts": [],
        "user_template": None,
        "schema": None,
    }

    bindings = _binding_cache.get(prompt_key, [])
    if not bindings:
        logger.warning(f"[PromptLoader] No bindings for prompt_key={prompt_key}")
        return result

    # Resolve which bindings apply: default + chain (if match) + location (if match)
    applicable: List[Tuple[int, Dict[str, Any]]] = []
    for priority, entry in bindings:
        scope = entry.get("scope", "default")
        if scope == "default":
            applicable.append((priority, entry))
        elif scope == "chain" and store_chain_id and str(entry.get("chain_id")) == str(store_chain_id):
            applicable.append((priority, entry))
        elif scope == "location" and location_id and str(entry.get("location_id")) == str(location_id):
            applicable.append((priority, entry))

    applicable.sort(key=lambda x: x[0])

    for _pri, entry in applicable:
        content_role = entry.get("content_role", "system")
        content = entry.get("content") or ""

        if content_role == "system":
            result["system_parts"].append(content)
        elif content_role == "user_template":
            result["user_template"] = content
        elif content_role == "schema":
            result["schema"] = content

    logger.info(f"[PromptLoader] Loaded {len(result['system_parts'])} system parts, "
                f"user_template={result['user_template'] is not None}, schema={result['schema'] is not None}")
    return result


# Appended to second-round system message only when first-run item count mismatch AND items contain fee/deposit (see build_second_round_system_message).
ITEM_COUNT_DEPOSIT_PARAGRAPH = (
    "**Item count vs. receipt:** If your extracted item count does not match the receipt's \"Items sold\" (or similar), "
    "check for bottle deposit, bottle fee, container fee, or environmental fee lines—stores may or may not count these as items. "
    "If the mismatch is within ± the number of such fee/deposit lines, do not change your extraction; "
    "add a bullet in reasoning (e.g. \"• Item count off by N; may be due to deposit/fee lines being counted or not as items.\"). "
    "Only correct the extraction if the difference is larger than that or there is another clear error."
)


def _should_append_item_count_deposit_paragraph(first_pass_result: Dict[str, Any]) -> bool:
    """
    True when first-pass has item count mismatch and at least one item looks like fee/deposit,
    so we should append the item-count/deposit paragraph to the second-round system message.
    """
    if not first_pass_result:
        return False
    items = first_pass_result.get("items") or []
    meta = first_pass_result.get("_metadata") or {}
    expected = meta.get("item_count_on_receipt")
    if expected is None:
        return False
    try:
        expected = int(expected)
    except (TypeError, ValueError):
        return False
    actual = len(items)
    if actual == expected:
        return False
    # Check for fee/deposit-like lines (case-insensitive)
    keywords = ("bottle", "deposit", "fee", "container", "environmental", "crf", "env ", "bag fee")
    for it in items:
        text = " ".join(
            str(it.get(k) or "") for k in ("product_name", "raw_text")
        ).lower()
        if any(kw in text for kw in keywords):
            return True
    return False


def build_second_round_system_message(
    store_chain_id: Optional[str] = None,
    location_id: Optional[str] = None,
    first_pass_result: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build the full system message for the second LLM pass (refinement).
    Uses load_second_round_prompts; then, only when first-pass item count is wrong
    AND items contain fee/deposit wording, appends the item-count vs. receipt paragraph.
    Call this (with first_pass_result) when building the second-round request.
    """
    loaded = load_second_round_prompts(
        store_chain_id=store_chain_id,
        location_id=location_id,
    )
    parts = loaded.get("system_parts") or []
    system_message = "\n\n".join(parts) if parts else ""
    if first_pass_result and _should_append_item_count_deposit_paragraph(first_pass_result):
        if system_message:
            system_message += "\n\n" + ITEM_COUNT_DEPOSIT_PARAGRAPH
        else:
            system_message = ITEM_COUNT_DEPOSIT_PARAGRAPH
        logger.info(
            "[PromptLoader] Appended item-count/deposit paragraph to second-round prompt "
            "(first-pass count mismatch and fee/deposit items present)"
        )
    return system_message


def load_second_round_prompts(
    store_chain_id: Optional[str] = None,
    location_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Load prompts for the second LLM pass (refinement when store is matched).
    Returns [common prefix] + [store-specific content]: corrected-input rules and
    suspicious-correction escalation are prepended for every store; then chain-
    scoped content (e.g. Costco discount merge) is appended when chain_id matches.
    Uses prompt_key='receipt_parse_second'. See migration 052.
    For the full system message with optional item-count/deposit paragraph, use
    build_second_round_system_message(..., first_pass_result=...).
    """
    return load_prompts_for_receipt_parse(
        prompt_key="receipt_parse_second",
        store_chain_id=store_chain_id,
        location_id=location_id,
    )


def has_chain_second_round_prompt(store_chain_id: Optional[str]) -> bool:
    """
    True if this chain has a chain-scoped binding for receipt_parse_second
    (i.e. there is a store-specific round-2 prompt in the DB for this chain).
    Used to decide whether to run second round after primary vision.
    """
    if not store_chain_id:
        return False
    _populate_binding_cache()
    bindings = _binding_cache.get("receipt_parse_second", [])
    chain_id_str = str(store_chain_id)
    for _priority, entry in bindings:
        if entry.get("scope") == "chain" and str(entry.get("chain_id") or "") == chain_id_str:
            return True
    return False


def get_debug_prompt_system(prompt_key: str) -> Optional[str]:
    """
    Load the system prompt for a debug cascade step (e.g. receipt_parse_debug_ocr, receipt_parse_debug_vision).
    Returns the combined system content or None if not found.
    """
    _populate_binding_cache()
    bindings = _binding_cache.get(prompt_key, [])
    if not bindings:
        return None
    parts: List[str] = []
    for _pri, entry in bindings:
        if entry.get("content_role") == "system" and entry.get("content"):
            parts.append(entry["content"])
    return "\n\n".join(parts) if parts else None


def load_classification_prompt() -> Optional[str]:
    """
    Load the system prompt for classification (product category + size/unit inference).
    Returns the prompt content or None if not found.
    """
    _populate_binding_cache()
    bindings = _binding_cache.get("classification", [])
    if not bindings:
        logger.warning("[PromptLoader] No bindings for prompt_key=classification")
        return None
    # Use first (highest priority) system entry
    for _pri, entry in bindings:
        if entry.get("content_role") == "system":
            return entry.get("content") or ""
    return None


def load_subcategory_prompt() -> Optional[str]:
    """
    Load the system prompt for user subcategory suggestion (subcategory_classification).
    Returns the prompt content or None if not found.
    """
    _populate_binding_cache()
    bindings = _binding_cache.get("subcategory_classification", [])
    if not bindings:
        logger.warning("[PromptLoader] No bindings for prompt_key=subcategory_classification")
        return None
    for _pri, entry in bindings:
        if entry.get("content_role") == "system":
            return entry.get("content") or ""
    return None


def _load_prompt_by_key(key: str) -> Optional[str]:
    """
    Load prompt content directly from prompt_library by key (bypasses binding routing).
    Used for vision-pipeline prompts that do not vary by chain/location at load time.
    Returns content string or None if not found or DB unavailable.
    """
    try:
        from ..services.database.supabase_client import _get_client
        supabase = _get_client()
        res = (
            supabase.table("prompt_library")
            .select("content")
            .eq("key", key)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return rows[0].get("content") or None
        logger.warning("[PromptLoader] prompt_library key=%r not found or inactive", key)
        return None
    except Exception as e:
        logger.error("[PromptLoader] Failed to load prompt key=%r: %s", key, e)
        return None


def load_vision_primary_prompt() -> Optional[str]:
    """
    Load the vision pipeline primary system prompt from prompt_library (key='vision_primary').
    This is the general first-pass prompt sent to Gemini; REFERENCE_DATE_INSTRUCTION
    (runtime-injected with today's date) is prepended by the caller before use.
    Returns None if the key is missing from DB — caller should fall back to the
    hardcoded constant in workflow_processor_vision.py.
    """
    return _load_prompt_by_key("vision_primary")


def load_vision_escalation_template() -> Optional[str]:
    """
    Load the vision escalation prompt template from prompt_library (key='vision_escalation').
    The returned string is a Python .format() template with placeholders:
      {reference_date}, {failure_reason}, {primary_notes}
    Literal JSON braces in the schema example use {{ and }} (Python format-string escaping).
    Caller is responsible for calling .format(reference_date=..., failure_reason=..., primary_notes=...).
    Returns None if the key is missing — caller should fall back to the hardcoded constant.
    """
    return _load_prompt_by_key("vision_escalation")


def clear_cache():
    """Clear cache (for testing or after DB updates)."""
    global _binding_cache, _cache_populated
    _binding_cache.clear()
    _cache_populated = False
    logger.info("[PromptLoader] Cache cleared")
