"""
查看 receipt_processing_runs 的详细输入输出数据。

运行方式:
    python view_processing_run_details.py [receipt_id]
    
    如果不提供 receipt_id，会显示最新的一条记录
"""
import os
import sys
import io
import json
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
    exit(1)

# Create Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Get receipt_id from command line or use latest
receipt_id = sys.argv[1] if len(sys.argv) > 1 else None

if not receipt_id:
    # Get latest receipt
    print("No receipt_id provided, showing latest receipt...\n")
    receipts = supabase.table("receipts").select("id, current_status, uploaded_at").order("uploaded_at", desc=True).limit(1).execute()
    if not receipts.data:
        print("ERROR: No receipts found")
        exit(1)
    receipt_id = receipts.data[0]["id"]
    print(f"Latest receipt: {receipt_id}")
    print(f"Status: {receipts.data[0]['current_status']}")
    print(f"Uploaded: {receipts.data[0]['uploaded_at']}")
    print()

# Query processing runs for this receipt
runs = supabase.table("receipt_processing_runs").select("*").eq("receipt_id", receipt_id).order("created_at", desc=False).execute()

if not runs.data:
    print(f"ERROR: No processing runs found for receipt {receipt_id}")
    exit(1)

print("=" * 100)
print(f"Receipt Processing Runs for: {receipt_id}")
print("=" * 100)
print()

for idx, run in enumerate(runs.data, 1):
    run_id = run.get("id")
    stage = run.get("stage")
    provider = run.get("model_provider") or "N/A"
    model = run.get("model_name") or "N/A"
    status = run.get("status")
    validation = run.get("validation_status") or "N/A"
    created = run.get("created_at")
    error = run.get("error_message")
    
    print(f"[{idx}] Processing Run: {run_id}")
    print(f"    Stage: {stage}")
    print(f"    Provider: {provider}")
    print(f"    Model: {model}")
    print(f"    Status: {status}")
    print(f"    Validation: {validation}")
    print(f"    Created: {created}")
    
    if error:
        print(f"    Error: {error}")
    
    # Input payload
    input_payload = run.get("input_payload")
    if input_payload:
        print("\n    📥 INPUT PAYLOAD:")
        print("    " + "-" * 80)
        # Pretty print with indentation
        input_json = json.dumps(input_payload, indent=2, ensure_ascii=False)
        for line in input_json.split('\n'):
            print(f"    {line}")
    else:
        print("\n    📥 INPUT PAYLOAD: (empty)")
    
    # Output payload
    output_payload = run.get("output_payload")
    if output_payload:
        print("\n    📤 OUTPUT PAYLOAD:")
        print("    " + "-" * 80)
        
        # Check size
        output_json = json.dumps(output_payload, indent=2, ensure_ascii=False)
        output_size = len(output_json)
        
        if output_size > 10000:  # If > 10KB, show summary
            print(f"    (Large output: {output_size} bytes, showing summary)")
            print()
            
            # Show keys
            if isinstance(output_payload, dict):
                print("    Keys:")
                for key in output_payload.keys():
                    value = output_payload[key]
                    if isinstance(value, dict):
                        print(f"      - {key}: dict with {len(value)} keys")
                    elif isinstance(value, list):
                        print(f"      - {key}: list with {len(value)} items")
                    else:
                        value_str = str(value)
                        if len(value_str) > 50:
                            value_str = value_str[:50] + "..."
                        print(f"      - {key}: {value_str}")
                
                # Show receipt summary if exists
                if "receipt" in output_payload:
                    print("\n    Receipt Summary:")
                    receipt_data = output_payload["receipt"]
                    for key, value in receipt_data.items():
                        if key not in ["_metadata", "store_address"]:  # Skip large fields
                            print(f"      - {key}: {value}")
                
                # Show items count if exists
                if "items" in output_payload:
                    items = output_payload["items"]
                    if isinstance(items, list):
                        print(f"\n    Items: {len(items)} item(s)")
                        # Show first 3 items
                        for i, item in enumerate(items[:3], 1):
                            name = item.get("name", "N/A")
                            price = item.get("price", "N/A")
                            print(f"      [{i}] {name}: ${price}")
                        if len(items) > 3:
                            print(f"      ... and {len(items) - 3} more items")
        else:
            # Show full output
            for line in output_json.split('\n'):
                print(f"    {line}")
    else:
        print("\n    📤 OUTPUT PAYLOAD: (empty)")
    
    print("\n" + "=" * 100)
    print()

print("\nTo view a specific receipt's runs:")
print(f"  python {sys.argv[0]} <receipt_id>")
print()
print("Example:")
print(f"  python {sys.argv[0]} {receipt_id}")
