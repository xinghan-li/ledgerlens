"""
LLM-based classification suggestion for classification_review.

Calls Gemini to infer L1 category, size, unit_type from raw_product_name
and merchant context. Results are used to pre-fill classification_review rows as unconfirmed.
"""
import logging
from typing import Any, Dict, List, Optional

from app.prompts.prompt_loader import load_classification_prompt
from app.services.database.supabase_client import _get_client
from app.services.llm.gemini_client import parse_receipt_with_gemini

logger = logging.getLogger(__name__)


def _name_to_l1_category_id(name: str, supabase) -> Optional[str]:
    """
    Look up L1 category_id by name (e.g. 'Groceries', 'Electronics').
    Case-insensitive match against active L1 categories.
    """
    if not name or not isinstance(name, str):
        return None
    name_clean = name.strip()
    if not name_clean:
        return None
    try:
        # Use ilike for case-insensitive matching in the database
        res = supabase.table("categories").select("id").eq("level", 1).eq("is_active", True).ilike("name", name_clean).limit(1).execute()
        if res.data:
            return res.data[0]["id"]
        return None
    except Exception as e:
        logger.warning(f"L1 category lookup failed for '{name}': {e}")
        return None


async def suggest_classifications(
    raw_product_names: List[str],
    store_chain_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Call Gemini to suggest L1 category, size, unit_type for each product.

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

    supabase = _get_client()

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
    results: List[Dict[str, Any]] = []

    def _parse_size(s: str) -> tuple:
        """Parse '3.5 oz' -> (3.5, 'oz', None); '12ct' -> (12, 'ct', None)."""
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
        """Parse a string that may be just a number (e.g. '3.5')."""
        import re
        s = (s or "").strip()
        if not s:
            return None
        m = re.match(r"^(\d+\.?\d*)", s)
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
                # New prompt returns "category" (L1 name)
                cat_name = (it.get("category") or "").strip()
                # Backward compat: also check old category_i field
                if not cat_name:
                    cat_name = (it.get("category_i") or "").strip()
                if cat_name:
                    out["category_id"] = _name_to_l1_category_id(cat_name, supabase)
                s = (it.get("size") or "").strip()
                u = (it.get("unit_type") or "").strip()
                combined = f"{s} {u}".strip() if (s and u) else (s or u or "")
                qty, unit, pkg = _parse_size(combined)
                if qty is not None:
                    out["size_quantity"] = qty
                if unit:
                    out["size_unit"] = unit
                elif u:
                    out["size_unit"] = u.lower()
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
