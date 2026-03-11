"""
LLM-based user subcategory suggestion.

After smart categorization assigns a system L1 category and the RPC maps it to
the user's L1 user_category_id, this module attempts to go deeper: it reads the
user's personal category tree and asks the LLM to assign the most appropriate
L2/L3 subcategory for each item.

Conservative by design — returns null when confidence is not high, to avoid
type-I errors (wrong subcategory is worse than no subcategory).
"""
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _build_user_tree(user_categories: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build a nested tree from the flat user_categories list.
    Returns:
      {
        l1_id: {
          "name": str,
          "children": [{"id": str, "name": str, "path": str, "level": int}, ...]
        },
        ...
      }
    Only L1 roots are top-level keys; all descendants (L2+) are flattened into children.
    """
    by_id: Dict[str, Dict[str, Any]] = {str(c["id"]): c for c in user_categories}
    tree: Dict[str, Any] = {}

    # Index L1 roots
    for cat in user_categories:
        if cat.get("level") == 1:
            tree[str(cat["id"])] = {"name": cat["name"], "children": []}

    def _find_l1_ancestor(cat_id: str) -> Optional[str]:
        """Walk up parent chain to find the L1 root id."""
        current = by_id.get(cat_id)
        while current:
            if current.get("level") == 1:
                return str(current["id"])
            pid = current.get("parent_id")
            if not pid:
                return None
            current = by_id.get(str(pid))
        return None

    # Assign all L2+ nodes to their L1 root's children list
    for cat in user_categories:
        if cat.get("level", 1) > 1:
            l1_id = _find_l1_ancestor(str(cat["id"]))
            if l1_id and l1_id in tree:
                tree[l1_id]["children"].append({
                    "id": str(cat["id"]),
                    "name": cat["name"],
                    "path": cat.get("path") or cat["name"],
                    "level": cat.get("level", 2),
                })

    return tree


def _build_user_message(
    items: List[Dict[str, Any]],
    tree: Dict[str, Any],
) -> str:
    """
    Build the user message for the LLM call.

    items: list of {"item_id": str, "product_name": str, "l1_user_category_id": str, "l1_name": str}
    tree: output of _build_user_tree
    """
    # Group items by their L1 category for a readable prompt
    l1_groups: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        l1_id = it.get("l1_user_category_id") or ""
        if l1_id not in l1_groups:
            l1_groups[l1_id] = []
        l1_groups[l1_id].append(it)

    lines: List[str] = ["User's category tree (subcategory options per L1):\n"]
    for l1_id, node in tree.items():
        children = node.get("children") or []
        # Only show L1s that have at least one child (otherwise nothing to suggest)
        if children:
            lines.append(f'  [{node["name"]}]  (l1_id: {l1_id})')
            for ch in children:
                lines.append(f'    - id: {ch["id"]}  path: {ch["path"]}')

    lines.append("\nItems to classify (assign subcategory from the tree above):\n")
    items_payload = []
    for it in items:
        items_payload.append({
            "item_id": it["item_id"],
            "product_name": it["product_name"],
            "l1_category": it["l1_name"],
            "l1_id": it.get("l1_user_category_id"),
        })
    lines.append(json.dumps({"items": items_payload}, ensure_ascii=False, indent=2))
    lines.append("\nOutput valid JSON with the items array as specified in the system prompt.")

    return "\n".join(lines)


async def suggest_user_subcategories(
    items: List[Dict[str, Any]],
    user_categories: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Call Gemini to suggest user subcategories for the given items.

    Args:
        items: list of {
            "item_id": str,          # record_items.id
            "product_name": str,
            "l1_user_category_id": str,  # current user_category_id (L1 node)
            "l1_name": str,
        }
        user_categories: flat list from get_user_categories(user_id)

    Returns:
        list of {"item_id": str, "subcategory_id": str | None}
        Only items where LLM returned high confidence with a valid subcategory ID.
    """
    if not items or not user_categories:
        return []

    tree = _build_user_tree(user_categories)

    # Filter to items whose L1 actually has children — no point asking LLM otherwise
    valid_l1_ids = {l1_id for l1_id, node in tree.items() if node.get("children")}
    eligible_items = [it for it in items if it.get("l1_user_category_id") in valid_l1_ids]
    if not eligible_items:
        logger.debug("suggest_user_subcategories: no eligible items (all L1s have no children)")
        return []

    # Build a set of valid subcategory IDs to validate LLM output
    valid_sub_ids: set = set()
    for node in tree.values():
        for ch in node.get("children") or []:
            valid_sub_ids.add(ch["id"])

    from ..prompts.prompt_loader import load_subcategory_prompt
    from ..llm.gemini_client import parse_receipt_with_gemini

    system_prompt = load_subcategory_prompt()
    if not system_prompt:
        logger.warning("suggest_user_subcategories: subcategory_classification prompt not found in DB")
        return []

    user_msg = _build_user_message(eligible_items, tree)

    try:
        result = await parse_receipt_with_gemini(
            system_message=system_prompt,
            user_message=user_msg,
            temperature=0,
        )
    except Exception as e:
        logger.warning("suggest_user_subcategories: LLM call failed: %s", e)
        return []

    raw_items = result.get("items") or []
    suggestions: List[Dict[str, Any]] = []
    for raw in raw_items:
        item_id = (raw.get("item_id") or "").strip()
        sub_id = (raw.get("subcategory_id") or "").strip() or None
        confidence = (raw.get("confidence") or "").strip().lower()

        if not item_id:
            continue
        # Only trust high-confidence non-null subcategory IDs that actually exist in the tree
        if confidence == "high" and sub_id and sub_id in valid_sub_ids:
            suggestions.append({"item_id": item_id, "subcategory_id": sub_id})

    logger.info(
        "suggest_user_subcategories: %d eligible items → %d subcategory assignments",
        len(eligible_items), len(suggestions),
    )
    return suggestions
