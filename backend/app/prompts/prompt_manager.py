"""
Prompt Manager: Manage prompts for receipt parsing.

Core prompts (system message, prompt template, output schema) are loaded from
local files under prompts/templates/ (git-tracked). Store-specific prompts
remain in the database (prompt_library + prompt_binding).
"""
from datetime import datetime, timezone
from pathlib import Path
from supabase import create_client, Client
from ..config import settings
from typing import Optional, Dict, Any
import logging
import json
from .prompt_loader import load_prompts_for_receipt_parse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local template files (git-tracked)
# ---------------------------------------------------------------------------
_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_template(filename: str) -> Optional[str]:
    """Load a prompt template file. Returns None if file missing."""
    path = _TEMPLATES_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    logger.warning("[PromptManager] Template file not found: %s", path)
    return None

# Singleton Supabase client
_supabase: Optional[Client] = None

# In-memory cache for prompts
_prompt_cache: Dict[str, Dict[str, Any]] = {}


def _get_client() -> Client:
    """Get or create the Supabase client."""
    global _supabase
    if _supabase is None:
        if not settings.supabase_url or not settings.supabase_anon_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment"
            )
        
        key = settings.supabase_service_role_key or settings.supabase_anon_key
        _supabase = create_client(settings.supabase_url, key)
        logger.info("Supabase client initialized for prompt manager")
    
    return _supabase


