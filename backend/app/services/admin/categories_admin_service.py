"""
Admin Categories service: tree read and CRUD for categories table.
"""
import logging
from typing import Any, Dict, List, Optional

from app.services.database.supabase_client import _get_client

logger = logging.getLogger(__name__)


def get_categories_tree(active_only: bool = True) -> List[Dict[str, Any]]:
    """
    Return categories as a flat list with id, parent_id, name, path, level.
    Frontend can build tree from parent_id. Optionally filter is_active.
    """
    supabase = _get_client()
    q = supabase.table("categories").select("id, parent_id, name, path, level, is_active, is_system")
    if active_only:
        q = q.eq("is_active", True)
    res = q.order("path").execute()
    return list(res.data or [])


def get_category(cat_id: str) -> Optional[Dict[str, Any]]:
    """Get one category by id."""
    supabase = _get_client()
    res = supabase.table("categories").select("*").eq("id", cat_id).limit(1).execute()
    if not res.data:
        return None
    return res.data[0]


def create_category(parent_id: Optional[str], name: str, level: int) -> Dict[str, Any]:
    """
    Create a category. parent_id None = level 1 root.
    Name stored as given (caller may normalize to lowercase for consistency).
    Raises ValueError with message "already_exists" if same name under same parent.
    """
    supabase = _get_client()
    name_clean = (name or "").strip().lower() or name
    q = supabase.table("categories").select("id").eq("name", name_clean).eq("is_active", True)
    if parent_id is None:
        q = q.is_("parent_id", "null")
    else:
        q = q.eq("parent_id", parent_id)
    existing = q.limit(1).execute()
    if existing.data:
        raise ValueError("already_exists")
    path = name_clean
    if parent_id:
        parent = get_category(parent_id)
        if parent:
            path = f"{parent.get('path', '')}/{name_clean}"
        else:
            raise ValueError("parent_id not found")
    payload = {
        "parent_id": parent_id,
        "name": name_clean,
        "path": path,
        "level": level,
        "is_system": False,
        "is_active": True,
    }
    res = supabase.table("categories").insert(payload).execute()
    if not res.data:
        raise ValueError("Failed to create category")
    return res.data[0]


def update_category(cat_id: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Update category name (and optionally path if we recalc)."""
    supabase = _get_client()
    if not get_category(cat_id):
        raise ValueError("Category not found")
    payload = {}
    if name is not None:
        payload["name"] = (name or "").strip().lower() or None
    if not payload:
        return get_category(cat_id)
    res = supabase.table("categories").update(payload).eq("id", cat_id).execute()
    if not res.data:
        raise ValueError("Category not found")
    return res.data[0]


def delete_category_soft(cat_id: str) -> None:
    """Soft delete: set is_active = false."""
    supabase = _get_client()
    res = supabase.table("categories").update({"is_active": False}).eq("id", cat_id).execute()
    if not res.data:
        raise ValueError("Category not found")
