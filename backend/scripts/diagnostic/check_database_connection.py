"""
Diagnostic script to check database connection and user_id configuration.
Run this script to diagnose why receipts are not being saved to database.
"""
import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings
from app.services.database.supabase_client import _get_client, get_test_user_id

def check_database_connection():
    """Check if database connection is working."""
    print("=" * 60)
    print("Database Connection Diagnostic")
    print("=" * 60)
    
    # Check 1: Environment variables
    print("\n1. Checking environment variables...")
    print(f"   SUPABASE_URL: {'✓ Set' if settings.supabase_url else '✗ Not set'}")
    print(f"   SUPABASE_ANON_KEY: {'✓ Set' if settings.supabase_anon_key else '✗ Not set'}")
    print(f"   TEST_USER_ID: {'✓ Set' if settings.test_user_id else '✗ Not set'}")
    
    if settings.test_user_id:
        print(f"   TEST_USER_ID value: {settings.test_user_id}")
    
    # Check 2: Test user ID
    print("\n2. Checking test user ID...")
    test_user_id = get_test_user_id()
    if test_user_id:
        print(f"   ✓ Test user ID found: {test_user_id}")
        
        # Validate UUID format
        import uuid
        try:
            uuid.UUID(test_user_id)
            print(f"   ✓ Valid UUID format")
        except ValueError:
            print(f"   ✗ Invalid UUID format!")
            return False
    else:
        print("   ✗ Test user ID not found!")
        print("   → Please set TEST_USER_ID in your .env file")
        print("   → The user_id must be a valid UUID that exists in the users table")
        return False
    
    # Check 3: Database connection
    print("\n3. Testing database connection...")
    try:
        supabase = _get_client()
        print("   ✓ Supabase client created successfully")
    except Exception as e:
        print(f"   ✗ Failed to create Supabase client: {e}")
        return False
    
    # Check 4: Check if user exists in users table
    print("\n4. Checking if user exists in users table...")
    try:
        res = supabase.table("users").select("id, user_name, email").eq("id", test_user_id).execute()
        if res.data:
            user = res.data[0]
            print(f"   ✓ User found in users table:")
            print(f"     - ID: {user.get('id')}")
            print(f"     - Name: {user.get('user_name', 'N/A')}")
            print(f"     - Email: {user.get('email', 'N/A')}")
        else:
            print(f"   ✗ User {test_user_id} not found in users table!")
            print("   → Please create a user record in the users table first")
            return False
    except Exception as e:
        print(f"   ✗ Error checking users table: {e}")
        return False
    
    # Check 5: Test creating a receipt
    print("\n5. Testing receipt creation...")
    try:
        from app.services.database.supabase_client import create_receipt
        receipt_id = create_receipt(user_id=test_user_id, raw_file_url=None)
        print(f"   ✓ Receipt created successfully: {receipt_id}")
        
        # Clean up: delete test receipt
        try:
            supabase.table("receipts").delete().eq("id", receipt_id).execute()
            print(f"   ✓ Test receipt deleted (cleanup)")
        except Exception as e:
            print(f"   ⚠ Warning: Could not delete test receipt: {e}")
            print(f"   → Please manually delete receipt {receipt_id} from database")
        
        return True
    except Exception as e:
        print(f"   ✗ Failed to create receipt: {type(e).__name__}: {e}")
        print("\n   Common causes:")
        print("   1. user_id does not exist in users table (foreign key constraint)")
        print("   2. user_id is not a valid UUID format")
        print("   3. Database connection or permission issue")
        return False

if __name__ == "__main__":
    success = check_database_connection()
    print("\n" + "=" * 60)
    if success:
        print("✓ All checks passed! Database connection is working.")
    else:
        print("✗ Some checks failed. Please fix the issues above.")
    print("=" * 60)
    sys.exit(0 if success else 1)