def get_merchant_prompt(
    merchant_name: str, 
    merchant_id: Optional[str] = None,
    location_id: Optional[str] = None,
    country_code: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Get default prompt configuration.
    
    NOTE: This function now returns default prompt only. Tag-based RAG system
    (via format_prompt()) automatically enhances prompts based on detected tags.
    
    Args:
        merchant_name: Store chain name (for logging only)
        merchant_id: Optional chain_id (for logging only)
        location_id: Optional location_id (for logging only)
        country_code: Optional country code (for logging only)
        
    Returns:
        Default prompt configuration dictionary
    """
    # Always return default prompt - tag-based RAG will enhance it
    logger.debug(f"Using default prompt for merchant: {merchant_name} (tag-based RAG will enhance)")
    return get_default_prompt()


def get_default_prompt() -> Dict[str, Any]:
    """
    Return default prompt template.
    
    Used when no merchant-specific prompt is found.
    """
    return {
        "prompt_template": _get_default_prompt_template(),
        "system_message": _get_default_system_message(),
        "model_name": settings.gemini_model,
        "temperature": 0.0,
        "output_schema": _get_default_output_schema(),
    }


def _get_default_system_message() -> str:
    """Load system message from local file (git-tracked)."""
    content = _load_template("system_message.txt")
    if content:
        return content
    raise RuntimeError(
        "System message template not found at prompts/templates/system_message.txt"
    )


def _get_default_prompt_template() -> str:
    """Load prompt template from local file (git-tracked)."""
    content = _load_template("prompt_template.txt")
    if content:
        return content
    raise RuntimeError(
        "Prompt template file not found at prompts/templates/prompt_template.txt"
    )


def _get_default_output_schema() -> Dict[str, Any]:
    """Load output schema from local JSON file (git-tracked)."""
    content = _load_template("output_schema.json")
    if content:
        return json.loads(content)
    raise RuntimeError(
        "Output schema file not found at prompts/templates/output_schema.json"
    )


def format_prompt(
    raw_text: str,
    trusted_hints: Dict[str, Any],
    prompt_config: Optional[Dict[str, Any]] = None,
    merchant_name: Optional[str] = None,
    store_chain_id: Optional[str] = None,
    location_id: Optional[str] = None,
    state: Optional[str] = None,
    country_code: Optional[str] = None,
    initial_parse_result: Optional[Dict[str, Any]] = None
) -> tuple[str, str, Dict[str, Any]]:
    """
    Format prompt from prompt_library + prompt_binding, prepare to send to LLM.
    
    Args:
        raw_text: Original receipt text
        trusted_hints: High-confidence fields (confidence >= 0.95)
        prompt_config: Prompt configuration (if None, use default)
        merchant_name: Merchant name (for logging)
        store_chain_id: Store chain ID for chain-scoped bindings
        location_id: Store location ID for location-scoped bindings
        state: State/province (for future fee policy injection)
        country_code: Country code (for future fee policy injection)
        initial_parse_result: Optional rule-based extraction result to guide LLM
        
    Returns:
        (system_message, user_message, rag_metadata) tuple
    """
    if prompt_config is None:
        prompt_config = get_default_prompt()
    
    rag_metadata: Dict[str, Any] = {
        "library_parts_loaded": 0,
        "user_template_from_library": False,
        "schema_from_library": False,
    }
    
    # Load prompts from prompt_library + prompt_binding
    try:
        loaded = load_prompts_for_receipt_parse(
            prompt_key="receipt_parse",
            store_chain_id=store_chain_id,
            location_id=location_id,
        )
    except Exception as e:
        logger.warning(f"Failed to load prompts from library: {e}, using defaults", exc_info=True)
        loaded = {"system_parts": [], "user_template": None, "schema": None}
    
    # Build system message from loaded parts (or fallback to default)
    if loaded["system_parts"]:
        # Fill placeholders in system parts: store_specific_region_rules, location_specific_rules, additional_rules
        filled_parts = []
        for part in loaded["system_parts"]:
            filled = part.replace("{store_specific_region_rules}", "").replace(
                "{location_specific_rules}", ""
            ).replace("{additional_rules}", "")
            filled_parts.append(filled)
        system_message = "\n\n".join(filled_parts)
        rag_metadata["library_parts_loaded"] = len(loaded["system_parts"])
    else:
        system_message = prompt_config.get("system_message") or _get_default_system_message()
    
    # User template: use library or fallback
    prompt_template = loaded.get("user_template") or prompt_config.get("prompt_template") or _get_default_prompt_template()
    rag_metadata["user_template_from_library"] = loaded.get("user_template") is not None
    
    # Schema: use library or fallback
    output_schema = prompt_config.get("output_schema")
    schema_str = loaded.get("schema")
    if schema_str:
        try:
            output_schema = json.loads(schema_str)
        except Exception:
            output_schema = output_schema or _get_default_output_schema()
        rag_metadata["schema_from_library"] = True
    else:
        output_schema = output_schema or _get_default_output_schema()
    
    # Format trusted_hints
    trusted_hints_str = json.dumps(trusted_hints, indent=2, ensure_ascii=False)
    
    # Format output_schema for user message
    if isinstance(output_schema, str):
        output_schema_str = output_schema
    else:
        output_schema_str = json.dumps(output_schema, indent=2, ensure_ascii=False)

    # Costco USA only: first subtotal/total and CC Rewards instructions (do not apply to other chains)
    costco_usa_totals_instructions = ""
    if merchant_name and "costco" in (merchant_name or "").lower():
        if (country_code or "").upper() not in ("CA", "CANADA") and "canada" not in (merchant_name or "").lower():
            costco_usa_totals_instructions = (
                "   - **Use the FIRST occurrence** of SUBTOTAL and TOTAL only. If the receipt shows a first SUBTOTAL/TAX/TOTAL block and later a line like \"CC Rewards $X.XX\" and then a second subtotal, record receipt.subtotal and receipt.total from the **first** block (e.g. SUBTOTAL $198.59, TOTAL $198.59), NOT the second (e.g. $114.07). The amount after CC Rewards is the amount charged to the card, not the receipt total for our records.\n"
                "   - If there is a \"CC Rewards\" or \"Credit Card Rewards\" line (a negative/credit applied after the first total), record payment_method as the card type plus \" / CC Rewards\" (e.g. \"Visa / CC Rewards\"). Do not use the second subtotal/total that appears after the rewards line.\n"
                "   - **Costco USA Liquor Tax**: Washington state and some other states impose a liquor excise tax on alcohol shown as a separate 'LIQUOR TAX' (or 'LIQ TAX', 'LIQUOR EXCISE') line on the receipt. **Include this as a regular line item** in the items array with product_name='Liquor Tax', is_on_sale=false. Do NOT absorb it into receipt.tax or skip it. The SUBTOTAL on Costco USA receipts equals the sum of all item line_totals INCLUDING the Liquor Tax line item — verify: items_sum (including Liquor Tax item) ≈ receipt.subtotal. **CRITICAL**: always use the SUBTOTAL value printed on the receipt directly; never compute or adjust it. If the items sum check fails even after including Liquor Tax as a line item, document the discrepancy in tbd and escalate.\n"
            )
    
    # Add initial parse result to user message if available
    initial_parse_str = ""
    if initial_parse_result and initial_parse_result.get("success"):
        # Create a simplified version for LLM (exclude ocr_blocks to save tokens)
        initial_parse_summary = {
            "method": initial_parse_result.get("method"),
            "chain_id": initial_parse_result.get("chain_id"),
            "store": initial_parse_result.get("store"),
            "address": initial_parse_result.get("address"),
            "items": initial_parse_result.get("items", []),
            "totals": initial_parse_result.get("totals", {}),
            "validation": initial_parse_result.get("validation", {})
        }
        initial_parse_str = f"""

## Initial Parse Result (Rule-Based Extraction):
We have already run a rule-based parser on the OCR data. Please use this as a reference along with the raw OCR text to generate the final structured JSON. This initial parse helps reduce hallucination.

```json
{json.dumps(initial_parse_summary, indent=2, ensure_ascii=False)}
```

**IMPORTANT**: The initial parse result above is from our rule-based system. It may not be 100% accurate due to OCR errors, but it provides a good starting point. Please:
1. Verify item names, quantities, and prices against the raw text
2. Correct any OCR errors you find (e.g., "SAMUCAS" → "SAMOSAS", "IKKA" → "TIKKA")
3. If the initial parse found items and totals, use them as guidance but cross-check with raw text
4. If validation in initial parse failed, investigate and correct the extraction
"""
        rag_metadata["initial_parse_provided"] = True
        rag_metadata["initial_parse_method"] = initial_parse_result.get("method")
        rag_metadata["initial_parse_items_count"] = len(initial_parse_result.get("items", []))
    else:
        rag_metadata["initial_parse_provided"] = False
    
    # Format user message (default template has {costco_usa_totals_instructions}, {reference_date}; library template may not)
    reference_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    format_kwargs = {
        "raw_text": raw_text,
        "trusted_hints": trusted_hints_str,
        "output_schema": output_schema_str,
        "reference_date": reference_date,
    }
    if "{costco_usa_totals_instructions}" in (prompt_template or ""):
        format_kwargs["costco_usa_totals_instructions"] = costco_usa_totals_instructions
    user_message = prompt_template.format(**format_kwargs) + initial_parse_str
    
    return system_message, user_message, rag_metadata


def clear_cache():
    """Clear prompt cache (for testing or after updating prompts)."""
    global _prompt_cache
    _prompt_cache.clear()
    from .prompt_loader import clear_cache as clear_loader_cache
    clear_loader_cache()
    logger.info("Prompt cache cleared")
