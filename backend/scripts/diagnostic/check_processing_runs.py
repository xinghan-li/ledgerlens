"""
检查 receipt_processing_runs 表的数据情况。

运行方式:
    python check_processing_runs.py
"""
import os
import sys
import io
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime

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

# Create Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

print("=" * 80)
print("Receipt Processing Runs Check Tool")
print("=" * 80)

# 1. Get recent receipts
print("\n1. Recent Receipts (last 10):")
print("-" * 80)
try:
    receipts = supabase.table("receipts").select("*").order("uploaded_at", desc=True).limit(10).execute()
    
    if receipts.data:
        print(f"Found {len(receipts.data)} recent receipts:\n")
        
        for idx, r in enumerate(receipts.data, 1):
            receipt_id = r.get("id")
            status = r.get("current_status")
            stage = r.get("current_stage")
            uploaded = r.get("uploaded_at")
            
            # Format timestamp
            if uploaded:
                try:
                    dt = datetime.fromisoformat(uploaded.replace("Z", "+00:00"))
                    uploaded_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    uploaded_str = uploaded
            else:
                uploaded_str = "N/A"
            
            print(f"[{idx}] Receipt ID: {receipt_id}")
            print(f"    Status: {status}, Stage: {stage}")
            print(f"    Uploaded: {uploaded_str}")
            
            # Query processing runs for this receipt
            runs = supabase.table("receipt_processing_runs").select(
                "id, stage, model_provider, model_name, status, validation_status, created_at"
            ).eq("receipt_id", receipt_id).order("created_at", desc=False).execute()
            
            if runs.data:
                print(f"    Processing Runs: {len(runs.data)} run(s)")
                for run in runs.data:
                    run_stage = run.get("stage")
                    provider = run.get("model_provider") or "N/A"
                    model = run.get("model_name") or "N/A"
                    run_status = run.get("status")
                    validation = run.get("validation_status") or "N/A"
                    
                    print(f"      - {run_stage} ({provider}/{model}): {run_status}, validation={validation}")
            else:
                print(f"    Processing Runs: 0 run(s) ⚠️  NO DATA!")
            
            print()
    else:
        print("No receipts found in database")
        
except Exception as e:
    print(f"ERROR: Failed to query receipts: {e}")

# 2. Overall statistics
print("\n2. Overall Statistics:")
print("-" * 80)
try:
    # Total receipts
    receipts_count = supabase.table("receipts").select("id", count="exact").execute()
    total_receipts = receipts_count.count if hasattr(receipts_count, 'count') else len(receipts_count.data)
    
    # Total processing runs
    runs_count = supabase.table("receipt_processing_runs").select("id", count="exact").execute()
    total_runs = runs_count.count if hasattr(runs_count, 'count') else len(runs_count.data)
    
    print(f"Total receipts: {total_receipts}")
    print(f"Total processing runs: {total_runs}")
    
    if total_receipts > 0:
        avg_runs = total_runs / total_receipts
        print(f"Average runs per receipt: {avg_runs:.2f}")
        
        if avg_runs == 0:
            print("\n⚠️  WARNING: No processing runs found!")
            print("This likely means:")
            print("  1. Database constraint error during receipt creation")
            print("  2. db_receipt_id was None, skipping all save_processing_run() calls")
            print("  3. Please fix constraint and re-upload a new receipt")
        elif avg_runs < 2:
            print("\n⚠️  NOTICE: Average runs per receipt is less than 2")
            print("Expected: at least 2 runs per receipt (OCR + LLM)")
        else:
            print("\n✅ Data looks normal")
    
except Exception as e:
    print(f"ERROR: Failed to get statistics: {e}")

# 3. Processing runs breakdown
print("\n3. Processing Runs Breakdown:")
print("-" * 80)
try:
    runs = supabase.table("receipt_processing_runs").select("stage, model_provider, status").execute()
    
    if runs.data:
        # Count by stage
        stage_counts = {}
        provider_counts = {}
        status_counts = {}
        
        for run in runs.data:
            stage = run.get("stage")
            provider = run.get("model_provider")
            status = run.get("status")
            
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print("By Stage:")
        for stage, count in sorted(stage_counts.items(), key=lambda x: -x[1]):
            print(f"  - {stage}: {count}")
        
        print("\nBy Provider:")
        for provider, count in sorted(provider_counts.items(), key=lambda x: -x[1]):
            print(f"  - {provider}: {count}")
        
        print("\nBy Status:")
        for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
            print(f"  - {status}: {count}")
    else:
        print("⚠️  No processing runs data")
        
except Exception as e:
    print(f"ERROR: Failed to analyze processing runs: {e}")

print("\n" + "=" * 80)
print("Check completed")
print("=" * 80)

print("\nRecommendations:")
print("- If no processing runs found: Fix constraint and upload a NEW receipt")
print("- If runs exist but less than expected: Check backend logs for errors")
print("- For detailed docs: See RECEIPT_PROCESSING_RUNS_EXPLAINED.md")
