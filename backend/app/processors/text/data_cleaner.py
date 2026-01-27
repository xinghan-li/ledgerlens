"""
Data Cleaner: Clean and normalize data fields after LLM processing.

Handles common issues like:
- Date/time fields with newlines or extra text
- Malformed formats
- Inconsistent data
"""
import re
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def clean_llm_result(llm_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean LLM result data, fixing common issues.
    
    Args:
        llm_result: LLM processing result
    
    Returns:
        Cleaned LLM result
    """
    receipt = llm_result.get("receipt", {})
    
    # Clean date field
    if "purchase_date" in receipt and receipt["purchase_date"]:
        receipt["purchase_date"] = clean_date(receipt["purchase_date"])
    
    # Clean time field
    if "purchase_time" in receipt and receipt["purchase_time"]:
        receipt["purchase_time"] = clean_time(receipt["purchase_time"])
    
    return llm_result


def clean_date(date_str: Optional[str]) -> Optional[str]:
    """
    Clean and normalize date string to YYYY-MM-DD format.
    
    Handles cases like:
    - "01-25-20\n01-25-2026 \n13:00\n" -> "2026-01-25"
    - "2026-01-25" -> "2026-01-25"
    - "01/25/2026" -> "2026-01-25"
    
    Args:
        date_str: Raw date string
    
    Returns:
        Cleaned date in YYYY-MM-DD format, or None if invalid
    """
    if not date_str:
        return None
    
    # Remove newlines and extra whitespace
    date_str = date_str.replace("\n", " ").strip()
    
    # Try to find a valid date pattern
    # Pattern 1: YYYY-MM-DD (already correct)
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', date_str)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"
    
    # Pattern 2: MM-DD-YYYY or MM/DD/YYYY
    match = re.search(r'(\d{2})[-/](\d{2})[-/](\d{4})', date_str)
    if match:
        month, day, year = match.groups()
        return f"{year}-{month}-{day}"
    
    # Pattern 3: MM-DD-YY (2-digit year)
    match = re.search(r'(\d{2})[-/](\d{2})[-/](\d{2})\b', date_str)
    if match:
        month, day, year = match.groups()
        # Assume 20xx for years 00-99
        full_year = f"20{year}"
        return f"{full_year}-{month}-{day}"
    
    # Pattern 4: YYYY/MM/DD or MM/DD/YY
    match = re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})', date_str)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    
    logger.warning(f"Could not parse date: {date_str}")
    return None


def clean_time(time_str: Optional[str]) -> Optional[str]:
    """
    Clean and normalize time string to HH:MM:SS format.
    
    Handles cases like:
    - "13:00:00" -> "13:00:00"
    - "13:00" -> "13:00:00"
    - "1:00 PM" -> "13:00:00"
    
    Args:
        time_str: Raw time string
    
    Returns:
        Cleaned time in HH:MM:SS format, or None if invalid
    """
    if not time_str:
        return None
    
    # Remove newlines and extra whitespace
    time_str = time_str.replace("\n", " ").strip()
    
    # Pattern 1: HH:MM:SS AM/PM (check AM/PM first)
    match = re.search(r'(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)', time_str, re.IGNORECASE)
    if match:
        hour, minute, second, meridiem = match.groups()
        hour = int(hour)
        
        if meridiem.upper() == "PM" and hour != 12:
            hour += 12
        elif meridiem.upper() == "AM" and hour == 12:
            hour = 0
        
        return f"{str(hour).zfill(2)}:{minute}:{second}"
    
    # Pattern 2: HH:MM AM/PM (no seconds)
    match = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str, re.IGNORECASE)
    if match:
        hour, minute, meridiem = match.groups()
        hour = int(hour)
        
        if meridiem.upper() == "PM" and hour != 12:
            hour += 12
        elif meridiem.upper() == "AM" and hour == 12:
            hour = 0
        
        return f"{str(hour).zfill(2)}:{minute}:00"
    
    # Pattern 3: HH:MM:SS (24-hour format, no AM/PM)
    match = re.search(r'(\d{1,2}):(\d{2}):(\d{2})', time_str)
    if match:
        hour, minute, second = match.groups()
        return f"{hour.zfill(2)}:{minute}:{second}"
    
    # Pattern 4: HH:MM (24-hour format, no seconds)
    match = re.search(r'(\d{1,2}):(\d{2})\b', time_str)
    if match:
        hour, minute = match.groups()
        return f"{hour.zfill(2)}:{minute}:00"
    
    logger.warning(f"Could not parse time: {time_str}")
    return None
