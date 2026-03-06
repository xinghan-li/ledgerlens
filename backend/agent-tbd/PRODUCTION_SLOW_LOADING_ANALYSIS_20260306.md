# 生产环境 Loading/Deleting 慢（8–10 秒）原因分析

**现象**：手机端刷新或操作时，Loading / Deleting 经常要 8–10 秒。

**架构**：前端 Vercel → 后端 GCP Cloud Run → 数据库 Supabase。

---

## 一、可能原因（按影响从大到小）

### 1. Cloud Run 冷启动（最可能）

- 未配置 **最小实例数** 时，空闲一段时间后实例会缩到 0，下一个请求会触发冷启动。
- 冷启动常见 5–15 秒（拉镜像、起容器、加载 Python/FastAPI、连 Supabase/Firebase 等）。
- **表现**：第一次请求（例如刷新后的 `/api/auth/me` 或第一次 `/api/receipt/list`）特别慢，后续请求明显变快。

**建议**：

- 在 Cloud Run 服务上设置 **min-instances=1**（至少 1 个实例常驻），消除冷启动。
- 若不想长期付费，可用 Cloud Scheduler 定时访问 `/health` 做“保温”，减少冷启动概率。

---

### 2. 首屏被“Layout auth/me”完全挡住

**流程**（`frontend/app/dashboard/layout.tsx`）：

1. `onAuthStateChanged` 得到 user  
2. `user.getIdToken()` → **一次到 Firebase 的网络**  
3. `fetch(apiBaseUrl + '/api/auth/me')` → **一次到后端的请求**  
4. 只有 `res.ok` 且 setUserInfo 后才会 `setLoading(false)`，**整页一直显示 “Loading…”**

也就是说：**在拿到 auth/me 之前，用户看不到任何 dashboard 内容**。  
若此时再叠加 Cloud Run 冷启动或网络慢，8–10 秒都在等这一个请求。

**建议**：

- 首屏先渲染 shell（导航 + 骨架屏），不阻塞在 auth/me；auth/me 在后台请求，拿到后再更新头像/权限。
- 或：先根据本地 Firebase 的 `user` 显示“已登录”的壳，再异步拉 auth/me 和列表。

---

### 3. 每次请求都做“完整鉴权”，无服务端缓存

**当前**（`backend/app/services/auth/jwt_auth.py` 的 `get_current_user`）：

- 每个带 Authorization 的请求都会：
  1. **Firebase**：`verify_id_token(token)`（可能涉及网络拿公钥）
  2. **Supabase**：`get_or_create_user_id(firebase_uid, email)`  
     - 先按 `firebase_uid` 查 users  
     - 未命中时还有 fallback 全表/email 查询，甚至 create  
     - 极端情况单次鉴权 = 2～4 次 Supabase 往返

然后 **`/api/auth/me`** 自己又对 Supabase 做一次 `users` 查询。  
所以一次“刷新”至少：**1 次 Firebase + 2～5 次 Supabase**，且 **列表、删除等每个接口都会再走一遍** get_current_user（再来 1 次 Firebase + 1～4 次 Supabase）。

**建议**：

- 在内存（或 Redis）里做 **短 TTL 的 token → user_id 缓存**（例如 5 分钟），同一 token 在 TTL 内只做一次 Firebase + get_or_create，后续请求直接读缓存。
- 这样列表、删除等接口的鉴权成本会明显下降。

---

### 4. 重复请求 auth/me

- **Layout**：为决定是否显示 dashboard，会请求一次 `/api/auth/me`。
- **Dashboard 页**：`page.tsx` 里又用 `useEffect` 请求一次 `/api/auth/me`（拿 user_class、username）。

同一刷新会触发 **2 次** auth/me，每次都是完整鉴权 + 1 次 Supabase users 查询。

**建议**：

- Layout 已拿到 userInfo（含 user_class、username）后，通过 Context 传给 Dashboard 页，页面不再单独请求 auth/me；或  
- 只在一个地方请求 auth/me，结果通过 Context 共享。

---

### 5. 列表接口多次串行查 Supabase

**当前**（`backend/app/services/database/supabase_client.py` 的 `list_receipts_by_user`）：

1. `receipt_status` 分页  
2. `record_summaries` 批量  
3. `store_chains`（有 chain 时）  
4. 需要 fallback 店名时再查 `receipt_processing_runs`

一共 **3～4 次** 串行 Supabase 往返。在手机高 RTT 下，每次多 100～200ms 就会明显拉长“列表 Loading”。

**建议**：

- 能合并的用 Supabase 的 join 或 RPC 一次查完，减少往返；  
- 或把 2、3、4 在后端用 asyncio 并行查，再在内存里拼装。

---

### 6. 删除接口多次串行写操作

**当前**（`failed_receipts_service.py` 的 `_clear_receipt_refs_and_delete`）：

1. `api_calls` update  
2. `store_candidates` update  
3. `receipt_status` delete（依赖 CASCADE 删关联表）

3 次串行写，每次一次网络 RTT。

**建议**：

- 若业务允许，可改为 **数据库侧** 用 1 个 transaction 或 1 个 RPC 完成 update + delete，减少往返；  
- 或至少把两次 update 合并为一次 RPC/批量更新。

---

### 7. 手机网络与前端

- 手机 RTT 比 WiFi 大，**每次** 请求多 50～200ms 很常见；  
- 若再叠加上面多次往返（auth 无缓存、列表多轮查询、删除多轮写），总时间容易到 8～10 秒。

---

## 二、建议优先顺序

| 优先级 | 项 | 预期效果 |
|--------|----|----------|
| P0 | Cloud Run 设 min-instances=1 或 health 保温 | 消除/减少冷启动，首请求从 8–10s 降到 1–2s |
| P1 | Layout 不阻塞首屏：先出 shell，auth/me 异步 | 刷新后先看到界面，再逐步加载 |
| P2 | 鉴权结果短 TTL 缓存（token → user_id） | 列表/删除等接口延迟明显下降 |
| P3 | 前端只请求一次 auth/me，用 Context 共享 | 少一次完整鉴权 + 一次 DB 查询 |
| P4 | list_receipts_by_user 并行/合并 Supabase 查询 | 列表 Loading 时间缩短 |
| P5 | 删除用 DB 事务/RPC 合并写 | Deleting 时间缩短 |

---

## 三、可顺带做的

- **JWT 鉴权**：`jwt_auth.py` 里大量 `logger.warning("[DEBUG] ...")` 建议改为 `logger.debug` 或移除，避免生产日志噪音和轻微 I/O。
- **健康检查**：确认 Cloud Run 的 health 探针指向的路径（如 `/health`）不触发 Firebase/Supabase，只做进程存活检查，避免冷启动时被健康检查拖慢。

以上改动后，再在手机 4G 下测一次刷新和删除，一般能明显缩短到 2～4 秒以内（在无冷启动且鉴权有缓存的情况下）。
