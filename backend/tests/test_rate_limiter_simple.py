"""Simple test for rate limiter core functionality (no FastAPI dependencies)."""
import time
import logging
from typing import Dict, Tuple
from collections import defaultdict
from threading import Lock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RateLimiter:
    """简单的内存 rate limiter，使用滑动窗口算法。"""
    
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, list] = defaultdict(list)
        self._locks: Dict[str, Lock] = defaultdict(Lock)
        self._cleanup_lock = Lock()
        self._last_cleanup = time.time()
        logger.info(f"Rate limiter initialized: {max_requests} requests per {window_seconds}s")
    
    def _cleanup_old_entries(self):
        """定期清理过期的请求记录"""
        now = time.time()
        if now - self._last_cleanup < 300:
            return
        
        with self._cleanup_lock:
            if now - self._last_cleanup < 300:
                return
            
            cutoff = now - self.window_seconds - 300
            users_to_remove = []
            
            for user_id, timestamps in self._requests.items():
                self._requests[user_id] = [ts for ts in timestamps if ts > cutoff]
                if not self._requests[user_id]:
                    users_to_remove.append(user_id)
            
            for user_id in users_to_remove:
                del self._requests[user_id]
                if user_id in self._locks:
                    del self._locks[user_id]
            
            self._last_cleanup = now
            logger.debug(f"Cleanup: removed {len(users_to_remove)} inactive users")
    
    def check_rate_limit(self, user_id: str) -> Tuple[bool, int, int]:
        """检查用户是否超过速率限制"""
        now = time.time()
        cutoff = now - self.window_seconds
        
        self._cleanup_old_entries()
        
        with self._locks[user_id]:
            timestamps = self._requests[user_id]
            self._requests[user_id] = [ts for ts in timestamps if ts > cutoff]
            
            current_count = len(self._requests[user_id])
            remaining = max(0, self.max_requests - current_count)
            
            if current_count >= self.max_requests:
                logger.warning(f"Rate limit exceeded for user {user_id}: {current_count}/{self.max_requests}")
                return False, current_count, 0
            
            self._requests[user_id].append(now)
            return True, current_count + 1, remaining - 1
    
    def reset_user(self, user_id: str):
        """重置某个用户的限流记录"""
        with self._locks[user_id]:
            self._requests[user_id] = []
            logger.info(f"Rate limit reset for user {user_id}")
    
    def get_stats(self, user_id: str) -> Dict:
        """获取用户的限流统计信息"""
        now = time.time()
        cutoff = now - self.window_seconds
        
        with self._locks[user_id]:
            timestamps = [ts for ts in self._requests[user_id] if ts > cutoff]
            current_count = len(timestamps)
            remaining = max(0, self.max_requests - current_count)
            
            reset_time = None
            if timestamps:
                oldest = min(timestamps)
                reset_time = oldest + self.window_seconds
            
            return {
                "user_id": user_id,
                "current_count": current_count,
                "max_requests": self.max_requests,
                "remaining": remaining,
                "window_seconds": self.window_seconds,
                "reset_at": reset_time
            }


def test_basic_rate_limiting():
    """测试基本的速率限制功能"""
    print("\n=== Test 1: Basic Rate Limiting ===")
    
    limiter = RateLimiter(max_requests=5, window_seconds=10)
    user_id = "test_user_1"
    
    for i in range(5):
        is_allowed, current, remaining = limiter.check_rate_limit(user_id)
        print(f"Request {i+1}: allowed={is_allowed}, current={current}, remaining={remaining}")
        assert is_allowed, f"Request {i+1} should be allowed"
    
    is_allowed, current, remaining = limiter.check_rate_limit(user_id)
    print(f"Request 6: allowed={is_allowed}, current={current}, remaining={remaining}")
    assert not is_allowed, "Request 6 should be rejected"
    
    print("[PASS]")


def test_window_expiration():
    """测试时间窗口过期"""
    print("\n=== Test 2: Window Expiration ===")
    
    limiter = RateLimiter(max_requests=3, window_seconds=2)
    user_id = "test_user_2"
    
    for i in range(3):
        is_allowed, _, _ = limiter.check_rate_limit(user_id)
        assert is_allowed, f"Request {i+1} should be allowed"
        print(f"Request {i+1}: allowed")
    
    is_allowed, _, _ = limiter.check_rate_limit(user_id)
    assert not is_allowed, "Request 4 should be rejected"
    print("Request 4: rejected (as expected)")
    
    print("Waiting 2.5 seconds for window to expire...")
    time.sleep(2.5)
    
    is_allowed, current, remaining = limiter.check_rate_limit(user_id)
    print(f"Request 5 (after expiration): allowed={is_allowed}, current={current}, remaining={remaining}")
    assert is_allowed, "Request should be allowed after window expiration"
    
    print("[PASS]")


def test_multiple_users():
    """测试多用户独立限流"""
    print("\n=== Test 3: Multiple Users ===")
    
    limiter = RateLimiter(max_requests=3, window_seconds=10)
    
    for i in range(3):
        is_allowed, _, _ = limiter.check_rate_limit("user_1")
        assert is_allowed
    
    is_allowed, _, _ = limiter.check_rate_limit("user_1")
    assert not is_allowed
    print("User 1: 3 requests allowed, 4th rejected [OK]")
    
    for i in range(3):
        is_allowed, _, _ = limiter.check_rate_limit("user_2")
        assert is_allowed
    print("User 2: 3 requests allowed [OK]")
    
    is_allowed, _, _ = limiter.check_rate_limit("user_2")
    assert not is_allowed
    print("User 2: 4th request rejected [OK]")
    
    print("[PASS]")


def test_production_scenario():
    """测试生产环境场景：每分钟10次"""
    print("\n=== Test 4: Production Scenario (10 req/min) ===")
    
    limiter = RateLimiter(max_requests=10, window_seconds=60)
    user_id = "production_user"
    
    print("Simulating normal usage (10 requests)...")
    for i in range(10):
        is_allowed, current, remaining = limiter.check_rate_limit(user_id)
        assert is_allowed, f"Request {i+1} should be allowed"
        if i % 3 == 0:
            print(f"  Request {i+1}: current={current}, remaining={remaining}")
    
    print("All 10 requests allowed [OK]")
    
    is_allowed, current, remaining = limiter.check_rate_limit(user_id)
    assert not is_allowed, "11th request should be rejected"
    print(f"11th request: rejected (current={current}, remaining={remaining}) [OK]")
    
    stats = limiter.get_stats(user_id)
    print(f"\nFinal stats:")
    print(f"  - Current: {stats['current_count']}/{stats['max_requests']}")
    print(f"  - Remaining: {stats['remaining']}")
    if stats.get('reset_at'):
        reset_in = int(stats['reset_at'] - time.time())
        print(f"  - Reset in: {reset_in}s")
    
    print("[PASS]")


if __name__ == "__main__":
    print("=" * 60)
    print("RATE LIMITER TEST SUITE")
    print("=" * 60)
    
    try:
        test_basic_rate_limiting()
        test_window_expiration()
        test_multiple_users()
        test_production_scenario()
        
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        import sys
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        import sys
        sys.exit(1)
