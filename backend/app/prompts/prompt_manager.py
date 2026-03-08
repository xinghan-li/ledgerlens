"""
Prompt Manager: Manage prompts for receipt parsing.

Uses prompt_library + prompt_binding (replaces legacy tag-based RAG).
Resolves prompts by scope: default + chain + location.
"""
from datetime import datetime, timezone
from supabase import create_client, Client
from ..config import settings
from typing import Optional, Dict, Any
import logging
import json
from .prompt_loader import load_prompts_for_receipt_parse

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
3. **All monetary amounts must be output in CENTS (integer), not dollars.** For example: $14.99 → 1499, $198.59 → 19859. This applies to receipt.subtotal, receipt.tax, receipt.total, receipt.fees, and every item's line_total, unit_price, original_price, discount_amount. We use cents to avoid floating-point errors; do not output decimals for money.
4. Perform validation in cents: quantity × unit_price ≈ line_total (tolerance: ±1 cent) - **EXCEPT for package price discounts** (see tag-based instructions)
5. Sum of all line_totals must ≈ total (tolerance: ±1 cent)
6. If information is missing or uncertain, set to null and document in tbd
7. Do not hallucinate or guess values
8. **IMPORTANT**: If you see package discount patterns (e.g., "2/$9.00"), follow the tag-based instructions - do NOT validate quantity × unit_price = line_total for those items
9. **NEW**: If an Initial Parse Result is provided, use it as a reference to reduce hallucination. The initial parse is from a rule-based system that extracts items, totals, and validation from OCR coordinates. Cross-check your extraction with the initial parse result, but correct any OCR errors you find in product names.
10. **User-facing notes (all stores)**: Our database stores monetary amounts in CENTS. In any free-text shown to the user (e.g. reason, tbd.notes, sum_check_notes, reasoning, or validation notes), always write amounts in DOLLARS with a $ sign (e.g. $198.59, $114.07). Never write raw cents (e.g. 19859, 11407) in these text fields.
11. If you cannot be confident or need to escalate, set top-level "reason" to your finding; otherwise omit or null. Still output the best-effort JSON."""


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
REFERENCE DATE (today): {reference_date}. Any receipt date on or before this date is valid; use the date exactly as printed on the receipt.

1. Extract receipt-level fields (merchant, date, time, amounts, payment method)
   - **Date format**: Must be YYYY-MM-DD (e.g., "2026-01-25"). Use the date EXACTLY as printed on the receipt; do NOT substitute or correct the year (e.g. if the receipt shows 2026, output 2026; never change it to the current year).
   - **Canadian date ambiguity**: Some Canadian stores print dates as YY/MM/DD (e.g. "26/03/07" = 2026-03-07) rather than MM/DD/YY. If the store is in Canada and BOTH YY/MM/DD and MM/DD/YY produce seemingly valid dates, choose the interpretation whose result is closest to the REFERENCE DATE.
   - **Time format**: Must be HH:MM:SS or HH:MM (e.g., "13:00:00" or "13:00")
   - Do NOT include newlines or extra text in date/time fields
   - **Payment**: Use full card brand name for payment_method (e.g. "Discover" not "DCVR", "Visa" not "VISA"). card_last4 = last 4 digits only (e.g. "3713" from "DCVR ************3713").
   - **Address (CRITICAL — output separate fields for DB)**: Do NOT put the whole address in merchant_address only. Output these separate fields so we can write correctly to the database:
     * **address_line1**: Street address only (e.g. "19715 Highway 99", "19630 Hwy 99"). No unit/suite, no city/state/zip.
     * **address_line2**: Unit/plaza/mall number only — output the number alone (e.g. "101", "200", "1000"). Do NOT include prefixes like "Suite", "Unit", "Apt", "#". Omit if not on receipt.
     * **city**: City name only (e.g. "Lynnwood", "Surrey").
     * **state**: State or province code/name (e.g. "WA", "BC").
     * **zip_code**: Zip or postal code only (e.g. "98036", "V3T 0A1").
     * **country**: Country code or name (e.g. "US", "USA", "Canada").
     * **merchant_address**: Optional fallback; if you fill the fields above, we will build the display address from them. You may set to null when structured fields are present.
     * Examples: "19715 Highway 99, Suite 101, Lynnwood, WA 98036" → address_line1="19715 Highway 99", address_line2="101", city="Lynnwood", state="WA", zip_code="98036". "#1000-3700 No.3 Rd." → address_line2="1000" (number only).
2. Extract all line items from raw_text, ensuring each item has:
   - product_name (cleaned, no extra formatting)
   - quantity and unit (if available)
   - unit_price (if available)
   - line_total (must match quantity × unit_price if both are present, **EXCEPT for package price discounts** - see tag-based instructions)
3. Important: Extract subtotal, tax, and ALL fees/deposits:
   - Extract subtotal ONLY if explicitly stated (e.g., "SUB TOTAL", "Subtotal")
{costco_usa_totals_instructions}
   - Extract tax ONLY if explicitly stated (e.g., "Tax", "GST", "PST", "HST")
   - Extract ALL deposits and fees as separate line items:
     * "Bottle Deposit" → include as item with product_name="Bottle Deposit"
     * "Environment fee", "Environmental fee", "Env fee" → include as item with product_name="Environment fee"
     * "CRF", "Container fee", "Bag fee" → include as items
   - DO NOT calculate or estimate tax by subtracting subtotal from total
   - Deposits, fees, and other charges are NOT tax - they are separate line items
   - If subtotal is not shown: set subtotal to null
   - If tax is not shown: set tax to null
4. **Monetary output**: All amounts (subtotal, tax, total, fees, line_total, unit_price, etc.) must be integers in CENTS (e.g. $36.75 → 3675). No floats for money.
5. Validate calculations (CRITICAL - follow this exact order, all in cents):
   a) **Line items sum check**: Sum of all line_totals (including deposits, fees, etc.) should ≈ subtotal (±3 cents)
      - If subtotal is NOT shown on receipt, skip this check
      - If subtotal IS shown, this MUST pass
   b) **Total sum check**: Starting from subtotal, add each component in order:
      - subtotal + tax + deposits + fees = total (±3 cents)
      - Example: If receipt shows "SUB TOTAL: $36.75, Tax: $1.73, Bottle Deposit: $0.05, Environment fee: $0.01, TOTAL: $38.54"
        * Output as cents: subtotal 3675, tax 173, bottle 5, env 1, total 3854; verify 3675+173+5+1=3854
      - Extract ALL fees/deposits as separate line items (Bottle Deposit, Environment fee, etc.)
      - Include them in the items array with their exact names and amounts (amounts in cents)
   c) **Item price validation**: For each item (if quantity and unit_price exist), verify: quantity × unit_price ≈ line_total (±1 cent)
      - **EXCEPTION**: If the item is part of a package price discount (e.g., "2/$9.00", "3 for $10"), **SKIP this validation** - use the actual line_total from receipt
6. Document any issues in the "tbd" section:
   - Items with inconsistent price calculations
   - Field conflicts between raw_text and trusted_hints
   - Missing information
   - In tbd.notes, reason, or any user-facing text: always write monetary amounts in dollars (e.g. $198.59), never in raw cents (e.g. 19859).

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
    """Default output schema. All monetary amounts in cents (integer) to avoid floating point."""
    return {
        "reason": "string or null (if escalating or not confident, explain here; otherwise omit or null)",
        "receipt": {
            "merchant_name": "string or null",
            "merchant_address": "string or null (optional; prefer filling structured address fields below)",
            "address_line1": "string or null (street address only, no unit no city/state/zip)",
            "address_line2": "string or null (unit/plaza number only, e.g. 101, 200 — no Suite/Unit/# prefix)",
            "city": "string or null",
            "state": "string or null (state or province)",
            "zip_code": "string or null (zip or postal code)",
            "country": "string or null",
            "merchant_phone": "string or null",
            "currency": "string (USD, CAD, etc.)",
            "purchase_date": "string (YYYY-MM-DD format ONLY, e.g. '2026-01-25') or null",
            "purchase_time": "string (HH:MM:SS or HH:MM format ONLY, e.g. '13:00:00') or null",
            "subtotal": "integer or null (amount in CENTS, e.g. 19859 for $198.59)",
            "tax": "integer or null (amount in CENTS)",
            "total": "integer (amount in CENTS)",
            "payment_method": "string or null",
            "card_last4": "string or null"
        },
        "items": [
            {
                "raw_text": "string",
                "product_name": "string or null",
                "quantity": "number or null",
                "unit": "string or null",
                "unit_price": "integer or null (amount in CENTS)",
                "line_total": "integer or null (amount in CENTS)",
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
