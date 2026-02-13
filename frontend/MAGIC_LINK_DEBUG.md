# Magic Link 登录故障排查指南

## 🐛 问题症状

点击 Magic Link 后：
- 重定向到 `/auth/callback?code=...`
- 然后立即重定向到 `/login?error=auth_failed`
- 无法登录

## 🔍 诊断步骤

### 1️⃣ 检查 Supabase Redirect URLs 配置

**操作步骤：**

1. 打开 [Supabase Dashboard](https://app.supabase.com)
2. 选择你的项目
3. 左侧菜单：**Authentication** → **URL Configuration**
4. 检查 **Redirect URLs** 部分

**必须包含以下 URL：**
```
http://localhost:3000/auth/callback
http://localhost:3001/auth/callback
```

**如果你的前端运行在其他端口，也要添加：**
```
http://localhost:3002/auth/callback
http://localhost:3003/auth/callback
```

**生产环境还需要添加：**
```
https://your-domain.com/auth/callback
```

---

### 2️⃣ 检查前端日志

**重启前端并查看 Console 输出：**

```bash
cd frontend
npm run dev
```

在浏览器中：
1. 打开开发者工具 (F12)
2. 切换到 **Console** 标签
3. 请求登录链接
4. 点击 Magic Link
5. 查看 Console 输出的错误信息

**应该看到：**
```
[Auth Callback] Request URL: http://localhost:3000/auth/callback?code=...
[Auth Callback] Code: bbabbadb-e...
[Auth Callback] Exchanging code for session...
```

**如果失败，会显示：**
```
[Auth Callback] Exchange failed: [错误信息]
```

---

### 3️⃣ 检查后端 Terminal 日志

后端应该显示类似的日志（如果有 Console 输出的话）。

---

## 🔧 常见问题和解决方案

### 问题 1: "Invalid redirect URL"

**原因：** Supabase Redirect URLs 配置不正确

**解决：**
1. 去 Supabase Dashboard → Authentication → URL Configuration
2. 添加 `http://localhost:3000/auth/callback`
3. 保存后等待 1-2 分钟生效
4. 重新请求 Magic Link

---

### 问题 2: "Email link is invalid or has expired"

**原因：** Magic Link 已过期或已使用

**解决：**
1. Magic Link **只能使用一次**
2. 有效期通常为 **1 小时**
3. 请求新的 Magic Link
4. 立即点击（不要等太久）

---

### 问题 3: "Email rate limit exceeded"

**原因：** Supabase 限制每小时发送邮件数量

**解决：**
1. 等待 1 小时后重试
2. 或者升级 Supabase 计划
3. 或者使用不同的邮箱测试

---

### 问题 4: Cookie 设置失败

**原因：** Next.js 的 cookie API 调用问题

**解决：**
```bash
# 清除浏览器 Cookie
# Chrome: F12 → Application → Cookies → 删除所有

# 重启前端
cd frontend
npm run dev
```

---

## 🧪 测试流程

### 完整测试步骤：

```bash
# 1. 停止所有服务
cd F:\LedgerLens
.\stop-all.ps1

# 2. 清除浏览器数据
# Chrome: Ctrl+Shift+Delete → 清除 Cookie 和缓存

# 3. 重启服务
.\start-all.ps1

# 4. 打开浏览器
# 访问: http://localhost:3000/login

# 5. 输入邮箱并发送 Magic Link

# 6. 检查邮箱
# 找到邮件并点击链接

# 7. 观察 Console 输出
# F12 → Console 标签
```

---

## 📋 检查清单

在请求帮助之前，请确认：

- [ ] Supabase Redirect URLs 已正确配置
- [ ] 前端运行在 http://localhost:3000 或 3001
- [ ] 后端已启动并可访问
- [ ] Magic Link 是新请求的（未过期）
- [ ] 浏览器 Console 无 CORS 错误
- [ ] 邮箱地址正确且可接收邮件
- [ ] 已检查垃圾邮件文件夹

---

## 🔬 深度调试

如果上述方法都无效，收集以下信息：

### 1. Console 日志

```javascript
// 在浏览器 Console 运行：
localStorage.getItem('supabase.auth.token')
document.cookie
```

### 2. Network 请求

1. F12 → Network 标签
2. 勾选 "Preserve log"
3. 点击 Magic Link
4. 查找失败的请求
5. 检查 Response

### 3. Supabase 日志

1. Supabase Dashboard → Logs → Auth
2. 查找最近的登录尝试
3. 检查错误信息

---

## 💡 快速修复脚本

创建测试账号并直接设置 token（仅用于开发调试）：

访问: http://localhost:3000/test-login

这个页面会自动设置测试 token 并跳转到 dashboard。

---

## 📞 需要帮助？

如果问题仍未解决，请提供：

1. **Console 日志截图**
2. **Supabase Redirect URLs 配置截图**
3. **错误信息**
4. **前端和后端运行的端口号**

---

## ✅ 验证成功

登录成功后，你应该：
1. 被重定向到 `/dashboard`
2. 看到用户邮箱
3. 能够上传小票

**祝调试顺利！** 🚀
