"""
LLM-based classification suggestion for classification_review.

Calls Gemini to infer category (L1/L2/L3), size, unit_type from raw_product_name
and merchant context. Results are used to pre-fill classification_review rows as unconfirmed.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from app.prompts.prompt_loader import load_classification_prompt
from app.services.database.supabase_client import _get_client
from app.services.llm.gemini_client import parse_receipt_with_gemini

logger = logging.getLogger(__name__)


def _path_to_category_id(path: str, supabase) -> Optional[str]:
    """
    Look up category_id from path (e.g. 'Grocery/Dairy/Milk' or 'Grocery/Produce/Fruit').
    Returns UUID of level-3 category or None.
    """
    if not path or not isinstance(path, str):
        return None
    path_clean = path.strip()
    if not path_clean:
        return None
    try:
        # Path in DB may use different casing; try exact first, then case-insensitive
        res = supabase.table("categories").select("id").eq("path", path_clean).eq("level", 3).limit(1).execute()
        if res.data and res.data[0]:
            return res.data[0]["id"]
        # Try matching by path segments: we have path like "Grocery/Dairy/Milk", DB has "grocery/dairy/milk"
        path_lower = path_clean.lower()
        res2 = supabase.table("categories").select("id, path").eq("level", 3).execute()
        for row in (res2.data or []):
            db_path = (row.get("path") or "").lower()
            if db_path == path_lower:
                return row["id"]
        # Fuzzy: check if path ends match (e.g. "dairy/milk")
        for row in (res2.data or []):
            db_path = (row.get("path") or "").lower()
            if path_lower.endswith(db_path.split("/")[-1] if "/" in db_path else db_path):
                # Weak match - prefer exact path
                pass
        return None
    except Exception as e:
        logger.warning(f"Category path lookup failed for '{path_clean}': {e}")
        return None


async def suggest_classifications(
    raw_product_names: List[str],
    store_chain_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Call Gemini to suggest category (L1/L2/L3), size, unit_type for each product.

    Args:
        raw_product_names: List of product names as on receipt
        store_chain_name: Merchant/store name for context

    Returns:
        List of dicts: [{raw_product_name, category_id, size, unit_type}, ...]
        category_id is None if LLM suggestion couldn't be matched to DB.
    """
    if not raw_product_names:
        return []

    system_prompt = load_classification_prompt()
    if not system_prompt:
        logger.warning("Classification prompt not loaded, skipping LLM suggestion")
        return []

    user_msg = "Infer categories, size, and unit_type for these products.\n\n"
    user_msg += f"Store/Merchant: {store_chain_name or 'Unknown'}\n\n"
    user_msg += "Raw product names:\n"
    for name in raw_product_names:
        user_msg += f"- {name}\n"
    user_msg += "\nOutput valid JSON with the items array."

    try:
        result = await parse_receipt_with_gemini(
            system_message=system_prompt,
            user_message=user_msg,
            temperature=0,
        )
    except Exception as e:
        logger.warning(f"Classification LLM call failed: {e}")
        return []

    items_in = result.get("items") or []
    supabase = _get_client()
    results: List[Dict[str, Any]] = []

    def _parse_size(s: str) -> tuple:
        """Parse '3.5 oz' -> (3.5, 'oz', None); '12ct' -> (12, 'ct', None). Requires number + unit suffix."""
        import re
        s = (s or "").strip()
        if not s:
            return (None, None, None)
        m = re.match(r"^(\d+\.?\d*)\s*([a-zA-Z]+)", s)
        if m:
            try:
                return (float(m.group(1)), m.group(2).lower(), None)
            except ValueError:
                return (None, None, None)
        return (None, None, None)

    def _parse_quantity_only(s: str) -> Optional[float]:
        """Parse a string that may be just a number (e.g. '3.5') when LLM returns size and unit separately."""
        import re
        s = (s or "").strip()
        if not s:
            return None
        m = re.match(r"^(\d+\.?\d*)\s*$", s) or re.match(r"^(\d+\.?\d*)", s)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    for raw in raw_product_names:
        out: Dict[str, Any] = {
            "raw_product_name": raw,
            "category_id": None,
            "size_quantity": None,
            "size_unit": None,
            "package_type": None,
        }
        for it in items_in:
            if (it.get("raw_product_name") or "").strip() == raw.strip():
                c1 = (it.get("category_i") or "").strip()
                c2 = (it.get("category_ii") or "").strip()
                c3 = (it.get("category_iii") or "").strip()
                path = "/".join(filter(None, [c1, c2, c3]))
                if path:
                    out["category_id"] = _path_to_category_id(path, supabase)
                s = (it.get("size") or "").strip()
                u = (it.get("unit_type") or "").strip()
                # Prefer combined "3.5 oz" so _parse_size can extract both; else LLM may return size="3.5", unit_type="oz" separately
                combined = f"{s} {u}".strip() if (s and u) else (s or u or "")
                qty, unit, pkg = _parse_size(combined)
                if qty is not None:
                    out["size_quantity"] = qty
                if unit:
                    out["size_unit"] = unit
                elif u:
                    out["size_unit"] = u.lower()
                # When LLM returns quantity in size and unit in unit_type, _parse_size("3.5") fails; fallback to numeric-only
                if out.get("size_quantity") is None and s:
                    q = _parse_quantity_only(s)
                    if q is not None:
                        out["size_quantity"] = q
                if not out.get("size_unit") and u:
                    out["size_unit"] = u.lower()
                if it.get("package_type"):
                    out["package_type"] = (it.get("package_type") or "").strip().lower()
                break
        results.append(out)

    return results
