"""
Export store candidates to CSV file.

This script:
1. Queries all pending store_candidates from database
2. Extracts structured metadata (address, phone, currency, etc.)
3. Exports to CSV file in output/store_locations/ folder
4. CSV filename format: YYYYMMDD-HHMM-pending_store_locations.csv

Args:
    simplified: If True, outputs raw format. If False, applies formatting rules.
"""
import sys
from pathlib import Path
from datetime import datetime
import csv
import re
from typing import List, Dict, Any, Optional, Tuple

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database.supabase_client import _get_client


def title_case(text: str) -> str:
    """Convert text to title case (first letter of each word capitalized)."""
    if not text:
        return ""
    return text.title()


def parse_chain_and_location(raw_name: str) -> Tuple[str, str]:
    """
    Parse store name to extract chain name and location.
    
    Handles patterns like:
    - "T&T Supermarket Lynnwood" -> ("T&T Supermarket", "Lynnwood")
    - "COSTCO WHOLESALE" -> ("Costco Wholesale", "")
    - "99 Ranch Market" -> ("99 Ranch Market", "")
    
    Returns:
        (chain_name, location_name)
    """
    if not raw_name:
        return ("", "")
    
    # Common patterns: "Chain Name Location" or "Chain Name - Location"
    # Try to identify if there's a location suffix
    raw_name_clean = raw_name.strip()
    
    # Pattern 1: "Chain Name Location" (e.g., "T&T Supermarket Lynnwood")
    # Look for common location indicators (city names, state abbreviations, etc.)
    # For now, simple heuristic: if last word is capitalized and not a common chain word, it might be location
    words = raw_name_clean.split()
    
    # Known chain-only words that shouldn't be split
    chain_words = {"supermarket", "market", "wholesale", "store", "drugs", "pharmacy", "burger", "restaurant"}
    
    # If last word is not a chain word and name has more than 2 words, try to split
    if len(words) > 2 and words[-1].lower() not in chain_words:
        # Check if last word looks like a location (capitalized, short)
        last_word = words[-1]
        if last_word[0].isupper() and len(last_word) > 2:
            chain_name = " ".join(words[:-1])
            location_name = last_word
            return (title_case(chain_name), title_case(location_name))
    
    # Pattern 2: "Chain Name - Location" (e.g., "TNT Supermarket - Osaka Branch")
    if " - " in raw_name_clean:
        parts = raw_name_clean.split(" - ", 1)
        chain_name = parts[0].strip()
        location_name = parts[1].strip()
        # Remove "Branch" suffix if present
        if location_name.lower().endswith(" branch"):
            location_name = location_name[:-7].strip()
        return (title_case(chain_name), title_case(location_name))
    
    # No location found, return whole name as chain
    return (title_case(raw_name_clean), "")


def format_zipcode(zipcode: str, country: str) -> str:
    """
    Format zipcode according to country rules.
    
    - US: Ensure 5 digits (pad with leading 0 if needed for East Coast)
    - Canada: Format as V0V 0V0 (ensure space in middle)
    
    Args:
        zipcode: Raw zipcode string
        country: Country code (USA, US, Canada, CA, etc.)
    
    Returns:
        Formatted zipcode
    """
    if not zipcode:
        return ""
    
    # Remove spaces and convert to uppercase
    zip_clean = re.sub(r'\s+', '', zipcode.upper())
    
    country_upper = country.upper() if country else ""
    
    # Canadian postal code: V0V0V0 -> V0V 0V0
    if country_upper in ("CANADA", "CA"):
        if len(zip_clean) == 6 and zip_clean[0].isalpha() and zip_clean[1].isdigit():
            return f"{zip_clean[:3]} {zip_clean[3:]}"
        return zipcode  # Return as-is if doesn't match pattern
    
    # US zipcode: Ensure 5 digits
    if country_upper in ("USA", "US"):
        # Extract only digits
        digits = re.sub(r'\D', '', zip_clean)
        if len(digits) < 5:
            # Pad with leading zeros (for East Coast 0-prefixed zipcodes)
            digits = digits.zfill(5)
        elif len(digits) > 5:
            # Take first 5 digits (for ZIP+4 format)
            digits = digits[:5]
        return digits
    
    # Other countries: return as-is
    return zipcode


def format_phone(phone: str) -> str:
    """
    Format phone number to 000-000-0000 format.
    
    Removes:
    - Parentheses: (425) -> 425
    - Plus signs: +1 -> removed
    - Dots: 425.670.0623 -> 425-670-0623
    - Spaces
    
    Args:
        phone: Raw phone string
    
    Returns:
        Formatted phone in 000-000-0000 format
    """
    if not phone:
        return ""
    
    # Remove all non-digit characters except keep structure
    digits = re.sub(r'\D', '', phone)
    
    # Remove leading 1 if present (US country code)
    if digits.startswith('1') and len(digits) == 11:
        digits = digits[1:]
    
    # Format as 000-000-0000 if we have 10 digits
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    
    # If not 10 digits, return cleaned version
    return digits


def format_address_components(
    address1: str,
    address2: str,
    city: str,
    state: str,
    country: str,
    zipcode: str
) -> Dict[str, str]:
    """
    Format address components with proper capitalization.
    
    Returns:
        Dictionary with formatted address components
    """
    return {
        "address1": title_case(address1) if address1 else "",
        "address2": title_case(address2) if address2 else "",
        "city": title_case(city) if city else "",
        "state": state.upper() if state else "",  # State should be uppercase
        "country": title_case(country) if country else "",
        "zipcode": format_zipcode(zipcode, country) if zipcode else "",
    }


