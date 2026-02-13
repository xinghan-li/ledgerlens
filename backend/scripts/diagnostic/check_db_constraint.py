"""
Check and fix receipts table current_stage constraint issue.

Usage:
    python check_db_constraint.py
"""
import os
import sys
import io
from dotenv import load_dotenv
from supabase import create_client, Client

# Fix Windows encoding issue
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("ERROR: Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    print("Please ensure .env file contains these configs")
    exit(1)

# Create Supabase client (using service role key for admin access)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

print("=" * 60)
print("Database Constraint Check Tool")
print("=" * 60)

# 1. Check current_stage value distribution in receipts table
print("\nStep 1: Check current data distribution...")
try:
    # Query receipts table for current_stage values
    result = supabase.table("receipt_status").select("current_stage, current_status").execute()
    
    if result.data:
        stage_counts = {}
        status_counts = {}
        combinations = {}
        
        for row in result.data:
            stage = row.get("current_stage")
            status = row.get("current_status")
            
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
            status_counts[status] = status_counts.get(status, 0) + 1
            
            combo = f"{status}+{stage}"
            combinations[combo] = combinations.get(combo, 0) + 1
        
        print("\nCurrent current_stage distribution:")
        for stage, count in sorted(stage_counts.items(), key=lambda x: -x[1]):
            print(f"  - {stage}: {count} records")
        
        print("\nCurrent current_status distribution:")
        for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
            print(f"  - {status}: {count} records")
        
        print("\nCombinations (status+stage):")
        for combo, count in sorted(combinations.items(), key=lambda x: -x[1]):
            print(f"  - {combo}: {count} records")
        
        # Check for invalid values
        valid_stages = {'ocr', 'llm_primary', 'llm_fallback', 'manual'}
        valid_statuses = {'success', 'failed', 'needs_review'}
        
        invalid_stages = set(stage_counts.keys()) - valid_stages
        invalid_statuses = set(status_counts.keys()) - valid_statuses
        
        if invalid_stages:
            print(f"\nWARNING: Found invalid current_stage values: {invalid_stages}")
            print("   These values need to be migrated")
        else:
            print("\nOK: All current_stage values are valid")
            
        if invalid_statuses:
            print(f"\nWARNING: Found invalid current_status values: {invalid_statuses}")
            print("   These values need to be migrated")
        else:
            print("\nOK: All current_status values are valid")
    else:
        print("\nOK: Table is empty (no data yet)")
        
except Exception as e:
    print(f"\nERROR: Query failed: {e}")
    print("\nTip: If permission issue, ensure using service_role_key")

# 2. Test constraint
print("\n" + "=" * 60)
print("Step 2: Recommendations")
print("=" * 60)
print("\nDue to Supabase limitations, cannot directly query constraint definition")
print("\nRecommendations:")
print("1. Login to Supabase Dashboard")
print("2. Go to Database > SQL Editor")
print("3. Run migration 011 to ensure constraint is correct:")
print("   f:\\LedgerLens\\backend\\database\\deprecated\\011_simplify_receipts_stage_values.sql")
print("\n4. Or check constraint manually:")
print("   SELECT conname, pg_get_constraintdef(oid)")
print("   FROM pg_constraint")
print("   WHERE conrelid = 'receipts'::regclass")
print("   AND conname = 'receipts_current_stage_check';")

print("\n" + "=" * 60)
print("Check completed")
print("=" * 60)
