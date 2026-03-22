"""
Google Gemini LLM Client: Call Google Gemini API for receipt parsing.
Supports text-only and vision (image + text) modes.
"""
import google.genai as genai
from google.genai import types
from ...config import settings
from typing import Dict, Any, Optional, Tuple
import logging
import json

from .gemini_rate_limiter import set_gemini_key_invalid

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Receipt output schema for Gemini Structured Output (response_schema)
# ---------------------------------------------------------------------------
# This schema enforces the JSON structure at the API level.
# All monetary fields are integers in CENTS.
# Note: "nullable": True is supported by google-genai SDK (verified v0.2+).
RECEIPT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string", "nullable": True},
        "receipt": {
            "type": "object",
            "properties": {
                "merchant_name": {"type": "string", "nullable": True},
                "merchant_address": {"type": "string", "nullable": True},
                "address_line1": {"type": "string", "nullable": True},
                "address_line2": {"type": "string", "nullable": True},
                "city": {"type": "string", "nullable": True},
                "state": {"type": "string", "nullable": True},
                "zip_code": {"type": "string", "nullable": True},
                "country": {"type": "string", "nullable": True},
                "merchant_phone": {"type": "string", "nullable": True},
                "currency": {"type": "string", "nullable": True},
                "purchase_date": {"type": "string", "nullable": True},
                "purchase_time": {"type": "string", "nullable": True},
                "subtotal": {"type": "integer", "nullable": True},
                "tax": {"type": "integer", "nullable": True},
                "total": {"type": "integer", "nullable": True},
                "payment_method": {"type": "string", "nullable": True},
                "card_last4": {"type": "string", "nullable": True},
            },
            "required": ["total"],
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw_text": {"type": "string"},
                    "product_name": {"type": "string", "nullable": True},
                    "quantity": {"type": "number", "nullable": True},
                    "unit": {"type": "string", "nullable": True},
                    "unit_price": {"type": "integer", "nullable": True},
                    "line_total": {"type": "integer", "nullable": True},
                    "is_on_sale": {"type": "boolean"},
                    "category": {"type": "string", "nullable": True},
                },
                "required": ["raw_text"],
            },
        },
        "tbd": {
            "type": "object",
            "properties": {
                "items_with_inconsistent_price": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "raw_text": {"type": "string"},
                            "product_name": {"type": "string", "nullable": True},
                            "reason": {"type": "string"},
                        },
                    },
                },
                "missing_info": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "notes": {"type": "string", "nullable": True},
            },
        },
        "metadata": {
            "type": "object",
            "properties": {
                "validation_status": {"type": "string", "nullable": True},
                "validation_reasoning": {"type": "string", "nullable": True},
                "sum_check_notes": {"type": "string", "nullable": True},
                "needs_review": {"type": "boolean", "nullable": True},
                "needs_review_reason": {"type": "string", "nullable": True},
                "item_count": {"type": "integer", "nullable": True},
            },
        },
    },
    "required": ["receipt", "items"],
}

# Message to show when Gemini API key is rejected by Google
_GEMINI_KEY_INVALID_HINT = (
    "Gemini API key was rejected. Get a valid key from https://aistudio.google.com/apikey "
    "and set GEMINI_API_KEY in backend/.env. If using a Google Cloud key, enable "
    "'Generative Language API' in your project. Then restart the backend."
)

# Thread-safe state management
import asyncio
import time
_lock = asyncio.Lock()
_client = None

# ---------------------------------------------------------------------------
# Context caching for vision prompts
# ---------------------------------------------------------------------------
# Caches the system instruction so repeated calls (e.g., bulk upload) don't
# re-send the same long prompt every time.  TTL = 1 hour.
_cached_content_name: Optional[str] = None
_cached_content_instruction: Optional[str] = None   # instruction text that was cached
_cached_content_model: Optional[str] = None          # model the cache was created for
_cached_content_expires: float = 0                   # time.time() when cache expires
_CACHE_TTL_SECONDS = 3600  # 1 hour


