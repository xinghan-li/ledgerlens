"""
Script to get the first user from users table and hardcode it.
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.database.supabase_client import _get_client

def get_first_user():
    """Get the first user from users table."""
    try:
        supabase = _get_client()
        res = supabase.table("users").select("id, user_name, email, created_at").limit(1).execute()
        
        if res.data and len(res.data) > 0:
            user = res.data[0]
            print(f"Found user:")
            print(f"  ID: {user['id']}")
            print(f"  Name: {user.get('user_name', 'N/A')}")
            print(f"  Email: {user.get('email', 'N/A')}")
            print(f"  Created: {user.get('created_at', 'N/A')}")
            print(f"\nUser ID to use: {user['id']}")
            return user['id']
        else:
            print("No users found in users table!")
            return None
    except Exception as e:
        print(f"Error querying users table: {e}")
        return None

if __name__ == "__main__":
    user_id = get_first_user()
    if user_id:
        print(f"\n✓ User ID: {user_id}")
        print("\nThis user_id will be hardcoded in the code.")
    else:
        print("\n✗ Could not find user ID")
        sys.exit(1)
