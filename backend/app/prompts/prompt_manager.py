"""
Prompt Manager: Manage merchant-specific RAG prompts.

Retrieve and cache merchant-specific prompts from Supabase.
Now supports both legacy store_chain_prompts and new tag-based RAG system.
"""
from supabase import create_client, Client
from ..config import settings
from typing import Optional, Dict, Any
import logging
import json
from .tag_based_rag import detect_tags_from_ocr, combine_rag_into_prompt

logger = logging.getLogger(__name__)

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
        "model_name": settings.openai_model,
        "temperature": 0.0,
        "output_schema": _get_default_output_schema(),
    }


def _get_default_system_message() -> str:
    """Default system message."""
    return """You are a receipt parsing expert. Your task is to extract structured information from receipt text and trusted hints from Document AI.

Key requirements:
1. Output ONLY valid JSON, no additional text
2. Follow the exact schema provided
3. Perform validation: quantity × unit_price ≈ line_total (tolerance: ±0.01) - **EXCEPT for package price discounts** (see tag-based instructions)
4. Sum of all line_totals must ≈ total (tolerance: ±0.01)
5. If information is missing or uncertain, set to null and document in tbd
6. Do not hallucinate or guess values
7. **IMPORTANT**: If you see package discount patterns (e.g., "2/$9.00"), follow the tag-based instructions - do NOT validate quantity × unit_price = line_total for those items"""


def _get_default_prompt_template() -> str:
    """Default prompt template."""
    return """Parse the following receipt text and extract structured information.

## Raw Text:
{raw_text}

## Trusted Hints (high confidence fields from Document AI):
{trusted_hints}

## Output Schema:
{output_schema}

## Instructions:
1. Extract receipt-level fields (merchant, date, time, amounts, payment method)
   - **Date format**: Must be YYYY-MM-DD (e.g., "2026-01-25")
   - **Time format**: Must be HH:MM:SS or HH:MM (e.g., "13:00:00" or "13:00")
   - Do NOT include newlines or extra text in date/time fields
   - **Address parsing**: When extracting merchant_address, include the full address with proper structure:
     * Street address should be on first line
     * Unit/Suite/Apt number should be separate (identify by keywords: Suite, Ste, Unit, Apt, #, or format like "#1000-3700" in Canadian addresses)
     * City, State/Province, Zipcode on separate line
     * Country on last line (USA, Canada, etc.)
     * Examples:
       - "19715 Highway 99, Suite 101" → Address includes suite number
       - "#1000-3700 No.3 Rd." → "#1000" is unit number in Canadian format
       - If you see a comma followed by Suite/Unit/Apt, it indicates a separate unit designation
2. Extract all line items from raw_text, ensuring each item has:
   - product_name (cleaned, no extra formatting)
   - quantity and unit (if available)
   - unit_price (if available)
   - line_total (must match quantity × unit_price if both are present, **EXCEPT for package price discounts** - see tag-based instructions)
3. Important: Extract subtotal, tax, and ALL fees/deposits:
   - Extract subtotal ONLY if explicitly stated (e.g., "SUB TOTAL", "Subtotal")
   - Extract tax ONLY if explicitly stated (e.g., "Tax", "GST", "PST", "HST")
   - Extract ALL deposits and fees as separate line items:
     * "Bottle Deposit" → include as item with product_name="Bottle Deposit"
     * "Environment fee", "Environmental fee", "Env fee" → include as item with product_name="Environment fee"
     * "CRF", "Container fee", "Bag fee" → include as items
   - DO NOT calculate or estimate tax by subtracting subtotal from total
   - Deposits, fees, and other charges are NOT tax - they are separate line items
   - If subtotal is not shown: set subtotal to null
   - If tax is not shown: set tax to null
4. Validate calculations (CRITICAL - follow this exact order):
   a) **Line items sum check**: Sum of all line_totals (including deposits, fees, etc.) should ≈ subtotal (±0.03)
      - If subtotal is NOT shown on receipt, skip this check
      - If subtotal IS shown, this MUST pass
   b) **Total sum check**: Starting from subtotal, add each component in order:
      - subtotal + tax + deposits + fees = total (±0.03)
      - Example: If receipt shows "SUB TOTAL: $36.75, Tax: $1.73, Bottle Deposit: $0.05, Environment fee: $0.01, TOTAL: $38.54"
        * Verify: $36.75 + $1.73 + $0.05 + $0.01 = $38.54
      - Extract ALL fees/deposits as separate line items (Bottle Deposit, Environment fee, etc.)
      - Include them in the items array with their exact names and amounts
   c) **Item price validation**: For each item (if quantity and unit_price exist), verify: quantity × unit_price ≈ line_total (±0.01)
      - **EXCEPTION**: If the item is part of a package price discount (e.g., "2/$9.00", "3 for $10"), **SKIP this validation** - use the actual line_total from receipt
5. Document any issues in the "tbd" section:
   - Items with inconsistent price calculations
   - Field conflicts between raw_text and trusted_hints
   - Missing information

## Currency Logic:
- If address is in USA, default currency is USD
- If address is in Canada, default currency is CAD
- If currency is explicitly mentioned in raw_text, use that

## Important:
- If raw_text conflicts with trusted_hints, prefer raw_text and document conflict in tbd
- Do not invent or guess values - use null if information is not available
- Output must be valid JSON matching the schema exactly

Output the JSON now:"""


