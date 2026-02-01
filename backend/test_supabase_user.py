"""
测试脚本：验证 Supabase 用户是否存在

这个脚本会：
1. 检查环境变量配置
2. 尝试连接到 Supabase Admin API
3. 验证指定的用户是否存在
"""
import os
import sys
from pathlib import Path
import httpx
from dotenv import load_dotenv

# 加载 .env 文件
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# 从环境变量获取配置
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
USER_ID = "7981c0a1-6017-4a8c-b551-3fb4118cd798"

def main():
    import sys
    import io
    # Fix encoding for Windows console
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    print("=" * 60)
    print("Supabase User Verification Test")
    print("=" * 60)
    
    # Check configuration
    print("\n1. Checking environment variables...")
    if not SUPABASE_URL:
        print("[ERROR] SUPABASE_URL not configured")
        return
    else:
        print(f"[OK] SUPABASE_URL: {SUPABASE_URL}")
    
    if not SUPABASE_SERVICE_ROLE_KEY:
        print("[ERROR] SUPABASE_SERVICE_ROLE_KEY not configured")
        return
    else:
        # Only show first 20 characters
        masked_key = SUPABASE_SERVICE_ROLE_KEY[:20] + "..." if len(SUPABASE_SERVICE_ROLE_KEY) > 20 else SUPABASE_SERVICE_ROLE_KEY
        print(f"[OK] SUPABASE_SERVICE_ROLE_KEY: {masked_key}")
    
    print(f"\n2. Test User ID: {USER_ID}")
    
    # Test connection
    print("\n3. Attempting to connect to Supabase Admin API...")
    try:
        async def test_connection():
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 尝试获取用户信息
                response = await client.get(
                    f"{SUPABASE_URL}/auth/v1/admin/users/{USER_ID}",
                    headers={
                        "apikey": SUPABASE_SERVICE_ROLE_KEY,
                        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                        "Content-Type": "application/json"
                    }
                )
                
                print(f"\nResponse Status Code: {response.status_code}")
                print(f"Response Headers: {dict(response.headers)}")
                
                if response.status_code == 200:
                    user_data = response.json()
                    print("\n[SUCCESS] User found!")
                    print(f"User Info: {user_data}")
                    return True
                elif response.status_code == 404:
                    print("\n[ERROR] User not found (404)")
                    print(f"Response: {response.text}")
                    print("\nPossible reasons:")
                    print("1. User ID is incorrect")
                    print("2. User does not exist in Supabase Authentication > Users")
                    print("3. SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is misconfigured")
                    return False
                elif response.status_code == 401:
                    print("\n[ERROR] Authentication failed (401)")
                    print(f"Response: {response.text}")
                    print("\nPossible reasons:")
                    print("1. SUPABASE_SERVICE_ROLE_KEY is incorrect")
                    print("2. Service Role Key does not have Admin API permissions")
                    return False
                else:
                    print(f"\n[ERROR] Request failed ({response.status_code})")
                    print(f"Response: {response.text}")
                    return False
        
        import asyncio
        result = asyncio.run(test_connection())
        
        if result:
            print("\n" + "=" * 60)
            print("[SUCCESS] Test passed! User exists, can use /api/auth/authorization endpoint")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("[ERROR] Test failed! Please check the error messages above")
            print("=" * 60)
            
    except Exception as e:
        print(f"\n[ERROR] Exception occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
