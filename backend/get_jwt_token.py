"""
Script to get JWT token from Supabase Auth for testing.

Usage:
    python get_jwt_token.py

Requirements:
    - SUPABASE_URL and SUPABASE_ANON_KEY in .env
    - A test user account in Supabase
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

try:
    from supabase import create_client
except ImportError:
    print("Error: supabase package not installed. Run: pip install supabase")
    sys.exit(1)

def main():
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY")
    
    if not supabase_url or not supabase_anon_key:
        print("Error: SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env file")
        sys.exit(1)
    
    # Create Supabase client
    supabase = create_client(supabase_url, supabase_anon_key)
    
    # Get credentials from user
    print("=" * 60)
    print("Supabase JWT Token Generator")
    print("=" * 60)
    print()
    
    email = input("Enter your email: ").strip()
    password = input("Enter your password: ").strip()
    
    if not email or not password:
        print("Error: Email and password are required")
        sys.exit(1)
    
    print()
    print("Logging in...")
    
    try:
        # Sign in
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if response.session:
            token = response.session.access_token
            user_id = response.user.id
            
            print()
            print("=" * 60)
            print("✅ Login successful!")
            print("=" * 60)
            print()
            print(f"User ID: {user_id}")
            print(f"Email: {response.user.email}")
            print()
            print("JWT Token:")
            print("-" * 60)
            print(token)
            print("-" * 60)
            print()
            print("=" * 60)
            print("How to use this token:")
            print("=" * 60)
            print()
            print("1. In Swagger UI (http://localhost:8000/docs):")
            print("   - Click 'Authorize' button (top right)")
            print("   - Enter: Bearer " + token[:50] + "...")
            print()
            print("2. With curl:")
            print(f'   curl -H "Authorization: Bearer {token[:50]}..." \\')
            print("        http://localhost:8000/api/auth/test-token")
            print()
            print("3. In Python requests:")
            print(f'   headers = {{"Authorization": "Bearer {token[:50]}..."}}')
            print()
            print("=" * 60)
            print()
            print("⚠️  Note: This token will expire in 1 hour.")
            print("   Run this script again to get a new token.")
            print()
            
        else:
            print("❌ Login failed: No session returned")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Login failed: {e}")
        print()
        print("Possible reasons:")
        print("  - Email or password is incorrect")
        print("  - User account doesn't exist")
        print("  - Email not confirmed (check Supabase Dashboard)")
        sys.exit(1)

if __name__ == "__main__":
    main()
