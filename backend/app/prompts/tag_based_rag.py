"""
Tag-based RAG System: Detect tags from OCR and combine RAG snippets.

This module implements a flexible tag-based RAG system where:
1. Tags are detected from OCR text and merchant names
2. RAG snippets are loaded for matched tags
3. Snippets are combined into final prompts

TODO: Performance Optimizations (Future)
- [ ] 倒排索引优化：当规则达到 1 万条时，需要创建 tag_inverted_index 表
  预建倒排索引，将匹配性能从 O(n) 降低到 O(1) 或 O(log n)
  详见：backend/development_log/2026-01-31_log.md "RAG 系统优化 TODO"
  
- [ ] Redis 缓存：多实例部署时需要使用 Redis 作为分布式缓存
  实现缓存 TTL 和自动刷新机制
  详见：backend/development_log/2026-01-31_log.md "RAG 系统优化 TODO"
"""
import logging
import re
from typing import List, Dict, Any, Optional, Set
from rapidfuzz import fuzz
from ..services.database.supabase_client import _get_client

logger = logging.getLogger(__name__)

# Cache for tags, snippets, and matching rules
_tag_cache: Dict[str, Dict[str, Any]] = {}
_snippet_cache: Dict[str, List[Dict[str, Any]]] = {}  # tag_id -> list of snippets
_matching_rules_cache: List[Dict[str, Any]] = []
_cache_populated = False


def _populate_cache():
    """
    Populate cache with tags, snippets, and matching rules from database.
    
    TODO: Redis Cache Optimization
    - 当前实现：简单的内存缓存，多实例部署时不同步
    - 未来优化：使用 Redis 作为分布式缓存，支持 TTL 和自动刷新
    - 详见：backend/development_log/2026-01-31_log.md "RAG 系统优化 TODO - Redis 缓存"
    """
    global _cache_populated, _tag_cache, _snippet_cache, _matching_rules_cache
    
    if _cache_populated:
        return
    
    try:
        supabase = _get_client()
        
        # Load tags
        tags_response = supabase.table("prompt_tags").select("*").eq("is_active", True).execute()
        if tags_response.data:
            for tag in tags_response.data:
                _tag_cache[tag["tag_name"]] = tag
            logger.info(f"Loaded {len(tags_response.data)} active tags")
        
        # Load snippets
        snippets_response = supabase.table("prompt_snippets").select("*").eq("is_active", True).order("priority", desc=True).execute()
        if snippets_response.data:
            for snippet in snippets_response.data:
                tag_id = snippet["tag_id"]
                if tag_id not in _snippet_cache:
                    _snippet_cache[tag_id] = []
                _snippet_cache[tag_id].append(snippet)
            logger.info(f"Loaded {len(snippets_response.data)} active snippets")
        
        # Load matching rules
        rules_response = supabase.table("tag_matching_rules").select("*").eq("is_active", True).order("priority", desc=True).execute()
        if rules_response.data:
            _matching_rules_cache = rules_response.data
            logger.info(f"Loaded {len(rules_response.data)} active matching rules")
        
        _cache_populated = True
        
    except Exception as e:
        logger.error(f"Failed to populate tag-based RAG cache: {e}", exc_info=True)


