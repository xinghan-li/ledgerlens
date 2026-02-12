"""
Migration script to move existing backend/output files to new structure.

New structure:
output/
  YYYYMMDD/
    debug-001/
    error-001/
    timeline/
    {receipt_id}_output.json
    YYYYMMDD.csv
"""
import json
import shutil
from pathlib import Path
from datetime import datetime
import re

# Paths
OLD_OUTPUT_DIR = Path(__file__).parent / "output"
NEW_OUTPUT_ROOT = Path(__file__).parent.parent / "output"

def extract_date_from_receipt_id(receipt_id: str) -> str:
    """Extract date from receipt_id (format: seq_mmyydd_hhmm) -> YYYYMMDD."""
    # Example: 062332_012126_0623 -> 012126 -> 01/21/26 -> 20260121
    match = re.search(r'_(\d{2})(\d{2})(\d{2})_', receipt_id)
    if match:
        month = match.group(1)
        day = match.group(2)
        year_2digit = match.group(3)
        # Assume 20XX
        year = f"20{year_2digit}"
        return f"{year}{month}{day}"
    return None

def migrate_files():
    """Migrate files from old structure to new structure."""
    if not OLD_OUTPUT_DIR.exists():
        print(f"Old output directory not found: {OLD_OUTPUT_DIR}")
        return
    
    print(f"Migrating from {OLD_OUTPUT_DIR} to {NEW_OUTPUT_ROOT}")
    
    # Process output JSON files
    for json_file in OLD_OUTPUT_DIR.glob("*_output.json"):
        receipt_id = json_file.stem.replace("_output", "")
        date_folder = extract_date_from_receipt_id(receipt_id)
        
        if not date_folder:
            print(f"Warning: Could not extract date from receipt_id: {receipt_id}")
            continue
        
        # Create new directory structure
        date_dir = NEW_OUTPUT_ROOT / date_folder
        date_dir.mkdir(parents=True, exist_ok=True)
        
        # Move JSON file
        new_json_path = date_dir / json_file.name
        shutil.copy2(json_file, new_json_path)
        print(f"Copied: {json_file.name} -> {date_dir / json_file.name}")
        
        # Process timeline file
        timeline_file = OLD_OUTPUT_DIR / f"{receipt_id}_timeline.json"
        if timeline_file.exists():
            timeline_dir = date_dir / "timeline"
            timeline_dir.mkdir(parents=True, exist_ok=True)
            new_timeline_path = timeline_dir / timeline_file.name
            shutil.copy2(timeline_file, new_timeline_path)
            print(f"Copied: {timeline_file.name} -> {timeline_dir / timeline_file.name}")
        
        # Process debug files
        debug_dir_old = OLD_OUTPUT_DIR / "debug"
        if debug_dir_old.exists():
            debug_dir_new = date_dir / "debug-001"
            debug_dir_new.mkdir(parents=True, exist_ok=True)
            
            # Copy all debug files for this receipt
            for debug_file in debug_dir_old.glob(f"{receipt_id}*"):
                new_debug_path = debug_dir_new / debug_file.name
                shutil.copy2(debug_file, new_debug_path)
                print(f"Copied: {debug_file.name} -> {debug_dir_new / debug_file.name}")
        
        # Process error files
        error_dir_old = OLD_OUTPUT_DIR / "error"
        if error_dir_old.exists():
            error_dir_new = date_dir / "error-001"
            error_dir_new.mkdir(parents=True, exist_ok=True)
            
            # Copy all error files for this receipt
            for error_file in error_dir_old.glob(f"{receipt_id}*"):
                new_error_path = error_dir_new / error_file.name
                shutil.copy2(error_file, new_error_path)
                print(f"Copied: {error_file.name} -> {error_dir_new / error_file.name}")
    
    print("\nMigration completed!")
    print(f"New structure created at: {NEW_OUTPUT_ROOT}")
    print("\nNote: Old files are still in backend/output. You can delete them after verifying the migration.")

if __name__ == "__main__":
    migrate_files()
