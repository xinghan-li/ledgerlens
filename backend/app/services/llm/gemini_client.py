"""
Google Gemini LLM Client: Call Google Gemini API for receipt parsing.
"""
import google.genai as genai
from ...config import settings
from typing import Dict, Any, Optional
import logging
import json

logger = logging.getLogger(__name__)

# Thread-safe state management
import asyncio
_lock = asyncio.Lock()
_client = None


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
    temperature: float = 0.0
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
    
    # Add debug logs to confirm the model being used
    logger.info(f"Gemini model from settings: {settings.gemini_model}")
    logger.info(f"Using Gemini model: {model}")
    
    try:
        # Merge system_message and user_message
        # In the new API, we can use system_instruction parameter
        combined_message = f"{system_message}\n\n{user_message}"
        
        # Configure generation settings to ensure JSON output
        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
            response_mime_type="application/json",
        )
        
        logger.info(f"Calling Google Gemini API with model: {model}")
        logger.debug(f"Gemini API call - message length: {len(combined_message)} chars")
        
        # Call API using the new google.genai API
        try:
            response = client.models.generate_content(
                model=model,
                contents=combined_message,
                generation_config=generation_config
            )
            logger.debug(f"Gemini API response received: {type(response)}")
        except Exception as api_error:
            logger.error(f"Gemini API call exception: {type(api_error).__name__}: {api_error}")
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
        
        logger.info("Google Gemini API call successful")
        
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
