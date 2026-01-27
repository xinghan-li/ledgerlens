"""
Gemini Rate Limiter: Manage Gemini API free tier limit (15 requests/minute).

Uses UTC time, resets counter every minute.
Uses asyncio.Lock to ensure thread safety.
"""
from datetime import datetime, timezone
from typing import Dict, Tuple
import logging
import asyncio

logger = logging.getLogger(__name__)

# Thread-safe state management
_lock = asyncio.Lock()
_current_minute: str = ""
_counter: int = 0
_max_requests_per_minute: int = 15


async def check_gemini_available() -> Tuple[bool, str]:
    """
    Check if Gemini is available (not exceeding free tier limit).
    
    Note: This function is async and uses a lock to ensure thread safety.
    
    Returns:
        (is_available, reason): 
        - is_available: True if Gemini can be used, False otherwise
        - reason: Reason for unavailability (empty string if available)
    """
    global _current_minute, _counter
    
    async with _lock:
        # Get current UTC time minute (format: YYYY-MM-DD HH:MM)
        now = datetime.now(timezone.utc)
        current_minute_str = now.strftime("%Y-%m-%d %H:%M")
        
        # If minute changed, reset counter
        if current_minute_str != _current_minute:
            logger.info(f"Gemini rate limiter: New minute {current_minute_str}, resetting counter")
            _current_minute = current_minute_str
            _counter = 0
        
        # Check if exceeded limit
        if _counter >= _max_requests_per_minute:
            reason = (
                f"Gemini free tier rate limit exceeded: {_counter}/{_max_requests_per_minute} "
                f"requests in the current minute. Request will be queued and retried after the "
                f"rate limit window resets."
            )
            logger.warning(reason)
            return False, reason
        
        # Increment counter
        _counter += 1
        logger.debug(f"Gemini rate limiter: {_counter}/{_max_requests_per_minute} requests this minute")
        return True, ""


async def record_gemini_request() -> Dict[str, any]:
    """
    Record Gemini request (for statistics and timeline).
    
    Note: This function is async and uses a lock to ensure read consistency.
    
    Returns:
        Dictionary containing request information
    """
    async with _lock:
        now = datetime.now(timezone.utc)
        return {
            "timestamp": now.isoformat(),
            "minute": now.strftime("%Y-%m-%d %H:%M"),
            "count_this_minute": _counter
        }


async def get_current_status() -> Dict[str, any]:
    """
    Get current rate limiter status (for debugging).
    
    Note: This function is async and uses a lock to ensure read consistency.
    
    Returns:
        Status information dictionary
    """
    async with _lock:
        return {
            "current_minute": _current_minute,
            "counter": _counter,
            "max_per_minute": _max_requests_per_minute,
            "available": _counter < _max_requests_per_minute
        }
