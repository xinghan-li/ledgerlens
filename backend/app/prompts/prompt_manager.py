"""
Prompt Manager: Manage merchant-specific RAG prompts.

Retrieve and cache merchant-specific prompts from Supabase.
"""
from supabase import create_client, Client
from ..config import settings
from typing import Optional, Dict, Any
import logging
import json

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


def get_merchant_prompt(merchant_name: str, merchant_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Get merchant-specific prompt.
    
    Args:
        merchant_name: Merchant name
        merchant_id: Optional merchant ID (if known)
        
    Returns:
        Prompt configuration dictionary, containing prompt_template, system_message, model_name, etc.
    """
    # Check cache
    cache_key = merchant_name.lower().strip()
    if cache_key in _prompt_cache:
        logger.debug(f"Using cached prompt for merchant: {merchant_name}")
        return _prompt_cache[cache_key]
    
    supabase = _get_client()
    
    try:
        # First try to find by merchant_id
        query = supabase.table("merchant_prompts").select("*").eq("is_active", True)
        
        if merchant_id:
            query = query.eq("merchant_id", merchant_id)
        else:
            # Find by merchant_name
            query = query.ilike("merchant_name", f"%{merchant_name}%")
        
        res = query.order("version", desc=True).limit(1).execute()
        
        if res.data and len(res.data) > 0:
            prompt_data = res.data[0]
            # If model_name not set in database, use default from environment variables
            if not prompt_data.get("model_name"):
                prompt_data["model_name"] = settings.openai_model
            # Cache result
            _prompt_cache[cache_key] = prompt_data
            logger.info(f"Loaded prompt for merchant: {merchant_name} (ID: {prompt_data.get('id')})")
            return prompt_data
        
        # If not found, return default prompt
        logger.warning(f"No custom prompt found for merchant: {merchant_name}, using default")
        return get_default_prompt()
        
    except Exception as e:
        logger.error(f"Failed to load prompt for merchant {merchant_name}: {e}")
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
3. Perform validation: quantity × unit_price ≈ line_total (tolerance: ±0.01)
4. Sum of all line_totals must ≈ total (tolerance: ±0.01)
5. If information is missing or uncertain, set to null and document in tbd
6. Do not hallucinate or guess values"""


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
   - line_total (must match quantity × unit_price if both are present)
3. Important: Extract subtotal and tax ONLY if explicitly stated on the receipt
   - If subtotal is not shown: set subtotal to null
   - If tax is not shown: set tax to null
   - DO NOT calculate or estimate tax by subtracting subtotal from total
   - Deposits, fees, and other charges are NOT tax
4. Validate calculations:
   - For each item: if quantity and unit_price exist, verify: quantity × unit_price ≈ line_total (±0.01)
   - Sum all line_totals should ≈ total (±0.03)
   - If subtotal exists: sum of product line_totals should ≈ subtotal (may exclude deposits/fees)
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
    prompt_config: Optional[Dict[str, Any]] = None
) -> tuple[str, str]:
    """
    Format prompt, prepare to send to LLM.
    
    Args:
        raw_text: Original receipt text
        trusted_hints: High-confidence fields (confidence >= 0.95)
        prompt_config: Prompt configuration (if None, use default)
        
    Returns:
        (system_message, user_message) tuple
    """
    if prompt_config is None:
        prompt_config = get_default_prompt()
    
    system_message = prompt_config.get("system_message") or _get_default_system_message()
    
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
    user_message = prompt_config.get("prompt_template", _get_default_prompt_template()).format(
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
