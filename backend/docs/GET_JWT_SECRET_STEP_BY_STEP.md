# 获取 Supabase JWT Secret 详细步骤

## 📍 当前位置

你现在在：**Authentication** > **Users** 页面

## 🎯 目标

获取 **Legacy JWT Secret**（用于后端 API 认证）

---

## 📝 详细步骤

### 步骤 1：导航到 Project Settings

1. **查看左侧边栏**
   - 你现在在 **Authentication** 部分（已展开）
   - 向下滚动左侧边栏，找到最底部的 **Project Settings**（带齿轮图标 ⚙️）

2. **点击 Project Settings**
   - 这会打开项目设置页面

---

### 步骤 2：进入 API 设置

1. **在 Project Settings 页面中**
   - 左侧会显示设置菜单
   - 找到并点击 **API** 选项

2. **或者直接访问**
   - 在浏览器地址栏，URL 应该是：`https://app.supabase.com/project/YOUR_PROJECT_ID/settings/api`

---

### 步骤 3：找到 JWT Keys 标签页

1. **在 API 设置页面中**
   - 你会看到多个标签页（如 "General", "JWT Keys" 等）
   - 找到并点击 **JWT Keys** 标签页

2. **你会看到两个标签**：
   - **JWT Signing Keys** - 新的 ECC 密钥系统（当前激活）
   - **Legacy JWT Secret** - 旧的 HS256 共享密钥 ← **我们需要这个**

---

### 步骤 4：切换到 Legacy JWT Secret

1. **点击 "Legacy JWT Secret" 标签页**
   - 如果这个标签页存在，点击它
   - 你会看到一个长字符串（JWT Secret）

2. **复制 JWT Secret**
   - 点击复制按钮（如果有）
   - 或者手动选中并复制整个字符串
   - 这个字符串通常很长（至少 32 个字符）

---

### 步骤 5：配置到环境变量

1. **打开 `backend/.env` 文件**

2. **添加以下行**：
   ```bash
   SUPABASE_JWT_SECRET=你刚才复制的长字符串
   ```

3. **保存文件**

---

## ⚠️ 常见问题

### Q1: 找不到 "Legacy JWT Secret" 标签页？

**可能原因**：
- 你的项目已经迁移到新的 ECC 密钥系统
- Legacy JWT Secret 已被禁用

**解决方案**：
- 联系开发人员更新代码以支持新的 ECC 密钥
- 或者检查是否有 "Legacy JWT Secret" 在其他位置

### Q2: Legacy JWT Secret 显示为 "PREVIOUS KEY"？

**说明**：
- 这意味着这个密钥已经被替换为新的 ECC 密钥
- 旧的 token 仍然可以用这个密钥验证
- 但新生成的 token 可能使用新的 ECC 密钥

**解决方案**：
- 如果可能，使用新的 ECC 密钥系统（需要更新代码）
- 或者继续使用 Legacy JWT Secret（如果它仍然有效）

### Q3: 如何验证 JWT Secret 是否正确？

**测试方法**：
1. 运行 `python get_jwt_token.py` 获取 token
2. 使用 token 测试 `/api/auth/test-token` 端点
3. 如果返回 401 错误，说明 JWT Secret 不正确

---

## 🔄 替代方案：使用新的 ECC 密钥系统

如果你的项目只有新的 ECC 密钥（没有 Legacy JWT Secret），我们需要更新代码以支持 JWKS（JSON Web Key Set）验证。

**这需要**：
1. 更新 `jwt_auth.py` 以支持 JWKS
2. 从 Supabase 获取 JWKS URL
3. 使用 `PyJWKClient` 来验证 token

**如果你需要这个方案，请告诉我，我会更新代码。**

---

## ✅ 完成检查清单

- [ ] 已导航到 Project Settings
- [ ] 已进入 API 设置
- [ ] 已找到 JWT Keys 标签页
- [ ] 已切换到 Legacy JWT Secret 标签页
- [ ] 已复制 JWT Secret
- [ ] 已添加到 `backend/.env` 文件
- [ ] 已保存文件

---

*最后更新：2026-01-31*
