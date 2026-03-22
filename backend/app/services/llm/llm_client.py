"""
OpenAI LLM Client: Call OpenAI API for receipt parsing.
Supports text-only and vision (image + prompt) for escalation.

DEPRECATED (2025-03-21): This module is no longer used. The pipeline is Gemini-only.
Kept for reference; will be removed in a future cleanup.
"""
from openai import OpenAI
from ...config import settings
from typing import Dict, Any, Optional
import logging
import json
import base64

logger = logging.getLogger(__name__)

# Singleton OpenAI client
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    """Get or create OpenAI client."""
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable must be set"
            )
        
        _client = OpenAI(api_key=settings.openai_api_key)
        logger.info("OpenAI client initialized")
    
    return _client


def parse_receipt_with_llm(
    system_message: str,
    user_message: str,
    model: str = None,
    temperature: float = 0.0
) -> Dict[str, Any]:
    """
    Parse receipt using OpenAI LLM.
    
    Args:
        system_message: System message
        user_message: User message (contains raw_text and trusted_hints)
        model: Model name (if None, uses default from config)
        temperature: Temperature parameter
        
    Returns:
        Parsed JSON data
    """
    client = _get_client()
    model = model or settings.openai_model
    
    try:
        logger.info(f"OpenAI API call: model={model}")

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            temperature=temperature,
            response_format={"type": "json_object"},  # Force JSON output
        )
        
        content = response.choices[0].message.content

        # Parse JSON
        try:
            parsed_data = json.loads(content)
            return parsed_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from OpenAI response: {e}")
            logger.error(f"Response content: {content[:500]}")  # Log first 500 characters
            raise ValueError(f"Invalid JSON response from OpenAI: {e}")
        
    except Exception as e:
        logger.error(f"OpenAI API call failed: {e}")
        raise


def parse_receipt_with_openai_vision(
    image_bytes: bytes,
    instruction: str,
    model: str,
    mime_type: str = "image/jpeg",
) -> Dict[str, Any]:
    """
    Parse receipt by sending the receipt image + instruction to OpenAI (vision).
    Used for escalation when cascade fails; model should be the escalation model (e.g. gpt-5.1).

    Args:
        image_bytes: Raw image bytes.
        instruction: Full prompt (system + user) asking for structured JSON.
        model: Model name (e.g. from settings.openai_escalation_model).
        mime_type: Image MIME type.

    Returns:
        Parsed receipt JSON (receipt + items structure).
    """
    client = _get_client()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"
    content = [
        {"type": "text", "text": instruction},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    try:
        logger.info(f"Calling OpenAI vision with model={model}, image size={len(image_bytes)} bytes")
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        out = json.loads(raw)
        return out
    except json.JSONDecodeError as e:
        logger.error(f"OpenAI vision returned invalid JSON: {e}")
        raise ValueError(f"Invalid JSON from OpenAI vision: {e}")
    except Exception as e:
        logger.error(f"OpenAI vision call failed: {e}")
        raise