async def _get_or_create_vision_cache(
    instruction: str,
    model: str,
) -> Optional[str]:
    """
    Return the cached_content resource name for the given instruction + model.
    Creates a new cache if none exists or the current one is stale/expired.
    Returns None if caching fails (caller should fall back to inline prompt).
    """
    global _cached_content_name, _cached_content_instruction
    global _cached_content_model, _cached_content_expires

    # Reuse existing cache if instruction, model match and not expired
    now = time.time()
    if (
        _cached_content_name
        and _cached_content_instruction == instruction
        and _cached_content_model == model
        and now < _cached_content_expires
    ):
        return _cached_content_name

    try:
        client = await _get_client()
        cached = client.caches.create(
            model=model,
            config={
                "display_name": "ledgerlens-vision-prompt",
                "system_instruction": instruction,
                "ttl": f"{_CACHE_TTL_SECONDS}s",
            },
        )
        _cached_content_name = cached.name
        _cached_content_instruction = instruction
        _cached_content_model = model
        _cached_content_expires = now + _CACHE_TTL_SECONDS - 60  # refresh 1 min early
        logger.info("[cache] Created vision prompt cache: %s (ttl=%ds)", cached.name, _CACHE_TTL_SECONDS)
        return cached.name
    except Exception as exc:
        logger.warning("[cache] Failed to create context cache: %s — falling back to inline prompt", exc)
        _cached_content_name = None
        return None


def _handle_gemini_api_error(api_error: Exception, context: str) -> None:
    """If error is 400 API key invalid, mark key invalid and log actionable message."""
    err_str = str(api_error).lower()
    is_key_error = (
        "api key not valid" in err_str
        or "api_key_invalid" in err_str
        or ("api key" in err_str and "invalid" in err_str)
    )
    if is_key_error:
        set_gemini_key_invalid(True)
        logger.error(
            "%s call failed: %s. %s",
            context,
            api_error,
            _GEMINI_KEY_INVALID_HINT,
        )
    else:
        logger.error("%s API call failed: %s", context, api_error)


async def _get_client():
    """
    Get or create Gemini client (only needs to be called once).
    
    Note: This function is async and uses a lock to ensure thread safety.
    """
    global _client
    
    async with _lock:
        if _client is None:
            if not settings.gemini_api_key:
                raise ValueError(
                    "GEMINI_API_KEY environment variable must be set"
                )
            
            _client = genai.Client(api_key=settings.gemini_api_key)
            logger.info("Google Gemini client configured")
        
        return _client


async def parse_receipt_with_gemini(
    system_message: str,
    user_message: str,
    model: str = None,
    temperature: float = 0,
) -> Dict[str, Any]:
    """
    Parse receipt using Google Gemini LLM.
    
    Note: This function is async and uses a lock to ensure thread safety of client configuration.
    
    Args:
        system_message: System message
        user_message: User message (contains raw_text and trusted_hints)
        model: Model name (if None, uses default from config)
        temperature: Temperature parameter
    
    Returns:
        Parsed JSON data
    """
    client = await _get_client()
    model = model or settings.gemini_model
    
    try:
        # Merge system_message and user_message
        # In the new API, we can use system_instruction parameter
        combined_message = f"{system_message}\n\n{user_message}"
        
        # Configure generation settings with Structured Output
        config = genai.types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=RECEIPT_OUTPUT_SCHEMA,
        )

        logger.info(f"Gemini API call: model={model} (structured output)")

        # Call API using google-genai SDK (config param, not generation_config)
        try:
            response = client.models.generate_content(
                model=model,
                contents=combined_message,
                config=config,
            )
        except Exception as api_error:
            _handle_gemini_api_error(api_error, "Gemini text")
            raise
        
        # Extract text from response
        # The new API structure may be different
        if hasattr(response, 'text'):
            content = response.text.strip()
        elif hasattr(response, 'candidates') and response.candidates:
            # Fallback: try to get text from candidates
            if hasattr(response.candidates[0], 'content'):
                if hasattr(response.candidates[0].content, 'parts'):
                    content = response.candidates[0].content.parts[0].text.strip()
                elif hasattr(response.candidates[0].content, 'text'):
                    content = response.candidates[0].content.text.strip()
                else:
                    raise ValueError("Unexpected response format from Gemini API")
            else:
                raise ValueError("Unexpected response format from Gemini API")
        else:
            raise ValueError("Unexpected response format from Gemini API")
        
        # Parse JSON (Gemini sometimes wraps it with ```json)
        content = _extract_json_from_response(content)
        
        try:
            parsed_data = json.loads(content)
            return parsed_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Gemini response: {e}")
            logger.error(f"Response content: {content[:500]}")  # Log first 500 characters
            raise ValueError(f"Invalid JSON response from Gemini: {e}")
        
    except Exception as e:
        logger.error(f"Google Gemini API call failed: {e}")
        raise


