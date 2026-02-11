"""
Rate Limiter Middleware

限流规则：
- super_admin 和 admin: 无限制
- 其他所有 user_class (premium, free, 未来的新等级): 每分钟 10 次

使用内存存储（适合单实例部署）。多实例部署时应改用 Redis。
"""
import time
import logging
from typing import Dict, Tuple
from collections import defaultdict
from threading import Lock
from fastapi import HTTPException, Depends

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    简单的内存 rate limiter，使用滑动窗口算法。
    
    存储结构：
    {
        user_id: [(timestamp1, timestamp2, ...), lock]
    }
    """
    
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        """
        初始化 rate limiter
        
        Args:
            max_requests: 窗口内最大请求次数
            window_seconds: 时间窗口（秒）
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        
        # 存储每个用户的请求时间戳
        # 格式: {user_id: [timestamp1, timestamp2, ...]}
        self._requests: Dict[str, list] = defaultdict(list)
        
        # 每个用户一个锁（避免并发问题）
        self._locks: Dict[str, Lock] = defaultdict(Lock)
        
        # 全局清理锁
        self._cleanup_lock = Lock()
        
        # 上次清理时间
        self._last_cleanup = time.time()
        
        logger.info(f"Rate limiter initialized: {max_requests} requests per {window_seconds}s")
    
    def _cleanup_old_entries(self):
        """
        定期清理过期的请求记录（避免内存泄漏）
        每 5 分钟运行一次
        """
        now = time.time()
        
        # 每 5 分钟清理一次
        if now - self._last_cleanup < 300:
            return
        
        with self._cleanup_lock:
            # 再次检查（double-check locking）
            if now - self._last_cleanup < 300:
                return
            
            cutoff = now - self.window_seconds - 300  # 保留窗口 + 5分钟的数据
            users_to_remove = []
            
            for user_id, timestamps in self._requests.items():
                # 清理该用户的过期时间戳
                self._requests[user_id] = [ts for ts in timestamps if ts > cutoff]
                
                # 如果该用户已经很久没有请求，删除记录
                if not self._requests[user_id]:
                    users_to_remove.append(user_id)
            
            # 删除空记录
            for user_id in users_to_remove:
                del self._requests[user_id]
                if user_id in self._locks:
                    del self._locks[user_id]
            
            self._last_cleanup = now
            logger.debug(f"Rate limiter cleanup: removed {len(users_to_remove)} inactive users")
    
    def check_rate_limit(self, user_id: str) -> Tuple[bool, int, int]:
        """
        检查用户是否超过速率限制
        
        Args:
            user_id: 用户 ID
            
        Returns:
            (is_allowed, current_count, remaining) tuple
            - is_allowed: 是否允许请求
            - current_count: 当前窗口内的请求数
            - remaining: 剩余可用请求数
        """
        now = time.time()
        cutoff = now - self.window_seconds
        
        # 定期清理
        self._cleanup_old_entries()
        
        # 使用用户特定的锁
        with self._locks[user_id]:
            # 移除过期的时间戳
            timestamps = self._requests[user_id]
            self._requests[user_id] = [ts for ts in timestamps if ts > cutoff]
            
            current_count = len(self._requests[user_id])
            remaining = max(0, self.max_requests - current_count)
            
            # 检查是否超限
            if current_count >= self.max_requests:
                logger.warning(f"Rate limit exceeded for user {user_id}: {current_count}/{self.max_requests}")
                return False, current_count, 0
            
            # 记录本次请求
            self._requests[user_id].append(now)
            
            return True, current_count + 1, remaining - 1
    
    def reset_user(self, user_id: str):
        """重置某个用户的限流记录（用于测试或管理）"""
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
            
            # 计算重置时间（最早的请求过期时间）
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


# 全局 rate limiter 实例
_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


def get_rate_limiter() -> RateLimiter:
    """获取全局 rate limiter 实例"""
    return _rate_limiter


