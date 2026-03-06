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

# Message to show when Gemini API key is rejected by Google
_GEMINI_KEY_INVALID_HINT = (
    "Gemini API key was rejected. Get a valid key from https://aistudio.google.com/apikey "
    "and set GEMINI_API_KEY in backend/.env. If using a Google Cloud key, enable "
    "'Generative Language API' in your project. Then restart the backend."
)

# Thread-safe state management
import asyncio
_lock = asyncio.Lock()
_client = None


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
        
        # Configure generation settings (google-genai: use config, not generation_config)
        config = genai.types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
        )

        logger.info(f"Gemini API call: model={model}")

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
    )

    logger.info(f"Gemini vision retry: model={model}")
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
) -> Tuple[Dict[str, Any], Optional[Dict[str, int]]]:
    """
    Escalation path: send receipt image + single instruction to Gemini (vision).
    Same instruction is used for both OpenAI and Gemini escalation for consensus.
    Returns (parsed_json, usage_dict). usage_dict has input_tokens, output_tokens (or None).
    """
    client = await _get_client()
    blob = types.Blob(data=image_bytes, mime_type=mime_type)
    parts = [
        types.Part(inline_data=blob),
        types.Part(text=instruction),
    ]
    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
    )
    logger.info(f"Gemini vision escalation: model={model}")
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
