# 如何从 Authentication 页面找到 JWT Secret

## 📍 当前位置

你现在在：**Authentication** > **Users** 页面

## 🎯 目标

找到 **Legacy JWT Secret**（在 Project Settings > API > JWT Keys 中）

---

## 📝 详细步骤（从当前位置开始）

### 步骤 1：找到 Project Settings

1. **查看左侧边栏**
   - 你现在在 **Authentication** 部分
   - **向下滚动**左侧边栏到最底部
   - 找到 **Project Settings**（带齿轮图标 ⚙️）
   - 它通常在边栏的最底部，不在 Authentication 下面

2. **点击 Project Settings**
   - 这会打开项目设置页面
   - 页面左侧会显示设置菜单

**提示**：如果找不到，可以尝试：
- 在浏览器地址栏直接输入：`https://app.supabase.com/project/YOUR_PROJECT_ID/settings`
- 或者点击页面右上角的项目名称，然后选择 "Settings"

---

### 步骤 2：进入 API 设置

1. **在 Project Settings 页面中**
   - 查看左侧设置菜单
   - 你会看到多个选项，如：
     - General
     - **API** ← 点击这个
     - Database
     - Auth
     - Storage
     - 等等

2. **点击 API**
   - 这会打开 API 设置页面
   - URL 应该是：`https://app.supabase.com/project/YOUR_PROJECT_ID/settings/api`

---

### 步骤 3：找到 JWT Keys 标签页

1. **在 API 设置页面中**
   - 查看页面顶部，你会看到多个标签页
   - 标签页可能包括：
     - General
     - **JWT Keys** ← 点击这个
     - 其他标签页

2. **点击 JWT Keys 标签页**
   - 这会显示 JWT 密钥相关的内容

---

### 步骤 4：切换到 Legacy JWT Secret

1. **在 JWT Keys 标签页中**
   - 你会看到两个子标签：
     - **JWT Signing Keys** - 新的 ECC 密钥系统（当前激活）
     - **Legacy JWT Secret** - 旧的 HS256 共享密钥 ← **点击这个**

2. **点击 Legacy JWT Secret 标签**
   - 你会看到一个长字符串（JWT Secret）
   - 这个字符串通常很长（至少 32 个字符）

3. **复制 JWT Secret**
   - 点击复制按钮（如果有）
   - 或者手动选中并复制整个字符串

---

### 步骤 5：配置到环境变量

1. **打开 `backend/.env` 文件**

2. **添加以下行**：
   ```bash
   SUPABASE_JWT_SECRET=你刚才复制的长字符串
   ```

3. **保存文件**

---

## 🔍 如果找不到 Project Settings？

### 方法 1：通过地址栏直接访问

1. 查看浏览器地址栏
2. 当前 URL 应该是：`https://app.supabase.com/project/YOUR_PROJECT_ID/auth/users`
3. 将 URL 改为：`https://app.supabase.com/project/YOUR_PROJECT_ID/settings/api`
4. 按 Enter 键

### 方法 2：通过项目菜单

1. 点击页面左上角的项目名称
2. 在下拉菜单中找到 "Settings" 或 "Project Settings"
3. 点击进入

### 方法 3：通过搜索

1. 在 Supabase Dashboard 中，使用浏览器搜索功能（Ctrl+F 或 Cmd+F）
2. 搜索 "Project Settings" 或 "Settings"
3. 找到后点击

---

## ⚠️ 如果看不到 Legacy JWT Secret？

如果你在 JWT Keys 页面只看到 "JWT Signing Keys" 标签，没有 "Legacy JWT Secret" 标签，说明：

1. **你的项目已经迁移到新的 ECC 密钥系统**
2. **Legacy JWT Secret 已被禁用或移除**

**解决方案**：
- 告诉我，我会更新代码以支持新的 ECC 密钥系统
- 或者检查是否有其他方式获取 Legacy JWT Secret

---

## ✅ 完成检查清单

- [ ] 已找到 Project Settings（在左侧边栏最底部）
- [ ] 已进入 API 设置
- [ ] 已找到 JWT Keys 标签页
- [ ] 已切换到 Legacy JWT Secret 标签页
- [ ] 已复制 JWT Secret
- [ ] 已添加到 `backend/.env` 文件
- [ ] 已保存文件

---

*最后更新：2026-01-31*