def _get_default_output_schema() -> Dict[str, Any]:
    """Default output schema."""
    return {
        "receipt": {
            "merchant_name": "string or null",
            "merchant_address": "string or null",
            "merchant_phone": "string or null",
            "country": "string or null",
            "currency": "string (USD, CAD, etc.)",
            "purchase_date": "string (YYYY-MM-DD format ONLY, e.g. '2026-01-25') or null",
            "purchase_time": "string (HH:MM:SS or HH:MM format ONLY, e.g. '13:00:00') or null",
            "subtotal": "number or null",
            "tax": "number or null",
            "total": "number",
            "payment_method": "string or null",
            "card_last4": "string or null"
        },
        "items": [
            {
                "raw_text": "string",
                "product_name": "string or null",
                "quantity": "number or null",
                "unit": "string or null",
                "unit_price": "number or null",
                "line_total": "number or null",
                "is_on_sale": "boolean",
                "category": "string or null"
            }
        ],
        "tbd": {
            "items_with_inconsistent_price": [
                {
                    "raw_text": "string",
                    "product_name": "string or null",
                    "reason": "string (e.g., 'quantity × unit_price (X.XX) does not equal line_total (Y.YY)' or 'Unable to match product name with correct price')"
                }
            ],
            "field_conflicts": {
                "field_name": {
                    "from_raw_text": "value or null",
                    "from_trusted_hints": "value or null",
                    "reason": "string"
                }
            },
            "missing_info": [
                "string (description of missing information)"
            ],
            "total_mismatch": {
                "calculated_total": "number (sum of all line_totals)",
                "documented_total": "number (from receipt total)",
                "difference": "number",
                "reason": "string"
            }
        }
    }


def format_prompt(
    raw_text: str,
    trusted_hints: Dict[str, Any],
    prompt_config: Optional[Dict[str, Any]] = None,
    merchant_name: Optional[str] = None,
    store_chain_id: Optional[str] = None,
    location_id: Optional[str] = None,
    state: Optional[str] = None,
    country_code: Optional[str] = None
) -> tuple[str, str, Dict[str, Any]]:
    """
    Format prompt, prepare to send to LLM.
    Now supports tag-based RAG system.
    
    Args:
        raw_text: Original receipt text
        trusted_hints: High-confidence fields (confidence >= 0.95)
        prompt_config: Prompt configuration (if None, use default)
        merchant_name: Merchant name for tag detection (optional)
        store_chain_id: Store chain ID for tag detection (optional)
        location_id: Store location ID for location-based tag detection (optional)
        state: State/province code for location-based tag detection (optional)
        country_code: Country code for location-based tag detection (optional)
        
    Returns:
        (system_message, user_message, rag_metadata) tuple
        rag_metadata contains information about detected tags and loaded snippets
    """
    if prompt_config is None:
        prompt_config = get_default_prompt()
    
    base_system_message = prompt_config.get("system_message") or _get_default_system_message()
    base_prompt_template = prompt_config.get("prompt_template") or _get_default_prompt_template()
    
    # Detect tags from OCR text, merchant name, and location
    tag_names = []
    rag_metadata = {
        "detected_tags": [],
        "tag_details": [],
        "snippets_loaded": {
            "system_messages": 0,
            "prompt_additions": 0,
            "extraction_rules": 0,
            "validation_rules": 0,
            "examples": 0
        }
    }
    
    if raw_text or merchant_name or location_id or state or country_code:
        try:
            tag_names = detect_tags_from_ocr(
                raw_text=raw_text or "",
                merchant_name=merchant_name,
                store_chain_id=store_chain_id,
                location_id=location_id,
                state=state,
                country_code=country_code
            )
            if tag_names:
                logger.info(f"Detected tags for RAG: {tag_names}")
                rag_metadata["detected_tags"] = tag_names
        except Exception as e:
            logger.warning(f"Failed to detect tags: {e}", exc_info=True)
    
    # Load RAG snippets and combine with base prompt
    if tag_names:
        snippets = load_rag_snippets(tag_names)
        system_message, prompt_template = combine_rag_into_prompt(
            base_system_message=base_system_message,
            base_prompt_template=base_prompt_template,
            tag_names=tag_names
        )
        
        # Record snippet counts
        rag_metadata["snippets_loaded"] = {
            "system_messages": len(snippets.get("system_messages", [])),
            "prompt_additions": len(snippets.get("prompt_additions", [])),
            "extraction_rules": len(snippets.get("extraction_rules", [])),
            "validation_rules": len(snippets.get("validation_rules", [])),
            "examples": len(snippets.get("examples", []))
        }
        
        # Record tag details
        from .tag_based_rag import _tag_cache
        for tag_name in tag_names:
            tag = _tag_cache.get(tag_name)
            if tag:
                rag_metadata["tag_details"].append({
                    "tag_name": tag_name,
                    "tag_type": tag.get("tag_type"),
                    "priority": tag.get("priority", 0)
                })
    else:
        system_message = base_system_message
        prompt_template = base_prompt_template
    
    # Format trusted_hints
    trusted_hints_str = json.dumps(trusted_hints, indent=2, ensure_ascii=False)
    
    # Format output_schema
    output_schema = prompt_config.get("output_schema")
    if isinstance(output_schema, str):
        # If already a string, use directly
        output_schema_str = output_schema
    else:
        # If dict, convert to JSON string
        output_schema = output_schema or _get_default_output_schema()
        output_schema_str = json.dumps(output_schema, indent=2, ensure_ascii=False)
    
    # Format user message
    user_message = prompt_template.format(
        raw_text=raw_text,
        trusted_hints=trusted_hints_str,
        output_schema=output_schema_str
    )
    
    return system_message, user_message


def clear_cache():
    """Clear prompt cache (for testing or after updating prompts)."""
    global _prompt_cache
    _prompt_cache.clear()
    logger.info("Prompt cache cleared")
