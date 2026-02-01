"""
RAG Management Service

Provides CRUD operations for managing RAG tags, snippets, and matching rules.
"""
from typing import Dict, Any, List, Optional
from ..database.supabase_client import _get_client
import logging

logger = logging.getLogger(__name__)


def create_tag(
    tag_name: str,
    tag_type: str,
    description: str,
    priority: int = 50,
    is_active: bool = True
) -> Dict[str, Any]:
    """
    Create a new RAG tag.
    
    Args:
        tag_name: Unique tag name (e.g., "deposit_and_fee", "t&t_supermarket")
        tag_type: Tag type ("store", "general", "discount_pattern", etc.)
        description: Description of what this tag is for
        priority: Priority (higher = more important, default 50)
        is_active: Whether the tag is active
        
    Returns:
        Created tag dict with id
    """
    supabase = _get_client()
    
    payload = {
        "tag_name": tag_name,
        "tag_type": tag_type,
        "description": description,
        "priority": priority,
        "is_active": is_active
    }
    
    try:
        res = supabase.table("prompt_tags").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to create tag, no data returned")
        logger.info(f"Created RAG tag: {tag_name}")
        return res.data[0]
    except Exception as e:
        logger.error(f"Failed to create tag: {e}")
        raise


def get_tag(tag_name: str) -> Optional[Dict[str, Any]]:
    """
    Get a tag by name.
    
    Args:
        tag_name: Tag name
        
    Returns:
        Tag dict or None if not found
    """
    supabase = _get_client()
    
    try:
        res = supabase.table("prompt_tags").select("*").eq("tag_name", tag_name).limit(1).execute()
        if res.data:
            return res.data[0]
        return None
    except Exception as e:
        logger.error(f"Failed to get tag: {e}")
        raise


def list_tags(is_active: Optional[bool] = None) -> List[Dict[str, Any]]:
    """
    List all tags, optionally filtered by is_active.
    
    Args:
        is_active: Filter by active status (None = all)
        
    Returns:
        List of tag dicts
    """
    supabase = _get_client()
    
    try:
        query = supabase.table("prompt_tags").select("*")
        if is_active is not None:
            query = query.eq("is_active", is_active)
        res = query.order("priority", desc=True).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"Failed to list tags: {e}")
        raise


def update_tag(
    tag_name: str,
    description: Optional[str] = None,
    priority: Optional[int] = None,
    is_active: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Update a tag.
    
    Args:
        tag_name: Tag name to update
        description: New description (optional)
        priority: New priority (optional)
        is_active: New active status (optional)
        
    Returns:
        Updated tag dict
    """
    supabase = _get_client()
    
    payload = {}
    if description is not None:
        payload["description"] = description
    if priority is not None:
        payload["priority"] = priority
    if is_active is not None:
        payload["is_active"] = is_active
    
    if not payload:
        raise ValueError("At least one field must be provided for update")
    
    try:
        res = supabase.table("prompt_tags").update(payload).eq("tag_name", tag_name).execute()
        if not res.data:
            raise ValueError(f"Tag '{tag_name}' not found")
        logger.info(f"Updated RAG tag: {tag_name}")
        return res.data[0]
    except Exception as e:
        logger.error(f"Failed to update tag: {e}")
        raise


def create_snippet(
    tag_name: str,
    snippet_type: str,
    content: str,
    priority: int = 10,
    is_active: bool = True
) -> Dict[str, Any]:
    """
    Create a snippet for a tag.
    
    Args:
        tag_name: Tag name (must exist)
        snippet_type: Type ("system_message", "prompt_addition", "extraction_rule", "validation_rule", "example")
        content: Snippet content
        priority: Priority (higher = more important, default 10)
        is_active: Whether the snippet is active
        
    Returns:
        Created snippet dict with id
    """
    supabase = _get_client()
    
    # Get tag_id
    tag = get_tag(tag_name)
    if not tag:
        raise ValueError(f"Tag '{tag_name}' not found")
    
    tag_id = tag["id"]
    
    payload = {
        "tag_id": tag_id,
        "snippet_type": snippet_type,
        "content": content,
        "priority": priority,
        "is_active": is_active
    }
    
    try:
        res = supabase.table("prompt_snippets").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to create snippet, no data returned")
        logger.info(f"Created snippet for tag '{tag_name}': {snippet_type}")
        return res.data[0]
    except Exception as e:
        logger.error(f"Failed to create snippet: {e}")
        raise


def list_snippets(tag_name: str) -> List[Dict[str, Any]]:
    """
    List all snippets for a tag.
    
    Args:
        tag_name: Tag name
        
    Returns:
        List of snippet dicts
    """
    supabase = _get_client()
    
    # Get tag_id
    tag = get_tag(tag_name)
    if not tag:
        return []
    
    tag_id = tag["id"]
    
    try:
        res = supabase.table("prompt_snippets").select("*").eq("tag_id", tag_id).order("priority", desc=True).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"Failed to list snippets: {e}")
        raise


def create_matching_rule(
    tag_name: str,
    match_type: str,
    match_pattern: str,
    priority: int = 100,
    is_active: bool = True
) -> Dict[str, Any]:
    """
    Create a matching rule for a tag.
    
    Args:
        tag_name: Tag name (must exist)
        match_type: Type ("store_name", "fuzzy_store_name", "keyword", "regex", "ocr_pattern", "location_state", "location_country")
        match_pattern: Pattern to match (exact value depends on match_type)
        priority: Priority (higher = more important, default 100)
        is_active: Whether the rule is active
        
    Returns:
        Created rule dict with id
    """
    supabase = _get_client()
    
    # Get tag_id
    tag = get_tag(tag_name)
    if not tag:
        raise ValueError(f"Tag '{tag_name}' not found")
    
    tag_id = tag["id"]
    
    payload = {
        "tag_id": tag_id,
        "match_type": match_type,
        "match_pattern": match_pattern,
        "priority": priority,
        "is_active": is_active
    }
    
    try:
        res = supabase.table("tag_matching_rules").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to create matching rule, no data returned")
        logger.info(f"Created matching rule for tag '{tag_name}': {match_type}='{match_pattern}'")
        return res.data[0]
    except Exception as e:
        logger.error(f"Failed to create matching rule: {e}")
        raise


def list_matching_rules(tag_name: str) -> List[Dict[str, Any]]:
    """
    List all matching rules for a tag.
    
    Args:
        tag_name: Tag name
        
    Returns:
        List of rule dicts
    """
    supabase = _get_client()
    
    # Get tag_id
    tag = get_tag(tag_name)
    if not tag:
        return []
    
    tag_id = tag["id"]
    
    try:
        res = supabase.table("tag_matching_rules").select("*").eq("tag_id", tag_id).order("priority", desc=True).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"Failed to list matching rules: {e}")
        raise