def export_store_candidates_to_csv(simplified: bool = True):
    """
    Export all pending store candidates to CSV.
    
    Args:
        simplified: If True, outputs raw format. If False, applies formatting rules.
    """
    try:
        supabase = _get_client()
        
        # Query all pending store candidates
        response = supabase.table("store_candidates").select("*").eq("status", "pending").execute()
        
        if not response.data:
            print("No pending store candidates found.")
            return
        
        candidates = response.data
        print(f"Found {len(candidates)} pending store candidates")
        
        # Prepare CSV data
        csv_rows = []
        for candidate in candidates:
            metadata = candidate.get("metadata", {}) or {}
            address_info = metadata.get("address", {}) or {}
            
            raw_name = candidate.get("raw_name", "")
            
            if simplified:
                # Simplified format: output raw data
                row = {
                    "id": candidate.get("id"),
                    "raw_name": raw_name,
                    "normalized_name": candidate.get("normalized_name"),
                    "source": candidate.get("source"),
                    "receipt_id": candidate.get("receipt_id"),
                    "suggested_chain_id": candidate.get("suggested_chain_id"),
                    "suggested_location_id": candidate.get("suggested_location_id"),
                    "confidence_score": candidate.get("confidence_score"),
                    "status": candidate.get("status"),
                    "created_at": candidate.get("created_at"),
                    # Address fields
                    "full_address": address_info.get("full_address", ""),
                    "address1": address_info.get("address1", ""),
                    "address2": address_info.get("address2", ""),
                    "city": address_info.get("city", ""),
                    "state": address_info.get("state", ""),
                    "country": address_info.get("country", ""),
                    "zipcode": address_info.get("zipcode", ""),
                    # Contact and other info
                    "phone": metadata.get("phone", ""),
                    "currency": metadata.get("currency", ""),
                    "purchase_date": metadata.get("purchase_date", ""),
                    "purchase_time": metadata.get("purchase_time", ""),
                }
            else:
                # Formatted format: apply all formatting rules
                chain_name, location_name = parse_chain_and_location(raw_name)
                formatted_address = format_address_components(
                    address_info.get("address1", ""),
                    address_info.get("address2", ""),
                    address_info.get("city", ""),
                    address_info.get("state", ""),
                    address_info.get("country", ""),
                    address_info.get("zipcode", "")
                )
                
                row = {
                    "id": candidate.get("id"),
                    "chain_name": chain_name,
                    "location_name": location_name,
                    "raw_name": raw_name,  # Keep original for reference
                    "normalized_name": candidate.get("normalized_name"),
                    "source": candidate.get("source"),
                    "receipt_id": candidate.get("receipt_id"),
                    "suggested_chain_id": candidate.get("suggested_chain_id"),
                    "suggested_location_id": candidate.get("suggested_location_id"),
                    "confidence_score": candidate.get("confidence_score"),
                    "status": candidate.get("status"),
                    "created_at": candidate.get("created_at"),
                    # Formatted address fields
                    "address1": formatted_address["address1"],
                    "address2": formatted_address["address2"],
                    "city": formatted_address["city"],
                    "state": formatted_address["state"],
                    "country": formatted_address["country"],
                    "zipcode": formatted_address["zipcode"],
                    # Formatted phone
                    "phone": format_phone(metadata.get("phone", "")),
                    "currency": metadata.get("currency", ""),
                    "purchase_date": metadata.get("purchase_date", ""),
                    "purchase_time": metadata.get("purchase_time", ""),
                }
            
            csv_rows.append(row)
        
        # Define CSV headers based on format
        if simplified:
            headers = [
                "id",
                "raw_name",
                "normalized_name",
                "source",
                "receipt_id",
                "suggested_chain_id",
                "suggested_location_id",
                "confidence_score",
                "status",
                "created_at",
                "full_address",
                "address1",
                "address2",
                "city",
                "state",
                "country",
                "zipcode",
                "phone",
                "currency",
                "purchase_date",
                "purchase_time",
            ]
        else:
            headers = [
                "id",
                "chain_name",
                "location_name",
                "raw_name",
                "normalized_name",
                "source",
                "receipt_id",
                "suggested_chain_id",
                "suggested_location_id",
                "confidence_score",
                "status",
                "created_at",
                "address1",
                "address2",
                "city",
                "state",
                "country",
                "zipcode",
                "phone",
                "currency",
                "purchase_date",
                "purchase_time",
            ]
        
        # Create output directory
        # Path(__file__).parent.parent.parent is project root
        # backend/scripts/export_store_candidates.py -> backend/scripts -> backend -> project root
        project_root = Path(__file__).parent.parent.parent
        output_dir = project_root / "output" / "store_locations"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with timestamp
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d-%H%M")
        format_suffix = "simplified" if simplified else "formatted"
        filename = f"{timestamp}-pending_store_locations_{format_suffix}.csv"
        csv_path = output_dir / filename
        
        # Write CSV file
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(csv_rows)
        
        print(f"[SUCCESS] Exported {len(csv_rows)} store candidates to: {csv_path}")
        print(f"  CSV file: {csv_path.relative_to(project_root)}")
        print(f"  Format: {'Simplified (raw)' if simplified else 'Formatted (with rules)'}")
        
    except Exception as e:
        print(f"[ERROR] Error exporting store candidates: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Export store candidates to CSV")
    parser.add_argument(
        "--simplified",
        action="store_true",
        default=True,
        help="Output simplified (raw) format (default: True)"
    )
    parser.add_argument(
        "--formatted",
        action="store_true",
        help="Output formatted format with rules applied"
    )
    
    args = parser.parse_args()
    
    # If --formatted is specified, use formatted format; otherwise use simplified
    simplified = not args.formatted
    
    export_store_candidates_to_csv(simplified=simplified)
