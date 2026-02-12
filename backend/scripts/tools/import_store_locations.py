"""
Import store locations from Excel file directly to database.

This script:
1. Reads Excel file from input/store_locations/
2. Creates or finds store chains in store_chains table
3. Creates store locations in store_locations table (matching chain_id via chain_name)
4. All data is inserted directly into the database via SQL
"""
import sys
from pathlib import Path
import pandas as pd
from typing import Dict, Any, Optional

# ============================================
# Configuration Variables
# ============================================
# Input Excel file path (relative to project root)
INPUT_EXCEL_PATH = "input/store_locations/20260130-1324-pending_store_locations.xlsx"

# ============================================
# Script Logic
# ============================================

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database.supabase_client import _get_client


def normalize_name(name: str) -> str:
    """Normalize store name for matching (lowercase, strip)."""
    if not name:
        return ""
    return name.lower().strip()


def extract_chain_name(raw_name: str, location_name: str = "") -> str:
    """
    Extract chain name from raw_name or use location_name if available.
    
    If location_name is provided and different from raw_name, 
    assume raw_name contains both chain and location.
    """
    if not raw_name:
        return ""
    
    # If location_name is provided and raw_name contains it, extract chain
    if location_name and location_name in raw_name:
        # Try to remove location from raw_name
        chain = raw_name.replace(location_name, "").strip()
        # Clean up common separators
        chain = chain.rstrip(" -,").strip()
        if chain:
            return chain
    
    return raw_name.strip()


def get_or_create_chain(supabase, chain_name: str) -> tuple[str, bool]:
    """
    Get existing chain or create new one.
    
    Args:
        supabase: Supabase client
        chain_name: Store chain name
    
    Returns:
        (chain_id, was_created): Tuple of chain_id (UUID string) and boolean indicating if it was newly created
    """
    if not chain_name:
        raise ValueError("Chain name cannot be empty")
    
    normalized = normalize_name(chain_name)
    
    # Try to find existing chain
    response = supabase.table("store_chains").select("id").eq("normalized_name", normalized).execute()
    
    if response.data:
        chain_id = response.data[0]["id"]
        print(f"  Found existing chain: {chain_name} (id: {chain_id})")
        return (chain_id, False)
    
    # Create new chain
    payload = {
        "name": chain_name,
        "normalized_name": normalized,
        "aliases": [],
        "is_active": True
    }
    
    try:
        res = supabase.table("store_chains").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to create chain, no data returned")
        chain_id = res.data[0]["id"]
        print(f"  Created new chain: {chain_name} (id: {chain_id})")
        return (chain_id, True)
    except Exception as e:
        print(f"  [ERROR] Failed to create chain '{chain_name}': {e}")
        raise


def create_store_location(
    supabase,
    chain_id: str,
    location_name: str,
    address_line1: Optional[str] = None,
    address_line2: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
    country_code: Optional[str] = None
) -> tuple[Optional[str], bool]:
    """
    Create store location.
    
    Args:
        supabase: Supabase client
        chain_id: Chain ID (UUID string)
        location_name: Location name
        address_line1: Address line 1
        address_line2: Address line 2
        city: City
        state: State/Province
        zip_code: ZIP/Postal code
        country_code: Country code (US, CA, etc.)
    
    Returns:
        (location_id, was_created): Tuple of location_id (UUID string or None) and boolean indicating if it was newly created
    """
    if not location_name:
        location_name = ""  # Allow empty location name
    
    # Check if location already exists (by name and chain_id)
    response = supabase.table("store_locations").select("id").eq("chain_id", chain_id).eq("name", location_name).execute()
    
    if response.data:
        location_id = response.data[0]["id"]
        print(f"    Location already exists: {location_name} (id: {location_id})")
        return (location_id, False)
    
    # Normalize country code
    if country_code:
        country_code_upper = country_code.upper()
        # Map common variations
        if country_code_upper in ("USA", "UNITED STATES", "UNITED STATES OF AMERICA"):
            country_code_upper = "US"
        elif country_code_upper in ("CANADA", "CA"):
            country_code_upper = "CA"
    else:
        country_code_upper = None
    
    payload = {
        "chain_id": chain_id,
        "name": location_name,
        "address_line1": address_line1 if address_line1 else None,
        "address_line2": address_line2 if address_line2 else None,
        "city": city if city else None,
        "state": state if state else None,
        "zip_code": zip_code if zip_code else None,
        "country_code": country_code_upper,
        "is_active": True
    }
    
    # Remove None and empty string values
    payload = {k: v for k, v in payload.items() if v is not None and v != ""}
    
    try:
        res = supabase.table("store_locations").insert(payload).execute()
        if not res.data:
            raise ValueError("Failed to create location, no data returned")
        location_id = res.data[0]["id"]
        print(f"    Created location: {location_name} (id: {location_id})")
        return (location_id, True)
    except Exception as e:
        print(f"    [ERROR] Failed to create location '{location_name}': {e}")
        return (None, False)