async def parse_receipt_with_gemini_vision(
    image_bytes: bytes,
    failure_context: str,
    output_schema_json: str,
    mime_type: str = "image/jpeg",
    model: Optional[str] = None,
    temperature: float = 0,
) -> Dict[str, Any]:
    """
    Parse receipt by sending the receipt image + failure context to Gemini (vision).
    Used when the first Gemini call (with OCR text) failed: we ask the model to look at
    the image and correct the extraction, outputting the same structured JSON.

    Args:
        image_bytes: Raw image bytes (receipt photo).
        failure_context: What went wrong in the previous attempt (error message / context).
        output_schema_json: JSON string of the expected output schema (receipt + items + tbd).
        mime_type: Image MIME type (e.g. image/jpeg, image/png).
        model: Gemini model name (default from config).
        temperature: Generation temperature.

    Returns:
        Parsed receipt JSON (same structure as text-based parse).
    """
    client = await _get_client()
    model = model or settings.gemini_model

    instruction = f"""You are parsing a receipt. A previous attempt using OCR text failed with the following context:

{failure_context}

Below is the actual receipt image. Look at the image and extract the receipt data correctly. Output valid JSON matching this schema exactly (same structure as before):

{output_schema_json}

Instructions:
1. Extract all line items with product_name, quantity, unit, unit_price, line_total.
2. Extract receipt-level fields: merchant_name, merchant_address, purchase_date, purchase_time, subtotal, tax, total, payment_method, card_last4 if visible.
3. Ensure sum of line_totals ≈ subtotal and subtotal + tax + fees = total (±0.03).
4. Output only the JSON object, no markdown or extra text."""

    blob = types.Blob(data=image_bytes, mime_type=mime_type)
    parts = [
        types.Part(inline_data=blob),
        types.Part(text=instruction),
    ]

    config = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=RECEIPT_OUTPUT_SCHEMA,
    )

    logger.info(f"Gemini vision retry: model={model} (structured output)")
    try:
        response = client.models.generate_content(
            model=model,
            contents=parts,
            config=config,
        )
    except Exception as api_error:
        _handle_gemini_api_error(api_error, "Gemini vision")
        raise

    if hasattr(response, "text"):
        content = response.text.strip()
    elif hasattr(response, "candidates") and response.candidates:
        c0 = response.candidates[0]
        if hasattr(c0, "content"):
            if hasattr(c0.content, "parts") and c0.content.parts:
                content = c0.content.parts[0].text.strip()
            elif hasattr(c0.content, "text"):
                content = c0.content.text.strip()
            else:
                raise ValueError("Unexpected Gemini vision response format")
        else:
            raise ValueError("Unexpected Gemini vision response format")
    else:
        raise ValueError("Unexpected Gemini vision response format")

    content = _extract_json_from_response(content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from Gemini vision response: {e}")
        raise ValueError(f"Invalid JSON response from Gemini vision: {e}")


def _usage_from_gemini_response(response: Any) -> Optional[Dict[str, int]]:
    """Extract token usage from Gemini GenerateContentResponse. Returns None if not available."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None
    in_tok = getattr(usage, "prompt_token_count", None) or getattr(usage, "promptTokenCount", None)
    out_tok = getattr(usage, "candidates_token_count", None) or getattr(usage, "candidatesTokenCount", None)
    if in_tok is None and out_tok is None:
        return None
    return {"input_tokens": in_tok, "output_tokens": out_tok}


async def parse_receipt_with_gemini_vision_escalation(
    image_bytes: bytes,
    instruction: str,
    model: str,
    mime_type: str = "image/jpeg",
    use_cache: bool = True,
) -> Tuple[Dict[str, Any], Optional[Dict[str, int]]]:
    """
    Send receipt image + instruction to Gemini (vision).
    Used for both primary vision call and escalation.
    When use_cache=True, attempts to cache the instruction via Context Caching
    to reduce token costs on repeated calls.
    Returns (parsed_json, usage_dict). usage_dict has input_tokens, output_tokens (or None).
    """
    client = await _get_client()
    blob = types.Blob(data=image_bytes, mime_type=mime_type)

    # Try context caching: instruction goes into cache, only image is sent per-call
    cache_name = None
    if use_cache:
        cache_name = await _get_or_create_vision_cache(instruction, model)

    if cache_name:
        # Cached path: instruction is in the cache, only send the image
        parts = [types.Part(inline_data=blob)]
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=RECEIPT_OUTPUT_SCHEMA,
            cached_content=cache_name,
        )
        logger.info(f"Gemini vision (cached): model={model}")
    else:
        # Fallback: send instruction inline
        parts = [
            types.Part(inline_data=blob),
            types.Part(text=instruction),
        ]
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=RECEIPT_OUTPUT_SCHEMA,
        )
        logger.info(f"Gemini vision (inline): model={model}")

    try:
        response = client.models.generate_content(
            model=model,
            contents=parts,
            config=config,
        )
    except Exception as api_error:
        _handle_gemini_api_error(api_error, "Gemini vision escalation")
        raise
    usage = _usage_from_gemini_response(response)
    if hasattr(response, "text"):
        content = response.text.strip()
    elif hasattr(response, "candidates") and response.candidates:
        c0 = response.candidates[0]
        if hasattr(c0, "content"):
            if hasattr(c0.content, "parts") and c0.content.parts:
                content = c0.content.parts[0].text.strip()
            elif hasattr(c0.content, "text"):
                content = c0.content.text.strip()
            else:
                raise ValueError("Unexpected Gemini vision escalation response format")
        else:
            raise ValueError("Unexpected Gemini vision escalation response format")
    else:
        raise ValueError("Unexpected Gemini vision escalation response format")
    content = _extract_json_from_response(content)
    try:
        return json.loads(content), usage
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from Gemini vision escalation: {e}")
        raise ValueError(f"Invalid JSON from Gemini vision escalation: {e}")


async def is_image_receipt_like(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    model: Optional[str] = None,
) -> bool:
    """
    Ask Gemini vision whether the image looks like a receipt (for OCR-fail branch).
    Returns True if yes, False if no. On API error, returns True (assume receipt-like and continue).
    """
    client = await _get_client()
    model = model or settings.gemini_model
    blob = types.Blob(data=image_bytes, mime_type=mime_type)
    prompt = "Does this image show a receipt (e.g. a store receipt with items and a total amount)? Answer with exactly one word: yes or no."
    parts = [types.Part(inline_data=blob), types.Part(text=prompt)]
    config = types.GenerateContentConfig(temperature=0)
    try:
        response = client.models.generate_content(model=model, contents=parts, config=config)
        if hasattr(response, "text"):
            text = (response.text or "").strip().lower()
        elif hasattr(response, "candidates") and response.candidates:
            c0 = response.candidates[0]
            if hasattr(c0, "content") and hasattr(c0.content, "parts") and c0.content.parts:
                text = (c0.content.parts[0].text or "").strip().lower()
            else:
                text = "yes"
        else:
            text = "yes"
        return text.startswith("yes")
    except Exception as e:
        logger.warning(f"Gemini is_image_receipt_like failed: {e}, assuming receipt-like")
        return True


def _extract_json_from_response(text: str) -> str:
    """
    Extract JSON from response (handles possible markdown code blocks).
    
    Gemini sometimes wraps JSON with ```json or ```.
    """
    text = text.strip()
    
    # Check if wrapped with ```json
    if text.startswith('```json'):
        # Find first ```json and last ```
        start = text.find('```json') + 7
        end = text.rfind('```')
        if end > start:
            text = text[start:end].strip()
    elif text.startswith('```'):
        # Check if wrapped with ``` (no language identifier)
        start = text.find('```') + 3
        end = text.rfind('```')
        if end > start:
            text = text[start:end].strip()
    
    return text
