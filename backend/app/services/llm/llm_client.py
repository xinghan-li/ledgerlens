"""
OpenAI LLM Client: Call OpenAI API for receipt parsing.
"""
from openai import OpenAI
from ...config import settings
from typing import Dict, Any, Optional
import logging
import json

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
        logger.info(f"Calling OpenAI API with model: {model}")
        
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
        logger.info("OpenAI API call successful")
        
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
