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


def clear_cache():
    """Clear cache (for testing or after DB updates)."""
    global _binding_cache, _cache_populated
    _binding_cache.clear()
    _cache_populated = False
    logger.info("[PromptLoader] Cache cleared")
