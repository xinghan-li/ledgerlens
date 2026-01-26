"""
CSV Exporter: Converts receipt JSON data to CSV format and appends to daily CSV files.

CSV Format:
- UserID (dummy for now)
- Date
- Time
- Class1, Class2, Class3 (category hierarchy, future feature)
- ItemName (product name)
- Amount (line_total)
- OnSale
- Payment Type
- Vendor (name, address, state, country, zip code)
"""
import csv
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pathlib import Path
import re

from ..processors.enrichment.payment_types import normalize_payment_type

logger = logging.getLogger(__name__)


def parse_address(address_str: Optional[str]) -> Dict[str, str]:
    """
    Parse address string into components.
    
    Expected format: "19630 Hwy 99, Lynnwood, WA 98036" or similar
    Returns: {"name": "", "address": "", "state": "", "country": "", "zip": ""}
    """
    result = {
        "name": "",
        "address": "",
        "state": "",
        "country": "",
        "zip": ""
    }
    
    if not address_str:
        return result
    
    original_address = address_str
    
    # Try to extract zip code (5 digits at the end)
    zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', address_str)
    if zip_match:
        result["zip"] = zip_match.group(1)
    
    # Try to extract state (2-letter code, usually before zip)
    state_match = re.search(r'\b([A-Z]{2})\b', address_str)
    if state_match:
        result["state"] = state_match.group(1)
    
    # Try to extract country (if explicitly mentioned)
    country_match = re.search(r'\b(USA|US|United States|Canada|CA)\b', address_str, re.IGNORECASE)
    if country_match:
        country = country_match.group(1).upper()
        if country in ["USA", "US", "United States"]:
            result["country"] = "US"
        elif country in ["CA", "Canada"]:
            result["country"] = "CA"
    
    # For address field, use the full original address string
    # (we'll format it properly in the vendor string)
    result["address"] = original_address
    
    return result


def extract_payment_type(payment_method: Optional[str]) -> str:
    """
    Extract and normalize payment type to one of the valid categories.
    
    Uses the payment_types module to ensure all outputs are valid.
    
    Args:
        payment_method: Raw payment method string from receipt
    
    Returns:
        Normalized payment type (one of: Visa, Master, American Express, Discover, Cash, Gift Card, Others, Unknown)
    """
    return normalize_payment_type(payment_method)


def convert_receipt_to_csv_rows(
    llm_result: Dict[str, Any],
    user_id: str = "dummy"
) -> List[Dict[str, Any]]:
    """
    Convert receipt JSON data to CSV rows (one row per item).
    
    Args:
        llm_result: Full LLM result JSON
        user_id: User ID (default: "dummy")
    
    Returns:
        List of dictionaries, each representing a CSV row
    """
    from ..processors.enrichment.address_matcher import extract_address_components_from_string
    
    receipt = llm_result.get("receipt", {})
    items = llm_result.get("items", [])
    
    # Extract receipt-level information
    purchase_date = receipt.get("purchase_date", "")
    purchase_time = receipt.get("purchase_time", "")
    merchant_name = receipt.get("merchant_name", "")
    merchant_address = receipt.get("merchant_address", "")
    payment_method = receipt.get("payment_method", "")
    currency = receipt.get("currency", "")
    
    # Extract payment type
    payment_type = extract_payment_type(payment_method)
    
    # Parse address into components
    address_components = extract_address_components_from_string(merchant_address)
    
    # IMPORTANT: If receipt has country field set (e.g., from address_matcher),
    # use it to override the parsed country from address string
    if receipt.get("country"):
        address_components["country"] = receipt.get("country")
    
    # Convert each item to a CSV row
    rows = []
    for item in items:
        # Extract category (currently single level, future: Class1, Class2, Class3)
        category = item.get("category", "")
        class1 = category  # For now, use category as Class1
        class2 = ""  # Future: subcategory
        class3 = ""  # Future: sub-subcategory
        
        row = {
            "UserID": user_id,
            "Date": purchase_date,
            "Time": purchase_time,
            "Class1": class1,
            "Class2": class2,
            "Class3": class3,
            "ItemName": item.get("product_name", ""),
            "Amount": item.get("line_total", ""),
            "Currency": currency,
            "OnSale": "Yes" if item.get("is_on_sale", False) else "No",
            "Payment Type": payment_type,
            "Vendor": merchant_name,
            "Address1": address_components["address1"],
            "Address2": address_components["address2"],
            "City": address_components["city"],
            "State": address_components["state"],
            "Country": address_components["country"],
            "ZipCode": address_components["zipcode"]
        }
        rows.append(row)
    
    return rows