def detect_tags_from_ocr(
    raw_text: str = "",
    merchant_name: Optional[str] = None,
    store_chain_id: Optional[str] = None,
    location_id: Optional[str] = None,
    state: Optional[str] = None,
    country_code: Optional[str] = None
) -> List[str]:
    """
    Detect tags from OCR text and merchant name.
    
    Args:
        raw_text: OCR text from receipt
        merchant_name: Extracted merchant name (optional)
        store_chain_id: Store chain ID from database (optional)
    
    Returns:
        List of tag names to apply (ordered by priority)
    """
    _populate_cache()
    
    detected_tags: Set[str] = set()
    tag_priorities: Dict[str, int] = {}
    
    # Normalize text for matching (handle None values)
    raw_text = raw_text or ""
    raw_text_lower = raw_text.lower()
    merchant_name_lower = merchant_name.lower() if merchant_name else ""
    
    # Match against all rules
    for rule in _matching_rules_cache:
        tag_id = rule["tag_id"]
        tag_name = None
        
        # Find tag name
        for tag in _tag_cache.values():
            if tag["id"] == tag_id:
                tag_name = tag["tag_name"]
                break
        
        if not tag_name:
            continue
        
        match_type = rule["match_type"]
        match_pattern = rule["match_pattern"]
        matched = False
        
        try:
            if match_type == "store_name":
                # Exact store name match
                if merchant_name and match_pattern.lower() in merchant_name_lower:
                    matched = True
            elif match_type == "fuzzy_store_name":
                # Fuzzy match store name
                if merchant_name:
                    similarity = fuzz.ratio(merchant_name_lower, match_pattern.lower())
                    if similarity >= 80:  # 80% similarity threshold
                        matched = True
            elif match_type == "keyword":
                # Simple keyword match (case-insensitive, whole word or substring)
                # Check both raw_text and merchant_name
                pattern_lower = match_pattern.lower()
                if pattern_lower in raw_text_lower or (merchant_name and pattern_lower in merchant_name_lower):
                    matched = True
                    logger.debug(f"Keyword match: '{pattern_lower}' found in text")
            elif match_type == "regex":
                # Regex pattern match
                pattern = re.compile(match_pattern, re.IGNORECASE)
                if pattern.search(raw_text) or (merchant_name and pattern.search(merchant_name)):
                    matched = True
            elif match_type == "ocr_pattern":
                # Simple pattern match (like "2/$")
                if match_pattern.lower() in raw_text_lower:
                    matched = True
            
            if matched:
                detected_tags.add(tag_name)
                # Store priority for sorting
                tag_priorities[tag_name] = rule.get("priority", 0)
                logger.debug(f"Matched tag '{tag_name}' using rule: {match_type}='{match_pattern}'")
        
        except Exception as e:
            logger.warning(f"Error matching rule {rule.get('id')}: {e}")
            continue
    
    # Also check store_chain_id for store-specific tags
    if store_chain_id:
        # Query store_chains to find matching tag
        try:
            supabase = _get_client()
            chain_response = supabase.table("store_chains").select("normalized_name, aliases").eq("id", store_chain_id).limit(1).execute()
            if chain_response.data:
                chain = chain_response.data[0]
                chain_name_normalized = chain.get("normalized_name", "").lower()
                chain_aliases = chain.get("aliases", [])
                
                # Check if any tag matches this chain
                for tag_name, tag in _tag_cache.items():
                    if tag["tag_type"] == "store":
                        # Check if tag name matches chain name or aliases
                        if (chain_name_normalized and tag_name.lower() in chain_name_normalized) or \
                           any(tag_name.lower() in alias.lower() for alias in chain_aliases):
                            detected_tags.add(tag_name)
                            tag_priorities[tag_name] = tag.get("priority", 0)
                            logger.debug(f"Matched store tag '{tag_name}' from chain_id")
        except Exception as e:
            logger.warning(f"Error checking store_chain_id for tags: {e}")
    
    # Sort by priority (higher first)
    sorted_tags = sorted(detected_tags, key=lambda t: tag_priorities.get(t, 0), reverse=True)
    
    if sorted_tags:
        logger.info(f"[RAG] Detected {len(sorted_tags)} tag(s): {sorted_tags}")
        for tag_name in sorted_tags:
            tag = _tag_cache.get(tag_name)
            if tag:
                logger.info(f"[RAG]   - {tag_name} (type: {tag.get('tag_type')}, priority: {tag.get('priority', 0)})")
    else:
        logger.info("[RAG] No tags detected")
    
    return sorted_tags


