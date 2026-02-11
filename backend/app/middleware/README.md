# Rate Limiter Middleware

## 概述

这是一个基于内存的速率限制器（Rate Limiter），用于保护 API 免受滥用和过载。

## 限流规则

- **super_admin 和 admin**: 无限制
- **其他所有用户等级** (premium, free, 未来的新等级): **每分钟 10 次请求**

## 技术实现

- **算法**: 滑动窗口（Sliding Window）
- **存储**: 内存存储（适合单实例部署）
- **并发安全**: 使用线程锁保证并发安全
- **自动清理**: 定期清理过期记录，防止内存泄漏

## 使用方法

### 在 API 端点中使用

```python
from fastapi import Depends
from app.middleware.rate_limiter import check_workflow_rate_limit
from app.services.auth.jwt_auth import get_current_user

@app.post("/api/receipt/workflow")
async def process_workflow(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    _rate_limit_check: str = Depends(check_workflow_rate_limit)  # 添加这一行
):
    # 如果通过了 rate limit 检查，才会执行到这里
    ...
```

### 响应格式

**成功时**: 正常返回 API 结果

**超过限制时** (HTTP 429):
```json
{
  "detail": {
    "error": "Rate limit exceeded",
    "message": "Too many requests. Limit: 10 per minute",
    "current_count": 10,
    "max_requests": 10,
    "reset_in_seconds": 45,
    "user_class": "free"
  }
}
```

响应头:
```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1706745600
Retry-After: 45
```

## 可选功能

### 添加 Rate Limit 响应头

可以在成功的响应中添加 rate limit 信息：

```python
from app.middleware.rate_limiter import add_rate_limit_headers
from fastapi.responses import JSONResponse

@app.post("/api/some-endpoint")
async def my_endpoint(user_id: str = Depends(get_current_user)):
    result = {"success": True, "data": ...}
    
    # 添加 rate limit 响应头
    headers = add_rate_limit_headers(user_id)
    return JSONResponse(content=result, headers=headers)
```

### 获取用户限流统计

```python
from app.middleware.rate_limiter import get_rate_limiter

rate_limiter = get_rate_limiter()
stats = rate_limiter.get_stats(user_id)

# 返回:
# {
#     "user_id": "...",
#     "current_count": 5,
#     "max_requests": 10,
#     "remaining": 5,
#     "window_seconds": 60,
#     "reset_at": 1706745600  # Unix timestamp
# }
```

### 重置用户限流

```python
from app.middleware.rate_limiter import get_rate_limiter

rate_limiter = get_rate_limiter()
rate_limiter.reset_user(user_id)  # 清空该用户的请求记录
```

### 清理用户等级缓存

```python
from app.middleware import clear_user_class_cache

# 清理单个用户的缓存（用户等级变更后）
clear_user_class_cache(user_id)

# 清理所有缓存
clear_user_class_cache()
```

## 自定义配置

如果需要修改限流参数，编辑 `rate_limiter.py`:

```python
# 全局 rate limiter 实例
_rate_limiter = RateLimiter(
    max_requests=10,    # 修改这里: 最大请求数
    window_seconds=60   # 修改这里: 时间窗口（秒）
)
```

## 性能考虑

### 当前实现（单实例）

- **存储**: 内存字典
- **适用场景**: 单服务器部署
- **性能**: O(n) 时间复杂度（n = 活跃用户数）
- **内存**: 自动清理过期记录

### 性能优化

#### 用户等级缓存 ✨

为了避免每次请求都查询数据库获取用户等级，系统实现了**内存 TTL 缓存**：

**工作原理**:
- 首次查询时从数据库获取用户等级
- 将结果缓存 5 分钟（TTL = 300 秒）
- 后续请求直接从缓存读取，无需查询数据库

**优势**:
- ✅ 减少 ~90% 的数据库查询（假设用户平均每 5 分钟多次请求）
- ✅ 降低数据库负载
- ✅ 提升响应速度

**权衡**:
- ⚠️ 用户等级变更最多延迟 5 分钟生效
- ⚠️ 如果需要立即生效，调用 `clear_user_class_cache(user_id)`

**缓存统计**（理论值）:
```
假设场景：
- 100 个活跃用户
- 每人每分钟 2 次请求
- 缓存 TTL = 5 分钟

无缓存：100 用户 × 2 req/min × 5 min = 1000 次数据库查询
有缓存：100 用户 × 1 次初始查询 = 100 次数据库查询

减少查询：90% 🎉
```

### 多实例部署（未来优化）

如果需要多实例部署，建议改用 Redis：

```python
# 伪代码示例
import redis

redis_client = redis.Redis(host='localhost', port=6379)

def check_rate_limit(user_id: str):
    key = f"rate_limit:{user_id}"
    count = redis_client.incr(key)
    
    if count == 1:
        redis_client.expire(key, window_seconds)
    
    return count <= max_requests
```

## 测试

运行测试脚本:

```bash
cd backend
python tests/test_rate_limiter_simple.py
```

测试覆盖:
- ✅ 基本限流功能
- ✅ 时间窗口过期
- ✅ 多用户独立计数
- ✅ 生产环境场景（10次/分钟）

## 已应用到的 API

- ✅ `POST /api/receipt/workflow` - 完整的收据处理流程

## 未来扩展

- [ ] Redis 支持（多实例部署）
- [ ] 动态配置（从数据库读取不同用户等级的限制）
- [ ] 更细粒度的限流（按 endpoint、按操作类型）
- [ ] 速率限制仪表板（可视化用户请求情况）
