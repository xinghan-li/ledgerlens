"""
Script to initialize deposit_and_fee RAG content via API.

This script creates the deposit_and_fee tag, snippets, and matching rules
using the RAG management API instead of SQL migrations.

Usage:
    python backend/scripts/init_deposit_fee_rag.py
"""
import sys
import httpx
import asyncio
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings


async def init_deposit_fee_rag():
    """
    Initialize deposit_and_fee RAG content via API.
    
    This creates:
    1. deposit_and_fee tag
    2. System message snippet
    3. Prompt addition snippet
    4. Matching rules (keywords and regex)
    5. Location-based matching rules (BC, HI, etc.)
    """
    base_url = f"http://localhost:8000"
    
    # You'll need to get a JWT token first
    # For now, we'll use the service role key to create a session
    # In production, use the /api/auth/authorization endpoint
    
    print("=" * 60)
    print("Initializing deposit_and_fee RAG content via API")
    print("=" * 60)
    
    # Step 1: Get authorization token
    print("\n[1/6] Getting authorization token...")
    
    # Get user_id from environment or database
    test_user_id = settings.test_user_id
    if not test_user_id:
        # Try to get first admin/super_admin user from database
        try:
            from app.services.database.supabase_client import _get_client
            supabase = _get_client()
            # Try to get admin or super_admin user first
            admin_res = supabase.table("users").select("id, user_class, user_name, email").in_("user_class", ["super_admin", "admin"]).limit(1).execute()
            if admin_res.data and len(admin_res.data) > 0:
                test_user_id = admin_res.data[0]["id"]
                user_class = admin_res.data[0].get("user_class", "N/A")
                user_name = admin_res.data[0].get("user_name", "N/A")
                print(f"  Found {user_class} user: {user_name} ({test_user_id})")
            else:
                # Fallback to first user
                user_res = supabase.table("users").select("id, user_class, user_name, email").limit(1).execute()
                if user_res.data and len(user_res.data) > 0:
                    test_user_id = user_res.data[0]["id"]
                    user_class = user_res.data[0].get("user_class", "N/A")
                    user_name = user_res.data[0].get("user_name", "N/A")
                    print(f"  Using first user: {user_name} ({user_class}) - {test_user_id}")
                else:
                    print("ERROR: No users found in database")
                    print("Please create a user first or set TEST_USER_ID in .env")
                    return
        except Exception as e:
            print(f"ERROR: Failed to get user from database: {e}")
            print("Please set TEST_USER_ID in .env file")
            return
    
    if not test_user_id:
        print("ERROR: No user_id available")
        return
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get token
        auth_response = await client.post(
            f"{base_url}/api/auth/authorization",
            json={"user_id": test_user_id}
        )
        
        if auth_response.status_code != 200:
            print(f"ERROR: Failed to get authorization token: {auth_response.status_code}")
            print(f"Response: {auth_response.text}")
            return
        
        auth_data = auth_response.json()
        token = auth_data.get("token")
        
        if not token:
            print("ERROR: No token in response")
            print(f"Response: {auth_data}")
            return
        
        print(f"✓ Got authorization token")
        headers = {"Authorization": f"Bearer {token}"}
        
        # Step 2: Create tag
        print("\n[2/6] Creating deposit_and_fee tag...")
        tag_response = await client.post(
            f"{base_url}/api/rag/tags",
            headers=headers,
            params={
                "tag_name": "deposit_and_fee",
                "tag_type": "general",
                "description": "Bottle deposits, environment fees, and similar charges (not tax)",
                "priority": "70",
                "is_active": "true"
            }
        )
        
        if tag_response.status_code == 200:
            print("✓ Tag created successfully")
        elif tag_response.status_code == 400:
            # Tag might already exist, that's okay
            print("⚠ Tag might already exist (400), continuing...")
        else:
            print(f"ERROR: Failed to create tag: {tag_response.status_code}")
            print(f"Response: {tag_response.text}")
            # Continue anyway, tag might already exist
            print("  Continuing anyway (tag might already exist)...")
        
        # Step 3: Create system message snippet
        print("\n[3/6] Creating system message snippet...")
        system_message = """You are a receipt parsing expert. When you encounter bottle deposits, environment fees, or similar charges:
1. These are legitimate line items and should be included in the items array
2. These are NOT tax - do not include them in the tax field
3. These charges are part of the total and should be included in sum calculations
4. Common examples: "Bottle deposit", "Env fee", "Environmental fee", "CRF", "Container fee", "Bag fee\""""
        
        snippet1_response = await client.post(
            f"{base_url}/api/rag/tags/deposit_and_fee/snippets",
            headers=headers,
            params={
                "snippet_type": "system_message",
                "content": system_message,
                "priority": "10",
                "is_active": "true"
            }
        )
        
        if snippet1_response.status_code == 200:
            print("✓ System message snippet created")
        else:
            print(f"⚠ Failed to create system message snippet: {snippet1_response.status_code}")
            print(f"  Response: {snippet1_response.text}")
            print("  Continuing... (snippet might already exist)")
        
        # Step 4: Create prompt addition snippet
        print("\n[4/6] Creating prompt addition snippet...")
        prompt_addition = """## Deposits and Fees (NOT Tax):

When you see items like:
- "Bottle deposit" or "Bottle Deposit" (e.g., "Bottle deposit $0.10")
- "Env fee" or "Environment fee" or "Environmental fee" (e.g., "Env fee (CRF) $0.01")
- "CRF" (Container Recycling Fee)
- "Container fee"
- "Bag fee"

**Important Rules:**
1. Extract these as separate line items with their exact names and amounts
2. These are NOT tax - do not include them in the tax field
3. Include them in the sum of all line_totals
4. The sum check formula is: `subtotal + tax + deposits + fees = total`

**Example:**
If receipt shows:
- Subtotal: $53.99
- Bottle deposit: $0.10
- Env fee: $0.01
- Tax: $0.00
- Total: $54.10

Then:
- `line_totals` should include $0.10 (bottle deposit) and $0.01 (env fee)
- `subtotal` = $53.99
- `tax` = $0.00 (not $0.11!)
- `total` = $54.10
- Sum check: $53.99 + $0.00 + $0.10 + $0.01 = $54.10 ✓"""
        
        snippet2_response = await client.post(
            f"{base_url}/api/rag/tags/deposit_and_fee/snippets",
            headers=headers,
            params={
                "snippet_type": "prompt_addition",
                "content": prompt_addition,
                "priority": "10",
                "is_active": "true"
            }
        )
        
        if snippet2_response.status_code == 200:
            print("✓ Prompt addition snippet created")
        else:
            print(f"⚠ Failed to create prompt addition snippet: {snippet2_response.status_code}")
            print(f"  Response: {snippet2_response.text}")
            print("  Continuing... (snippet might already exist)")
        
        # Step 5: Create keyword and regex matching rules
        print("\n[5/6] Creating keyword and regex matching rules...")
        matching_rules = [
            ("keyword", "bottle deposit", 100),
            ("keyword", "bottle", 95),
            ("keyword", "env fee", 100),
            ("keyword", "environmental fee", 100),
            ("keyword", "environment fee", 100),
            ("keyword", "environment", 95),
            ("keyword", "environmental", 95),
            ("keyword", "crf", 100),
            ("keyword", "container fee", 90),
            ("keyword", "bag fee", 90),
            ("keyword", "deposit", 85),
            ("regex", "bottle\\s+deposit", 100),
            ("regex", "env\\s+fee", 100),
            ("regex", "environment\\s+fee", 100),
            ("regex", "environmental\\s+fee", 100),
        ]
        
        for match_type, pattern, priority in matching_rules:
            rule_response = await client.post(
                f"{base_url}/api/rag/tags/deposit_and_fee/matching-rules",
                headers=headers,
                params={
                    "match_type": match_type,
                    "match_pattern": pattern,
                    "priority": str(priority),
                    "is_active": "true"
                }
            )
            
            if rule_response.status_code == 200:
                print(f"  ✓ Created {match_type} rule: {pattern}")
            else:
                # Rule might already exist, that's okay
                print(f"  ⚠ {match_type} rule '{pattern}' might already exist (status: {rule_response.status_code})")
        
        # Step 6: Create location-based matching rules
        print("\n[6/6] Creating location-based matching rules...")
        # States/Provinces that have bottle deposits or environment fees
        locations = [
            ("location_state", "BC", "British Columbia, Canada - has bottle deposit and environment fee"),
            ("location_state", "HI", "Hawaii, USA - has bottle deposit"),
            ("location_state", "CA", "California, USA - has CRF (California Redemption Fee)"),
            ("location_country", "CA", "Canada - many provinces have bottle deposits"),
        ]
        
        for match_type, pattern, description in locations:
            rule_response = await client.post(
                f"{base_url}/api/rag/tags/deposit_and_fee/matching-rules",
                headers=headers,
                params={
                    "match_type": match_type,
                    "match_pattern": pattern,
                    "priority": "80",
                    "is_active": "true"
                }
            )
            
            if rule_response.status_code == 200:
                print(f"  ✓ Created {match_type} rule: {pattern} ({description})")
            else:
                # Rule might already exist, that's okay
                print(f"  ⚠ {match_type} rule '{pattern}' might already exist (status: {rule_response.status_code})")
        
        print("\n" + "=" * 60)
        print("✓ Deposit and fee RAG initialization complete!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(init_deposit_fee_rag())
