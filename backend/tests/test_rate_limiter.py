"""Test rate limiter functionality."""
import time
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import only the RateLimiter class (not the FastAPI dependencies)
import importlib.util
spec = importlib.util.spec_from_file_location(
    "rate_limiter", 
    Path(__file__).resolve().parents[1] / "app" / "middleware" / "rate_limiter.py"
)
rate_limiter_module = importlib.util.module_from_spec(spec)

# Mock FastAPI dependencies before loading the module
import sys
from unittest.mock import MagicMock
sys.modules['fastapi'] = MagicMock()

# Now load the module
spec.loader.exec_module(rate_limiter_module)
RateLimiter = rate_limiter_module.RateLimiter


def test_basic_rate_limiting():
    """测试基本的速率限制功能"""
    print("=== Test 1: Basic Rate Limiting ===")
    
    # 创建一个限制器：5次/10秒
    limiter = RateLimiter(max_requests=5, window_seconds=10)
    user_id = "test_user_1"
    
    # 前5次应该通过
    for i in range(5):
        is_allowed, current, remaining = limiter.check_rate_limit(user_id)
        print(f"Request {i+1}: allowed={is_allowed}, current={current}, remaining={remaining}")
        assert is_allowed, f"Request {i+1} should be allowed"
    
    # 第6次应该被拒绝
    is_allowed, current, remaining = limiter.check_rate_limit(user_id)
    print(f"Request 6: allowed={is_allowed}, current={current}, remaining={remaining}")
    assert not is_allowed, "Request 6 should be rejected"
    
    print("✓ Basic rate limiting works!\n")


def test_window_expiration():
    """测试时间窗口过期"""
    print("=== Test 2: Window Expiration ===")
    
    # 创建一个限制器：3次/2秒
    limiter = RateLimiter(max_requests=3, window_seconds=2)
    user_id = "test_user_2"
    
    # 发3次请求
    for i in range(3):
        is_allowed, _, _ = limiter.check_rate_limit(user_id)
        assert is_allowed, f"Request {i+1} should be allowed"
        print(f"Request {i+1}: allowed")
    
    # 第4次应该被拒绝
    is_allowed, _, _ = limiter.check_rate_limit(user_id)
    assert not is_allowed, "Request 4 should be rejected (within window)"
    print("Request 4: rejected (as expected)")
    
    # 等待窗口过期
    print("Waiting 2.5 seconds for window to expire...")
    time.sleep(2.5)
    
    # 现在应该可以再次请求
    is_allowed, current, remaining = limiter.check_rate_limit(user_id)
    print(f"Request 5 (after expiration): allowed={is_allowed}, current={current}, remaining={remaining}")
    assert is_allowed, "Request should be allowed after window expiration"
    
    print("✓ Window expiration works!\n")


def test_multiple_users():
    """测试多用户独立限流"""
    print("=== Test 3: Multiple Users ===")
    
    limiter = RateLimiter(max_requests=3, window_seconds=10)
    
    # 用户1发3次请求
    for i in range(3):
        is_allowed, _, _ = limiter.check_rate_limit("user_1")
        assert is_allowed
    
    # 用户1的第4次请求应该被拒绝
    is_allowed, _, _ = limiter.check_rate_limit("user_1")
    assert not is_allowed
    print("User 1: 3 requests allowed, 4th rejected ✓")
    
    # 用户2应该还能发3次请求（独立计数）
    for i in range(3):
        is_allowed, _, _ = limiter.check_rate_limit("user_2")
        assert is_allowed
    print("User 2: 3 requests allowed ✓")
    
    # 用户2的第4次也应该被拒绝
    is_allowed, _, _ = limiter.check_rate_limit("user_2")
    assert not is_allowed
    print("User 2: 4th request rejected ✓")
    
    print("✓ Multiple users work independently!\n")


