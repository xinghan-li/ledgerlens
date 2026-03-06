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


def _update_descendant_paths(supabase, parent_id: str, new_parent_path: str) -> None:
    """Recursively set path for all descendants to new_parent_path + '/' + child.name."""
    children = (
        supabase.table("categories")
        .select("id, name")
        .eq("parent_id", parent_id)
        .execute()
    )
    for row in (children.data or []):
        child_path = f"{new_parent_path}/{row['name']}".lstrip("/") if new_parent_path else (row.get("name") or "")
        if not child_path:
            continue
        supabase.table("categories").update({"path": child_path}).eq("id", row["id"]).execute()
        _update_descendant_paths(supabase, row["id"], child_path)


def update_category(cat_id: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Update category name and path; recursively update paths of all descendants."""
    supabase = _get_client()
    row = get_category(cat_id)
    if not row:
        raise ValueError("Category not found")
    if name is None:
        return row
    new_name = (name or "").strip().lower()
    if not new_name:
        return row
    parent_id = row.get("parent_id")
    if parent_id is None:
        new_path = new_name
    else:
        parent = get_category(parent_id)
        if not parent:
            raise ValueError("Parent category not found")
        new_path = f"{parent.get('path', '')}/{new_name}".lstrip("/")
    payload = {"name": new_name, "path": new_path}
    res = supabase.table("categories").update(payload).eq("id", cat_id).execute()
    if not res.data:
        raise ValueError("Category not found")
    _update_descendant_paths(supabase, cat_id, new_path)
    return res.data[0]


def delete_category_soft(cat_id: str) -> None:
    """Soft delete: set is_active = false."""
    supabase = _get_client()
    res = supabase.table("categories").update({"is_active": False}).eq("id", cat_id).execute()
    if not res.data:
        raise ValueError("Category not found")


def _get_descendant_ids(supabase, cat_id: str) -> List[str]:
    """Return all category ids that are descendants of cat_id (children, grandchildren, ...)."""
    out: List[str] = []
    stack = [cat_id]
    while stack:
        parent_id = stack.pop()
        res = supabase.table("categories").select("id").eq("parent_id", parent_id).execute()
        for row in (res.data or []):
            cid = row.get("id")
            if cid:
                out.append(str(cid))
                stack.append(cid)
    return out


def get_category_and_descendant_ids(cat_id: str) -> List[Dict[str, Any]]:
    """
    Return the category row and all its descendants as list of dicts with id, level.
    Used to know which category ids will be removed by hard delete and to delete in correct order (children first).
    """
    supabase = _get_client()
    row = get_category(cat_id)
    if not row:
        raise ValueError("Category not found")
    ids_with_level = [(str(row["id"]), int(row.get("level", 1)))]
    descendant_ids = _get_descendant_ids(supabase, cat_id)
    if descendant_ids:
        res = supabase.table("categories").select("id, level").in_("id", descendant_ids).execute()
        for r in (res.data or []):
            if r.get("id"):
                ids_with_level.append((str(r["id"]), int(r.get("level", 1))))
    # Sort by level desc so we delete children before parents
    ids_with_level.sort(key=lambda x: -x[1])
    return [{"id": i, "level": lv} for i, lv in ids_with_level]


def hard_delete_category(
    cat_id: str,
    action: str,
    target_category_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Hard delete a category (and all its descendants). Before deleting, handle related data:
    - action "release": set record_items.category_id and classification_review.category_id to NULL
      for any ref to this category or descendants; rules/overrides referencing this category are
      deleted (CASCADE) or updated so we can delete the category.
    - action "reassign": set all such references to target_category_id (must be L3, not in deleted set).
    Then delete the category and all descendants (children first).
    """
    if action not in ("release", "reassign"):
        raise ValueError("action must be 'release' or 'reassign'")
    if action == "reassign" and not target_category_id:
        raise ValueError("target_category_id required when action is reassign")

    supabase = _get_client()
    nodes = get_category_and_descendant_ids(cat_id)
    ids_to_remove = [n["id"] for n in nodes]
    if not ids_to_remove:
        raise ValueError("Category not found")

    if action == "reassign":
        target = get_category(target_category_id)
        if not target:
            raise ValueError("Target category not found")
        if int(target.get("level", 0)) != 3:
            raise ValueError("Target category must be level 3 (L3)")
        if target_category_id in ids_to_remove:
            raise ValueError("Target category cannot be the deleted category or its descendant")

    # 1) record_items: set category_id to NULL (release) or target (reassign)
    if action == "release":
        supabase.table("record_items").update({"category_id": None}).in_("category_id", ids_to_remove).execute()
    else:
        supabase.table("record_items").update({"category_id": target_category_id}).in_("category_id", ids_to_remove).execute()

    # 2) classification_review: RESTRICT, so we must update before delete
    if action == "release":
        supabase.table("classification_review").update({"category_id": None}).in_("category_id", ids_to_remove).execute()
    else:
        supabase.table("classification_review").update({"category_id": target_category_id}).in_("category_id", ids_to_remove).execute()

    # 3) product_categorization_rules: CASCADE would delete; for reassign we update to target first
    if action == "reassign":
        supabase.table("product_categorization_rules").update({"category_id": target_category_id}).in_("category_id", ids_to_remove).execute()

    # 4) user_item_category_overrides: CASCADE would delete; for reassign we update to target first
    if action == "reassign":
        supabase.table("user_item_category_overrides").update({"category_id": target_category_id}).in_("category_id", ids_to_remove).execute()

    # 5) Delete categories: children first (nodes already sorted by level desc)
    for n in nodes:
        supabase.table("categories").delete().eq("id", n["id"]).execute()
        logger.info("Hard-deleted category %s (level %s)", n["id"], n["level"])

    return {"message": "hard_deleted", "deleted_count": len(nodes)}
