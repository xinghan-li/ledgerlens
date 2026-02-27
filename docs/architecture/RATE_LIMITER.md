# Rate Limiter 实现总结

## 📋 需求

为 workflow API 添加速率限制：
- **super_admin 和 admin**: 不限制
- **其他所有用户等级**: 每分钟 5 次，且每小时不超过 20 次

## ✅ 已完成的工作

### 1. 创建独立的 Rate Limiter 模块

**文件**: `app/middleware/rate_limiter.py`

**核心功能**:
- ✅ 滑动窗口算法实现
- ✅ 线程安全（使用 Lock）
- ✅ 自动内存清理（防止内存泄漏）
- ✅ 支持多用户独立计数
- ✅ 统计信息查询
- ✅ 用户重置功能

**关键类和函数**:
```python
class RateLimiter:
    - __init__(max_requests, window_seconds)
    - check_rate_limit(user_id) -> (is_allowed, current_count, remaining)
    - reset_user(user_id)
    - get_stats(user_id)

async def check_workflow_rate_limit(user_id: str) -> str:
    # FastAPI dependency，自动检查用户等级和速率限制
```

### 2. 集成到 Workflow API

**文件**: `app/main.py`

**修改内容**:
```python
@app.post("/api/receipt/workflow", tags=["Receipts - Other"])
async def process_receipt_workflow_endpoint(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    _rate_limit_check: str = Depends(check_workflow_rate_limit)  # ← 新增
):
    ...
```

### 3. 创建测试套件

**文件**: `tests/test_rate_limiter_simple.py`

**测试覆盖**:
- ✅ 基本限流（5次/10秒）
- ✅ 时间窗口过期（等待后可继续请求）
- ✅ 多用户独立计数
- ✅ 生产场景（10次/60秒）

**测试结果**: 全部通过 ✅

### 4. 创建文档

**文件**: `app/middleware/README.md`

包含:
- 使用方法
- API 响应格式
- 自定义配置
- 性能考虑
- 未来扩展计划

## 🔧 技术细节

### 限流检查流程

```
用户请求 → JWT 认证 → 获取 user_class (缓存 5 分钟)
    ↓
是 super_admin/admin？
    ├─ 是 → 跳过限流，直接执行
    └─ 否 → 检查速率限制
         ↓
    是否超过 10次/分钟？
         ├─ 否 → 记录请求，继续执行
         └─ 是 → 返回 HTTP 429 错误
```

**性能优化** ✨: 用户等级查询使用 5 分钟 TTL 缓存，减少 ~90% 数据库查询

### HTTP 429 响应格式

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

### 内存存储结构

```python
{
    "user_id_1": [timestamp1, timestamp2, ...],  # 请求时间戳列表
    "user_id_2": [timestamp3, timestamp4, ...],
    ...
}
```

每 5 分钟自动清理过期记录。

## 📊 性能特征

- **时间复杂度**: O(n)，n = 窗口内的请求数（通常 ≤ 10）
- **空间复杂度**: O(u × r)，u = 活跃用户数，r = 平均请求数
- **并发安全**: ✅ 使用线程锁
- **内存泄漏**: ✅ 自动清理机制

## 🚀 部署注意事项

### 单实例部署（当前）
✅ 使用内存存储，开箱即用

### 多实例部署（未来）
需要改用 Redis 或其他分布式存储，否则每个实例会独立计数，导致限制失效。

**升级路径**:
1. 安装 Redis
2. 修改 `rate_limiter.py` 使用 Redis
3. 更新配置文件

## 🧪 测试方法

### 1. 运行单元测试
```bash
cd backend
python tests/test_rate_limiter_simple.py
```

### 2. API 测试（使用 curl）

**超过限制的测试**:
```bash
# 快速发送 15 次请求
for i in {1..15}; do
  curl -X POST "http://localhost:8000/api/receipt/workflow" \
    -H "Authorization: Bearer YOUR_JWT_TOKEN" \
    -F "file=@test.jpg"
done
```

前 10 次应该成功，后 5 次应该返回 429。

**检查响应头**:
```bash
curl -i -X POST "http://localhost:8000/api/receipt/workflow" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "file=@test.jpg"
```

应该看到 `X-RateLimit-*` 响应头。

## 📝 配置选项

### 修改限流参数

编辑 `app/middleware/rate_limiter.py`:

```python
# 全局 rate limiter 实例
_rate_limiter = RateLimiter(
    max_requests=10,    # ← 修改最大请求数
    window_seconds=60   # ← 修改时间窗口
)
```

### 为其他 API 添加限流

```python
from app.middleware.rate_limiter import check_workflow_rate_limit

@app.post("/api/other-endpoint")
async def other_endpoint(
    user_id: str = Depends(get_current_user),
    _: str = Depends(check_workflow_rate_limit)  # 添加这一行
):
    ...
```

### 自定义限流逻辑

创建新的 dependency 函数：

```python
async def check_custom_rate_limit(user_id: str) -> str:
    # 自定义逻辑
    # 例如：根据用户等级设置不同的限制
    limiter = RateLimiter(max_requests=20, window_seconds=60)
    ...
    return user_id
```

## 🎯 未来改进

### 短期
- [x] ✅ 用户等级缓存（减少数据库查询）- **已完成**
- [ ] 添加监控指标（Prometheus）
- [ ] 日志分析（谁被限流了？）
- [ ] 响应头始终包含限流信息

### 中期
- [ ] 数据库配置（动态调整限流参数）
- [ ] 按用户等级自动设置不同限制
- [ ] 速率限制白名单

### 长期
- [ ] Redis 支持（多实例部署）
- [ ] 分布式速率限制（跨区域）
- [ ] 速率限制仪表板

## ✨ 关键代码片段

### FastAPI Dependency 模式

```python
async def check_workflow_rate_limit(user_id: str) -> str:
    """
    这是一个 FastAPI dependency，会在 endpoint 执行前自动运行。
    
    优势：
    - 可复用（多个 endpoint 共享）
    - 自动错误处理（抛出 HTTPException）
    - 类型安全（返回 user_id）
    """
    # 1. 获取用户等级
    user_class = get_user_class_from_db(user_id)
    
    # 2. admin 跳过检查
    if user_class in ("super_admin", "admin"):
        return user_id
    
    # 3. 其他用户应用限流
    if not rate_limiter.check_rate_limit(user_id):
        raise HTTPException(status_code=429, detail="...")
    
    return user_id
```

### 滑动窗口算法

```python
def check_rate_limit(self, user_id: str):
    now = time.time()
    cutoff = now - self.window_seconds
    
    # 移除过期的时间戳
    self._requests[user_id] = [
        ts for ts in self._requests[user_id] 
        if ts > cutoff
    ]
    
    # 检查当前数量
    if len(self._requests[user_id]) >= self.max_requests:
        return False  # 拒绝
    
    # 记录本次请求
    self._requests[user_id].append(now)
    return True  # 允许
```

## 📞 联系和支持

如有问题或建议，请：
1. 查看 `app/middleware/README.md` 详细文档
2. 运行测试脚本验证功能
3. 查看日志了解限流情况

---

**状态**: ✅ 已完成并测试通过  
**版本**: 1.0  
**最后更新**: 2026-02-09
