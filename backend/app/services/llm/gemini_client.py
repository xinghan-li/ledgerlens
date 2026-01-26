"""
Google Gemini LLM Client: Call Google Gemini API for receipt parsing.
"""
import google.generativeai as genai
from ...config import settings
from typing import Dict, Any, Optional
import logging
import json

logger = logging.getLogger(__name__)

# Thread-safe state management
import asyncio
_lock = asyncio.Lock()
_client_configured = False


async def _configure_client():
    """
    Configure Gemini client (only needs to be called once).
    
    Note: This function is async and uses a lock to ensure thread safety.
    """
    global _client_configured
    
    async with _lock:
        if not _client_configured:
            if not settings.gemini_api_key:
                raise ValueError(
                    "GEMINI_API_KEY environment variable must be set"
                )
            
            genai.configure(api_key=settings.gemini_api_key)
            _client_configured = True
            logger.info("Google Gemini client configured")


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
    await _configure_client()
    model = model or settings.gemini_model
    
    # Add debug logs to confirm the model being used
    logger.info(f"Gemini model from settings: {settings.gemini_model}")
    logger.info(f"Using Gemini model: {model}")
    
    try:
        # Create GenerativeModel
        generative_model = genai.GenerativeModel(model)
        
        # Merge system_message and user_message (Gemini doesn't directly support system message)
        # Solution: Put system_message at the beginning of user_message
        combined_message = f"{system_message}\n\n{user_message}"
        
        # Configure generation parameters
        generation_config = {
            "temperature": temperature,
            "response_mime_type": "application/json",  # Force JSON output
        }
        
        logger.info(f"Calling Google Gemini API with model: {model}")
        
        # Call API
        response = generative_model.generate_content(
            combined_message,
            generation_config=generation_config
        )
        
        content = response.text.strip()
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