def load_rag_snippets(tag_names: List[str]) -> Dict[str, Any]:
    """
    Load and combine RAG snippets for given tags.
    
    Args:
        tag_names: List of tag names to load snippets for
    
    Returns:
        Dictionary with combined snippets:
        {
            "system_messages": [str, ...],
            "prompt_additions": [str, ...],
            "extraction_rules": [dict, ...],
            "validation_rules": [str, ...],
            "examples": [str, ...]
        }
    """
    _populate_cache()
    
    result = {
        "system_messages": [],
        "prompt_additions": [],
        "extraction_rules": [],
        "validation_rules": [],
        "examples": []
    }
    
    # Load snippets for each tag (in priority order)
    logger.info(f"[RAG] Loading snippets for {len(tag_names)} tag(s): {tag_names}")
    
    for tag_name in tag_names:
        tag = _tag_cache.get(tag_name)
        if not tag:
            logger.warning(f"[RAG] Tag '{tag_name}' not found in cache")
            continue
        
        tag_id = tag["id"]
        snippets = _snippet_cache.get(tag_id, [])
        
        # Sort snippets by priority (higher first)
        snippets_sorted = sorted(snippets, key=lambda s: s.get("priority", 0), reverse=True)
        
        logger.info(f"[RAG]   Tag '{tag_name}': Found {len(snippets_sorted)} snippet(s)")
        
        for snippet in snippets_sorted:
            snippet_type = snippet["snippet_type"]
            content = snippet["content"]
            snippet_priority = snippet.get("priority", 0)
            
            logger.info(f"[RAG]     - {snippet_type} (priority: {snippet_priority}, length: {len(str(content))} chars)")
            
            if snippet_type == "system_message":
                result["system_messages"].append(content)
            elif snippet_type == "prompt_addition":
                result["prompt_additions"].append(content)
            elif snippet_type == "extraction_rule":
                # Try to parse as JSON if it's a string
                try:
                    import json
                    if isinstance(content, str):
                        content = json.loads(content)
                    result["extraction_rules"].append(content)
                except:
                    result["extraction_rules"].append(content)
            elif snippet_type == "validation_rule":
                result["validation_rules"].append(content)
            elif snippet_type == "example":
                result["examples"].append(content)
    
    # Log summary
    total_snippets = sum(len(v) for v in result.values())
    logger.info(f"[RAG] Loaded {total_snippets} total snippet(s): "
                f"{len(result['system_messages'])} system_message, "
                f"{len(result['prompt_additions'])} prompt_addition, "
                f"{len(result['extraction_rules'])} extraction_rule, "
                f"{len(result['validation_rules'])} validation_rule, "
                f"{len(result['examples'])} example")
    
    return result


def combine_rag_into_prompt(
    base_system_message: str,
    base_prompt_template: str,
    tag_names: List[str]
) -> tuple[str, str]:
    """
    Combine base prompt with tag-based RAG snippets.
    
    Args:
        base_system_message: Base system message
        base_prompt_template: Base prompt template
        tag_names: List of tag names to apply
    
    Returns:
        (combined_system_message, combined_prompt_template) tuple
    """
    if not tag_names:
        return base_system_message, base_prompt_template
    
    snippets = load_rag_snippets(tag_names)
    
    # Combine system messages
    system_parts = [base_system_message]
    if snippets["system_messages"]:
        system_parts.append("\n\n## Additional Context from Tag-based RAG:")
        system_parts.extend(snippets["system_messages"])
    
    combined_system_message = "\n".join(system_parts)
    
    # Combine prompt additions
    prompt_parts = [base_prompt_template]
    if snippets["prompt_additions"]:
        prompt_parts.append("\n\n## Tag-based Instructions:")
        prompt_parts.extend(snippets["prompt_additions"])
    
    combined_prompt_template = "\n\n".join(prompt_parts)
    
    return combined_system_message, combined_prompt_template


def clear_cache():
    """Clear all caches (for testing or after updating tags/snippets)."""
    global _tag_cache, _snippet_cache, _matching_rules_cache, _cache_populated
    _tag_cache.clear()
    _snippet_cache.clear()
    _matching_rules_cache.clear()
    _cache_populated = False
    logger.info("Tag-based RAG cache cleared")