def import_store_locations_from_excel(excel_path: str):
    """
    Import store locations from Excel file directly to database.
    
    Args:
        excel_path: Path to Excel file
    """
    excel_file = Path(excel_path)
    
    if not excel_file.exists():
        print(f"[ERROR] Excel file not found: {excel_path}")
        sys.exit(1)
    
    print(f"Reading Excel file: {excel_file}")
    
    try:
        # Read Excel file
        df = pd.read_excel(excel_file)
        print(f"Found {len(df)} rows in Excel file")
        print(f"Columns: {', '.join(df.columns.tolist())}")
        
        # Get Supabase client
        supabase = _get_client()
        
        # Process each row
        success_count = 0
        error_count = 0
        chains_created = 0
        chains_found = 0
        locations_created = 0
        locations_skipped = 0
        
        for idx, row in df.iterrows():
            print(f"\nProcessing row {idx + 1}/{len(df)}:")
            
            try:
                # Extract chain name (try multiple column name variations)
                chain_name = None
                for col in ["Store Chain Name", "store chain name", "chain_name", "Chain Name", "chain", "Chain"]:
                    if col in df.columns and pd.notna(row[col]):
                        chain_name = str(row[col]).strip()
                        break
                
                if not chain_name:
                    print(f"  [WARNING] No chain name found, skipping row")
                    error_count += 1
                    continue
                
                # Extract location name (try multiple column name variations)
                location_name = ""
                for col in ["Store Location Name", "store location name", "location_name", "Location Name", "location", "Location"]:
                    if col in df.columns and pd.notna(row[col]):
                        location_name = str(row[col]).strip()
                        break
                
                # If no location name, use chain name
                if not location_name:
                    location_name = chain_name
                
                # Extract chain name (remove location if present)
                final_chain_name = extract_chain_name(chain_name, location_name if location_name != chain_name else "")
                
                # Get or create chain
                chain_id, was_created = get_or_create_chain(supabase, final_chain_name)
                
                # Track chain creation
                if was_created:
                    chains_created += 1
                else:
                    chains_found += 1
                
                # Extract address fields
                address_line1 = None
                for col in ["address1", "Address1", "address_line1", "Address Line 1"]:
                    if col in df.columns and pd.notna(row[col]):
                        address_line1 = str(row[col]).strip()
                        break
                
                address_line2 = None
                for col in ["address2", "Address2", "address_line2", "Address Line 2"]:
                    if col in df.columns and pd.notna(row[col]):
                        value = row[col]
                        # Handle numeric values (e.g., 1190.0 -> "1190")
                        if isinstance(value, (int, float)):
                            # Convert to int first to remove decimal, then to string
                            address_line2 = str(int(value)).strip()
                        else:
                            address_line2 = str(value).strip()
                        break
                
                city = None
                for col in ["city", "City"]:
                    if col in df.columns and pd.notna(row[col]):
                        city = str(row[col]).strip()
                        break
                
                state = None
                for col in ["state", "State", "state/province", "State/Province"]:
                    if col in df.columns and pd.notna(row[col]):
                        state = str(row[col]).strip()
                        break
                
                zip_code = None
                for col in ["zipcode", "Zipcode", "zip_code", "Zip Code", "postal_code", "Postal Code"]:
                    if col in df.columns and pd.notna(row[col]):
                        zip_code = str(row[col]).strip()
                        break
                
                country_code = None
                for col in ["country", "Country", "country_code", "Country Code"]:
                    if col in df.columns and pd.notna(row[col]):
                        country_code = str(row[col]).strip()
                        break
                
                # Create location
                location_id, was_created = create_store_location(
                    supabase=supabase,
                    chain_id=chain_id,
                    location_name=location_name,
                    address_line1=address_line1,
                    address_line2=address_line2,
                    city=city,
                    state=state,
                    zip_code=zip_code,
                    country_code=country_code
                )
                
                if location_id:
                    success_count += 1
                    if was_created:
                        locations_created += 1
                    else:
                        locations_skipped += 1
                else:
                    error_count += 1
                    
            except Exception as e:
                print(f"  [ERROR] Failed to process row: {e}")
                import traceback
                traceback.print_exc()
                error_count += 1
        
        print(f"\n[SUMMARY]")
        print(f"  Total rows processed: {len(df)}")
        print(f"  Store chains - Created: {chains_created}, Found existing: {chains_found}")
        print(f"  Store locations - Created: {locations_created}, Skipped (duplicates): {locations_skipped}")
        print(f"  Successfully imported: {success_count}")
        print(f"  Errors: {error_count}")
        
    except Exception as e:
        print(f"[ERROR] Failed to read Excel file: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # Get project root
    project_root = Path(__file__).parent.parent.parent
    
    # Resolve paths
    if not Path(INPUT_EXCEL_PATH).is_absolute():
        excel_path = project_root / INPUT_EXCEL_PATH
    else:
        excel_path = Path(INPUT_EXCEL_PATH)
    
    import_store_locations_from_excel(str(excel_path))
