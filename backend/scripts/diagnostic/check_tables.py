"""
Check which tables exist in the database
"""
import os
import sys
import io
from dotenv import load_dotenv
from supabase import create_client

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")
    sys.exit(1)

# Create Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Check which tables exist
print("Checking database tables...")
print("-" * 60)

tables_to_check = [
    'users',
    'receipt_status',
    'receipt_processing_runs',
    'record_summaries',
    'record_items',
    'brands',
    'categories',
    'products',
    'price_snapshots',
    'store_chains',
    'store_locations'
]

try:
    response = supabase.table('information_schema.tables').select('table_name').execute()
    
    # Get list of public schema tables
    result = supabase.rpc('check_tables_exist', {}).execute()
except:
    # Use direct SQL query
    query = """
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'public' 
      AND table_type = 'BASE TABLE'
    ORDER BY table_name;
    """
    
    try:
        result = supabase.postgrest.rpc('exec_sql', {'query': query}).execute()
        existing_tables = [row['table_name'] for row in result.data]
    except:
        # Alternative method: try to select from each table
        existing_tables = []
        for table in tables_to_check:
            try:
                supabase.table(table).select('id').limit(1).execute()
                existing_tables.append(table)
            except:
                pass

print("Tables in database:")
for table in sorted(existing_tables):
    print(f"  ✅ {table}")

print("\nTables needed but missing:")
for table in tables_to_check:
    if table not in existing_tables:
        print(f"  ❌ {table}")

print("\n" + "-" * 60)
print(f"Total tables found: {len(existing_tables)}")