async def check_workflow_rate_limit(user_id: str) -> str:
    """
    FastAPI dependency: 检查 workflow API 的速率限制
    
    规则：
    - super_admin 和 admin: 不限制
    - 其他所有 user_class: 每分钟 10 次
    
    Args:
        user_id: 用户 ID（从 get_current_user 获取）
        
    Returns:
        user_id（如果通过检查）
        
    Raises:
        HTTPException 429: 超过速率限制
        HTTPException 500: 检查失败
        
    Usage:
        @app.post("/api/receipt/workflow")
        async def workflow(
            file: UploadFile = File(...),
            user_id: str = Depends(get_current_user),
            _rate_limit: str = Depends(check_workflow_rate_limit)
        ):
            ...
    """
    from ..services.database.supabase_client import _get_client
    
    try:
        # 1. 获取用户等级
        supabase = _get_client()
        res = supabase.table("users").select("user_class").eq("id", user_id).limit(1).execute()
        
        if not res.data:
            logger.warning(f"User {user_id} not found in database")
            # 用户不存在，应用限流（安全起见）
            user_class = "free"
        else:
            user_class = res.data[0].get("user_class", "free")
        
        # 2. super_admin 和 admin 不限制
        if user_class in ("super_admin", "admin"):
            logger.debug(f"Rate limit bypassed for {user_class} user {user_id}")
            return user_id
        
        # 3. 其他所有等级应用限流
        rate_limiter = get_rate_limiter()
        is_allowed, current_count, remaining = rate_limiter.check_rate_limit(user_id)
        
        if not is_allowed:
            # 获取重置时间
            stats = rate_limiter.get_stats(user_id)
            reset_at = stats.get("reset_at")
            reset_in = int(reset_at - time.time()) if reset_at else 60
            
            logger.warning(
                f"Rate limit exceeded for user {user_id} ({user_class}): "
                f"{current_count}/{rate_limiter.max_requests} requests in {rate_limiter.window_seconds}s"
            )
            
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Limit: {rate_limiter.max_requests} per minute",
                    "current_count": current_count,
                    "max_requests": rate_limiter.max_requests,
                    "reset_in_seconds": reset_in,
                    "user_class": user_class
                },
                headers={
                    "X-RateLimit-Limit": str(rate_limiter.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(reset_at)) if reset_at else "",
                    "Retry-After": str(reset_in)
                }
            )
        
        # 4. 添加 rate limit 信息到响应头（通过 logger 记录，实际响应头需要在 endpoint 中设置）
        logger.info(
            f"Rate limit check passed for user {user_id} ({user_class}): "
            f"{current_count}/{rate_limiter.max_requests}, remaining: {remaining}"
        )
        
        return user_id
        
    except HTTPException:
        # 重新抛出 HTTPException（rate limit 或其他 HTTP 错误）
        raise
    except Exception as e:
        logger.error(f"Rate limit check failed for user {user_id}: {e}", exc_info=True)
        # 发生错误时，为了安全起见，拒绝请求
        raise HTTPException(
            status_code=500,
            detail="Failed to check rate limit"
        )


def add_rate_limit_headers(user_id: str) -> Dict[str, str]:
    """
    生成 rate limit 响应头（可选）
    
    返回格式符合 RFC 6585 和 GitHub API 标准：
    - X-RateLimit-Limit: 最大请求数
    - X-RateLimit-Remaining: 剩余请求数
    - X-RateLimit-Reset: 重置时间（Unix timestamp）
    
    Args:
        user_id: 用户 ID
        
    Returns:
        响应头字典
        
    Usage:
        headers = add_rate_limit_headers(user_id)
        return JSONResponse(content=data, headers=headers)
    """
    rate_limiter = get_rate_limiter()
    stats = rate_limiter.get_stats(user_id)
    
    headers = {
        "X-RateLimit-Limit": str(stats["max_requests"]),
        "X-RateLimit-Remaining": str(stats["remaining"]),
    }
    
    if stats.get("reset_at"):
        headers["X-RateLimit-Reset"] = str(int(stats["reset_at"]))
    
    return headers
