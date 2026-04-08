"""
User Categories service: per-user category tree CRUD.

Architecture:
  - System `categories` table: L1 roots (admin-managed, fixed)
  - `user_categories` table: per-user full tree (L1 locked copies + L2+ user-editable)
  - L1 nodes: is_locked=True, system_category_id points to system L1
  - L2+ nodes: is_locked=False, user can create/rename/delete/reorder
"""
import logging
from typing import Any, Dict, List, Optional

from app.services.database.supabase_client import _get_client

logger = logging.getLogger(__name__)


# ============================================================
# Read
# ============================================================

def get_user_categories(user_id: str) -> List[Dict[str, Any]]:
    """
    Return all user categories as a flat list ordered by path.
    Frontend builds the tree from parent_id.
    Each row: id, parent_id, level, name, path, system_category_id, is_locked, sort_order.
    """
    supabase = _get_client()
    res = (
        supabase.table("user_categories")
        .select("id, parent_id, level, name, path, system_category_id, is_locked, sort_order, created_at, updated_at")
        .eq("user_id", user_id)
        .order("path")
        .execute()
    )
    return list(res.data or [])


def get_user_category(user_id: str, cat_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single user category. Returns None if not found or doesn't belong to user."""
    supabase = _get_client()
    res = (
        supabase.table("user_categories")
        .select("*")
        .eq("id", cat_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# ============================================================
# Create
# ============================================================

def create_user_category(
    user_id: str,
    name: str,
    parent_id: str,
    sort_order: int = 0,
) -> Dict[str, Any]:
    """
    Create a new user-defined category under an existing parent (must be level >= 1).
    Users cannot create L1 categories (those are system-seeded, is_locked=True).
    Raises ValueError for invalid inputs or duplicates.
    """
    supabase = _get_client()

    # Verify parent exists and belongs to this user
    parent = get_user_category(user_id, parent_id)
    if not parent:
        raise ValueError("parent_not_found")

    # Determine level
    new_level = int(parent.get("level", 1)) + 1
    if new_level > 10:
        raise ValueError("max_depth_exceeded")

    name_clean = (name or "").strip()
    if not name_clean:
        raise ValueError("name_required")
    name_lower = name_clean.lower()

    # Check uniqueness under parent
    existing = (
        supabase.table("user_categories")
        .select("id")
        .eq("user_id", user_id)
        .eq("parent_id", parent_id)
        .eq("name", name_lower)
        .limit(1)
        .execute()
    )
    if existing.data:
        raise ValueError("already_exists")

    parent_path = parent.get("path") or ""
    new_path = f"{parent_path}/{name_lower}".strip("/") if parent_path else name_lower

    payload = {
        "user_id": user_id,
        "parent_id": parent_id,
        "level": new_level,
        "name": name_lower,
        "path": new_path,
        "system_category_id": None,
        "is_locked": False,
        "sort_order": sort_order,
    }
    res = supabase.table("user_categories").insert(payload).execute()
    if not res.data:
        raise ValueError("create_failed")
    return res.data[0]


# ============================================================
# Update
# ============================================================

def _update_user_descendant_paths(supabase, user_id: str, parent_id: str, new_parent_path: str) -> None:
    """Recursively update path for all descendants of a user category."""
    children = (
        supabase.table("user_categories")
        .select("id, name")
        .eq("user_id", user_id)
        .eq("parent_id", parent_id)
        .execute()
    )
    for row in (children.data or []):
        child_path = f"{new_parent_path}/{row['name']}".strip("/") if new_parent_path else row.get("name", "")
        if child_path:
            supabase.table("user_categories").update({"path": child_path}).eq("id", row["id"]).execute()
            _update_user_descendant_paths(supabase, user_id, row["id"], child_path)


def update_user_category(
    user_id: str,
    cat_id: str,
    name: Optional[str] = None,
    sort_order: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Update a user category's name and/or sort_order.
    Cannot rename locked (L1) categories.
    Recursively updates paths of all descendants on rename.
    Raises ValueError for invalid inputs.
    """
    supabase = _get_client()

    row = get_user_category(user_id, cat_id)
    if not row:
        raise ValueError("not_found")

    if row.get("is_locked") and name is not None:
        raise ValueError("locked_category")

    updates: Dict[str, Any] = {}

    if sort_order is not None:
        updates["sort_order"] = sort_order

    if name is not None:
        new_name = (name or "").strip().lower()
        if not new_name:
            raise ValueError("name_required")

        # Check uniqueness among siblings
        parent_id = row.get("parent_id")
        existing_q = (
            supabase.table("user_categories")
            .select("id")
            .eq("user_id", user_id)
            .neq("id", cat_id)
            .eq("name", new_name)
        )
        if parent_id:
            existing_q = existing_q.eq("parent_id", parent_id)
        else:
            existing_q = existing_q.is_("parent_id", "null")
        existing = existing_q.limit(1).execute()
        if existing.data:
            raise ValueError("already_exists")

        # Compute new path
        if parent_id is None:
            new_path = new_name
        else:
            parent = get_user_category(user_id, parent_id)
            parent_path = parent.get("path", "") if parent else ""
            new_path = f"{parent_path}/{new_name}".strip("/") if parent_path else new_name

        updates["name"] = new_name
        updates["path"] = new_path

    if not updates:
        return row

    res = supabase.table("user_categories").update(updates).eq("id", cat_id).eq("user_id", user_id).execute()
    if not res.data:
        raise ValueError("not_found")

    # Recursively update descendant paths if name changed
    if "path" in updates:
        _update_user_descendant_paths(supabase, user_id, cat_id, updates["path"])

    return res.data[0]


# ============================================================
# Delete
# ============================================================

def delete_user_category(
    user_id: str,
    cat_id: str,
    child_action: str = "move_to_parent",
) -> Dict[str, Any]:
    """
    Delete a user category (not locked L1).
    child_action:
      - "move_to_parent": reassign direct children to the deleted node's parent
      - "delete_recursive": delete this node and all descendants (CASCADE handles record_items)
    Returns dict with deleted_count.
    Raises ValueError for locked categories or not found.
    """
    supabase = _get_client()

    row = get_user_category(user_id, cat_id)
    if not row:
        raise ValueError("not_found")
    if row.get("is_locked"):
        raise ValueError("locked_category")

    parent_id = row.get("parent_id")

    if child_action == "move_to_parent":
        # Move children up to grandparent before deleting
        children = (
            supabase.table("user_categories")
            .select("id, name")
            .eq("user_id", user_id)
            .eq("parent_id", cat_id)
            .execute()
        )
        for child in (children.data or []):
            # Recompute child path
            if parent_id:
                grand = get_user_category(user_id, parent_id)
                grand_path = grand.get("path", "") if grand else ""
                child_path = f"{grand_path}/{child['name']}".strip("/") if grand_path else child["name"]
            else:
                child_path = child["name"]
            supabase.table("user_categories").update({
                "parent_id": parent_id,
                "path": child_path,
                "level": int(row.get("level", 2)) - 1,
            }).eq("id", child["id"]).execute()
        # Null out user_category_id in record_items pointing to this node
        supabase.table("record_items").update({"user_category_id": None}).eq("user_id", user_id).eq("user_category_id", cat_id).execute()
        supabase.table("user_categories").delete().eq("id", cat_id).eq("user_id", user_id).execute()
        return {"deleted_count": 1, "children_moved": len(children.data or [])}

    elif child_action == "delete_recursive":
        # Collect all descendant ids
        all_ids = _collect_descendant_ids(supabase, user_id, cat_id)
        all_ids.append(cat_id)
        # Null out record_items.user_category_id for any of these
        supabase.table("record_items").update({"user_category_id": None}).eq("user_id", user_id).in_("user_category_id", all_ids).execute()
        # Delete all nodes in one query (id in all_ids, user_id match)
        supabase.table("user_categories").delete().in_("id", all_ids).eq("user_id", user_id).execute()
        return {"deleted_count": len(all_ids)}

    else:
        raise ValueError("invalid_child_action")


def _collect_descendant_ids(supabase, user_id: str, cat_id: str) -> List[str]:
    """Return all descendant IDs (children, grandchildren, ...) for a user category."""
    out: List[str] = []
    stack = [cat_id]
    while stack:
        pid = stack.pop()
        res = (
            supabase.table("user_categories")
            .select("id")
            .eq("user_id", user_id)
            .eq("parent_id", pid)
            .execute()
        )
        for r in (res.data or []):
            cid = r.get("id")
            if cid:
                out.append(str(cid))
                stack.append(cid)
    return out


# ============================================================
# Seed / Resolve helpers (Python-side wrappers for DB functions)
# ============================================================

def seed_user_default_categories_if_needed(user_id: str) -> bool:
    """
    Ensures the user's category tree is up-to-date with system categories.
    - New users (no categories): full seed via seed_user_default_categories.
    - Existing users: incremental sync via sync_system_categories_to_user
      (adds any new system L1s + their L2/L3 children).
    Returns True if any categories were added.
    """
    supabase = _get_client()
    try:
        res = supabase.rpc("sync_system_categories_to_user", {"p_user_id": user_id}).execute()
        added = res.data if isinstance(res.data, int) else 0
        return added > 0
    except Exception:
        logger.warning(
            "sync_system_categories_to_user RPC failed for user %s — likely race condition or stale data; "
            "categories endpoint still returns existing rows normally",
            user_id,
            exc_info=True,
        )
        return False


def resolve_system_to_user_category_id(user_id: str, system_category_id: str) -> Optional[str]:
    """
    Call DB function resolve_system_to_user_category to map system category_id
    to the user's corresponding user_category_id.
    Returns None if the user has no categories or the call fails.
    """
    if not user_id or not system_category_id:
        return None
    supabase = _get_client()
    try:
        res = supabase.rpc("resolve_system_to_user_category", {
            "p_user_id": user_id,
            "p_system_category_id": system_category_id,
        }).execute()
        data = res.data
        if isinstance(data, str) and data:
            return data
        if isinstance(data, list) and data:
            return str(data[0]) if data[0] else None
        return None
    except Exception:
        logger.debug("resolve_system_to_user_category failed for user=%s sys_cat=%s", user_id, system_category_id)
        return None


# ============================================================
# Admin helpers
# ============================================================

def admin_get_user_categories(target_user_id: str) -> List[Dict[str, Any]]:
    """Admin: get full category tree for any user."""
    supabase = _get_client()
    res = (
        supabase.table("user_categories")
        .select("id, parent_id, level, name, path, system_category_id, is_locked, sort_order, created_at")
        .eq("user_id", target_user_id)
        .order("path")
        .execute()
    )
    return list(res.data or [])
