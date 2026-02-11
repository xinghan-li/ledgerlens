"""
Float precision utility for reducing token usage in LLM inputs.

Truncates float numbers to 5 decimal places to save tokens when sending
coordinate data to LLMs.
"""
from typing import Any, Dict, List, Union


def truncate_float(value: float, precision: int = 5) -> float:
    """
    Truncate a float to specified decimal places.
    
    Args:
        value: Float value to truncate
        precision: Number of decimal places to keep (default: 5)
    
    Returns:
        Truncated float value
    """
    if not isinstance(value, (float, int)):
        return value
    
    # Convert to float if it's an int
    value = float(value)
    
    # Use string formatting to truncate (not round)
    format_str = f"{{:.{precision}f}}"
    truncated_str = format_str.format(value)
    
    # Convert back to float
    return float(truncated_str)


def truncate_floats_in_dict(data: Dict[str, Any], precision: int = 5) -> Dict[str, Any]:
    """
    Recursively truncate all float values in a dictionary.
    
    Args:
        data: Dictionary to process
        precision: Number of decimal places to keep
    
    Returns:
        Dictionary with truncated float values
    """
    result = {}
    
    for key, value in data.items():
        if isinstance(value, float):
            result[key] = truncate_float(value, precision)
        elif isinstance(value, dict):
            result[key] = truncate_floats_in_dict(value, precision)
        elif isinstance(value, list):
            result[key] = truncate_floats_in_list(value, precision)
        else:
            result[key] = value
    
    return result


def truncate_floats_in_list(data: List[Any], precision: int = 5) -> List[Any]:
    """
    Recursively truncate all float values in a list.
    
    Args:
        data: List to process
        precision: Number of decimal places to keep
    
    Returns:
        List with truncated float values
    """
    result = []
    
    for item in data:
        if isinstance(item, float):
            result.append(truncate_float(item, precision))
        elif isinstance(item, dict):
            result.append(truncate_floats_in_dict(item, precision))
        elif isinstance(item, list):
            result.append(truncate_floats_in_list(item, precision))
        else:
            result.append(item)
    
    return result


def truncate_floats_in_result(result: Dict[str, Any], precision: int = 5) -> Dict[str, Any]:
    """
    Truncate float values in processor result, especially in ocr_blocks.
    
    This is the main function to call at the end of each processor.
    It focuses on ocr_blocks and other coordinate-heavy fields.
    
    Args:
        result: Processor result dictionary
        precision: Number of decimal places to keep (default: 5)
    
    Returns:
        Result with truncated float values
    """
    # Process the entire result recursively
    return truncate_floats_in_dict(result, precision)