def append_to_daily_csv(
    csv_path: Path,
    rows: List[Dict[str, Any]],
    csv_headers: List[str]
):
    """
    Append rows to daily CSV file with intelligent fallback.
    
    If the existing CSV has different headers (schema mismatch), creates a new file
    with suffix (1), (2), etc., like Windows default behavior.
    
    Args:
        csv_path: Path to CSV file
        rows: List of dictionaries to append
        csv_headers: List of CSV column headers
    """
    if not rows:
        logger.warning("No rows to append to CSV")
        return
    
    # Find the appropriate CSV file to use
    target_csv_path = _find_or_create_csv_path(csv_path, csv_headers)
    
    # Ensure parent directory exists
    target_csv_path.parent.mkdir(parents=True, exist_ok=True)
    
    file_exists = target_csv_path.exists()
    
    try:
        with open(target_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_headers)
            
            # Write headers if file is new
            if not file_exists or target_csv_path.stat().st_size == 0:
                writer.writeheader()
            
            # Write rows
            for row in rows:
                writer.writerow(row)
        
        logger.info(f"Appended {len(rows)} rows to CSV: {target_csv_path}")
    
    except Exception as e:
        logger.error(f"Failed to append to CSV {target_csv_path}: {e}")
        raise


def _find_or_create_csv_path(csv_file_path: Path, headers: List[str]) -> Path:
    """
    Find appropriate CSV file path, creating a new one if headers mismatch.
    
    If the file exists but has different headers, creates a new file with suffix:
    - original.csv
    - original(1).csv
    - original(2).csv
    - etc.
    
    Args:
        csv_file_path: Original CSV file path
        headers: Expected headers
    
    Returns:
        Path to use for CSV writing
    """
    # If file doesn't exist, use it
    if not csv_file_path.exists():
        return csv_file_path
    
    # If file is empty, use it
    if csv_file_path.stat().st_size == 0:
        return csv_file_path
    
    # Check if headers match
    try:
        with open(csv_file_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            existing_headers = reader.fieldnames
            
            # Headers match, use this file
            if existing_headers and list(existing_headers) == headers:
                return csv_file_path
            
            # Headers mismatch, need to create a new file
            logger.warning(
                f"CSV headers mismatch in {csv_file_path.name}. "
                f"Expected: {headers}, Got: {existing_headers}. "
                f"Creating new file with suffix."
            )
    
    except Exception as e:
        logger.warning(f"Error reading CSV headers from {csv_file_path}: {e}. Using original file.")
        return csv_file_path
    
    # Find next available filename with suffix
    base_name = csv_file_path.stem  # e.g., "20260126"
    suffix = csv_file_path.suffix  # e.g., ".csv"
    parent_dir = csv_file_path.parent
    
    counter = 1
    while True:
        new_name = f"{base_name}({counter}){suffix}"
        new_path = parent_dir / new_name
        
        # If this file doesn't exist, use it
        if not new_path.exists():
            logger.info(f"Creating new CSV file: {new_name}")
            return new_path
        
        # If this file exists and is empty, use it
        if new_path.stat().st_size == 0:
            logger.info(f"Using empty CSV file: {new_name}")
            return new_path
        
        # If this file exists and has matching headers, use it
        try:
            with open(new_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                existing_headers = reader.fieldnames
                
                if existing_headers and list(existing_headers) == headers:
                    logger.info(f"Using existing CSV file with matching headers: {new_name}")
                    return new_path
        
        except Exception:
            pass
        
        # Try next counter
        counter += 1
        
        # Safety limit to avoid infinite loop
        if counter > 100:
            logger.error(f"Too many CSV file variants (>100). Using original file.")
            return csv_file_path


def get_csv_headers() -> List[str]:
    """Get CSV column headers in the correct order."""
    return [
        "UserID",
        "Date",
        "Time",
        "Class1",
        "Class2",
        "Class3",
        "ItemName",
        "Amount",
        "Currency",
        "OnSale",
        "Payment Type",
        "Vendor",
        "Address1",
        "Address2",
        "City",
        "State",
        "Country",
        "ZipCode"
    ]
