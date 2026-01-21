"""
Gemini Rate Limiter: 管理 Gemini API 的免费层限制（15份/分钟）。

使用 UTC 时间，每分钟重置计数器。
使用 asyncio.Lock 确保线程安全。
"""
from datetime import datetime, timezone
from typing import Dict, Tuple
import logging
import asyncio

logger = logging.getLogger(__name__)

# 线程安全的状态管理
_lock = asyncio.Lock()
_current_minute: str = ""
_counter: int = 0
_max_requests_per_minute: int = 15


async def check_gemini_available() -> Tuple[bool, str]:
    """
    检查 Gemini 是否可用（未超过免费层限制）。
    
    注意：此函数是异步的，使用锁确保线程安全。
    
    Returns:
        (is_available, reason): 
        - is_available: True 如果可以使用 Gemini，False 否则
        - reason: 不可用的原因（如果可用则为空字符串）
    """
    global _current_minute, _counter
    
    async with _lock:
        # 获取当前 UTC 时间的分钟（格式：YYYY-MM-DD HH:MM）
        now = datetime.now(timezone.utc)
        current_minute_str = now.strftime("%Y-%m-%d %H:%M")
        
        # 如果分钟变了，重置计数器
        if current_minute_str != _current_minute:
            logger.info(f"Gemini rate limiter: New minute {current_minute_str}, resetting counter")
            _current_minute = current_minute_str
            _counter = 0
        
        # 检查是否超过限制
        if _counter >= _max_requests_per_minute:
            reason = f"Gemini free tier limit exceeded: {_counter}/{_max_requests_per_minute} requests this minute"
            logger.warning(reason)
            return False, reason
        
        # 增加计数器
        _counter += 1
        logger.debug(f"Gemini rate limiter: {_counter}/{_max_requests_per_minute} requests this minute")
        return True, ""


async def record_gemini_request() -> Dict[str, any]:
    """
    记录 Gemini 请求（用于统计和时间线）。
    
    注意：此函数是异步的，使用锁确保读取一致性。
    
    Returns:
        包含请求信息的字典
    """
    async with _lock:
        now = datetime.now(timezone.utc)
        return {
            "timestamp": now.isoformat(),
            "minute": now.strftime("%Y-%m-%d %H:%M"),
            "count_this_minute": _counter
        }


async def get_current_status() -> Dict[str, any]:
    """
    获取当前限流器状态（用于调试）。
    
    注意：此函数是异步的，使用锁确保读取一致性。
    
    Returns:
        状态信息字典
    """
    async with _lock:
        return {
            "current_minute": _current_minute,
            "counter": _counter,
            "max_per_minute": _max_requests_per_minute,
            "available": _counter < _max_requests_per_minute
        }