def test_get_stats():
    """测试统计信息获取"""
    print("=== Test 4: Get Stats ===")
    
    limiter = RateLimiter(max_requests=10, window_seconds=60)
    user_id = "test_user_stats"
    
    # 发3次请求
    for _ in range(3):
        limiter.check_rate_limit(user_id)
    
    # 获取统计信息
    stats = limiter.get_stats(user_id)
    print(f"Stats after 3 requests:")
    print(f"  - Current count: {stats['current_count']}")
    print(f"  - Max requests: {stats['max_requests']}")
    print(f"  - Remaining: {stats['remaining']}")
    print(f"  - Window: {stats['window_seconds']}s")
    
    assert stats['current_count'] == 3
    assert stats['max_requests'] == 10
    assert stats['remaining'] == 7
    
    print("✓ Stats retrieval works!\n")


def test_reset_user():
    """测试重置用户限流"""
    print("=== Test 5: Reset User ===")
    
    limiter = RateLimiter(max_requests=2, window_seconds=10)
    user_id = "test_user_reset"
    
    # 发2次请求（达到限制）
    limiter.check_rate_limit(user_id)
    limiter.check_rate_limit(user_id)
    
    # 第3次应该被拒绝
    is_allowed, _, _ = limiter.check_rate_limit(user_id)
    assert not is_allowed
    print("Before reset: 3rd request rejected ✓")
    
    # 重置用户
    limiter.reset_user(user_id)
    print("User reset")
    
    # 现在应该可以再次请求
    is_allowed, current, _ = limiter.check_rate_limit(user_id)
    assert is_allowed
    assert current == 1
    print(f"After reset: request allowed, current={current} ✓")
    
    print("✓ User reset works!\n")


def test_concurrent_requests():
    """测试并发请求（简单模拟）"""
    print("=== Test 6: Concurrent Requests Simulation ===")
    
    limiter = RateLimiter(max_requests=5, window_seconds=10)
    user_id = "test_user_concurrent"
    
    # 快速发送多个请求（模拟并发）
    results = []
    for i in range(7):
        is_allowed, current, remaining = limiter.check_rate_limit(user_id)
        results.append(is_allowed)
        print(f"Request {i+1}: allowed={is_allowed}, current={current}, remaining={remaining}")
    
    # 应该有5个通过，2个被拒绝
    allowed_count = sum(results)
    rejected_count = len(results) - allowed_count
    
    print(f"\nResults: {allowed_count} allowed, {rejected_count} rejected")
    assert allowed_count == 5, f"Should allow exactly 5 requests, got {allowed_count}"
    assert rejected_count == 2, f"Should reject exactly 2 requests, got {rejected_count}"
    
    print("✓ Concurrent requests handled correctly!\n")


def test_production_scenario():
    """测试生产环境场景：每分钟10次"""
    print("=== Test 7: Production Scenario (10 req/min) ===")
    
    limiter = RateLimiter(max_requests=10, window_seconds=60)
    user_id = "production_user"
    
    # 模拟正常使用（10次请求在1分钟内）
    print("Simulating normal usage (10 requests)...")
    for i in range(10):
        is_allowed, current, remaining = limiter.check_rate_limit(user_id)
        assert is_allowed, f"Request {i+1} should be allowed"
        if i % 3 == 0:
            print(f"  Request {i+1}: current={current}, remaining={remaining}")
    
    print("All 10 requests allowed ✓")
    
    # 第11次应该被拒绝
    is_allowed, current, remaining = limiter.check_rate_limit(user_id)
    assert not is_allowed, "11th request should be rejected"
    print(f"11th request: rejected (current={current}, remaining={remaining}) ✓")
    
    # 获取统计信息
    stats = limiter.get_stats(user_id)
    print(f"\nFinal stats:")
    print(f"  - Current: {stats['current_count']}/{stats['max_requests']}")
    print(f"  - Remaining: {stats['remaining']}")
    if stats.get('reset_at'):
        reset_in = int(stats['reset_at'] - time.time())
        print(f"  - Reset in: {reset_in}s")
    
    print("✓ Production scenario works correctly!\n")


if __name__ == "__main__":
    print("=" * 60)
    print("RATE LIMITER TEST SUITE")
    print("=" * 60)
    print()
    
    try:
        test_basic_rate_limiting()
        test_window_expiration()
        test_multiple_users()
        test_get_stats()
        test_reset_user()
        test_concurrent_requests()
        test_production_scenario()
        
        print("=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
